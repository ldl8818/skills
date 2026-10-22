"""Total-update scope, self-source preservation and real isolated Git/CLI coverage."""
from contextlib import contextmanager, redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch


LOOKUP = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('lookup_total_tests', LOOKUP / 'scripts/upstream.py')
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)
own = api.self_update
audit = api.customization


def tree(root, version='1.0.0', extra='old'):
    root.mkdir(parents=True, exist_ok=True)
    (root / 'scripts').mkdir(exist_ok=True)
    (root / 'SKILL.md').write_text('---\nname: lookup\ndescription: Synthetic lookup\n'
        f'metadata:\n  source: local\n  version: "{version}"\n---\n# Lookup\n')
    (root / 'scripts/lookup').write_text('# synthetic entry\n')
    (root / 'scripts/customization.py').write_text('# synthetic source\n')
    (root / 'scripts/self_update.py').write_text('# synthetic source\n')
    (root / 'scripts/owned_process.py').write_text('# synthetic source\n')
    (root / 'scripts/upstream.py').write_text("# 'upgrade' '--self-only'\n" +
        'import json,sys\n'
        'if "--help" in sys.argv: print("update upgrade --self-only opencli agent-reach ego-browser");sys.exit(0)\n'
        + 'print(json.dumps({"status":"batch","results":[' +
        ','.join(repr({'dependency': name, 'status': 'not_installed', 'executor': extra})
                 for name in api.UPDATE_DEPENDENCIES) + ']}))\n')
    (root / 'scripts/read.py').write_text('def read(value):\n    return value or ""\n')
    return root


class SourceUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='lookup-total-')
        self.root = Path(self.temp.name)
        self.store = api.Store(self.root / 'state')
        self.base = tree(self.root / 'base')
        self.live = self.root / 'live'
        shutil.copytree(self.base, self.live)
        self.new = tree(self.root / 'new', '1.1.0', 'new')
        self.revision = 'a' * 40

    def tearDown(self):
        self.temp.cleanup()

    @contextmanager
    def remote(self, known=True):
        @contextmanager
        def snapshot(*args):
            yield self.base if known else None, self.new, self.revision
        with patch.object(own, 'source', snapshot):
            yield

    def test_pristine_switch_keeps_runtime_files_and_full_recovery(self):
        (self.live / '.env').write_text('SYNTHETIC_ONLY=retained\n')
        (self.live / 'node_modules').mkdir()
        (self.live / 'node_modules/local').write_text('retained')
        before = audit.files(self.live)
        with self.remote():
            result = own.update(self.store, self.live, audit)
        self.assertEqual(result['status'], 'updated')
        self.assertEqual(own.version(self.live), '1.1.0')
        self.assertEqual(audit.files(Path(result['recovery'])), before)
        self.assertEqual((self.live / '.env').read_text(), 'SYNTHETIC_ONLY=retained\n')
        self.assertEqual((self.live / 'node_modules/local').read_text(), 'retained')

    def test_unknown_baseline_generates_material_and_changes_nothing(self):
        before = audit.files(self.live)
        with self.remote(known=False):
            result = own.update(self.store, self.live, audit)
        self.assertEqual(result['status'], 'manual_review')
        self.assertEqual(audit.files(self.live), before)
        request = json.loads(Path(result['request']).read_text())
        self.assertFalse(request['scopes'][0]['base_known'])
        self.assertEqual(request['target'], self.revision)

    def test_higher_local_version_still_merges_changed_upstream_source(self):
        entry = self.live / 'SKILL.md'
        entry.write_text(entry.read_text().replace('"1.0.0"', '"2.0.0"'))
        (self.new / 'new-feature.txt').write_text('new source capability')
        with self.remote():
            self.assertEqual(own.inspect(self.store, self.live, audit)['status'], 'update_available')
            self.assertEqual(own.update(self.store, self.live, audit)['status'], 'manual_review')
            directory, request = audit.load(self.store, 'lookup')
            merged = directory / '0/merged/SKILL.md'
            merged.write_text(merged.read_text().replace('"1.1.0"', '"2.0.0"'))
            decision = self.root / 'version-decision.json'
            decision.write_text(json.dumps({'target': self.revision, 'decisions': [{
                'scope': 'lookup', 'path': 'SKILL.md', 'disposition': 'preserved',
                'reason': 'Keep the independent local version without hiding new source content.',
                'evidence': 'Only the version metadata differs in this source entry.',
                'validation': 'Merged source includes the new-feature file and retains version 2.0.0.'}],
                'adaptations': [{'scope': 'lookup', 'path': 'SKILL.md', 'reason': 'Prevent version downgrade.'}]}))
            audit.accept(self.store, 'lookup', decision)
            result = own.update(self.store, self.live, audit)
            self.assertEqual(result['status'], 'updated')
            self.assertEqual(own.version(self.live), '2.0.0')
            self.assertEqual((self.live / 'new-feature.txt').read_text(), 'new source capability')
            remembered = own.baseline(self.store, self.live.resolve(), self.root / 'remembered-base',
                                      audit, None, self.revision)
            self.assertEqual(audit.files(remembered), audit.files(self.new))
            with patch.object(self, 'base', remembered):
                self.assertEqual(own.update(self.store, self.live, audit)['status'], 'local_ahead')

    def test_snapshot_drift_cannot_bind_stale_local_content_to_a_new_live_hash(self):
        original = audit.copy_source
        def edit_after_copy(source, destination):
            original(source, destination)
            if Path(source) == self.live:
                (self.live / 'new-edit.txt').write_text('concurrent edit')
        with patch.object(audit, 'copy_source', side_effect=edit_after_copy):
            with self.assertRaisesRegex(audit.ReviewError, 'CHANGED_DURING_SNAPSHOT'):
                audit.create(self.store, 'lookup', self.revision, [{
                    'name': 'lookup', 'live': self.live, 'base': self.base, 'upstream': self.new}])
        self.assertEqual((self.live / 'new-edit.txt').read_text(), 'concurrent edit')
        self.assertEqual(self.store.read('review-lookup.json'), {})

    def test_absorbed_customization_review_applies_new_source(self):
        preserved = 'def read(value):\n    return value\n'
        (self.live / 'scripts/read.py').write_text(preserved)
        (self.new / 'scripts/read.py').write_text(preserved)
        with self.remote():
            self.assertEqual(own.update(self.store, self.live, audit)['status'], 'manual_review')
            directory, request = audit.load(self.store, 'lookup')
            namespace = {}
            exec((directory / '0/merged/scripts/read.py').read_text(), namespace)
            self.assertIsNone(namespace['read'](None))
            self.assertEqual(namespace['read']('text'), 'text')
            decision = self.root / 'decision.json'
            decision.write_text(json.dumps({'target': self.revision, 'decisions': [{
                'scope': 'lookup', 'path': 'scripts/read.py', 'disposition': 'absorbed',
                'reason': 'Upstream now preserves empty values.',
                'evidence': 'Compared all three complete read implementations.',
                'validation': 'Executed merged read(None) and read(text).'}], 'adaptations': []}))
            audit.accept(self.store, 'lookup', decision)
            result = own.update(self.store, self.live, audit)
        self.assertEqual(result['status'], 'updated')
        self.assertEqual((self.live / 'scripts/read.py').read_text(), preserved)

    def test_drift_requires_restart_and_preserves_new_local_content(self):
        (self.live / 'local.txt').write_text('original custom')
        with self.remote():
            own.update(self.store, self.live, audit)
            (self.live / 'local.txt').write_text('concurrent custom')
            with self.assertRaisesRegex(audit.ReviewError, 'CHANGED_DURING_REVIEW'):
                own.update(self.store, self.live, audit)
            audit.restart(self.store, 'lookup')
            self.assertEqual(own.update(self.store, self.live, audit)['status'], 'manual_review')
        self.assertEqual((self.live / 'local.txt').read_text(), 'concurrent custom')

    def test_failed_activation_restores_complete_original(self):
        before = own.complete_state(self.live)
        original = own.os.rename
        def fail_candidate(source, destination):
            if Path(source).name == 'next':
                raise OSError('synthetic activation failure')
            return original(source, destination)
        with self.remote(), patch.object(own.os, 'rename', side_effect=fail_candidate):
            with self.assertRaises(OSError):
                own.update(self.store, self.live, audit)
        self.assertEqual(own.complete_state(self.live), before)
        self.assertTrue(self.store.read('self-transaction.json')['restored'])
        self.assertEqual(self.store.read('self-source.json'), {})

    def test_retained_customization_keeps_new_upstream_capability(self):
        preserved = 'def read(value):\n    return value\n'
        (self.live / 'scripts/read.py').write_text(preserved)
        (self.new / 'scripts/read.py').write_text(
            'def read(value):\n    return value or ""\n\ndef page(items):\n    return list(items)\n')
        with self.remote():
            own.update(self.store, self.live, audit)
            directory, request = audit.load(self.store, 'lookup')
            merged = directory / '0/merged/scripts/read.py'
            merged.write_text(preserved + '\ndef page(items):\n    return list(items)\n')
            namespace = {}
            exec(merged.read_text(), namespace)
            self.assertIsNone(namespace['read'](None))
            self.assertEqual(namespace['page'](range(3)), [0, 1, 2])
            decision = self.root / 'preserve.json'
            decision.write_text(json.dumps({'target': self.revision, 'decisions': [{
                'scope': 'lookup', 'path': 'scripts/read.py', 'disposition': 'preserved',
                'reason': 'New source still loses None.', 'evidence': 'Compared read implementations.',
                'validation': 'Executed None preservation and the new page(range(3)) behavior.'}],
                'adaptations': [{'scope': 'lookup', 'path': 'scripts/read.py',
                                 'reason': 'Retain None while preserving upstream pagination.'}]}))
            audit.accept(self.store, 'lookup', decision)
            own.update(self.store, self.live, audit)
        namespace = {}
        exec((self.live / 'scripts/read.py').read_text(), namespace)
        self.assertIsNone(namespace['read'](None))
        self.assertEqual(namespace['page'](range(3)), [0, 1, 2])

    def test_concurrent_edit_after_switch_is_preserved_and_blocks_replay(self):
        def edit_then_fail(*args):
            (self.live / 'concurrent.txt').write_text('must survive')
            raise OSError('synthetic state write failure')
        with self.remote(), patch.object(own, 'remember', side_effect=edit_then_fail):
            with self.assertRaises(OSError):
                own.update(self.store, self.live, audit)
        self.assertEqual((self.live / 'concurrent.txt').read_text(), 'must survive')
        self.assertTrue(Path(self.store.read('self-transaction.json')['recovery']).is_dir())
        with self.remote():
            self.assertEqual(own.update(self.store, self.live, audit)['status'], 'outcome_unknown')
            self.assertEqual(own.inspect(self.store, self.live, audit)['status'], 'outcome_unknown')

    def test_disabled_skill_stays_disabled(self):
        (self.live / 'SKILL.md').rename(self.live / 'SKILL.md.disabled')
        with self.remote():
            result = own.update(self.store, self.live, audit)
        self.assertEqual(result['status'], 'updated')
        self.assertFalse((self.live / 'SKILL.md').exists())
        self.assertEqual(own.version(self.live), '1.1.0')

    def test_disabled_customization_review_uses_canonical_source_entry(self):
        (self.live / 'SKILL.md').rename(self.live / 'SKILL.md.disabled')
        (self.live / 'scripts/read.py').write_text('def read(value):\n    return value\n')
        (self.new / 'scripts/read.py').write_text('def read(value):\n    return value\n')
        with self.remote():
            own.update(self.store, self.live, audit)
            directory, request = audit.load(self.store, 'lookup')
            self.assertEqual(request['scopes'][0]['customizations'], ['scripts/read.py'])
            self.assertTrue((directory / '0/local/SKILL.md').is_file())
            decision = self.root / 'decision.json'
            decision.write_text(json.dumps({'target': self.revision, 'decisions': [{
                'scope': 'lookup', 'path': 'scripts/read.py', 'disposition': 'absorbed',
                'reason': 'Both implementations preserve values.', 'evidence': 'Complete source comparison.',
                'validation': 'Equivalent None and text inputs verified in the adjacent regression.'}],
                'adaptations': []}))
            audit.accept(self.store, 'lookup', decision)
            result = own.update(self.store, self.live, audit)
        self.assertEqual(result['status'], 'updated')
        self.assertFalse((self.live / 'SKILL.md').exists())
        self.assertEqual(own.version(self.live), '1.1.0')

    def test_total_update_reloads_new_executor_and_preserves_result_scope(self):
        shutil.copytree(self.new, self.live, dirs_exist_ok=True)
        with patch.object(api, 'ROOT', self.live), patch.object(own, 'update', return_value={
                'dependency': 'lookup', 'status': 'updated', 'current': '1.1.0'}):
            result = api.maintain(self.store)
        self.assertEqual([r['dependency'] for r in result['results']], ['lookup', *api.UPDATE_DEPENDENCIES])
        self.assertTrue(all(r['executor'] == 'new' for r in result['results'][1:]))

    def test_reloaded_executor_owns_its_current_dependency_inventory(self):
        items = [{'dependency': name, 'status': 'not_installed'}
                 for name in (*api.UPDATE_DEPENDENCIES, 'optional-example')]
        (self.live / 'scripts/upstream.py').write_text(
            'print(' + repr(json.dumps({'status': 'batch', 'results': items})) + ')\n')
        with patch.object(api, 'ROOT', self.live), patch.object(own, 'update', return_value={
                'dependency': 'lookup', 'status': 'updated', 'current': '1.1.0'}):
            result = api.maintain(self.store)
        self.assertEqual(result['results'][1:], items)
        self.assertFalse(api.result_failed(result))

    def test_total_continues_existing_dependency_checks_after_self_review(self):
        with patch.object(api, 'ROOT', self.live), patch.object(own, 'update', return_value={
                'dependency': 'lookup', 'status': 'manual_review'}), patch.object(api, 'update_all', return_value={
                'status': 'batch', 'results': [{'dependency': 'opencli', 'status': 'up_to_date'}]}) as dependencies:
            result = api.maintain(self.store)
        dependencies.assert_called_once()
        self.assertTrue(api.result_failed(result))

    def test_cli_scopes_and_legacy_alias_do_not_expand_selection(self):
        with patch.object(api, 'Store', return_value=self.store), patch.object(api, 'maintain', return_value={
                'status': 'up_to_date', 'current': '1.1.0'}) as total, patch.object(api, 'update_all', return_value={
                'status': 'batch', 'results': []}) as dependencies, patch.object(api, 'update', return_value={
                'status': 'up_to_date', 'current': '2.0.3'}) as single, redirect_stdout(io.StringIO()):
            self.assertEqual(api.main(['update']), 0)
            total.assert_called_with(self.store, False, False, False)
            api.main(['update', '--self-only'])
            total.assert_called_with(self.store, True, False, False)
            api.main(['upgrade'])
            dependencies.assert_called_once_with(self.store, False, False)
            for verb in ('upgrade', 'update'):
                api.main([verb, 'agent-reach'])
                single.assert_called_with(self.store, 'agent-reach', False)

    def test_empty_native_version_does_not_hide_other_component_checks(self):
        binary = self.root / 'empty-ego'
        binary.write_text('#!' + sys.executable + '\n')
        binary.chmod(0o700)
        with patch.object(api, 'ROOT', self.live), patch.object(own, 'inspect', return_value={
                'dependency': 'lookup', 'status': 'up_to_date', 'current': '1.0.0'}), \
                patch.object(api.shutil, 'which', return_value=None), \
                patch.dict(os.environ, EGO_BROWSER_BIN=str(binary)):
            result = api.inspect_all(self.store)
        self.assertEqual(len(result['results']), 4)
        self.assertEqual(result['results'][-1]['dependency'], 'ego-browser')
        self.assertEqual(result['results'][-1]['status'], 'check_failed')
        self.assertEqual(result['results'][1]['status'], 'not_installed')
        self.assertTrue(api.result_failed(result))


