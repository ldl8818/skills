"""Offline composition regressions for lifecycle maintenance."""
import contextlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import audit_upstream as audit
import core
import delete_skill
import lifecycle
import native_tools
import scan_and_check
import trace_source
import update_skill

ENTRY = '---\nname: demo\ndescription: Demo\n---\n# Mode\n'


class ReviewRegressionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='manager-regression-')
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name).resolve()
        self.live = self.home / '.agents/skills/demo'
        self.live.mkdir(parents=True)
        self.env = {**os.environ, 'HOME': str(self.home), 'USERPROFILE': str(self.home),
                    'SKILL_MANAGER_HOME': str(self.home / 'state'),
                    'XDG_CONFIG_HOME': str(self.home / '.config'),
                    'PYTHONDONTWRITEBYTECODE': '1'}
        overrides = {
            'STATE_DIR': str(self.home / 'state'),
            'FINGERPRINTS': str(self.home / 'state/data/fingerprints.json'),
            'DESCRIPTIONS_ZH': str(self.home / 'state/data/descriptions_zh.json'),
            'PROJECTS': str(self.home / 'state/data/projects.json'),
            'GLOBAL_SETTINGS': str(self.home / '.claude/settings.json'),
            'INSTALLED_PLUGINS_JSON': str(self.home / '.claude/plugins/installed_plugins.json'),
            'CLAUDE_DIR': str(self.home / '.claude'),
            '_MIGRATION_CHECKED': True,
        }
        for manager in (patch.dict(os.environ, self.env),
                        patch.object(tempfile, 'tempdir', str(self.home)),
                        patch.multiple(core, **overrides),
                        patch.object(core, 'global_skill_roots',
                                     return_value=[('shared', str(self.live.parent))]),
                        patch.object(core, 'known_projects', return_value=[]),
                        patch.object(update_skill, 'BACKUP_ROOT', str(self.home / 'backups')),
                        patch.object(delete_skill, 'ARCHIVE_ROOT', str(self.home / 'deleted'))):
            manager.start()
            self.addCleanup(manager.stop)
        self.prepare_live()

    def prepare_live(self, count=2):
        self.live.mkdir(parents=True, exist_ok=True)
        (self.live / 'SKILL.md').write_text(ENTRY.replace(
            '---\n# Mode', 'metadata:\n  github_url: https://github.com/example/demo\n'
            '  github_hash: ' + 'a' * 40 + '\n---\n# Mode'))
        for index in range(count - 1):
            (self.live / f'file{index:03}.py').write_text('VALUE = 1\n')

    @contextlib.contextmanager
    def update_fixture(self, count=2):
        def download(url, ref, destination):
            Path(destination, 'SKILL.md').write_text(ENTRY)
            for index in range(count - 1):
                Path(destination, f'file{index:03}.py').write_text(
                    'VALUE = 1\n' if ref == 'a' * 40 else 'VALUE = 2\n')
            return True
        with patch.object(update_skill, 'download_repo', side_effect=download), \
                patch.object(update_skill, 'resolve_update_target',
                             return_value=('v1.1.0', 'b' * 40, '')), \
                patch.object(update_skill, 'get_commit_date', return_value=None), \
                contextlib.redirect_stdout(io.StringIO()):
            yield

    def cli(self, script, *args):
        return subprocess.run([sys.executable, '-B', str(SCRIPTS / script), *args],
                              cwd=self.home, env=self.env, capture_output=True,
                              text=True, timeout=15)

    def test_interruption_at_each_rename_keeps_a_complete_live_skill(self):
        rename = os.rename
        for boundary in ('after_old', 'before_new', 'after_new'):
            self.live = self.home / boundary / 'demo'
            with self.subTest(boundary=boundary), patch.object(
                    core, 'global_skill_roots', return_value=[('shared', str(self.live.parent))]):
                self.prepare_live()
                def interrupt(source, destination):
                    installing = str(destination) == str(self.live) and '.stage-' in str(source)
                    retiring = str(source) == str(self.live)
                    if boundary == 'before_new' and installing:
                        raise KeyboardInterrupt()
                    result = rename(source, destination)
                    if (boundary == 'after_old' and retiring) or (boundary == 'after_new' and installing):
                        raise KeyboardInterrupt()
                    return result
                with self.update_fixture(), patch.object(os, 'rename', side_effect=interrupt):
                    with self.assertRaises(KeyboardInterrupt):
                        update_skill.update_direct_skill('demo')
                self.assertTrue((self.live / 'SKILL.md').is_file())
                self.assertIn((self.live / 'file000.py').read_text(),
                              ('VALUE = 1\n', 'VALUE = 2\n'))

    @unittest.skipUnless(hasattr(os, 'fork'), 'requires POSIX process isolation')
    def test_process_loss_between_renames_is_recovered_on_next_update(self):
        rename = os.rename
        for boundary in ('after_old', 'after_new'):
            self.live = self.home / boundary / 'demo'
            with self.subTest(boundary=boundary), patch.object(
                    core, 'global_skill_roots', return_value=[('shared', str(self.live.parent))]):
                self.prepare_live()
                with self.update_fixture():
                    child = os.fork()
                    if child == 0:
                        def stop(source, destination):
                            result = rename(source, destination)
                            if ((boundary == 'after_old' and str(source) == str(self.live))
                                    or (boundary == 'after_new' and '.stage-' in str(source))):
                                os.kill(os.getpid(), signal.SIGKILL)
                            return result
                        with patch.object(os, 'rename', side_effect=stop):
                            update_skill.update_direct_skill('demo')
                        os._exit(72)
                    _, status = os.waitpid(child, 0)
                    self.assertEqual(os.waitstatus_to_exitcode(status), -signal.SIGKILL)
                    self.assertTrue(update_skill.update_one('demo'))
                self.assertEqual((self.live / 'file000.py').read_text(), 'VALUE = 2\n')
                self.assertFalse(list(self.live.parent.glob('demo.old-*')))
                self.assertFalse(list(self.live.parent.glob('.demo.stage-*')))

    @unittest.skipUnless(hasattr(os, 'fork'), 'requires POSIX process isolation')
    def test_sigterm_during_switch_recovers_and_restores_signal_handlers(self):
        rename = os.rename
        handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGHUP)}
        for boundary in ('after_old', 'after_new'):
            self.live = self.home / boundary / 'demo'
            with self.subTest(boundary=boundary), patch.object(
                    core, 'global_skill_roots', return_value=[('shared', str(self.live.parent))]):
                self.prepare_live()
                with self.update_fixture():
                    child = os.fork()
                    if child == 0:
                        def interrupt(source, destination):
                            result = rename(source, destination)
                            if ((boundary == 'after_old' and str(source) == str(self.live))
                                    or (boundary == 'after_new' and '.stage-' in str(source))):
                                os.kill(os.getpid(), signal.SIGTERM)
                            return result
                        try:
                            with patch.object(os, 'rename', side_effect=interrupt):
                                update_skill.update_direct_skill('demo')
                        except KeyboardInterrupt:
                            restored = all(signal.getsignal(sig) == handler
                                           for sig, handler in handlers.items())
                            os._exit(73 if restored else 74)
                        os._exit(72)
                    _, status = os.waitpid(child, 0)
                self.assertEqual(os.waitstatus_to_exitcode(status), 73)
                expected = 'VALUE = 1\n' if boundary == 'after_old' else 'VALUE = 2\n'
                self.assertEqual((self.live / 'file000.py').read_text(), expected)

    def test_secondary_recovery_failure_preserves_original_exception_and_material(self):
        rename = os.rename
        def interrupt_and_fail_restore(source, destination):
            if '.stage-' in str(source) and str(destination) == str(self.live):
                raise SystemExit(17)
            if '.old-' in str(source) and str(destination) == str(self.live):
                raise PermissionError('synthetic rollback failure')
            return rename(source, destination)
        with self.update_fixture(), patch.object(os, 'rename', side_effect=interrupt_and_fail_restore):
            with self.assertRaises(SystemExit) as raised:
                update_skill.update_direct_skill('demo')
        self.assertEqual(raised.exception.code, 17)
        self.assertFalse(self.live.exists())
        journal = Path(core.direct_state_dir(self.live)) / 'transaction.json'
        self.assertTrue(journal.is_file())
        saved = json.loads(journal.read_text())
        self.assertTrue(Path(saved['old'], 'SKILL.md').is_file())
        self.assertTrue(Path(saved['stage'], 'SKILL.md').is_file())
        with self.update_fixture():
            self.assertTrue(update_skill.update_one('demo'))
        self.assertFalse(journal.exists())

    def test_recovery_drift_preserves_all_material_for_manual_review(self):
        rename = os.rename
        def interrupt_and_fail_restore(source, destination):
            if '.stage-' in str(source):
                raise SystemExit(17)
            if '.old-' in str(source):
                raise PermissionError('synthetic rollback failure')
            return rename(source, destination)
        with self.update_fixture(), patch.object(os, 'rename', side_effect=interrupt_and_fail_restore):
            with self.assertRaises(SystemExit):
                update_skill.update_direct_skill('demo')
        journal = Path(core.direct_state_dir(self.live)) / 'transaction.json'
        saved = json.loads(journal.read_text())
        Path(saved['old'], 'file000.py').write_text('LOCAL_EDIT = True\n')
        with self.update_fixture():
            self.assertFalse(update_skill.update_one('demo'))
        self.assertTrue(journal.is_file())
        self.assertEqual(Path(saved['old'], 'file000.py').read_text(), 'LOCAL_EDIT = True\n')
        self.assertTrue(Path(saved['stage'], 'SKILL.md').is_file())

    def test_delete_restores_cache_even_when_settings_rollback_also_fails(self):
        cached = self.home / '.claude/plugins/cache/market/demo/1.0'
        (cached / 'skills/guide').mkdir(parents=True)
        (cached / 'skills/guide/SKILL.md').write_text(ENTRY)
        key = 'demo@market'
        registry = {'plugins': {key: [{'installPath': str(cached)}]}}
        core.write_json(core.INSTALLED_PLUGINS_JSON, registry)
        core.write_json(core.GLOBAL_SETTINGS, {'enabledPlugins': {key: True}})
        core.write_json(core.DESCRIPTIONS_ZH, {'guide': 'synthetic description'})
        write = core.write_json
        def fail_settings(path, data):
            if path == core.GLOBAL_SETTINGS:
                raise PermissionError('synthetic settings failure')
            return write(path, data)
        with patch.object(core, 'write_json', side_effect=fail_settings), \
                contextlib.redirect_stdout(io.StringIO()), self.assertRaises(PermissionError):
            delete_skill.delete_plugin(key)
        self.assertTrue(cached.is_dir())
        self.assertEqual(core.read_json(core.INSTALLED_PLUGINS_JSON), registry)
        self.assertEqual(core.read_json(core.DESCRIPTIONS_ZH), {'guide': 'synthetic description'})

    def test_download_preserves_regular_modes_and_strips_special_bits(self):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode='w:gz') as archive:
            for name, mode in (('run.sh', 0o6755), ('data.txt', 0o644)):
                content = b'#!/bin/sh\nexit 0\n'
                item = tarfile.TarInfo('repo/' + name)
                item.size, item.mode = len(content), mode
                archive.addfile(item, io.BytesIO(content))
            link = tarfile.TarInfo('repo/alias.sh')
            link.type, link.linkname = tarfile.SYMTYPE, 'run.sh'
            archive.addfile(link)
        root = self.home / 'download'
        with patch.object(update_skill.urllib.request, 'urlopen',
                          return_value=io.BytesIO(stream.getvalue())):
            update_skill.download_repo('https://github.com/example/demo', 'a' * 40, str(root))
        self.assertEqual((root / 'run.sh').stat().st_mode & 0o7777, 0o755)
        self.assertEqual((root / 'alias.sh').stat().st_mode & 0o7777, 0o755)
        self.assertEqual((root / 'data.txt').stat().st_mode & 0o7777, 0o644)
        self.assertEqual(subprocess.run([str(root / 'run.sh')]).returncode, 0)

    def test_delete_continues_other_restores_after_registry_rollback_fails(self):
        cached = self.home / '.claude/plugins/cache/market/demo/1.0'
        (cached / 'skills/guide').mkdir(parents=True)
        (cached / 'skills/guide/SKILL.md').write_text(ENTRY)
        key = 'demo@market'
        registry = {'plugins': {key: [{'installPath': str(cached)}]}}
        descriptions = {'guide': 'synthetic description'}
        core.write_json(core.INSTALLED_PLUGINS_JSON, registry)
        core.write_json(core.GLOBAL_SETTINGS, {'enabledPlugins': {key: True}})
        core.write_json(core.DESCRIPTIONS_ZH, descriptions)
        write = core.write_json
        original = OSError('initial settings failure')
        def fail_independently(path, data):
            if path == core.GLOBAL_SETTINGS:
                raise original
            if path == core.INSTALLED_PLUGINS_JSON and data == registry:
                raise PermissionError('registry rollback failure')
            return write(path, data)
        output = io.StringIO()
        with patch.object(core, 'write_json', side_effect=fail_independently), \
                contextlib.redirect_stdout(output), self.assertRaises(OSError) as raised:
            delete_skill.delete_plugin(key)
        self.assertIs(raised.exception, original)
        self.assertTrue(cached.is_dir())
        self.assertEqual(core.read_json(core.DESCRIPTIONS_ZH), descriptions)
        self.assertIn('registry rollback failure', output.getvalue())

    def test_out_of_band_disable_invalidates_the_update_candidate(self):
        verify = audit.verify
        def disable(root, receipt, source=None):
            errors = verify(root, receipt, source)
            if '.stage-' in str(root):
                (self.live / 'SKILL.md').rename(self.live / 'SKILL.md.disabled')
            return errors
        with self.update_fixture(), patch.object(audit, 'verify', side_effect=disable):
            self.assertFalse(update_skill.update_direct_skill('demo'))
        self.assertTrue((self.live / 'SKILL.md.disabled').exists())
        self.assertFalse((self.live / 'SKILL.md').exists())

    def test_out_of_band_chmod_invalidates_the_update_candidate(self):
        verify = audit.verify
        helper = self.live / 'file000.py'
        helper.chmod(0o644)
        def chmod(root, receipt, source=None):
            errors = verify(root, receipt, source)
            if '.stage-' in str(root):
                helper.chmod(0o755)
            return errors
        with self.update_fixture(), patch.object(audit, 'verify', side_effect=chmod):
            self.assertFalse(update_skill.update_direct_skill('demo'))
        self.assertEqual(helper.stat().st_mode & 0o777, 0o755)
        self.assertEqual(helper.read_text(), 'VALUE = 1\n')

    def test_disabled_update_preserves_entry_and_executable_mode(self):
        (self.live / 'SKILL.md').rename(self.live / 'SKILL.md.disabled')
        def download(url, ref, destination):
            Path(destination, 'SKILL.md').write_text(ENTRY)
            helper = Path(destination, 'file000.py')
            helper.write_text('VALUE = 1\n' if ref == 'a' * 40 else 'VALUE = 2\n')
            helper.chmod(0o755)
            return True
        with self.update_fixture(), patch.object(update_skill, 'download_repo', side_effect=download):
            self.assertTrue(update_skill.update_direct_skill('demo'))
        self.assertTrue((self.live / 'SKILL.md.disabled').is_file())
        self.assertFalse((self.live / 'SKILL.md').exists())
        self.assertEqual((self.live / 'file000.py').stat().st_mode & 0o7777, 0o755)

    def test_toggle_cannot_interleave_with_an_update(self):
        verify = audit.verify
        attempts = []
        def toggle(root, receipt, source=None):
            if '.stage-' in str(root):
                attempts.append(self.cli('toggle_skill.py', 'disable', 'demo'))
            return verify(root, receipt, source)
        with self.update_fixture(), patch.object(audit, 'verify', side_effect=toggle):
            self.assertTrue(update_skill.update_direct_skill('demo'))
        self.assertEqual(len(attempts), 1)
        self.assertNotEqual(attempts[0].returncode, 0)
        self.assertTrue((self.live / 'SKILL.md').exists())
        self.assertEqual(self.cli('toggle_skill.py', 'disable', 'demo').returncode, 0)
        self.assertTrue((self.live / 'SKILL.md.disabled').exists())

    def test_native_sigterm_stops_owned_child_and_restores_handlers(self):
        pid_file = self.home / 'child.pid'
        release, marker = self.home / 'release', self.home / 'unexpected-write'
        child_code = (
            'import os,time\nfrom pathlib import Path\n'
            f'Path({str(pid_file)!r}).write_text(str(os.getpid()))\n'
            f'while not Path({str(release)!r}).exists(): time.sleep(0.01)\n'
            f'Path({str(marker)!r}).write_text("late write")\n')
        parent_code = (
            f'import sys; sys.path.insert(0, {str(SCRIPTS)!r}); import native_tools\n'
            f'native_tools.run([sys.executable, "-c", {child_code!r}], timeout=10)\n')
        parent = subprocess.Popen([sys.executable, '-B', '-c', parent_code], env=self.env,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        child_pid = None
        try:
            deadline = time.monotonic() + 5
            while not pid_file.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(pid_file.exists(), 'synthetic child did not start')
            child_pid = int(pid_file.read_text())
            parent.send_signal(signal.SIGTERM)
            self.assertNotEqual(parent.wait(timeout=5), 0)
            release.touch()
            deadline = time.monotonic() + 0.3
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertFalse(marker.exists(), 'child survived parent termination')
        finally:
            if parent.poll() is None:
                parent.kill()
                parent.wait()
            if child_pid:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(child_pid, signal.SIGKILL)
        handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGHUP)}
        self.assertEqual(native_tools.run([sys.executable, '-c', 'print("ok")']).strip(), 'ok')
        for sig, handler in handlers.items():
            self.assertEqual(signal.getsignal(sig), handler)

    def test_lookup_unknown_result_is_not_reinvoked_when_configs_are_unchanged(self):
        for nested in (False, True):
            with self.subTest(nested=nested), patch.object(core, 'STATE_DIR',
                                                         str(self.home / str(nested))):
                unknown = {'status': 'outcome_unknown', 'retry_safe': False}
                payload = {'status': 'batch', 'results': [unknown]} if nested else unknown
                callback = Mock(return_value=(payload, 1))
                first, first_code = native_tools.guard_lookup(callback)
                state = Path(core.STATE_DIR) / 'native/lookup/state.json'
                before = state.read_bytes()
                second, second_code = native_tools.guard_lookup(callback)
                self.assertEqual((first_code, second_code), (1, 1))
                self.assertTrue(first['config_unchanged'])
                self.assertIs(second.get('retry_safe'), False)
                self.assertEqual(callback.call_count, 1)
                self.assertEqual(state.read_bytes(), before)

    def assert_historical_retry_guard(self, marker, unsafe_value):
        for nested in (False, True):
            for unsafe in (False, True):
                with self.subTest(nested=nested, unsafe=unsafe), patch.object(
                        core, 'STATE_DIR', str(self.home / f'{marker}-{nested}-{unsafe}')):
                    item = {'status': 'failed', marker: unsafe_value if unsafe else not unsafe_value}
                    previous = {'status': 'batch', 'results': [item]} if nested else item
                    previous = {**previous, 'config_unchanged': True}
                    state = Path(core.STATE_DIR) / 'native/lookup/state.json'
                    core.write_json(str(state), previous)
                    before = state.read_bytes()
                    callback = Mock(return_value=({'status': 'updated'}, 0))
                    result, code = native_tools.guard_lookup(callback)
                    if unsafe:
                        callback.assert_not_called()
                        self.assertEqual((code, result['status']), (1, 'manual_review'))
                        self.assertIs(result.get('retry_safe'), False)
                        self.assertEqual(state.read_bytes(), before)
                    else:
                        callback.assert_called_once_with()
                        self.assertEqual((code, result['status']), (0, 'updated'))

    def test_lookup_historical_outcome_unknown_blocks_retry_without_retry_safe(self):
        self.assert_historical_retry_guard('outcome_unknown', True)

    def test_lookup_historical_current_not_preserved_blocks_retry_without_retry_safe(self):
        self.assert_historical_retry_guard('current_preserved', False)

    def test_lookup_pending_blocks_retry_but_semantic_review_can_resume(self):
        for status in ('pending', 'invoking', 'interrupted', 'unexpected', 'unknown',
                       'manual_review', 'deferred'):
            with self.subTest(status=status), patch.object(
                    core, 'STATE_DIR', str(self.home / status)):
                callback = Mock(return_value=({'status': status}, 1))
                native_tools.guard_lookup(callback)
                native_tools.guard_lookup(callback)
                self.assertEqual(callback.call_count, 2 if status in ('manual_review', 'deferred') else 1)

    def test_lookup_unreadable_receipt_is_unknown_and_never_automatically_retried(self):
        scripts = self.live / 'scripts'
        scripts.mkdir()
        for name in ('upstream.py', 'self_update.py'):
            (scripts / name).write_text('')
        counter = self.home / 'invocations'
        (scripts / 'owned_process.py').write_text(
            'from pathlib import Path\nfrom types import SimpleNamespace\n'
            'def run(command, timeout):\n'
            f'    path = Path({str(counter)!r})\n'
            '    path.write_text(path.read_text() + "x" if path.exists() else "x")\n'
            '    return SimpleNamespace(stdout="not JSON", stderr="", returncode=0)\n')
        first, code = lifecycle.invoke(self.live)
        self.assertEqual(code, 1)
        self.assertIs(first.get('retry_safe'), False)
        lifecycle.invoke(self.live)
        self.assertEqual(counter.read_text(), 'x')

    def test_batch_preserves_project_scope_and_deduplicates_by_entity(self):
        second = self.home / 'project/.agents/skills/demo'
        second.mkdir(parents=True)
        (second / 'SKILL.md').write_text(ENTRY)
        def record(path, scope):
            return core.Skill(name='demo', path=str(path), md_path=str(path / 'SKILL.md'),
                              source='github', version='1.0', enabled=True, plugin_key='',
                              github_url='https://github.com/example/demo', github_hash='a' * 40,
                              github_ref='', scope=scope)
        skills = [record(self.live, 'global'), record(second, str(self.home / 'project')),
                  record(self.live, str(self.home / 'alias-project'))]
        with patch.object(core, 'collect_all', return_value=skills):
            targets = scan_and_check.build_targets()
            with patch.object(scan_and_check, 'remote_latest', return_value=('v1.1.0', 'b' * 40)), \
                    patch.object(update_skill, 'update_direct_skill', return_value=True) as update, \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertTrue(update_skill.update_all())
        self.assertEqual(len(targets), 2)
        actual = {call.kwargs['target_path']: call.kwargs.get('project')
                  for call in update.call_args_list}
        self.assertEqual(actual, {str(self.live): None,
                                 str(second): str(self.home / 'project')})

    def test_toggle_bare_name_uses_the_same_target_as_update_and_delete(self):
        key = 'demo@market'
        core.write_json(core.INSTALLED_PLUGINS_JSON, {'plugins': {key: [{}]}})
        core.write_json(core.GLOBAL_SETTINGS, {'enabledPlugins': {key: True}})
        self.assertEqual(core.resolve_target('demo', quiet=True)[0], 'skill')
        result = self.cli('toggle_skill.py', 'disable', 'demo')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.live / 'SKILL.md.disabled').exists())
        self.assertTrue(core.read_json(core.GLOBAL_SETTINGS)['enabledPlugins'][key])
        self.assertEqual(self.cli('toggle_skill.py', 'disable', key).returncode, 0)
        self.assertFalse(core.read_json(core.GLOBAL_SETTINGS)['enabledPlugins'][key])

    def test_trace_rejects_source_hints_outside_downloaded_snapshot(self):
        root = self.home / 'source'
        root.mkdir()
        for hint in (str(self.live), os.path.relpath(self.live, root)):
            with self.subTest(hint=hint), self.assertRaises(ValueError):
                trace_source.find_skill_dir(str(root), 'demo', hint)
        valid = root / 'skills/demo'
        valid.mkdir(parents=True)
        (valid / 'SKILL.md').write_text(ENTRY)
        self.assertEqual(Path(trace_source.find_skill_dir(str(root), 'demo', 'skills/demo')), valid)
        (root / 'escape').symlink_to(self.live, target_is_directory=True)
        with self.assertRaises(ValueError):
            trace_source.find_skill_dir(str(root), 'demo', 'escape')
        (valid / 'SKILL.md').write_text(ENTRY.replace('name: demo', 'name: other'))
        with self.assertRaises(ValueError):
            trace_source.find_skill_dir(str(root), 'demo', 'skills/demo')

    def test_stage_reads_scale_linearly(self):
        measurements = []
        original = audit.local_files
        for count in (32, 64):
            self.prepare_live(count)
            scans = []
            def measured(path):
                data = original(path)
                if '.stage-' in str(path):
                    scans.append((len(data), sum(map(len, data.values()))))
                return data
            with self.update_fixture(count), patch.object(audit, 'local_files', side_effect=measured):
                self.assertTrue(update_skill.update_direct_skill('demo'))
            measurements.append({'files': count, 'stage_scans': len(scans),
                                 'file_reads': sum(row[0] for row in scans),
                                 'bytes_read': sum(row[1] for row in scans)})
        print('PERF ' + json.dumps(measurements, sort_keys=True))
        for sample in measurements:
            self.assertLessEqual(sample['file_reads'], sample['files'] * 8)
        self.assertLessEqual(measurements[1]['file_reads'], measurements[0]['file_reads'] * 2 + 8)

    def test_empty_check_has_a_successful_human_and_json_result(self):
        with tempfile.TemporaryDirectory(prefix='manager-empty-') as temporary:
            env = {**self.env, 'HOME': temporary, 'USERPROFILE': temporary,
                   'SKILL_MANAGER_HOME': str(Path(temporary) / 'state')}
            for args in ([], ['--json']):
                result = subprocess.run([sys.executable, '-B', str(SCRIPTS / 'scan_and_check.py'), *args],
                                        env=env, cwd=temporary, capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertNotIn('Traceback', result.stderr)


if __name__ == '__main__':
    unittest.main()
