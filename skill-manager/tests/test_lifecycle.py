"""Resolved lookup delegation, legacy detection and truthful partial outcomes."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import lifecycle
import core
import scan_and_check


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='skill-manager-lifecycle-')
        self.home = Path(self.temp.name)
        self.skill = self.home / '.agents/skills/lookup'
        (self.skill / 'scripts').mkdir(parents=True)
        (self.skill / 'SKILL.md').write_text('---\nname: lookup\ndescription: Synthetic\n'
                                          'metadata:\n  source: local\n  version: 1.0.0\n---\n')
        for filename in ('self_update.py', 'upstream.py'):
            (self.skill / 'scripts' / filename).write_text('# synthetic\n')
        shutil.copyfile(ROOT.parent / 'lookup/scripts/owned_process.py',
                        self.skill / 'scripts/owned_process.py')
        self.updater = self.skill / 'scripts/upstream.py'
        self.log = self.home / 'calls.json'
        self.env = {**os.environ, 'HOME': str(self.home), 'USERPROFILE': str(self.home),
                    'PYTHONDONTWRITEBYTECODE': '1'}

    def tearDown(self):
        self.temp.cleanup()

    def executor(self, status='up_to_date', exit_code=0):
        self.updater.write_text('import json,sys\nfrom pathlib import Path\n'
            f'Path({str(self.log)!r}).write_text(json.dumps(sys.argv[1:]))\n'
            'names=["lookup"] if "--self-only" in sys.argv else '
            '["opencli","agent-reach","ego-browser"] if sys.argv[1]=="upgrade" else '
            '["lookup","opencli","agent-reach","ego-browser"]\n'
            f'items=[{{"status":{status!r},"dependency":name}} for name in names]\n'
            'print(json.dumps(items[0] if "--self-only" in sys.argv else {"status":"batch","results":items}))\n'
            f'raise SystemExit({exit_code})\n')

    def cli(self, *args):
        return subprocess.run([sys.executable, str(ROOT / 'scripts/update_skill.py'), *args],
                              env=self.env, capture_output=True, text=True, timeout=20)

    def test_named_local_lookup_delegates_total_update(self):
        self.executor()
        result = self.cli('lookup')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(self.log.read_text()), ['update'])

    def test_scoped_updates_and_dry_run_use_same_resolved_target(self):
        self.executor()
        for flag, expected in (('--self-only', ['update', '--self-only']),
                               ('--upstream-only', ['upgrade'])):
            result = self.cli('lookup', flag)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(json.loads(self.log.read_text()), expected)
        self.log.unlink()
        plan = self.cli('lookup', '--self-only', '--dry-run')
        self.assertEqual(plan.returncode, 0, plan.stdout + plan.stderr)
        self.assertFalse(self.log.exists())
        payload = json.loads(plan.stdout)
        self.assertEqual(payload['scope'], 'self')
        self.assertEqual(payload['command'][1], str(self.updater.resolve()))

    def test_project_scope_does_not_update_same_named_global_skill(self):
        self.executor()
        project = self.home / 'project'
        target = project / '.agents/skills/lookup'
        target.parent.mkdir(parents=True)
        shutil.copytree(self.skill, target)
        project_log = self.home / 'project-calls.json'
        (target / 'scripts/upstream.py').write_text(self.updater.read_text().replace(str(self.log), str(project_log)))
        result = self.cli('lookup', '--project', str(project))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(project_log.read_text()), ['update'])
        self.assertFalse(self.log.exists())

    def test_partial_result_is_not_success_even_with_zero_exit(self):
        self.executor(status='manual_review')
        result = self.cli('lookup')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('manual_review', result.stdout)

    def test_body_only_success_cannot_masquerade_as_total_update(self):
        self.executor()
        self.updater.write_text('import json\nprint(json.dumps({"status":"up_to_date",'
                                '"dependency":"lookup"}))\n')
        result = self.cli('lookup')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('LOOKUP_MAINTENANCE_SCOPE_MISMATCH', result.stdout)

    def test_redirected_updater_cannot_maintain_another_installation(self):
        self.executor()
        foreign = self.home / 'other-updater.py'
        self.updater.rename(foreign)
        self.updater.symlink_to(foreign)
        result = self.cli('lookup')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('LOOKUP_MAINTENANCE_ENTRY_REDIRECTED', result.stdout)
        self.assertFalse(self.log.exists())

    def test_legacy_local_lookup_is_discovered_and_reports_missing_interface(self):
        self.updater.unlink()
        (self.skill / 'scripts/self_update.py').unlink()
        self.assertEqual(lifecycle.lookup_root(self.skill), self.skill.resolve())
        class Skill(dict):
            __getattr__ = dict.__getitem__
        skill = Skill(name='lookup', md_path=str(self.skill / 'SKILL.md'), source='local',
                      version='1.0.0', enabled=True, plugin_key='')
        with patch.object(core, 'collect_all', return_value=[skill]), patch.object(core, 'read_json', return_value={}):
            targets = scan_and_check.build_targets()
        self.assertEqual(len(targets), 1)
        result = scan_and_check.check_one(targets[0])
        self.assertTrue(result['managed_update'])
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['components']['error'], 'LOOKUP_MAINTENANCE_INTERFACE_UNAVAILABLE')
        named = self.cli('lookup')
        self.assertNotEqual(named.returncode, 0)
        self.assertIn('LOOKUP_MAINTENANCE_INTERFACE_UNAVAILABLE', named.stdout)
        self.assertNotIn('没有 github_url', named.stdout)

    def test_batch_updates_local_lookup_and_reports_failed_component(self):
        self.executor(status='manual_review')
        result = self.cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(self.log.read_text()), ['update'])
        self.assertIn('未全部完成', result.stdout)

    def test_rejects_scope_conflicts_and_extra_targets_without_running(self):
        self.executor()
        for args in (('lookup', '--self-only', '--upstream-only'),
                     ('lookup', 'opencli'), ('--self-only',)):
            with self.subTest(args=args):
                self.assertNotEqual(self.cli(*args).returncode, 0)
        self.assertFalse(self.log.exists())

    def test_named_tools_delegate_only_the_requested_dependency(self):
        self.updater.write_text('import json,sys\nfrom pathlib import Path\n'
            f'Path({str(self.log)!r}).write_text(json.dumps(sys.argv[1:]))\n'
            'print(json.dumps({"status":"up_to_date","dependency":sys.argv[2]}))\n')
        for name, dependency in lifecycle.TOOL_DEPENDENCIES.items():
            with self.subTest(name=name):
                result = self.cli(name)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(json.loads(self.log.read_text()), ['upgrade', dependency])

    def test_named_tool_plan_rejects_scope_changes_and_does_not_invoke(self):
        self.executor()
        bridge = self.home / '.agents/tools/lark/scripts/read_embedded.py'
        bridge.parent.mkdir(parents=True)
        bridge.write_text('# synthetic\n')
        binary = self.home / 'bin/lark-cli'
        binary.parent.mkdir()
        binary.write_text('#!/bin/sh\nexit 2\n')
        binary.chmod(0o700)
        self.env['PATH'] = str(binary.parent) + os.pathsep + self.env['PATH']
        for name in lifecycle.TOOL_NAMES:
            result = self.cli(name, '--dry-run')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(json.loads(result.stdout)['status'], 'plan')
            self.assertNotEqual(self.cli(name, '--dry-run', '--ref', 'main').returncode, 0)
        self.assertFalse(self.log.exists())

    def test_named_tool_rejects_wrong_dependency_success(self):
        self.updater.write_text('import json\nprint(json.dumps('
            '{"status":"up_to_date","dependency":"lookup"}))\n')
        result = self.cli('ego-lite')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('LOOKUP_MAINTENANCE_SCOPE_MISMATCH', result.stdout)

    def test_deferred_and_unknown_outcomes_never_claim_a_completed_update(self):
        for status in ('deferred', 'unexpected'):
            with self.subTest(status=status):
                self.executor(status=status)
                result = self.cli('lookup')
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn(status, result.stdout)

    def test_nonzero_malformed_batch_returns_an_error_without_a_traceback(self):
        self.updater.write_text('import json\n'
                               'print(json.dumps({"status":"batch","results":[None]}))\n'
                               'raise SystemExit(1)\n')
        result = self.cli('lookup')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('Traceback', result.stderr)

    def test_check_rejects_malformed_batch_items_without_starting_a_config_transaction(self):
        for items in (None, 1, [None], [{}]):
            with self.subTest(items=items):
                self.updater.write_text('import json\nprint(json.dumps('
                    + repr({'status': 'batch', 'results': items}) + '))\n')
                result, code = lifecycle.invoke(self.skill, action='check')
                self.assertEqual(code, 1, result)
                self.assertEqual(result['error'], 'LOOKUP_MAINTENANCE_RESULT_UNAVAILABLE')


if __name__ == '__main__':
    unittest.main()