class GitSourceTests(unittest.TestCase):
    def test_real_git_baseline_excludes_unpublished_commits_and_normalizes_modes(self):
        with tempfile.TemporaryDirectory(prefix='lookup-git-') as temporary:
            base = Path(temporary)
            upstream = base / 'origin'
            upstream.mkdir()
            def git(*args, cwd=upstream):
                return subprocess.check_output(['git', *map(str, args)], cwd=cwd, text=True).strip()
            git('init', '-q', '-b', 'main')
            git('config', 'user.name', 'Synthetic Test')
            git('config', 'user.email', 'test@example.invalid')
            tree(upstream / 'lookup')
            git('add', 'lookup')
            git('commit', '-qm', 'base')
            installed = base / 'installed'
            git('clone', '-q', upstream, installed, cwd=base)
            git('config', 'user.name', 'Synthetic Test', cwd=installed)
            git('config', 'user.email', 'test@example.invalid', cwd=installed)
            git('remote', 'set-url', 'origin', str(upstream), cwd=installed)
            (installed / 'lookup/scripts/read.py').write_text('def read(value):\n    return value\n')
            git('add', 'lookup', cwd=installed)
            git('commit', '-qm', 'unpublished customization', cwd=installed)
            tree(upstream / 'lookup', '1.1.0')
            git('add', 'lookup')
            git('commit', '-qm', 'new official version')
            store = api.Store(base / 'state')
            with patch.object(own, 'REPOSITORY', str(upstream)):
                result = own.update(store, installed / 'lookup', audit)
            self.assertEqual(result['status'], 'manual_review')
            directory, request = audit.load(store, 'lookup')
            self.assertEqual(request['scopes'][0]['customizations'], ['scripts/read.py'])
            self.assertIn('return value\n', (installed / 'lookup/scripts/read.py').read_text())
            self.assertEqual(audit.files(directory / '0/base')['scripts/read.py']['mode'], 0o644)


