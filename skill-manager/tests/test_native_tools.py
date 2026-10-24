"""Native maintenance protects full Skill trees, configuration and retry state."""
import fcntl
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import core
import native_tools as native

REAL_SNAPSHOT = native.official_snapshot


class NativeToolTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='native-manager-')
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name).resolve()
        self.state = self.home / '.skill-manager'
        self.root = self.state / 'native/lark-cli'
        self.shared = self.home / '.agents/skills'
        self.shared.mkdir(parents=True)
        self.bin = self.home / 'bin'
        self.bin.mkdir()
        self.version = self.home / 'version'
        self.version.write_text('1.0.0')
        self.calls = self.home / 'calls'
        self.calls.write_text('')
        self.sources = self.home / 'official'
        for version in ('1.0.0', '1.1.0'):
            source = self.sources / version / 'lark-doc'
            (source / 'references').mkdir(parents=True)
            (source / 'scripts').mkdir()
            (source / 'SKILL.md').write_text(
                '---\nname: lark-doc\ndescription: Synthetic\n---\n' + version)
            (source / 'references/read.md').write_text('reference ' + version)
            (source / 'scripts/helper.py').write_text('print("synthetic")\n')
        shutil.copytree(self.sources / '1.0.0/lark-doc', self.shared / 'lark-doc')
        config = self.home / '.lark-cli/config.json'
        config.parent.mkdir()
        config.write_text('{"synthetic": true}')
        self.config = config
        binary = self.bin / 'lark-cli'
        binary.write_text('#!' + sys.executable + '\n' + '''\
import json, os, pathlib, shutil, sys
home = pathlib.Path.home()
args = sys.argv[1:]
version = (home / 'version').read_text()
if args == ['--version']:
    print('lark-cli version ' + version)
elif args == ['skills', 'list']:
    print(json.dumps({'ok': True, 'skills': [{'name': 'lark-doc'}]}))
elif args[:2] == ['skills', 'read']:
    sys.stdout.write((home / 'official' / version / args[2] / 'SKILL.md').read_text())
elif args == ['update', '--check', '--json']:
    target = os.environ.get('SYNTHETIC_TARGET', '1.1.0')
    print(json.dumps({'ok': True, 'current_version': version, 'latest_version': target,
        'action': 'already_up_to_date' if target == version else 'update_available'}))
elif args == ['update', '--json']:
    with (home / 'calls').open('a') as log:
        log.write('update\\n')
    target = os.environ.get('SYNTHETIC_TARGET', '1.1.0')
    (home / 'version').write_text(target)
    entry = home / '.agents/skills/lark-doc'
    shutil.copytree(home / 'official' / target / 'lark-doc', entry)
    client = home / '.claude/skills'
    client.mkdir(parents=True, exist_ok=True)
    (client / 'lark-doc').symlink_to('../../.agents/skills/lark-doc')
    change = os.environ.get('SYNTHETIC_CONFIG')
    if change:
        config = home / '.lark-cli' / ('new/config.json' if change == 'new' else 'config.json')
        config.parent.mkdir(parents=True, exist_ok=True)
        if change == 'delete':
            config.unlink()
        elif change == 'mode':
            config.chmod(0o777)
        else:
            config.write_text('{"synthetic": "changed"}')
    if os.environ.get('SYNTHETIC_FAILURE'):
        raise SystemExit(7)
    print(json.dumps({'ok': True, 'action': 'updated'}))
else:
    raise SystemExit(2)
''')
        binary.chmod(0o700)
        bridge = self.home / '.agents/tools/lark/scripts/read_embedded.py'
        bridge.parent.mkdir(parents=True)
        bridge.write_text('import sys\n'
                          'print("1" if "--manager-protocol" in sys.argv else "verified")\n')
        env = {'HOME': str(self.home), 'PATH': str(self.bin) + os.pathsep + os.environ['PATH'],
               'XDG_CONFIG_HOME': str(self.home / '.config'),
               'LARKSUITE_CLI_CONFIG_DIR': str(self.home / '.lark-cli')}
        for context in (patch.dict(os.environ, env), patch.object(core, 'STATE_DIR', str(self.state)),
                        patch.object(core, 'global_skill_roots',
                                     return_value=[('shared', str(self.shared)),
                                         ('client', str(self.home / '.claude/skills'))]),
                        patch.object(native, 'official_snapshot', side_effect=self.snapshot)):
            context.start()
            self.addCleanup(context.stop)

    def snapshot(self, binary, version, recovery, names):
        destination = recovery / ('source-' + version)
        if not destination.exists():
            shutil.copytree(self.sources / version, destination / 'skills')
        core.write_json(str(destination / 'source-receipt.json'),
                        {'version': version, 'url': native.LARK_SOURCE,
                         'commit': 'a' * 40, 'skills': names})
        source = destination / 'skills'
        return source, native.source_files(source, names)

    def read_state(self):
        return json.loads((self.root / 'state.json').read_text())

    def test_update_reconciles_registered_entries_and_keeps_readable_backups(self):
        result, code = native.update_lark()
        self.assertEqual(code, 0, result)
        self.assertEqual(result['status'], 'updated')
        self.assertEqual(result['archived_before'], 1)
        self.assertEqual(result['archived_after'], 2)
        self.assertEqual(native.entries(['lark-doc']), [])
        recovery = Path(result['recovery'])
        after = json.loads((recovery / 'after.json').read_text())
        for row in after['entries']:
            self.assertEqual((Path(row['preserved']) / 'references/read.md').read_text(),
                             'reference 1.1.0')
        self.assertEqual(self.config.read_text(), '{"synthetic": true}')
        resources = json.loads((self.root / 'resources.json').read_text())
        self.assertIn('lark-doc/scripts/helper.py', resources['files'])
        self.assertEqual(self.calls.read_text(), 'update\n')

    def test_repeated_update_does_not_reinstall_or_rearchive(self):
        native.update_lark()
        result, code = native.update_lark()
        self.assertEqual(code, 0, result)
        self.assertEqual(result['status'], 'up_to_date')
        self.assertFalse(result['native_invoked'])
        self.assertEqual(result['archived_before'] + result['archived_after'], 0)
        self.assertEqual(self.calls.read_text(), 'update\n')

    def test_dry_run_makes_no_state_or_native_change(self):
        result, code = native.update_lark(dry_run=True)
        self.assertEqual(code, 0)
        self.assertEqual(result['status'], 'plan')
        self.assertFalse(self.state.exists())
        self.assertTrue((self.shared / 'lark-doc').exists())
        self.assertEqual(self.calls.read_text(), '')

    def test_full_tree_customizations_and_missing_files_block_before_update(self):
        for change in ('reference', 'extra', 'missing'):
            with self.subTest(change=change):
                path = self.shared / 'lark-doc/references/read.md'
                if change == 'reference':
                    path.write_text('custom')
                elif change == 'extra':
                    path.write_text('reference 1.0.0')
                    (path.parent / 'extra.md').write_text('unique')
                else:
                    (path.parent / 'extra.md').unlink()
                    path.unlink()
                result, code = native.update_lark()
                self.assertEqual(code, 1, result)
                self.assertIn('CUSTOM_SKILL', result['error'])
                self.assertTrue((self.shared / 'lark-doc').exists())
                self.assertEqual(self.calls.read_text(), '')

    def test_configuration_changes_keep_both_versions_and_prevent_retry(self):
        with patch.dict(os.environ, SYNTHETIC_CONFIG='change'):
            result, code = native.update_lark()
        self.assertEqual(code, 1, result)
        self.assertFalse(result['config_unchanged'])
        self.assertIn('CONFIG_CHANGED', result['error'])
        backup = Path(result['recovery'])
        self.assertTrue((backup / 'config-before.json').is_file())
        self.assertTrue((backup / 'config-after.json').is_file())
        self.assertEqual(native.entries(['lark-doc']), [])
        again, code = native.update_lark()
        self.assertEqual(code, 1)
        self.assertFalse(again['retry_safe'])
        self.assertEqual(self.calls.read_text(), 'update\n')

    def test_new_deleted_and_permission_changed_configurations_are_detected(self):
        recovery = self.home / 'snapshot'
        recovery.mkdir()
        before = native.config_snapshot(recovery)
        self.assertFalse(native.config_changed(before))
        self.config.chmod(0o777)
        self.assertTrue(native.config_changed(before))
        self.config.unlink()
        self.assertTrue(native.config_changed(before))
        self.config.write_text('{"synthetic": true}')
        self.config.chmod(before[str(self.config)]['mode'])
        nested = self.config.parent / 'new/config.json'
        nested.parent.mkdir()
        nested.write_text('{}')
        self.assertTrue(native.config_changed(before))

    def test_native_failure_still_reconciles_entries_and_blocks_blind_retry(self):
        with patch.dict(os.environ, SYNTHETIC_FAILURE='1'):
            result, code = native.update_lark()
        self.assertEqual(code, 1)
        self.assertEqual(result['status'], 'outcome_unknown')
        self.assertEqual(result['archived_after_failure'], 2)
        self.assertEqual(native.entries(['lark-doc']), [])
        again, code = native.update_lark()
        self.assertEqual(code, 1)
        self.assertFalse(again['retry_safe'])
        self.assertEqual(self.calls.read_text(), 'update\n')

    def test_lock_prevents_parallel_installer(self):
        self.root.mkdir(parents=True)
        with (self.root / 'maintenance.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result, code = native.update_lark()
        self.assertEqual(code, 1)
        self.assertEqual(result['status'], 'deferred')
        self.assertEqual(self.calls.read_text(), '')

    def test_shared_directory_links_survive_archive_and_are_not_dangling(self):
        client = self.home / '.claude/skills'
        client.mkdir(parents=True)
        (client / 'lark-doc').symlink_to('../../.agents/skills/lark-doc')
        with patch.dict(os.environ, SYNTHETIC_TARGET='1.0.0'):
            result, code = native.update_lark()
        self.assertEqual(code, 0, result)
        before = json.loads((Path(result['recovery']) / 'before.json').read_text())
        for row in before['entries']:
            self.assertTrue((Path(row['preserved']) / 'scripts/helper.py').is_file())

    def test_archive_failure_restores_original_entries_and_links(self):
        client = self.home / '.claude/skills'
        client.mkdir(parents=True)
        link = client / 'lark-doc'
        link.symlink_to('../../.agents/skills/lark-doc')
        recovery = self.home / 'archive'
        recovery.mkdir()
        original_rename = Path.rename

        def rename(path, target):
            if path == link:
                raise OSError('synthetic failure')
            return original_rename(path, target)

        with patch.object(Path, 'rename', rename):
            with self.assertRaises(OSError):
                native.archive_entries(['lark-doc'], recovery, 'before',
                                       self.sources / '1.0.0')
        self.assertTrue((self.shared / 'lark-doc/references/read.md').is_file())
        self.assertTrue(link.is_dir())
        self.assertEqual(os.readlink(link), '../../.agents/skills/lark-doc')

    def test_source_and_config_redirects_fail_before_installation(self):
        reference = self.shared / 'lark-doc/references/read.md'
        reference.unlink()
        reference.symlink_to(self.config)
        result, code = native.update_lark()
        self.assertEqual(code, 1)
        self.assertIn('REDIRECTED_SKILL_FILE', result['error'])
        reference.unlink()
        reference.write_text('reference 1.0.0')
        self.config.rename(self.config.with_name('real.json'))
        self.config.symlink_to('real.json')
        result, code = native.update_lark()
        self.assertEqual(code, 1)
        self.assertIn('REDIRECTED_MAINTENANCE_PATH', result['error'])
        self.assertEqual(self.calls.read_text(), '')

    def test_change_during_archive_is_preserved_and_not_reported_as_success(self):
        recovery = self.home / 'archive'
        recovery.mkdir()
        original_rename = Path.rename

        def rename(path, target):
            result = original_rename(path, target)
            if path == self.shared / 'lark-doc':
                (Path(target) / 'references/read.md').write_text('concurrent edit')
            return result

        with patch.object(Path, 'rename', rename):
            with self.assertRaisesRegex(native.NativeError, 'SKILL_CHANGED'):
                native.archive_entries(['lark-doc'], recovery, 'before',
                                       self.sources / '1.0.0')
        self.assertEqual((self.shared / 'lark-doc/references/read.md').read_text(),
                         'concurrent edit')

    def test_unknown_suite_is_preserved_for_review(self):
        (self.shared / 'lark-suite').mkdir()
        result, code = native.update_lark()
        self.assertEqual(code, 1)
        self.assertEqual(result['error'], 'UNSUPPORTED_SUITE_LAYOUT')
        self.assertTrue((self.shared / 'lark-doc').is_dir())
        self.assertEqual(self.calls.read_text(), '')

    def test_unreviewed_legacy_vendor_is_not_silently_replaced(self):
        vendor = self.home / '.agents/tools/lark/vendor'
        vendor.mkdir()
        (vendor / 'custom.py').write_text('custom')
        result, code = native.update_lark()
        self.assertEqual(code, 1)
        self.assertEqual(result['error'], 'LEGACY_RESOURCE_REVIEW_REQUIRED')
        self.assertFalse((self.root / 'resources.json').exists())
        self.assertEqual(self.calls.read_text(), '')

    def test_modified_managed_resource_is_preserved(self):
        native.update_lark()
        manifest = json.loads((self.root / 'resources.json').read_text())
        helper = Path(manifest['root']) / 'lark-doc/scripts/helper.py'
        helper.write_text('custom')
        result, code = native.update_lark()
        self.assertEqual(code, 1)
        self.assertEqual(result['error'], 'MANAGED_RESOURCES_CHANGED')
        self.assertEqual(helper.read_text(), 'custom')
        self.assertEqual(self.calls.read_text(), 'update\n')

    def test_lookup_configuration_change_is_preserved_and_blocks_reinvocation(self):
        binding = self.home / '.config/lookup/opencli-binding.json'
        binding.parent.mkdir(parents=True)
        binding.write_text('{"synthetic": "confirmed"}')

        def maintain():
            binding.write_text('{"synthetic": "redirected"}')
            return {'status': 'updated', 'dependency': 'ego-browser'}, 0

        result, code = native.guard_lookup(maintain)
        self.assertEqual(code, 1)
        self.assertEqual(result['maintenance_status'], 'updated')
        self.assertFalse(result['config_unchanged'])
        self.assertTrue((Path(result['config_recovery']) / 'config-after.json').is_file())
        with patch.object(native, 'run') as callback:
            result, code = native.guard_lookup(callback)
        self.assertEqual(code, 1)
        callback.assert_not_called()
        self.assertIn('redirected', binding.read_text())

    def test_lookup_unchanged_configuration_preserves_the_scoped_result(self):
        for _ in range(2):
            result, code = native.guard_lookup(lambda: (
                {'status': 'up_to_date', 'dependency': 'opencli'}, 0))
            self.assertEqual(code, 0, result)
            self.assertEqual(result['dependency'], 'opencli')
            self.assertTrue(result['config_unchanged'])

    def test_malformed_official_lists_fail_with_a_stable_error(self):
        for data in ([], {}, {'ok': True, 'skills': {}},
                     {'ok': True, 'skills': [None]}, {'ok': True, 'skills': [{}]},
                     {'ok': True, 'skills': [{'name': []}]},
                     {'ok': True, 'skills': [{'name': 'lark-doc'}] * 2}):
            with self.subTest(data=data), patch.object(native, 'run', return_value=json.dumps(data)):
                with self.assertRaisesRegex(native.NativeError, 'INVALID_OFFICIAL_SKILL_LIST'):
                    native.official_skills('synthetic')

    def test_corrupt_states_remain_unchanged_and_never_invoke_installers(self):
        self.root.mkdir(parents=True)
        lookup = self.state / 'native/lookup'
        lookup.mkdir()
        for value in ('{broken', '[]', '{}', '{"status":1}', '{"status":"invoking","native_invoked":0}'):
            with self.subTest(value=value):
                state = self.root / 'state.json'
                state.write_text(value)
                result, code = native.update_lark()
                self.assertEqual(code, 1, result)
                self.assertEqual(result['error'], 'INVALID_NATIVE_STATE')
                self.assertEqual(state.read_text(), value)
                lookup_state = lookup / 'state.json'
                lookup_state.write_text(value)
                callback = unittest.mock.Mock()
                result, code = native.guard_lookup(callback)
                self.assertEqual(code, 1, result)
                self.assertEqual(result['error'], 'INVALID_NATIVE_STATE')
                self.assertEqual(lookup_state.read_text(), value)
                callback.assert_not_called()
        self.assertEqual(self.calls.read_text(), '')

    def test_redirected_state_root_returns_a_structured_failure(self):
        outside = self.home / 'elsewhere'
        outside.mkdir()
        self.root.parent.mkdir(parents=True)
        self.root.symlink_to(outside, target_is_directory=True)
        result, code = native.update_lark()
        self.assertEqual(code, 1, result)
        self.assertEqual(result['error'], 'REDIRECTED_MAINTENANCE_PATH')
        self.assertFalse(any(outside.iterdir()))

    def managed_fixture(self):
        self.root.mkdir(parents=True, exist_ok=True)
        recovery = self.root / 'fixture'
        recovery.mkdir()
        source, files = self.snapshot('synthetic', '1.0.0', recovery, ['lark-doc'])
        native.publish_resources(str(self.bin / 'lark-cli'), source, ['lark-doc'], self.root, files)
        return source, recovery

    def test_managed_source_rejects_receipt_version_and_path_changes(self):
        source, _ = self.managed_fixture()
        receipt = source.parent / 'source-receipt.json'
        original = receipt.read_text()
        for changes in ({'version': '1.1.0'}, {'commit': 'invalid'}, {'skills': []}):
            with self.subTest(changes=changes):
                receipt.write_text(json.dumps({**json.loads(original), **changes}))
                with self.assertRaisesRegex(native.NativeError, 'INVALID_SOURCE_RECEIPT'):
                    native.managed_source(self.root)
        receipt.write_text(original)
        parent = source.parent
        renamed = parent.with_name('redirected')
        parent.rename(renamed)
        parent.symlink_to(renamed, target_is_directory=True)
        with self.assertRaisesRegex(native.NativeError, 'REDIRECTED_MAINTENANCE_PATH'):
            native.managed_source(self.root)

    def test_cached_snapshot_hashes_each_source_once_and_uses_the_given_names(self):
        source, recovery = self.managed_fixture()
        with patch.object(native, 'fingerprint', wraps=native.fingerprint) as fingerprint, \
                patch.object(native, 'official_skills') as listing:
            actual, files = REAL_SNAPSHOT(str(self.bin / 'lark-cli'), '1.0.0', recovery, ['lark-doc'])
        self.assertEqual(actual, source)
        self.assertIn('lark-doc/SKILL.md', files)
        fingerprint.assert_called_once_with(source / 'lark-doc')
        listing.assert_not_called()

    def test_official_download_uses_the_shared_peeled_tag_resolver(self):
        import update_skill
        self.root.mkdir(parents=True)
        recovery = self.root / 'fixture'
        recovery.mkdir()

        def download(url, commit, destination):
            self.assertEqual(commit, 'b' * 40)
            shutil.copytree(self.sources / '1.0.0', Path(destination) / 'skills')

        with patch.object(core, 'remote_tags', return_value={'v1.0.0': 'b' * 40}) as tags, \
                patch.object(update_skill, 'download_repo', side_effect=download):
            source, files = REAL_SNAPSHOT(str(self.bin / 'lark-cli'), '1.0.0', recovery, ['lark-doc'])
        tags.assert_called_once_with(native.LARK_SOURCE + '.git')
        self.assertEqual(json.loads((source.parent / 'source-receipt.json').read_text())['commit'],
                         'b' * 40)
        self.assertEqual(files, native.source_files(source, ['lark-doc']))

    def test_update_reads_official_names_once_per_runtime_version(self):
        with patch.object(native, 'official_skills', wraps=native.official_skills) as listing:
            result, code = native.update_lark()
            self.assertEqual(code, 0, result)
            self.assertEqual(listing.call_count, 2)
            listing.reset_mock()
            result, code = native.update_lark()
            self.assertEqual(code, 0, result)
            self.assertEqual(listing.call_count, 1)

    def test_interrupted_lookup_keeps_both_configs_and_blocks_reinvocation(self):
        binding = self.home / '.config/lookup/opencli-binding.json'
        binding.parent.mkdir(parents=True)
        binding.write_text('before')

        def maintain():
            state = json.loads((self.state / 'native/lookup/state.json').read_text())
            self.assertEqual(state['status'], 'invoking')
            binding.write_text('after')
            raise KeyboardInterrupt

        result, code = native.guard_lookup(maintain)
        self.assertEqual(code, 1, result)
        self.assertEqual(result['error'], 'KeyboardInterrupt')
        after = json.loads((Path(result['config_recovery']) / 'config-after.json').read_text())
        self.assertEqual(Path(after[str(binding)]['backup']).read_text(), 'after')
        callback = unittest.mock.Mock()
        result, code = native.guard_lookup(callback)
        self.assertEqual(code, 1)
        callback.assert_not_called()

    def test_interrupted_native_update_reconciles_entries_without_blind_retry(self):
        original = native.run

        def run(argv, timeout=30):
            output = original(argv, timeout)
            if argv[1:] == ['update', '--json']:
                raise KeyboardInterrupt
            return output

        with patch.object(native, 'run', side_effect=run):
            result, code = native.update_lark()
        self.assertEqual(code, 1, result)
        self.assertEqual(result['archived_after_failure'], 2)
        self.assertEqual(native.entries(['lark-doc']), [])
        result, code = native.update_lark()
        self.assertEqual(code, 1)
        self.assertFalse(result['retry_safe'])
        self.assertEqual(self.calls.read_text(), 'update\n')

    def test_external_upgrade_can_reconcile_stale_resources_without_reinstalling(self):
        self.managed_fixture()
        self.version.write_text('1.1.0')
        shutil.rmtree(self.shared / 'lark-doc')
        shutil.copytree(self.sources / '1.1.0/lark-doc', self.shared / 'lark-doc')
        bridge = self.home / '.agents/tools/lark/scripts/read_embedded.py'
        bridge.write_text('import json,sys\nfrom pathlib import Path\n'
            'if "--manager-protocol" in sys.argv:\n'
            '    print("1")\n'
            'else:\n'
            f'    data=json.loads(Path({str(self.root / "resources.json")!r}).read_text())\n'
            '    expected="lark-cli version " + (Path.home()/"version").read_text()\n'
            '    raise SystemExit(0 if data["runtime"]==expected else 1)\n')
        result, code = native.update_lark()
        self.assertEqual(code, 0, result)
        self.assertFalse(result['native_invoked'])
        self.assertEqual(result['archived_before'], 1)
        self.assertEqual(self.calls.read_text(), '')
        self.assertEqual(json.loads((self.root / 'resources.json').read_text())['runtime'],
                         'lark-cli version 1.1.0')

    def test_lookup_inflight_state_survives_process_loss_and_blocks_reinvocation(self):
        root = self.state / 'native/lookup'
        root.mkdir(parents=True)
        state = root / 'state.json'
        record = {'status': 'invoking', 'config_unchanged': False, 'config_recovery': 'synthetic'}
        state.write_text(json.dumps(record))
        callback = unittest.mock.Mock()
        result, code = native.guard_lookup(callback)
        self.assertEqual(code, 1)
        self.assertEqual(result['status'], 'manual_review')
        self.assertEqual(result['error'], 'INSPECT_PRIOR_LOOKUP_OPERATION')
        self.assertEqual(json.loads(state.read_text()), record)
        callback.assert_not_called()

    def test_inconsistent_or_malformed_update_checks_stop_before_archiving_or_installation(self):
        original = native.run
        base = {'ok': True, 'current_version': '1.0.0', 'latest_version': '1.1.0',
                'action': 'update_available'}
        for changes in ({'latest_version': []}, {'latest_version': 'invalid'},
                        {'latest_version': '0.9.0'}, {'action': 'already_up_to_date'},
                        {'latest_version': '1.0.0'}):
            with self.subTest(changes=changes):
                def run(argv, timeout=30):
                    if argv[1:] == ['update', '--check', '--json']:
                        return json.dumps({**base, **changes})
                    return original(argv, timeout)
                with patch.object(native, 'run', side_effect=run):
                    result, code = native.update_lark()
                self.assertEqual(code, 1, result)
                self.assertEqual(result['error'], 'UNVERIFIED_UPDATE_CHECK')
                self.assertTrue((self.shared / 'lark-doc').is_dir())
        self.assertEqual(self.calls.read_text(), '')

    def test_managed_skill_directory_redirect_is_rejected(self):
        source, _ = self.managed_fixture()
        skill = source / 'lark-doc'
        actual = source.parent / 'real-doc'
        skill.rename(actual)
        skill.symlink_to(actual, target_is_directory=True)
        with self.assertRaisesRegex(native.NativeError, 'REDIRECTED_MAINTENANCE_PATH'):
            native.managed_source(self.root)


if __name__ == '__main__':
    unittest.main()
