import argparse
import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/download_video.py"
SPEC = importlib.util.spec_from_file_location("download_video", SCRIPT)
VIDEO = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VIDEO
SPEC.loader.exec_module(VIDEO)


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / "output"
        self.output.mkdir()
        self.args = argparse.Namespace(
            output_dir=self.output, date=None, inspect=False, deep_verify=True,
            concurrent_fragments=1, cookies_from_browser=None, proxy=None,
            _all_urls=["https://example.com/video"],
        )
        self.metadata = {"title": "\u5408\u6210\u89c6\u9891", "upload_date": "20261025"}
        self.spec = VIDEO.DownloadSpec(1, self.args._all_urls[0], None)

    def fake_download(self, command, **kwargs):
        template = command[command.index("-o") + 1]
        source = Path(template.replace("%(ext)s", "mp4"))
        source.write_bytes(b"synthetic media")
        return subprocess.CompletedProcess(command, 0, str(source) + "\n", "")

    def test_failed_verification_never_publishes_and_retry_rechecks(self):
        with patch.object(VIDEO, "fetch_metadata", return_value=self.metadata), \
                patch.object(VIDEO.Path, "home", return_value=self.root), \
                patch.object(VIDEO, "run_command", side_effect=self.fake_download), \
                patch.object(VIDEO, "probe_video", return_value={"duration_seconds": 2}), \
                patch.object(VIDEO, "deep_verify", side_effect=RuntimeError("corrupt")) as verify:
            first = VIDEO.process_one(self.spec, self.args)
            second = VIDEO.process_one(self.spec, self.args)
        self.assertEqual(first["status"], "failed")
        self.assertEqual(second["status"], "failed")
        self.assertEqual(verify.call_count, 2)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_successful_download_is_verified_before_publication(self):
        observations = []

        def verify(source):
            observations.append((source.is_file(), list(self.output.glob("*.mp4"))))

        with patch.object(VIDEO.Path, "home", return_value=self.root), \
                patch.object(VIDEO, "run_command", side_effect=self.fake_download), \
                patch.object(VIDEO, "probe_video", return_value={"duration_seconds": 2}), \
                patch.object(VIDEO, "deep_verify", side_effect=verify):
            destination, details = VIDEO.download_media(self.spec.url, self.output, "sample", self.args)
        self.assertEqual(observations, [(True, [])])
        self.assertEqual(destination.read_bytes(), b"synthetic media")
        self.assertTrue(details["deep_verified"])
        self.assertEqual(list(self.output.iterdir()), [destination])

    def test_existing_file_honors_requested_full_decode(self):
        existing = self.output / "\u5408\u6210\u89c6\u9891_2026-10-25.mp4"
        existing.write_bytes(b"synthetic media")
        with patch.object(VIDEO, "fetch_metadata", return_value=self.metadata), \
                patch.object(VIDEO, "probe_video", return_value={"duration_seconds": 2}) as probe, \
                patch.object(VIDEO, "deep_verify", side_effect=RuntimeError("corrupt")) as verify:
            result = VIDEO.process_one(self.spec, self.args)
        self.assertEqual(result["status"], "failed")
        verify.assert_called_once_with(existing)
        self.assertEqual(probe.call_count, 1)
        self.assertEqual(existing.read_bytes(), b"synthetic media")

    def test_valid_existing_file_reuses_one_probe(self):
        existing = self.output / "\u5408\u6210\u89c6\u9891_2026-10-25.mp4"
        existing.write_bytes(b"synthetic media")
        with patch.object(VIDEO, "fetch_metadata", return_value=self.metadata), \
                patch.object(VIDEO, "probe_video", return_value={"duration_seconds": 2}) as probe, \
                patch.object(VIDEO, "deep_verify") as verify:
            result = VIDEO.process_one(self.spec, self.args)
        self.assertEqual(result["status"], "existing")
        self.assertTrue(result["deep_verified"])
        self.assertEqual(probe.call_count, 1)
        verify.assert_called_once_with(existing)

    def test_filename_matching_treats_brackets_literally(self):
        exact = self.output / "sample[1].mp4"
        other = self.output / "sample1.mp4"
        exact.touch()
        other.touch()
        with patch.object(VIDEO, "probe_video", return_value={"duration_seconds": 2}):
            result = VIDEO.find_existing(self.output, "sample[1]")
        path = result[0] if isinstance(result, tuple) else result
        self.assertEqual(path, exact)

    def test_downloader_cannot_publish_an_unowned_output(self):
        outside = self.root / "outside.mp4"
        outside.write_bytes(b"keep")
        result = subprocess.CompletedProcess([], 0, str(outside) + "\n", "")
        with patch.object(VIDEO.Path, "home", return_value=self.root), \
                patch.object(VIDEO, "run_command", return_value=result), \
                patch.object(VIDEO, "probe_video", return_value={"duration_seconds": 2}), \
                patch.object(VIDEO, "deep_verify"):
            with self.assertRaises(RuntimeError):
                VIDEO.download_media(self.spec.url, self.output, "sample", self.args)
        self.assertEqual(outside.read_bytes(), b"keep")
        self.assertEqual(list(self.output.iterdir()), [])

    def test_existing_file_without_deep_verification_reports_that_boundary(self):
        existing = self.output / "\u5408\u6210\u89c6\u9891_2026-10-25.mp4"
        existing.write_bytes(b"synthetic media")
        self.args.deep_verify = False
        with patch.object(VIDEO, "fetch_metadata", return_value=self.metadata), \
                patch.object(VIDEO, "probe_video", return_value={"duration_seconds": 2}), \
                patch.object(VIDEO, "deep_verify") as verify:
            result = VIDEO.process_one(self.spec, self.args)
        self.assertEqual(result["status"], "existing")
        self.assertFalse(result["deep_verified"])
        verify.assert_not_called()

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "requires local media tools")
    def test_real_decode_accepts_valid_video_and_rejects_damaged_frames(self):
        good = self.root / "good.mp4"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
             "testsrc2=size=64x64:rate=10", "-t", "2", "-c:v", "mpeg4", str(good)],
            check=True, capture_output=True, timeout=30,
        )
        VIDEO.deep_verify(good)
        raw = bytearray(good.read_bytes())
        start = raw.index(b"mdat") + 4
        raw[start + 80:start + 480] = b"\xff" * 400
        bad = self.root / "bad.mp4"
        bad.write_bytes(raw)
        self.assertEqual(VIDEO.probe_video(bad)["duration_seconds"], 2.0)
        with self.assertRaises(RuntimeError):
            VIDEO.deep_verify(bad)
