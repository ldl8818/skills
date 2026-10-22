"""The existing updater enforces the fused capability and discovery contracts."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('lookup_update_integration', ROOT / 'scripts/upstream.py')
upstream = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(upstream)
SPEC = importlib.util.spec_from_file_location('lookup_source_integration', ROOT / 'scripts/reach.py')
reach = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reach)


class IntegratedUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='lookup update integration ')
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve()
        env = patch.dict(os.environ, HOME=str(self.home), XDG_STATE_HOME=str(self.home / 'state'))
        env.start()
        self.addCleanup(env.stop)

    def test_installed_candidate_requires_all_fused_channels(self):
        package = self.home / 'package/agent_reach'
        _, originals = reach.source_files()
        for name, content in originals.items():
            if name.startswith('agent_reach/'):
                target = package / name.removeprefix('agent_reach/')
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
        with patch.object(upstream, 'read_version', return_value='1.5.0'), \
             patch.object(upstream, 'command', return_value='agent-reach doctor skill'), \
             patch.object(upstream, 'agent_reach_environment', return_value={'skill_root': str(package / 'skill')}):
            result = upstream.agent_reach_probe('/synthetic/agent-reach')
            self.assertEqual(len(result['lookup_contract']['channels']), 16)
            registry = package / 'channels/__init__.py'
            registry.write_text('\n'.join(line for line in registry.read_text().splitlines()
                                          if not any(name in line for name in ('BossChannel','FacebookChannel','InstagramChannel'))))
            with self.assertRaisesRegex(upstream.MaintenanceError, 'LOOKUP_CONTRACT_CHANGED'):
                upstream.agent_reach_probe('/synthetic/agent-reach')

    def test_opencli_candidate_cannot_skip_the_complete_registry_gate(self):
        response = types.SimpleNamespace(stdout=json.dumps({'ok':True,'data':{'commands':[],'total':0}}))
        with patch.object(upstream, 'read_version', return_value='2.0.2'), \
             patch.object(upstream, 'command', return_value='opencli-browser'), \
             patch.object(upstream.subprocess, 'run', return_value=response):
            with self.assertRaisesRegex(upstream.MaintenanceError, 'OPENCLI_COMPLETE_CONTRACT_CHANGED'):
                upstream.qualify('/synthetic/opencli', '2.0.2')

    def test_native_upgrade_reintroduced_skill_is_preserved_outside_discovery(self):
        entry = self.home / '.agents/skills/ego-browser'
        entry.mkdir(parents=True)
        (entry / 'SKILL.md').write_text('---\nname: ego-browser\n---\nnew guide')
        result = upstream.finish_native_discovery('ego-browser', {'status':'updated','current':'2.0.0'})
        self.assertEqual(result['status'], 'updated')
        self.assertFalse(result['discovery_pending'])
        self.assertFalse(entry.exists())
        self.assertTrue((self.home / '.agents/skills/lookup').is_symlink())
        receipt = json.loads((self.home / '.local/share/lookup/execution-skills/entries.json').read_text())
        self.assertTrue((Path(receipt['entries'][0]['preserved']) / 'SKILL.md').is_file())

    def test_discovery_conflict_resumes_without_another_native_upgrade(self):
        entry = self.home / '.agents/skills/lookup'
        entry.mkdir(parents=True)
        (entry / 'unique').write_text('keep')
        store = upstream.Store()
        store.write('native-ego-browser.json', {'status':'manual_review','native_status':'updated',
                    'current':'2.0.0','discovery_pending':True})
        with patch.object(upstream, 'installed', return_value={'status':'installed','current':'2.0.0'}), \
             patch.object(upstream, 'command') as command:
            first = upstream.native_update(store, 'ego-browser')
            self.assertTrue(first['discovery_pending'])
            self.assertEqual((entry / 'unique').read_text(), 'keep')
            shutil.rmtree(entry)
            second = upstream.native_update(store, 'ego-browser')
            self.assertEqual(second['status'], 'updated')
            self.assertFalse(second['discovery_pending'])
            self.assertFalse(second['native_reinvoked'])
            command.assert_not_called()


if __name__ == '__main__':
    unittest.main()
