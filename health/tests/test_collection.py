import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
spec = importlib.util.spec_from_file_location('collect_data', SCRIPTS / 'collect_data.py')
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)


class CollectionTests(unittest.TestCase):
    def test_default_never_reads_global_or_transcript(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            project = root / 'project'
            project.mkdir()
            (project / '.mcp.json').write_text(json.dumps({'mcpServers': {'private-name': {'token': 'SECRET_SENTINEL'}}}))
            original = collector.file_summary
            calls = []
            def guarded(path, scope):
                self.assertTrue(path.is_relative_to(project))
                calls.append(path)
                return original(path, scope)
            with patch.object(collector, 'file_summary', side_effect=guarded), patch.object(Path, 'home', side_effect=AssertionError('global access')):
                result = collector.collect(project)
            self.assertNotIn('SECRET_SENTINEL', json.dumps(result))
            self.assertNotIn('private-name', json.dumps(result))
            self.assertEqual(result['project']['.mcp.json']['mcpServers_entries'], 1)
            self.assertEqual(result['global'], 'excluded')
            self.assertEqual(result['history'], 'excluded')
            self.assertTrue(calls)

    def test_symlink_escape_and_invalid_json_are_reported(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            project = root / 'project'
            project.mkdir()
            outside = root / 'private'
            outside.write_text('SECRET_SENTINEL')
            (project / 'AGENTS.md').symlink_to(outside)
            (project / '.mcp.json').write_text('{broken')
            result = collector.collect(project)
            self.assertEqual(result['project']['AGENTS.md']['status'], 'invalid_or_outside_scope')
            self.assertEqual(result['project']['.mcp.json']['status'], 'invalid_or_outside_scope')
            self.assertNotIn('SECRET_SENTINEL', json.dumps(result))

    def test_history_requires_flag_and_path(self):
        for args in (['--include-history'], ['--history-path', '/nonexistent']):
            result = subprocess.run([sys.executable, str(SCRIPTS / 'collect_data.py'), *args], capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 2)

    def test_history_metadata_never_reads_payload(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            history = root / 'session.jsonl'
            history.write_text('SECRET_SENTINEL')
            result = collector.collect(root, history=history)
            self.assertEqual(result['history']['status'], 'metadata_only')
            self.assertNotIn('SECRET_SENTINEL', json.dumps(result))

    def test_project_checker_cannot_read_global_config(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            project = root / 'project'
            project.mkdir()
            (project / 'AGENTS.md').write_text('Project instructions')
            home = root / 'home'
            (home / '.codex').mkdir(parents=True)
            (home / '.codex/config.toml').write_text('SECRET_SENTINEL')
            result = subprocess.run([sys.executable, '-I', str(SCRIPTS / 'check_agent_context.py'), str(project)], env={**os.environ, 'HOME': str(home)}, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn('SECRET_SENTINEL', result.stdout)
            self.assertNotIn('CODEX SURFACE', result.stdout)

    def test_shell_collector_rejects_project_python_from_path(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            project = root / 'project'
            project.mkdir()
            fake = project / 'python3'
            sentinel = root / 'executed'
            fake.write_text('#!/bin/sh\ntouch "' + str(sentinel) + '"\nexit 0\n')
            fake.chmod(0o755)
            result = subprocess.run(['/bin/bash', str(SCRIPTS / 'collect-data.sh'), '--root', str(project)], env={**os.environ, 'PATH': str(project) + os.pathsep + os.environ['PATH']}, cwd=root, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(sentinel.exists())
            self.assertEqual(json.loads(result.stdout)['mcp_live'], 'not_run')


if __name__ == '__main__':
    unittest.main()
