from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from urllib.parse import parse_qs, urlsplit

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "context7.py"


class Context7MockHandler(BaseHTTPRequestHandler):
    last_auth = None
    last_query = None

    def do_GET(self):
        parsed = urlsplit(self.path)
        params = parse_qs(parsed.query)
        Context7MockHandler.last_auth = self.headers.get("Authorization")
        Context7MockHandler.last_query = params

        query = (params.get("query") or [""])[0]
        fmt = (params.get("type") or ["txt"])[0]
        auth = self.headers.get("Authorization")

        if query == "trigger-400":
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":"validation_error","message":"Invalid version"}')
            return

        if query == "trigger-404":
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.send_header("context7-quota-tier", "free" if auth else "anonymous")
            self.end_headers()
            self.wfile.write(b'{"error":"no_documentation_found"}')
            return

        if query == "trigger-401":
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":"invalid_api_key"}')
            return

        if query == "trigger-429":
            self.send_response(429)
            self.send_header("Content-Type", "application/json")
            self.send_header("ratelimit-limit", "1000")
            self.send_header("ratelimit-remaining", "0")
            self.send_header("ratelimit-reset", "1796083200")
            self.send_header("Retry-After", "60")
            self.end_headers()
            self.wfile.write(b'{"error":"rate_limited"}')
            return

        if query == "trigger-large":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("context7-quota-tier", "free")
            self.end_headers()
            self.wfile.write(("Source: /example/lib\n\n" + "snippet line\n" * 200).encode())
            return

        self.send_response(200)
        self.send_header("context7-quota-tier", "free" if auth else "anonymous")
        self.send_header("ratelimit-limit", "1000" if auth else "200")
        self.send_header("ratelimit-remaining", "999" if auth else "199")
        if params.get("version") == ["9.9.9"]:
            self.send_header("x-context7-search-status", "partial")
            self.send_header("x-context7-search-version", "unverified")
            self.send_header("x-context7-search-reason", "versionUnverified")
        else:
            self.send_header("x-context7-search-status", "ok")
            self.send_header("x-context7-search-version", "verified")

        if fmt == "json":
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            payload = {
                "codeSnippets": [
                    {
                        "libraryId": "/mrdoob/three.js",
                        "codeTitle": "WebGPURenderer setup",
                        "rank": 1,
                    }
                ],
                "infoSnippets": [
                    {
                        "libraryId": "/websites/threejs_org",
                        "content": "Configure tone mapping.",
                        "rank": 2,
                    }
                ],
            }
            self.wfile.write(json.dumps(payload).encode())
            return

        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(
            b"### WebGPURenderer\nSource: https://threejs.org/docs/#WebGPURenderer\n\nconst renderer = new WebGPURenderer();\n"
        )

    def log_message(self, *args):
        pass


