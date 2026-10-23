#!/usr/bin/env python3
"""Offline regressions for evidence normalization and subtitle preservation."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"

def load_module(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

SUBTITLES = load_module("clean-subtitles")
RESULTS = load_module("normalize-result")

class SubtitleTests(unittest.TestCase):
    def run_subtitles(self, source, *args):
        with tempfile.TemporaryDirectory(prefix="lookup-subtitles-test-") as folder:
            target = Path(folder) / "sample.vtt"
            target.write_text(source, encoding="utf-8")
            return subprocess.run([sys.executable, str(SCRIPTS / "clean-subtitles.py"),
                                   str(target), *args], capture_output=True, text=True, timeout=5)

    def test_manual_repeated_speech_is_preserved_with_times(self):
        source = "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nTry again.\n\n00:00:10.000 --> 00:00:11.000\nTry again.\n"
        result = self.run_subtitles(source)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.count("Try again."), 2)
        self.assertIn("[00:00:10.000]", result.stdout)

    def test_adjacent_rolling_prefix_is_removed(self):
        source = "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nHello<00:00:00.500><c> world</c>\n\n00:00:01.500 --> 00:00:03.000\nHello world<00:00:02.000><c> again</c>\n"
        result = self.run_subtitles(source)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.count("Hello world"), 1)
        self.assertIn("[00:00:01.500] again", result.stdout)

    def test_cjk_rolling_prefix_and_srt_time(self):
        cues, malformed = SUBTITLES.parse_cues("1\n00:00:00,000 --> 00:00:01,000\n你好<00:00:00.500>世界\n\n2\n00:00:00,800 --> 00:00:02,000\n你好世界<00:00:01.000>朋友\n")
        self.assertEqual(malformed, 0)
        self.assertEqual([cue["text"] for cue in SUBTITLES.clean_cues(cues)], ["你好世界", "朋友"])

    def test_cjk_rolling_suffix_is_removed_but_separate_speech_survives(self):
        for rolling, expected in ((True, ["你好世界", "朋友"]),
                                  (False, ["你好世界", "世界朋友"])):
            with self.subTest(rolling=rolling):
                cues = [
                    {"start": 0, "end": 2000, "text": "你好世界", "rolling": rolling},
                    {"start": 1500, "end": 3000, "text": "世界朋友", "rolling": rolling},
                ]
                self.assertEqual([cue["text"] for cue in SUBTITLES.clean_cues(cues)], expected)

    def test_word_overlap_uses_longest_suffix_and_keeps_new_speech(self):
        cases = (("a b a b", "a b a b c", "c"),
                 ("a b a", "a b c", "b c"),
                 ("a a a", "a a b", "b"),
                 ("before ends", "different beginning", "different beginning"))
        for old, new, expected in cases:
            with self.subTest(old=old, new=new):
                cues = [{"start": 0, "end": 2000, "text": old, "rolling": True},
                        {"start": 1500, "end": 3000, "text": new, "rolling": True}]
                self.assertEqual([cue["text"] for cue in SUBTITLES.clean_cues(cues)], [old, expected])

    def test_single_latin_words_do_not_deduplicate_shared_letters(self):
        cues = [{"start": 0, "end": 2000, "text": "shell", "rolling": True},
                {"start": 1500, "end": 3000, "text": "hello", "rolling": True}]
        self.assertEqual([cue["text"] for cue in SUBTITLES.clean_cues(cues)], ["shell", "hello"])

    def test_entity_text_is_decoded_once(self):
        cues, _ = SUBTITLES.parse_cues("00:00:00.000 --> 00:00:01.000\n&lt;script&gt; &amp;lt;\n")
        self.assertEqual(cues[0]["text"], "<script> &lt;")

    def test_partial_output_is_explicit(self):
        result = self.run_subtitles("WEBVTT\n\n00:00:00.000 --> 00:00:02.000\n" + "内容" * 100 + "\n", "--max-output-chars", "64")
        self.assertEqual(result.returncode, 3)
        self.assertLessEqual(len(result.stdout), 64)
        self.assertEqual(json.loads(result.stderr)["status"], "partial")
        self.assertTrue(json.loads(result.stderr)["truncated"])

    def test_malformed_cue_is_not_silently_ignored(self):
        result = self.run_subtitles("WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nusable\n\n00:00:09.000 --> 00:00:08.000\nbad time\n")
        self.assertEqual(result.returncode, 3)
        self.assertEqual(json.loads(result.stderr)["malformed_cues"], 1)


    def test_unknown_angle_brackets_preserve_technical_literals(self):
        source = "1\n00:00:00,000 --> 00:00:02,000\nUse vector<T> and include <stdio.h>. <b>Keep</b> <i>formatting text</i>.\n"
        result = self.run_subtitles(source)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("vector<T> and include <stdio.h>", result.stdout)
        self.assertIn("Keep formatting text.", result.stdout)
        self.assertNotIn("<b>", result.stdout)

    def test_broken_arrow_marks_missing_cue_as_partial(self):
        source = "1\n00:00:00,000 --> 00:00:01,000\nFirst sentence.\n\n2\n00:00:03,000 -> 00:00:04,000\nSecond sentence.\n"
        result = self.run_subtitles(source)
        self.assertEqual(result.returncode, 3)
        self.assertEqual(json.loads(result.stderr)["malformed_cues"], 1)
        self.assertEqual(json.loads(result.stderr)["status"], "partial")

    def test_no_cues_is_an_input_error(self):
        result = self.run_subtitles("WEBVTT\n\nLanguage: en\n")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stderr)["error"]["code"], "SUBTITLE_INPUT")

class ResultTests(unittest.TestCase):
    def capture(self, stdout, **kwargs):
        return {"provider": "opencli/example/search", "exit_code": 0,
                "stdout": stdout, "stderr": "", **kwargs}

    def test_capture_retains_access_url_without_claiming_time(self):
        result = RESULTS.normalize(self.capture([{"title": "Result"}],
            url="https://example.invalid/note", access_url="https://example.invalid/note?xsec_token=synthetic"))
        self.assertEqual(result["status"], "ok")
        self.assertIn("xsec_token=synthetic", result["access_url"])
        self.assertIsNone(result["published_at"])
        self.assertIsNone(result["fetched_at"])
        self.assertEqual(result["verification_scope"], "capture_and_shape")

    def test_empty_requires_confirmation(self):
        self.assertEqual(RESULTS.normalize(self.capture("[]"))["status"], "partial")
        self.assertEqual(RESULTS.normalize(self.capture("[]", empty_confirmed=True))["status"], "empty")

    def test_json_parse_failure_is_scoped(self):
        result = RESULTS.normalize(self.capture("[broken", stdout_format="json"))
        self.assertEqual(result["error"]["code"], "PARSE")
        self.assertEqual(result["error"]["scope"], "site_action")

    def test_security_block_pauses_the_site_profile(self):
        for stdout, exit_code in [
            ({"ok": False, "error": {"code": "SECURITY_BLOCK", "message": "Security controls blocked search"}}, 1),
            ({"ok": True, "data": {"error": {"code": "SECURITY_BLOCK"}}}, 0),
        ]:
            with self.subTest(stdout=stdout):
                result = RESULTS.normalize(self.capture(stdout, exit_code=exit_code))
                self.assertEqual(result["status"], "error")
                self.assertEqual(result["error"]["code"], "SECURITY_BLOCK")
                self.assertEqual(result["error"]["scope"], "site_profile")

    def test_yaml_code_is_parsed_without_interpreting_message(self):
        result = RESULTS.normalize(self.capture("", exit_code=1, stderr="error:\n  code: AUTH_REQUIRED\n  message: |\n    code: BROWSER_CONNECT\n"))
        self.assertEqual(result["error"]["code"], "AUTH_REQUIRED")
        self.assertEqual(result["error"]["scope"], "site_profile")
        ambiguous = RESULTS.normalize(self.capture("", exit_code=1, stderr="error:\n  code: AUTH_REQUIRED\n  code: BROWSER_CONNECT\n"))
        self.assertEqual(ambiguous["error"]["code"], "UNKNOWN")
        unstructured = RESULTS.normalize(self.capture("", exit_code=1, stderr="AUTH_REQUIRED happened"))
        self.assertEqual(unstructured["error"]["code"], "UNKNOWN")

    def test_unknown_outcome_does_not_become_empty(self):
        result = RESULTS.normalize(self.capture("", exit_code=None, empty_confirmed=True))
        self.assertEqual(result["status"], "error")
        self.assertTrue(result["error"]["outcome_unknown"])

    def test_douyin_unavailable_counts_are_unknown_not_zero(self):
        result = RESULTS.normalize(self.capture([{"likes": 0, "plays": 0, "comments": 0, "shares": 0}],
                                   provider="opencli/douyin/search"))
        self.assertIsNone(result["items"][0]["plays"])
        self.assertEqual(result["items"][0]["likes"], 0)
        self.assertEqual(result["status"], "partial")

    def test_other_providers_keep_real_zero(self):
        result = RESULTS.normalize(self.capture([{"plays": 0, "comments": 0}]))
        self.assertEqual(result["items"][0]["plays"], 0)
        self.assertEqual(result["status"], "ok")

    def test_local_partial_keeps_content_and_status(self):
        result = RESULTS.normalize(self.capture("readable preview", provider="lookup/fetch", exit_code=3,
                 stdout_format="text", stderr='{"status":"partial","truncated":true}'))
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["text"], "readable preview")
        self.assertIsNone(result["error"])

    def test_success_exit_with_error_envelope_is_not_content(self):
        result = RESULTS.normalize(self.capture('{"error":{"code":"AUTH_REQUIRED"}}', stdout_format="json"))
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"]["code"], "AUTH_REQUIRED")

    def test_upstream_truncation_is_retained(self):
        result = RESULTS.normalize(self.capture({"items": [{"text": "preview"}], "truncated": True}))
        self.assertEqual(result["status"], "partial")
        self.assertTrue(result["truncated"])

    def test_content_budget_retains_valid_json(self):
        result = RESULTS.normalize(self.capture([{"text": "资料" * 500}, {"text": "later"}]), 64)
        self.assertTrue(result["truncated"])
        self.assertEqual(result["status"], "partial")
        self.assertLessEqual(len(RESULTS.encoded(result["items"])), 64)


    def test_find_url_collections_preserve_source_and_confirmed_empty(self):
        output = {"profile": "Default", "bookmarks": [], "history": [], "more_available": False}
        stderr = {"provider": "lookup/find-url", "status": "empty",
                  "empty_confirmed": True, "truncated": False}
        result = RESULTS.normalize(self.capture(output, provider="lookup/find-url", stderr=stderr))
        self.assertEqual(result["status"], "empty")
        self.assertEqual(result["items"], [])
        self.assertEqual(result["profile"], "Default")
        self.assertEqual(RESULTS.normalize(self.capture(output, provider="lookup/find-url"))["status"], "partial")
        output["history"] = [{"title": "A visit", "url": "https://example.invalid/", "visit_count": 2}]
        output["more_available"] = True
        result = RESULTS.normalize(self.capture(output, provider="lookup/find-url",
            stderr={"provider": "lookup/find-url", "status": "ok"}))
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["more_available"])
        self.assertEqual(result["items"][0]["collection"], "history")

    def test_find_url_partial_and_malformed_envelope(self):
        output = {"profile": "Default", "bookmarks": [],
                  "history": [{"title": "Preview"}], "more_available": True}
        result = RESULTS.normalize(self.capture(output, provider="lookup/find-url", exit_code=3,
            stderr={"provider": "lookup/find-url", "status": "partial", "truncated": True}))
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["items"][0]["title"], "Preview")
        malformed = RESULTS.normalize(self.capture({"profile": "Default"}, provider="lookup/find-url"))
        self.assertEqual(malformed["error"]["code"], "PARSE")

    def test_structured_stderr_error_and_nested_timeout_are_not_success(self):
        result = RESULTS.normalize(self.capture("apparently usable", stderr={"error": {"code": "AUTH_REQUIRED"}}))
        self.assertEqual(result["error"]["code"], "AUTH_REQUIRED")
        unknown = RESULTS.normalize(self.capture({"error": {"code": "TIMEOUT"}}))
        self.assertTrue(unknown["error"]["outcome_unknown"])
        self.assertEqual(unknown["error"]["code"], "OUTCOME_UNKNOWN")

    def test_single_object_obeys_content_budget(self):
        result = RESULTS.normalize(self.capture({"text": "资料" * 100}), 64)
        self.assertLessEqual(len(RESULTS.encoded(result["items"])), 64)
        self.assertEqual(result["status"], "partial")


    def test_subtitle_stdout_round_trip_uses_text(self):
        run = SubtitleTests().run_subtitles("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHello world.\n")
        self.assertEqual(run.returncode, 0, run.stderr)
        capture = self.capture(run.stdout, provider="lookup/subtitles", exit_code=run.returncode,
                               stderr=run.stderr, evidence_type="subtitles")
        result = RESULTS.normalize(capture)
        self.assertEqual(result["status"], "ok")
        self.assertIn("[00:00:00.000] Hello world.", result["text"])
        raw_document = RESULTS.normalize(self.capture("[a literal text file]", provider="lookup/fetch"))
        self.assertEqual(raw_document["text"], "[a literal text file]")

    def test_nonzero_stdout_error_retains_known_scope(self):
        for code, scope in (("AUTH_REQUIRED", "site_profile"), ("BROWSER_CONNECT", "transport_profile")):
            result = RESULTS.normalize(self.capture({"error": {"code": code}}, exit_code=1))
            self.assertEqual(result["error"]["code"], code)
            self.assertEqual(result["error"]["scope"], scope)

    def test_runner_error_after_banner_retains_unknown_outcome(self):
        error = {"error": {"code": "OUTCOME_UNKNOWN", "original_code": "OPENCLI_RUN_DEADLINE_EXCEEDED",
                           "message": "bounded wait ended"}, "phase": "action",
                 "outcome_unknown": True, "retryable": False}
        result = RESULTS.normalize(self.capture("", exit_code=75, stderr="upstream update notice\n" + json.dumps(error)))
        self.assertEqual(result["error"]["code"], "OUTCOME_UNKNOWN")
        self.assertTrue(result["error"]["outcome_unknown"])

    def test_invalid_capture_is_rejected(self):
        for capture in ({"provider": "x", "stdout": "text"}, self.capture("text", exit_code=True),
                        self.capture("text", empty_confirmed="yes")):
            with self.assertRaises(ValueError):
                RESULTS.normalize(capture)

    def test_opencli_envelope_unwraps_content_and_empty(self):
        result = RESULTS.normalize(self.capture({"ok": True, "data": [{"text": "article"}]}))
        self.assertEqual(result["items"], [{"text": "article"}])
        self.assertEqual(RESULTS.normalize(self.capture({"ok": True, "data": []}))["status"], "partial")
        self.assertEqual(RESULTS.normalize(self.capture({"ok": True, "data": []}, empty_confirmed=True))["status"], "empty")

    def test_opencli_unknown_outcome_and_invalid_success(self):
        result = RESULTS.normalize(self.capture({"ok": False, "error": {"code": "COMMAND_FAILED", "outcome": "unknown"}}, exit_code=1))
        self.assertTrue(result["error"]["outcome_unknown"])
        self.assertEqual(RESULTS.normalize(self.capture({"ok": True}))["status"], "error")
        self.assertEqual(RESULTS.normalize(self.capture({"ok": False}))["status"], "error")

    def test_opencli_wrapper_preserves_payload_verdict(self):
        cases = [
            ({"text": "complete article"}, {}, "ok", None),
            ([{"title": "result"}], {}, "ok", None),
            ([], {}, "partial", None),
            ([], {"empty_confirmed": True}, "empty", None),
            ({"items": [{"text": "preview"}], "truncated": True}, {}, "partial", None),
            ({"items": [{"text": "preview"}], "status": "partial"}, {}, "partial", None),
            ({"status": "error"}, {}, "error", "UNKNOWN"),
            ({"error": {"code": "AUTH_REQUIRED"}}, {}, "error", "AUTH_REQUIRED"),
            ({"error": {"code": "COMMAND_FAILED", "outcome": "unknown"}}, {}, "error", "OUTCOME_UNKNOWN"),
        ]
        for payload, options, status, code in cases:
            with self.subTest(payload=payload, options=options):
                bare = RESULTS.normalize(self.capture(payload, **options))
                wrapped = RESULTS.normalize(self.capture({"ok": True, "data": payload}, **options))
                self.assertEqual(bare["status"], status)
                self.assertEqual(wrapped["status"], status)
                self.assertEqual(wrapped, bare)
                if code:
                    self.assertEqual(wrapped["error"]["code"], code)

    def test_opencli_outer_error_cannot_be_hidden_by_data(self):
        for envelope in (
            {"ok": False, "error": {"code": "AUTH_REQUIRED"}, "data": [{"text": "stale"}]},
            {"ok": True, "error": {"code": "AUTH_REQUIRED"}, "data": [{"text": "stale"}]},
        ):
            with self.subTest(envelope=envelope):
                result = RESULTS.normalize(self.capture(envelope))
                self.assertEqual(result["status"], "error")
                self.assertEqual(result["error"]["code"], "AUTH_REQUIRED")
                self.assertNotIn("items", result)

    def test_cli_returns_structured_error_for_malformed_input(self):
        run = subprocess.run([sys.executable, str(SCRIPTS / "normalize-result.py")],
                             input="{broken", capture_output=True, text=True, timeout=5)
        self.assertEqual(run.returncode, 2)
        self.assertEqual(json.loads(run.stdout)["error"]["code"], "NORMALIZER_INPUT")

if __name__ == "__main__":
    unittest.main()