class IsolatedCliTests(unittest.TestCase):
    def test_clean_home_real_entry_source_switch_idempotence_and_scopes(self):
        with tempfile.TemporaryDirectory(prefix='lookup-cli-source-') as temporary:
            area = Path(temporary)
            home, origin, installed = area / 'home', area / 'origin', area / 'installed'
            home.mkdir()
            origin.mkdir()
            def git(*args, cwd=origin):
                return subprocess.check_output(['git', *map(str, args)], cwd=cwd, text=True).strip()
            git('init', '-q', '-b', 'main')
            git('config', 'user.name', 'Synthetic Test')
            git('config', 'user.email', 'test@example.invalid')
            shutil.copytree(LOOKUP, origin / 'lookup', ignore=shutil.ignore_patterns('__pycache__'))
            entry = origin / 'lookup/SKILL.md'
            import re
            entry.write_text(re.sub(r'  version: "[^"]+"', '  version: "1.0.0"', entry.read_text(), count=1))
            (origin / 'other-skill').mkdir()
            (origin / 'other-skill/keep.txt').write_text('original')
            git('add', 'lookup', 'other-skill')
            git('commit', '-qm', 'synthetic base')
            git('clone', '-q', origin, installed, cwd=area)
            git('remote', 'set-url', 'origin', own.REPOSITORY, cwd=installed)
            old_head = git('rev-parse', 'HEAD', cwd=installed)
            entry.write_text(entry.read_text().replace('version: "1.0.0"', 'version: "1.1.0"'))
            (origin / 'other-skill/keep.txt').write_text('must not be applied')
            git('add', 'lookup', 'other-skill')
            git('commit', '-qm', 'synthetic update')
            toolbin = area / 'bin'
            toolbin.mkdir()
            (toolbin / 'git').symlink_to(shutil.which('git'))
            (toolbin / 'python3').symlink_to(sys.executable)
            config = home / '.gitconfig'
            config.write_text(f'[url "{origin}"]\n\tinsteadOf = {own.REPOSITORY}\n')
            env = {**os.environ, 'HOME': str(home), 'USERPROFILE': str(home),
                   'PATH': str(home / '.local/bin') + os.pathsep + str(toolbin),
                   'XDG_STATE_HOME': str(home / 'state'), 'GIT_CONFIG_GLOBAL': str(config),
                   'GIT_CONFIG_NOSYSTEM': '1', 'PYTHONDONTWRITEBYTECODE': '1'}
            install = subprocess.run([sys.executable, str(installed / 'lookup/scripts/install-cli.py')],
                                     env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(install.returncode, 0, install.stderr)
            command = home / '.local/bin/lookup'
            for args in (['upgrade'], ['upgrade', 'agent-reach'], ['update']):
                result = subprocess.run([str(command), *args], env=env, capture_output=True,
                                        text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(own.version(installed / 'lookup'), '1.1.0')
            self.assertEqual(git('rev-parse', 'HEAD', cwd=installed), old_head)
            self.assertEqual((installed / 'other-skill/keep.txt').read_text(), 'original')
            before = audit.files(installed / 'lookup')
            again = subprocess.run([str(command), 'update', '--self-only'], env=env,
                                   capture_output=True, text=True, timeout=30)
            self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
            self.assertEqual(audit.files(installed / 'lookup'), before)
            self.assertIn('本体', again.stdout)


class ProcessOwnershipTests(unittest.TestCase):
    def test_cancel_handoff_allows_executor_to_reap_owned_install_process(self):
        with tempfile.TemporaryDirectory(prefix='lookup-cancel-') as temporary:
            area = Path(temporary)
            pid_file = area / 'child.pid'
            worker = area / 'worker.py'
            worker.write_text('import importlib.util,sys\n'
                f's=importlib.util.spec_from_file_location("api",{str(LOOKUP / "scripts/upstream.py")!r})\n'
                'm=importlib.util.module_from_spec(s);s.loader.exec_module(m)\n'
                'm.command([sys.executable,"-c",' + repr('import os,time;from pathlib import Path;'
                f'Path({str(pid_file)!r}).write_text(str(os.getpid()));time.sleep(30)') + '],timeout=40)\n')
            supervisor = area / 'supervisor.py'
            supervisor.write_text('import importlib.util,sys\n'
                f's=importlib.util.spec_from_file_location("run",{str(LOOKUP / "scripts/owned_process.py")!r})\n'
                'm=importlib.util.module_from_spec(s);s.loader.exec_module(m)\n'
                f'm.run([sys.executable,{str(worker)!r}],timeout=40)\n')
            process = subprocess.Popen([sys.executable, str(supervisor)],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            owned_pid = None
            try:
                deadline = time.monotonic() + 5
                while not pid_file.exists() and time.monotonic() < deadline:
                    if process.poll() is not None:
                        break
                    time.sleep(0.02)
                self.assertTrue(pid_file.exists())
                owned_pid = int(pid_file.read_text())
                process.send_signal(signal.SIGTERM)
                process.communicate(timeout=5)
                self.assertNotEqual(process.returncode, 0)
                with self.assertRaises(ProcessLookupError):
                    os.kill(owned_pid, 0)
            finally:
                if process.poll() is None:
                    process.kill()
                process.communicate()
                if owned_pid:
                    try:
                        os.kill(owned_pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass


if __name__ == '__main__':
    unittest.main()
