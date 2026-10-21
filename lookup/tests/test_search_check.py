"""Search acceptance tests use only a private mock CLI, never a real API or key."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("search_check", ROOT / "scripts/search-check.py")
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)
GOOD = {"content": [{"type": "text", "text": "Title: Specification\n"
        "URL: https://modelcontextprotocol.io/specification/example\n"
        "Highlights:\nModel Context Protocol defines the message format.\n"}]}
CONFIG = {"name": "exa", "transport": "http", "baseUrl": CHECK.EXA_URL,
          "headers": {"accept": "application/json, text/event-stream"}}
SCHEMA = {"status": "ok", "tools": [{"name": "web_search_exa", "inputSchema": {
    "properties": {"query": {}, "objective": {}, "numResults": {}},
    "required": ["query", "objective"]}}]}


class SearchCheckTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lookup-search-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        cli = self.root / "mcporter"
        cli.write_text("#!" + sys.executable + "\n" + '''
import os,sys,json,pathlib
args=sys.argv[1:]
with pathlib.Path(os.environ['FAKE_LOG']).open('a') as f:f.write(json.dumps(args)+'\\n')
if args[:2]==['config','get']:
    if args[2]=='exa':
        if os.environ.get('FAKE_MISSING')=='1':sys.exit(1)
        print(os.environ['FAKE_CONFIG'])
    else:
        if os.environ.get('FAKE_DOUBAO')!='1':sys.exit(1)
        print(json.dumps({'env':{'DOUBAO_SEARCH_API_KEY':'synthetic-not-a-secret'}}))
elif args[0]=='list':print(os.environ['FAKE_SCHEMA'])
elif args[0]=='call':print(os.environ['FAKE_REPLY'])
else:sys.exit(99)
''')
        cli.chmod(0o700)
        self.env = dict(os.environ, PATH=str(self.root) + os.pathsep + os.environ["PATH"],
                        FAKE_LOG=str(self.root / "calls"), FAKE_CONFIG=json.dumps(CONFIG),
                        FAKE_SCHEMA=json.dumps(SCHEMA), FAKE_REPLY=json.dumps(GOOD))

    def run_check(self, **env):
        run = subprocess.run(["bash", str(ROOT / "scripts/selftest.sh"), "--search"],
                             env=dict(self.env, **env), capture_output=True, text=True, timeout=5)
        self.assertEqual(run.stderr, "")
        return run.returncode, json.loads(run.stdout)

    def calls(self):
        return [json.loads(s) for s in (self.root / "calls").read_text().splitlines()]

    def test_real_entry_requires_content_and_preserves_sources(self):
        code, report = self.run_check()
        self.assertEqual(code, 0)
        self.assertEqual(report["exa"]["sources"][0]["url"],
                         "https://modelcontextprotocol.io/specification/example")
        self.assertEqual(report["doubao"]["status"], "configuration_unavailable")
        calls = self.calls()
        dispatched = [args for args in calls if args[0] == "call"]
        self.assertEqual(len(dispatched), 1)
        self.assertEqual(dispatched[0][1], "exa.web_search_exa")
        arguments = json.loads(dispatched[0][dispatched[0].index("--args") + 1])
        self.assertTrue(arguments["objective"])
        self.assertTrue(all("--no-oauth" in a for a in calls if a[0] in {"list", "call"}))

    def test_missing_config_fails_before_any_search(self):
        code, report = self.run_check(FAKE_MISSING="1")
        self.assertEqual(code, 1)
        self.assertEqual(report["exa"]["error"], "EXA_CONFIG_UNAVAILABLE")
        self.assertEqual(len(self.calls()), 1)

    def test_keyed_or_other_endpoint_configs_are_not_probed(self):
        for change in ({"headers": {"x-api-key": "synthetic"}}, {"auth": "oauth"},
                       {"baseUrl": CHECK.EXA_URL + "?login"}, {"env": {"ANY": "value"}}):
            with self.subTest(change=change):
                code, report = self.run_check(FAKE_CONFIG=json.dumps({**CONFIG, **change}))
                self.assertEqual(code, 1)
                self.assertEqual(report["exa"]["error"], "EXA_KEYLESS_CONFIG_REQUIRED")
        self.assertFalse(any(a[0] == "call" for a in self.calls()))

    def test_schema_drift_fails_before_search(self):
        changed = json.loads(json.dumps(SCHEMA))
        changed["tools"][0]["inputSchema"]["required"].append("new_contract")
        code, report = self.run_check(FAKE_SCHEMA=json.dumps(changed))
        self.assertEqual(code, 1)
        self.assertEqual(report["exa"]["error"], "EXA_SCHEMA_CHANGED")
        self.assertFalse(any(a[0] == "call" for a in self.calls()))

    def test_zero_exit_error_empty_and_metadata_only_do_not_pass(self):
        for payload in ({"isError": True, **GOOD}, {"content": []},
                        {"content": [{"type": "text", "text": "Title: Specification\n"
                                     "URL: https://modelcontextprotocol.io/\n"}]},
                        {"content": [{"type": "text", "text": "No matching results"}]}):
            with self.subTest(payload=payload):
                code, report = self.run_check(FAKE_REPLY=json.dumps(payload))
                self.assertEqual(code, 1)
                self.assertEqual(report["status"], "error")

    def test_free_rate_limit_metadata_is_failure_even_without_is_error(self):
        payload = {"_meta": {"ai.exa/rateLimited": True}, **GOOD}
        code, report = self.run_check(FAKE_REPLY=json.dumps(payload))
        self.assertEqual(code, 1)
        self.assertEqual(report["exa"]["error"], "EXA_RATE_LIMITED")
        self.assertEqual(len([a for a in self.calls() if a[0] == "call"]), 1)
        self.assertFalse(any("auth" in a for a in self.calls()))

    def test_doubao_is_not_called_even_when_configured(self):
        code, report = self.run_check(FAKE_DOUBAO="1")
        self.assertEqual(code, 0)
        self.assertEqual(report["doubao"]["status"], "configured_not_tested")
        self.assertEqual(report["doubao"]["live_query"], "not_run")
        self.assertNotIn("synthetic-not-a-secret", json.dumps(report))
        self.assertEqual([a[1] for a in self.calls() if a[0] == "call"], ["exa.web_search_exa"])

    def test_timeout_is_unknown_and_does_not_retry(self):
        responses = [subprocess.CompletedProcess([], 0, json.dumps(CONFIG), ""),
                     subprocess.CompletedProcess([], 1, "", ""),
                     subprocess.CompletedProcess([], 0, json.dumps(SCHEMA), ""),
                     subprocess.TimeoutExpired("mcporter", 1)]
        with patch.object(CHECK.shutil, "which", return_value="mcporter"), \
                patch.object(CHECK.subprocess, "run", side_effect=responses) as run:
            report, code = CHECK.check()
        self.assertEqual(code, 1)
        self.assertTrue(report["exa"]["outcome_unknown"])
        self.assertEqual(report["phase"], "search")
        self.assertEqual(run.call_count, 4)

    def test_setup_timeout_does_not_claim_a_search_was_dispatched(self):
        with patch.object(CHECK.shutil, "which", return_value="mcporter"), \
                patch.object(CHECK.subprocess, "run", side_effect=subprocess.TimeoutExpired("mcporter", 1)) as run:
            report, code = CHECK.check()
        self.assertEqual(code, 1)
        self.assertEqual(report["exa"]["error"], "CHECK_TIMEOUT")
        self.assertFalse(report["exa"]["outcome_unknown"])
        self.assertEqual(run.call_count, 1)

    def test_unrelated_and_malformed_urls_are_not_evidence(self):
        for url in ("https://modelcontextprotocol.io.attacker.invalid/", "https://[broken/"):
            payload = json.loads(json.dumps(GOOD))
            payload["content"][0]["text"] = payload["content"][0]["text"].replace(
                "https://modelcontextprotocol.io/specification/example", url)
            with self.subTest(url=url), self.assertRaises(CHECK.CheckError):
                CHECK.sources_from(payload)


if __name__ == "__main__":
    unittest.main()
