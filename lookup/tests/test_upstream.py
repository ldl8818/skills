"""Update lifecycle regressions. Synthetic releases, no network or browser."""
import base64
from contextlib import redirect_stdout
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import signal
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/upstream.py'
spec = importlib.util.spec_from_file_location('lookup_upstream', SCRIPT)
upstream = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upstream)

CONTRACT = {'actions': {'sample/read': {'providers': [{
    'type': 'opencli', 'status': 'active', 'command': 'sample/read',
    'required_access': 'read', 'required_args': ['url'], 'required_columns': ['text'],
}]}}}


def cli(path, version='2.0.2', access='read', fields=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    help_data = {'site': 'sample', 'name': 'read', 'access': access,
                 'positionals': [{'name': 'url', 'positional': True}],
                 'command_options': [], 'columns': ['text'] if fields is None else fields}
    path.write_text('#!' + sys.executable + '\n' +
                    'import json,sys,time\n'
                    f'if sys.argv[1:]==["--version"]: print({version!r})\n'
                    'elif sys.argv[1:3]==["skills","read"]: print("name: opencli-browser\\n# guide")\n'
                    f'elif "--help" in sys.argv: print({json.dumps(help_data)!r})\n'
                    'else: print(json.dumps({"ok":True,"args":sys.argv[1:]}))\n')
    path.chmod(0o700)
    return path


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='lookup-upstream-test-')
        self.base = Path(self.temp.name)
        self.store = upstream.Store(self.base/'state/lookup/upstream')
        self.bin = self.base/'bin'
        self.baseline = cli(self.bin/'opencli')
        self.skill = self.base/'skill'
        (self.skill/'references').mkdir(parents=True)
        (self.skill/'references/providers.json').write_text(json.dumps(CONTRACT))
        self.env = patch.dict(os.environ, HOME=str(self.base/'home'),
                              XDG_STATE_HOME=str(self.base/'state'),
                              PATH=str(self.bin)+os.pathsep+os.environ['PATH'], CI='1')
        self.env.start()
        self.root = patch.object(upstream, 'ROOT', self.skill)
        self.root.start()
        # These lifecycle fixtures are intentionally stand-alone fake binaries.
        # Full package provenance and customization paths are exercised separately.
        self.custom = patch.object(upstream, 'opencli_customizations', return_value=(None, {}))
        self.custom.start()
        self.release = {'latest': '2.0.3', 'published_at': '2026-01-01T00:00:00Z',
                        'url': 'https://www.npmjs.com/package/@jackwener/opencli',
                        'tarball': upstream.REGISTRY + '@jackwener/opencli/-/opencli-2.0.3.tgz',
                        'integrity': 'sha512-' + base64.b64encode(b'fixture').decode()}

    def tearDown(self):
        self.custom.stop()
        self.root.stop()
        self.env.stop()
        self.temp.cleanup()

    def candidate(self, store=None, release=None):
        binary = cli(self.store.root/'versions/fixture/opencli', '2.0.3')
        return {'binary': str(binary), 'version': '2.0.3', 'sha256': upstream.digest(binary),
                'validation': upstream.qualify(binary, '2.0.3')}

    def test_cache_only_checks_once_across_store_instances(self):
        with patch.object(upstream, 'latest', return_value=self.release) as fetch:
            a = upstream.check(self.store, 'opencli')
            b = upstream.check(upstream.Store(self.store.root), 'opencli')
        self.assertEqual(a['status'], 'update_available')
        self.assertTrue(b['cached'])
        self.assertEqual(fetch.call_count, 1)

    def test_remote_failure_is_not_current_and_has_retry_backoff(self):
        with patch.object(upstream, 'latest', side_effect=OSError('offline')) as fetch:
            result = upstream.check(self.store, 'opencli')
            again = upstream.check(self.store, 'opencli')
        self.assertEqual(result['status'], 'check_failed')
        self.assertTrue(again['cached'])
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(upstream.notices(self.store, ['opencli']), [])

    def test_empty_version_output_is_a_reported_failure_not_an_index_error(self):
        with patch.object(upstream, 'command', return_value=''):
            for dependency in upstream.UPDATE_DEPENDENCIES:
                with self.assertRaisesRegex(upstream.MaintenanceError, 'VERSION_OUTPUT_EMPTY'):
                    upstream.read_version('synthetic', dependency)

    def test_native_version_on_stderr_does_not_select_embedded_runtime_versions(self):
        binary = self.bin / 'stderr-ego'
        binary.write_text('#!' + sys.executable + '\nimport sys\n'
                          'print("ego-browser 0.6.0.16\\n  chromium 154.0.8037.44\\n  node v24.21.0", file=sys.stderr)\n')
        binary.chmod(0o700)
        self.assertEqual(upstream.read_version(binary, 'ego-browser'), '0.6.0.16')

    def test_absent_and_reference_only_dependencies_do_not_fetch_or_notify(self):
        with patch.object(upstream.shutil, 'which', return_value=None), patch.object(upstream, 'latest') as fetch:
            self.assertEqual(upstream.check(self.store, 'agent-reach')['status'], 'not_installed')
            self.assertEqual(upstream.check(self.store, 'web-access')['status'], 'reference_only')
        fetch.assert_not_called()
        self.assertEqual(upstream.notices(self.store, ['agent-reach', 'web-access']), [])

    def test_background_schedule_is_bounded_and_does_not_fetch_in_caller(self):
        with patch.object(upstream.subprocess, 'Popen') as process, patch.object(upstream, 'latest') as fetch:
            result = upstream.check(self.store, 'opencli', background=True, current='2.0.2')
            again = upstream.check(self.store, 'opencli', background=True, current='2.0.2')
        self.assertEqual(result['status'], 'scheduled')
        self.assertEqual(again['status'], 'checking')
        self.assertEqual(process.call_count, 1)
        self.assertTrue(process.call_args.kwargs['start_new_session'])
        fetch.assert_not_called()

    def test_notices_are_claimed_once_across_processes(self):
        with patch.object(upstream, 'latest', return_value=self.release):
            upstream.check(self.store, 'opencli')
        processes = [subprocess.Popen([sys.executable, str(SCRIPT), 'notices', 'opencli'],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                     for _ in range(4)]
        notices = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 0, stderr)
            notices.extend(json.loads(stdout)['notices'])
        self.assertEqual(len(notices), 1)
        self.assertIn('lookup upgrade opencli', notices[0]['message'])
        self.assertEqual(notices[0]['action'], 'notify')

    def test_ego_only_reports_local_change_without_running_native_upgrade(self):
        with patch.object(upstream, 'installed', return_value={'status': 'installed', 'current': '0.6.0.16'}):
            upstream.check(self.store, 'ego-browser')
        self.assertEqual(upstream.notices(self.store, ['ego-browser']), [])
        with patch.object(upstream, 'installed', return_value={'status': 'installed', 'current': '0.6.0.17'}), patch.object(upstream, 'latest') as fetch:
            result = upstream.check(self.store, 'ego-browser')
        self.assertFalse(result['remote_checked'])
        fetch.assert_not_called()
        self.assertEqual(upstream.notices(self.store, ['ego-browser'])[0]['action'], 'reload_guide')

    def test_auto_request_is_not_duplicated_across_sessions(self):
        upstream.policy(self.store, 'opencli', 'auto')
        with patch.object(upstream, 'latest', return_value=self.release):
            upstream.check(self.store, 'opencli')
        self.assertEqual(upstream.notices(self.store, ['opencli'])[0]['action'], 'maintain')
        self.assertEqual(upstream.notices(upstream.Store(self.store.root), ['opencli']), [])

    def test_corrupt_state_is_not_silently_replaced(self):
        path = self.store.root/'state.json'
        path.write_text('{broken')
        with self.assertRaisesRegex(upstream.MaintenanceError, 'STATE_UNREADABLE'):
            upstream.check(self.store, 'opencli')
        self.assertEqual(path.read_text(), '{broken')

    def test_auto_requires_explicit_policy_and_unsupported_policies_are_rejected(self):
        with patch.object(upstream, 'prepare_candidate') as prepare:
            with self.assertRaisesRegex(upstream.MaintenanceError, 'AUTO_NOT_AUTHORIZED'):
                upstream.update(self.store, 'opencli', automatic=True)
            with self.assertRaisesRegex(upstream.MaintenanceError, 'AUTOMATION_NOT_SUPPORTED'):
                upstream.policy(self.store, 'ego-browser', 'auto')
        prepare.assert_not_called()

    def test_recent_release_is_deferred_but_manual_update_can_proceed(self):
        upstream.policy(self.store, 'opencli', 'auto')
        recent = {**self.release, 'published_at': upstream.datetime.now(upstream.timezone.utc).isoformat()}
        with patch.object(upstream, 'latest', return_value=recent), patch.object(upstream, 'prepare_candidate', side_effect=self.candidate) as prepare:
            self.assertEqual(upstream.update(self.store, 'opencli', automatic=True)['status'], 'deferred')
            prepare.assert_not_called()
            self.assertEqual(upstream.update(self.store, 'opencli')['status'], 'updated')

    def test_install_failure_keeps_original_and_auto_does_not_retry_same_release(self):
        upstream.policy(self.store, 'opencli', 'auto')
        with patch.object(upstream, 'latest', return_value=self.release), patch.object(upstream, 'prepare_candidate', side_effect=upstream.MaintenanceError('COMMAND_TIMEOUT')) as prepare:
            result = upstream.update(self.store, 'opencli', automatic=True)
            again = upstream.update(self.store, 'opencli', automatic=True)
        self.assertEqual(result['status'], 'failed')
        self.assertTrue(result['current_preserved'])
        self.assertEqual(again['status'], 'deferred')
        self.assertEqual(prepare.call_count, 1)
        self.assertEqual(Path(upstream.resolve_opencli(self.store)), self.baseline)

    def test_success_activates_only_lookup_and_rollback_restores_original(self):
        baseline_hash = upstream.digest(self.baseline)
        with patch.object(upstream, 'latest', return_value=self.release), patch.object(upstream, 'prepare_candidate', side_effect=self.candidate):
            result = upstream.update(self.store, 'opencli')
        self.assertEqual(result['status'], 'updated')
        self.assertFalse(result['validation']['business_verified'])
        self.assertEqual(upstream.installed(self.store, 'opencli')['current'], '2.0.3')
        self.assertEqual(upstream.digest(self.baseline), baseline_hash)
        self.assertEqual(upstream.rollback(self.store)['current'], '2.0.2')
        self.assertEqual(Path(upstream.resolve_opencli(self.store)), self.baseline)

    def test_in_use_dependency_defers_switch(self):
        with patch.object(upstream, 'latest', return_value=self.release), patch.object(upstream, 'prepare_candidate', side_effect=self.candidate), self.store.lock('usage', shared=True):
            result = upstream.update(self.store, 'opencli')
        self.assertEqual(result['status'], 'deferred')
        self.assertTrue(result['current_preserved'])
        self.assertEqual(Path(upstream.resolve_opencli(self.store)), self.baseline)

    def test_busy_candidate_is_reused_when_dependency_becomes_idle(self):
        with patch.object(upstream, 'latest', return_value=self.release), patch.object(upstream, 'prepare_candidate', side_effect=self.candidate) as prepare:
            with self.store.lock('usage', shared=True):
                self.assertEqual(upstream.update(self.store, 'opencli')['status'], 'deferred')
            result = upstream.update(self.store, 'opencli')
        self.assertEqual(result['status'], 'updated')
        self.assertEqual(prepare.call_count, 1)

    def test_auto_can_resume_after_first_notice_or_be_enabled_after_notification(self):
        with patch.object(upstream, 'latest', return_value=self.release):
            upstream.check(self.store, 'opencli')
        self.assertEqual(upstream.notices(self.store, ['opencli'])[0]['action'], 'notify')
        upstream.policy(self.store, 'opencli', 'auto')
        resumed = upstream.notices(self.store, ['opencli'])[0]
        self.assertEqual(resumed['action'], 'maintain')
        self.assertTrue(resumed['already_notified'])
        with patch.object(upstream, 'latest', return_value=self.release), patch.object(upstream, 'prepare_candidate', side_effect=self.candidate), self.store.lock('usage', shared=True):
            upstream.update(self.store, 'opencli', automatic=True)
        self.assertEqual(upstream.notices(self.store, ['opencli']), [])

    def test_interrupted_preparation_is_not_blindly_repeated(self):
        self.store.write('transaction.json', {'status': 'preparing', 'version': '2.0.3'})
        with patch.object(upstream, 'prepare_candidate') as prepare:
            self.assertEqual(upstream.update(self.store, 'opencli')['status'], 'interrupted')
        prepare.assert_not_called()

    def test_native_runner_rejects_corrupt_active_version(self):
        config = self.base / 'home/.config/lookup/opencli-binding.json'
        config.parent.mkdir(parents=True)
        config.write_text(json.dumps({'version': 1, 'browser': 'ego-lite',
                                      'context_id': 'fixture-context'}))
        candidate = self.candidate()
        self.store.write('active.json', candidate)
        Path(candidate['binary']).write_text('changed')
        runner = SCRIPT.with_name('opencli-run.mjs')
        result = subprocess.run(['node', str(runner), '--version'], capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 78)
        self.assertIn('ACTIVE_CONTENT_CHANGED', result.stderr)

    def test_cli_link_is_idempotent_and_preserves_unrelated_command(self):
        script = SCRIPT.with_name('install-cli.py')
        installer_spec = importlib.util.spec_from_file_location('lookup_cli_installer', script)
        installer = importlib.util.module_from_spec(installer_spec)
        installer_spec.loader.exec_module(installer)
        home = self.base/'cli-home'
        target = installer.install(home)
        self.assertEqual(installer.install(home), target)
        self.assertEqual(target.readlink(), SCRIPT.with_name('lookup'))
        other_home = self.base/'other-home'
        other = other_home/'.local/bin/lookup'
        other.parent.mkdir(parents=True)
        other.write_text('existing command')
        with self.assertRaisesRegex(RuntimeError, 'LOOKUP_COMMAND_EXISTS'):
            installer.install(other_home)
        self.assertEqual(other.read_text(), 'existing command')

    def test_post_switch_failure_restores_old_pointer(self):
        original = upstream.read_version
        calls = 0

        def read(binary, dependency):
            nonlocal calls
            if '/versions/' in str(binary):
                calls += 1
                if calls > 1:
                    raise upstream.MaintenanceError('ACTIVATION_VERIFY_FAILED')
            return original(binary, dependency)

        with patch.object(upstream, 'latest', return_value=self.release), patch.object(upstream, 'prepare_candidate', side_effect=self.candidate), patch.object(upstream, 'read_version', side_effect=read):
            result = upstream.update(self.store, 'opencli')
        self.assertEqual(result['status'], 'failed')
        self.assertTrue(result['current_preserved'])

    def test_changed_system_version_cannot_be_used_as_a_false_successful_rollback(self):
        with patch.object(upstream, 'latest', return_value=self.release), patch.object(upstream, 'prepare_candidate', side_effect=self.candidate):
            upstream.update(self.store, 'opencli')
        active = self.store.read('active.json')
        cli(self.baseline, '3.0.0')
        with self.assertRaisesRegex(upstream.MaintenanceError, 'ROLLBACK_TARGET_CHANGED'):
            upstream.rollback(self.store)
        self.assertEqual(self.store.read('active.json'), active)

    def test_custom_review_keeps_current_version_and_candidate_for_resumption(self):
        override = Path.home()/'.opencli/clis/custom/read.js'
        override.parent.mkdir(parents=True)
        override.write_text('user adapter')
        pending = {'status': 'manual_review', 'request': '/synthetic/review/request.json'}
        with patch.object(upstream, 'latest', return_value=self.release), patch.object(upstream, 'prepare_candidate', side_effect=self.candidate), patch.object(upstream, 'opencli_customizations', return_value=(pending, {})):
            self.assertEqual(upstream.update(self.store, 'opencli'), pending)
        self.assertEqual(self.store.read('transaction.json')['status'], 'manual_review')
        self.assertEqual(upstream.read_version(self.baseline, 'opencli'), '2.0.2')
        self.assertEqual(override.read_text(), 'user adapter')

    def test_candidate_help_writes_only_to_isolated_home(self):
        probe = self.base/'write-probe'
        probe.write_text('#!'+sys.executable+'\nimport pathlib\n(pathlib.Path.home()/"native-probe").touch()\nprint("guide")\n')
        probe.chmod(0o700)
        original = upstream.qualify
        def execute(binary, version, env=None):
            upstream.command([str(probe)], env=env)
            return {'checked': True}
        with patch.object(upstream, 'qualify', side_effect=execute):
            self.assertTrue(upstream.isolated_qualification(probe, '2.0.3')['checked'])
        self.assertFalse((Path.home()/'native-probe').exists())

    def test_write_permission_and_missing_fields_fail_qualification(self):
        for access, fields in [('write', ['text']), ('read', [])]:
            binary = cli(self.store.root/'versions/bad/opencli', '2.0.3', access, fields)
            with self.assertRaisesRegex(upstream.MaintenanceError, 'COMMAND_CONTRACT_CHANGED'):
                upstream.qualify(binary, '2.0.3')

    def test_unknown_major_is_not_installed(self):
        with patch.object(upstream, 'latest', return_value={**self.release, 'latest': '3.0.0'}), patch.object(upstream, 'prepare_candidate') as prepare:
            result = upstream.update(self.store, 'opencli')
        self.assertEqual(result['status'], 'manual_review')
        prepare.assert_not_called()

    def test_use_preserves_literal_arguments_and_exit_code(self):
        args = ['read', 'literal $(touch forbidden); spaces']
        process = subprocess.run([sys.executable, str(SCRIPT), 'use', '--expected', str(self.baseline), '--', *args],
                                 capture_output=True, text=True, timeout=5)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(json.loads(process.stdout)['args'], args)

    def test_lookup_upgrade_defaults_to_all_supported_dependencies(self):
        output = io.StringIO()
        with patch.object(upstream, 'update', return_value={'status': 'up_to_date', 'current': '1.0.0'}) as update, redirect_stdout(output):
            self.assertEqual(upstream.main(['upgrade']), 0)
        self.assertEqual([call.args[1] for call in update.call_args_list], list(upstream.UPDATE_DEPENDENCIES))
        self.assertEqual(json.loads(output.getvalue())['status'], 'batch')

    def test_unwritable_new_cache_does_not_block_original_cli(self):
        output = io.StringIO()
        with patch.object(upstream, 'Store', side_effect=PermissionError), redirect_stdout(output):
            self.assertEqual(upstream.main(['resolve']), 0)
        result = json.loads(output.getvalue())
        self.assertEqual(Path(result['binary']), self.baseline)
        self.assertFalse(result['supervised'])

    def test_existing_managed_state_does_not_fall_back_when_unreadable(self):
        self.store.write('active.json', {'binary': '/unreadable/managed'})
        with patch.object(upstream, 'Store', side_effect=PermissionError), patch('sys.stderr', io.StringIO()):
            self.assertEqual(upstream.main(['resolve']), 78)

    def test_interrupted_command_reaps_its_own_child(self):
        for signum in (signal.SIGINT, signal.SIGTERM):
            with self.subTest(signal=signum):
                record = self.base/('child-pid-'+str(signum))
                child_code = f'import os,time,pathlib;pathlib.Path({str(record)!r}).write_text(str(os.getpid()));time.sleep(30)'
                code = (f'import runpy; m=runpy.run_path({str(SCRIPT)!r});'
                        f'm["command"]([{sys.executable!r},"-c",{child_code!r}],timeout=25)')
                parent = subprocess.Popen([sys.executable, '-c', code], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                child_pid = None
                try:
                    deadline = time.monotonic()+3
                    while not record.exists() and time.monotonic()<deadline:
                        time.sleep(0.01)
                    self.assertTrue(record.exists())
                    child_pid = int(record.read_text())
                    parent.send_signal(signum)
                    parent.wait(timeout=3)
                    with self.assertRaises(ProcessLookupError):
                        os.kill(child_pid, 0)
                finally:
                    if parent.poll() is None:
                        parent.kill();parent.wait()
                    if child_pid is not None:
                        try: os.kill(child_pid, signal.SIGKILL)
                        except ProcessLookupError: pass


if __name__ == '__main__':
    unittest.main()
