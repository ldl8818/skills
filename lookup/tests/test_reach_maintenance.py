"""The bundled source exists independently of a globally installed Reach CLI."""
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('reach_maintenance', ROOT / 'scripts/upstream.py')
upstream = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upstream)


class BundledMaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'lookup'
        shutil.copytree(ROOT / 'upstream', self.root / 'upstream')
        self.store = upstream.Store(Path(self.temp.name) / 'state')
        self.manifest = json.loads((self.root / 'upstream/agent-reach.json').read_text())
        self.absent = patch.object(upstream, 'installed', return_value={'status': 'not_installed'})
        self.absent.start()
        self.addCleanup(self.absent.stop)
        root = patch.object(upstream, 'ROOT', self.root)
        root.start()
        self.addCleanup(root.stop)

    def remote(self, commit=None):
        return patch.object(upstream, 'command', return_value=(commit or self.manifest['commit']) + '\trefs/heads/main\n')

    def test_source_without_standalone_is_current_and_cached(self):
        with self.remote() as remote:
            first = upstream.check(self.store, 'agent-reach')
            second = upstream.check(self.store, 'agent-reach')
        self.assertEqual(first['status'], 'up_to_date')
        self.assertEqual(first['standalone']['status'], 'not_installed')
        self.assertEqual(first['bundle']['commit'], self.manifest['commit'])
        self.assertTrue(second['bundle']['cached'])
        self.assertEqual(remote.call_count, 1)

    def test_same_version_with_new_main_commit_requires_merge(self):
        with self.remote('f' * 40), patch.object(upstream, 'native_update', return_value={'status': 'not_installed'}):
            check = upstream.check(self.store, 'agent-reach')
            update = upstream.update(self.store, 'agent-reach')
        self.assertEqual(check['status'], 'update_available')
        self.assertEqual(update['status'], 'manual_review')
        self.assertEqual(update['reason'], 'BUNDLED_SOURCE_MERGE_REQUIRED')
        self.assertTrue(upstream.result_failed(update))

    def test_failed_remote_check_cannot_report_not_installed_or_current(self):
        with patch.object(upstream, 'command', side_effect=upstream.MaintenanceError('COMMAND_FAILED')):
            result = upstream.check(self.store, 'agent-reach')
        self.assertEqual(result['status'], 'check_failed')

    def test_changed_source_cannot_reuse_success_cache(self):
        with self.remote():
            self.assertEqual(upstream.check(self.store, 'agent-reach')['status'], 'up_to_date')
            archive = self.root / 'upstream/agent-reach.tar.gz'
            archive.write_bytes(archive.read_bytes() + b'changed')
            self.assertEqual(upstream.check(self.store, 'agent-reach')['status'], 'check_failed')

    def test_bundle_current_does_not_promote_unknown_native_result(self):
        with self.remote(), patch.object(upstream, 'native_update', return_value={
                'status': 'pending', 'outcome_unknown': True, 'retry_safe': False}):
            result = upstream.update(self.store, 'agent-reach')
        self.assertEqual(result['status'], 'pending')
        self.assertTrue(result['outcome_unknown'])
        self.assertEqual(result['bundle']['status'], 'up_to_date')

    def test_current_bundle_update_does_not_install_standalone(self):
        with self.remote(), patch.object(upstream, 'native_update', return_value={'status': 'not_installed'}) as native:
            result = upstream.update(self.store, 'agent-reach')
        self.assertEqual(result['status'], 'up_to_date')
        self.assertEqual(result['standalone']['status'], 'not_installed')
        native.assert_called_once()

    def test_background_source_check_schedules_once_without_network_in_caller(self):
        with patch.object(upstream.subprocess, 'Popen') as process, patch.object(upstream, 'command') as remote:
            first = upstream.check(self.store, 'agent-reach', background=True)
            upstream.check(self.store, 'agent-reach', background=True)
        self.assertEqual(first['bundle']['status'], 'scheduled')
        self.assertEqual(process.call_count, 1)
        remote.assert_not_called()

    def test_standalone_release_update_and_bundle_check_remain_separate(self):
        with self.remote(), patch.object(upstream, 'check_standalone', return_value={
                'status': 'update_available', 'current': '1.5.0', 'latest': '1.6.1'}):
            result = upstream.check(self.store, 'agent-reach')
        self.assertEqual(result['status'], 'update_available')
        self.assertEqual(result['latest'], '1.6.1')
        self.assertEqual(result['bundle']['status'], 'up_to_date')


if __name__ == '__main__':
    unittest.main()