class Context7ScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Context7MockHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def run_cli(self, *args, extra_env=None):
        env = {k: v for k, v in os.environ.items() if k != "CONTEXT7_API_KEY"}
        env["NO_PROXY"] = "127.0.0.1"
        env["no_proxy"] = "127.0.0.1"
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            [sys.executable, "-B", str(SCRIPT), "--base-url", self.base_url, *args],
            capture_output=True,
            text=True,
            timeout=10,
            env=env,
        )

    def parse_meta(self, result):
        lines = result.stderr.splitlines()
        self.assertEqual(len(lines), 1, result.stderr)
        data = json.loads(lines[0])
        self.assertEqual(data["provider"], "lookup/context7")
        return data

    def test_reads_key_from_env_file_without_echoing_secret(self):
        secret = "ctx7sk-synthetic-test-token-123456"
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / "context7.env"
            env_file.write_text(f"# comment\nCONTEXT7_API_KEY=\"{secret}\"\n", encoding="utf-8")
            result = self.run_cli(
                "How to configure WebGPURenderer",
                "--library",
                "three.js",
                "--env-file",
                str(env_file),
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(Context7MockHandler.last_auth, f"Bearer {secret}")
        self.assertNotIn(secret, result.stdout)
        self.assertNotIn(secret, result.stderr)
        meta = self.parse_meta(result)
        self.assertEqual(meta["status"], "ok")
        self.assertEqual(meta["auth_mode"], "api_key")
        self.assertEqual(meta["key_source"], "env_file")
        self.assertEqual(meta["quota_tier"], "free")
        self.assertEqual(meta["ratelimit_remaining"], 999)
        self.assertIn("https://threejs.org/docs/#WebGPURenderer", meta["sources"])

    def test_anonymous_fallback_when_env_file_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing.env"
            result = self.run_cli("How to use hooks", "--env-file", str(missing))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNone(Context7MockHandler.last_auth)
        meta = self.parse_meta(result)
        self.assertEqual(meta["auth_mode"], "anonymous")
        self.assertEqual(meta["quota_tier"], "anonymous")

    def test_no_key_overrides_process_env(self):
        result = self.run_cli(
            "How to use hooks",
            "--no-key",
            extra_env={"CONTEXT7_API_KEY": "ctx7sk-should-not-be-sent"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNone(Context7MockHandler.last_auth)
        meta = self.parse_meta(result)
        self.assertEqual(meta["auth_mode"], "anonymous")

    def test_json_format_and_unverified_version_headers(self):
        result = self.run_cli(
            "How to render scene",
            "--library",
            "three.js",
            "--library",
            "/mrdoob/three.js",
            "--version",
            "9.9.9",
            "--language",
            "TypeScript",
            "--format",
            "json",
            "--no-key",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(Context7MockHandler.last_query["library"], ["three.js", "/mrdoob/three.js"])
        self.assertEqual(Context7MockHandler.last_query["version"], ["9.9.9"])
        self.assertEqual(Context7MockHandler.last_query["language"], ["TypeScript"])
        body = json.loads(result.stdout)
        self.assertEqual(body["codeSnippets"][0]["libraryId"], "/mrdoob/three.js")
        meta = self.parse_meta(result)
        self.assertEqual(meta["search_version"], "unverified")
        self.assertEqual(meta["search_reason"], "versionUnverified")
        self.assertEqual(meta["sources"], ["/mrdoob/three.js", "/websites/threejs_org"])

    def test_404_returns_empty_status(self):
        result = self.run_cli("trigger-404", "--no-key")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        meta = self.parse_meta(result)
        self.assertEqual(meta["status"], "empty")
        self.assertEqual(meta["http_status"], 404)

    def test_400_401_and_429_return_typed_errors(self):
        r400 = self.run_cli("trigger-400", "--library", "three.js", "--version", "r186", "--no-key")
        self.assertEqual(r400.returncode, 1)
        m400 = self.parse_meta(r400)
        self.assertEqual(m400["status"], "error")
        self.assertEqual(m400["error"]["code"], "INVALID_REQUEST")
        self.assertIn("Invalid version", m400["error"]["message"])

        r401 = self.run_cli("trigger-401", extra_env={"CONTEXT7_API_KEY": "ctx7sk-bad"})
        self.assertEqual(r401.returncode, 1)
        m401 = self.parse_meta(r401)
        self.assertEqual(m401["status"], "error")
        self.assertEqual(m401["error"]["code"], "AUTH_ERROR")

        r429 = self.run_cli("trigger-429", "--no-key")
        self.assertEqual(r429.returncode, 1)
        m429 = self.parse_meta(r429)
        self.assertEqual(m429["status"], "error")
        self.assertEqual(m429["error"]["code"], "RATE_LIMITED")
        self.assertEqual(m429["retry_after"], "60")
        self.assertEqual(m429["ratelimit_remaining"], 0)

    def test_truncation_returns_exit_3(self):
        result = self.run_cli("trigger-large", "--max-output-chars", "300", "--no-key")
        self.assertEqual(result.returncode, 3)
        self.assertIn("[TRUNCATED:", result.stdout)
        meta = self.parse_meta(result)
        self.assertEqual(meta["status"], "partial")
        self.assertTrue(meta["truncated"])

    def test_invalid_arguments_exit_2(self):
        r1 = self.run_cli("test", "--version", "1.0.0", "--no-key")
        self.assertEqual(r1.returncode, 2)
        r2 = self.run_cli(
            "test",
            "--library", "a",
            "--library", "b",
            "--library", "c",
            "--library", "d",
            "--library", "e",
            "--no-key",
        )
        self.assertEqual(r2.returncode, 2)


if __name__ == "__main__":
    unittest.main()
