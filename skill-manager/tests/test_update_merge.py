from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import json

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import update_skill
import core
import scan_and_check


class ThreeWayUpdateTests(unittest.TestCase):
    def test_wrong_source_identity_never_replaces_the_requested_skill(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            live = root / 'sample'
            live.mkdir()
            original = '---\nname: sample\ndescription: Sample\nmetadata:\n  github_url: https://github.com/example/skills\n---\n'
            (live / 'SKILL.md').write_text(original)
            def download(_url, _ref, destination):
                Path(destination, 'SKILL.md').write_text('---\nname: unrelated\ndescription: Wrong source\n---\n')
                return True
            with mock.patch.object(core, 'resolve_direct_path', return_value=(str(live), None)), \
                    mock.patch.object(update_skill, 'BACKUP_ROOT', str(root / 'backups')), \
                    mock.patch.object(update_skill, 'latest_release', return_value=('v1.0.0', 'a' * 40)), \
                    mock.patch.object(update_skill, 'download_repo', side_effect=download):
                self.assertFalse(update_skill.update_direct_skill('sample'))
            self.assertEqual((live / 'SKILL.md').read_text(), original)

    def test_batch_rechecks_equal_commit_without_coverage_and_keeps_failure_visible(self):
        target = dict(kind='skill', name='sample', status='current', remote='v1', enabled=True, needs_merge_verification=True)
        with mock.patch.object(scan_and_check, 'build_targets', return_value=[object()]), \
                mock.patch.object(scan_and_check, 'check_one', return_value=target), \
                mock.patch.object(update_skill, 'update_direct_skill', return_value=True) as update:
            self.assertTrue(update_skill.update_all())
            update.assert_called_once_with('sample')
        with mock.patch.object(scan_and_check, 'build_targets', return_value=[object()]), \
                mock.patch.object(scan_and_check, 'check_one', return_value=dict(kind='skill', name='unavailable', status='error')):
            self.assertFalse(update_skill.update_all())

    def fixture(self, root):
        paths = [root / name for name in ('base', 'upstream', 'local')]
        for path in paths:
            path.mkdir()
            (path / 'SKILL.md').write_text('---\nname: sample\ndescription: Sample\n---\n# Full mode\n')
            (path / 'helper.py').write_text('one = 1\n\ntwo = 2\n\nthree = 3\n')
        return paths

    def test_nonoverlapping_local_and_upstream_edits_both_survive(self):
        with tempfile.TemporaryDirectory() as temp:
            base, upstream, local = self.fixture(Path(temp))
            (local / 'helper.py').write_text('one = 10\n\ntwo = 2\n\nthree = 3\n')
            (upstream / 'helper.py').write_text('one = 1\n\ntwo = 2\n\nthree = 30\n')
            (upstream / 'new-mode.md').write_text('# New source capability\n')
            (local / 'adapter.py').write_text('LOCAL_ADAPTER = True\n')
            update_skill.merge_skill_dir(str(upstream), str(local), {}, baseline=str(base))
            self.assertEqual((local / 'helper.py').read_text(), 'one = 10\n\ntwo = 2\n\nthree = 30\n')
            self.assertTrue((local / 'new-mode.md').is_file())
            self.assertTrue((local / 'adapter.py').is_file())

    def test_unregistered_baseline_never_overwrites_different_content(self):
        with tempfile.TemporaryDirectory() as temp:
            _base, upstream, local = self.fixture(Path(temp))
            (local / 'helper.py').write_text('LOCAL_CUSTOMIZATION = True\n')
            with self.assertRaisesRegex(ValueError, 'baseline'):
                update_skill.merge_skill_dir(str(upstream), str(local), {})

    def test_local_routing_fields_survive_upstream_body_update(self):
        with tempfile.TemporaryDirectory() as temp:
            base, upstream, local = self.fixture(Path(temp))
            original = (base / 'SKILL.md').read_text() + '\nShared instructions.\n\n## Workflow\nOld workflow.\n'
            for path in (base, upstream, local):
                (path / 'SKILL.md').write_text(original)
            customized = original.replace('description: Sample\n',
                'description: Sample\nwhen_to_use: "检查示例功能"\ndispatch_intent: "示例功能检查"\n')
            (local / 'SKILL.md').write_text(customized)
            (upstream / 'SKILL.md').write_text(original.replace('Old workflow.', 'Updated upstream workflow.'))
            update_skill.merge_skill_dir(str(upstream), str(local), {}, baseline=str(base))
            result = (local / 'SKILL.md').read_text()
            fields = update_skill.parse_frontmatter(result)
            self.assertEqual(fields['when_to_use'], '检查示例功能')
            self.assertEqual(fields['dispatch_intent'], '示例功能检查')
            self.assertIn('Updated upstream workflow.', result)

    def test_upstream_description_replaces_local_summary_and_keeps_chinese_display(self):
        for updated, header in ((False, '>-'), (True, '>-'), (False, '|+'), (True, '|+')):
            with self.subTest(updated=updated, header=header), tempfile.TemporaryDirectory() as temp:
                base, upstream, local = self.fixture(Path(temp))
                original = (base / 'SKILL.md').read_text() + '\nShared context.\n\n## Workflow\nOld workflow.\n'
                source_block = f'description: {header}\n  Complete upstream purpose.\n  Use when reviewing a project.\n'
                original = original.replace('description: Sample\n', source_block)
                (base / 'SKILL.md').write_text(original)
                next_block = source_block.replace('Complete upstream purpose.', 'Updated upstream purpose.') if updated else source_block
                source = original.replace(source_block, next_block).replace('Old workflow.', 'New upstream workflow.')
                (upstream / 'SKILL.md').write_text(source)
                customized = original.replace(source_block,
                    'description: "本地简短摘要"\nwhen_to_use: "审查示例项目"\ndispatch_intent: "示例项目审查"\nmetadata:\n  zh_description: "本地中文展示"\n')
                (local / 'SKILL.md').write_text(customized)
                update_skill.merge_skill_dir(str(upstream), str(local), {}, baseline=str(base))
                result = (local / 'SKILL.md').read_text()
                fields = update_skill.parse_frontmatter(result)
                self.assertIn(next_block, result)
                self.assertEqual(fields['description'], update_skill.parse_frontmatter(source)['description'])
                self.assertEqual(fields['zh_description'], '本地中文展示')
                self.assertEqual(fields['when_to_use'], '审查示例项目')
                self.assertEqual(fields['dispatch_intent'], '示例项目审查')
                self.assertIn('New upstream workflow.', result)

    def test_divergent_routing_edits_report_conflict_without_changing_local(self):
        for field in ('when_to_use', 'dispatch_intent'):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temp:
                base, upstream, local = self.fixture(Path(temp))
                original = (base / 'SKILL.md').read_text().replace('description: Sample\n',
                    'description: Sample\n' + field + ': Original route\n')
                (base / 'SKILL.md').write_text(original)
                customized = original.replace('Original route', 'Local route')
                (local / 'SKILL.md').write_text(customized)
                (upstream / 'SKILL.md').write_text(original.replace('Original route', 'New upstream route'))
                with self.assertRaisesRegex(ValueError, 'conflict'):
                    update_skill.merge_skill_dir(str(upstream), str(local), {}, baseline=str(base))
                self.assertEqual((local / 'SKILL.md').read_text(), customized)

    def test_legacy_description_override_cannot_bypass_upstream_policy(self):
        with tempfile.TemporaryDirectory() as temp:
            base, upstream, local = self.fixture(Path(temp))
            original = (base / 'SKILL.md').read_text() + '\nShared context.\n\n## Workflow\nOld workflow.\n'
            (base / 'SKILL.md').write_text(original)
            (upstream / 'SKILL.md').write_text(original.replace('Old workflow.', 'New upstream workflow.'))
            local_block = 'description: |-\n  Explicit local description.\n  Preserve literal line breaks.\n'
            customized = original.replace('description: Sample\n',
                local_block + 'metadata:\n  keep_local_description: true\n')
            (local / 'SKILL.md').write_text(customized)
            update_skill.merge_skill_dir(str(upstream), str(local), {}, baseline=str(base))
            result = (local / 'SKILL.md').read_text()
            self.assertNotIn(local_block, result)
            self.assertIn('description: Sample\n', result)
            self.assertIn('New upstream workflow.', result)

    def test_updater_rejects_rewritten_upstream_routing_before_writing_files(self):
        for field in ('when_to_use', 'dispatch_intent'):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temp:
                base, upstream, local = self.fixture(Path(temp))
                original = (base / 'SKILL.md').read_text().replace('description: Sample\n',
                    'description: Sample\n' + field + ': "debug, crash, regression"\n')
                for path in (base, upstream, local):
                    (path / 'SKILL.md').write_text(original)
                customized = original.replace('debug, crash, regression', 'debug, regression')
                (local / 'SKILL.md').write_text(customized)
                (upstream / 'new-mode.md').write_text('# New mode\n')
                with self.assertRaisesRegex(ValueError, 'upstream routing'):
                    update_skill.merge_skill_dir(str(upstream), str(local), {}, baseline=str(base))
                self.assertEqual((local / 'SKILL.md').read_text(), customized)
                self.assertFalse((local / 'new-mode.md').exists())

    def test_same_line_conflict_and_modified_upstream_deletion_are_visible(self):
        with tempfile.TemporaryDirectory() as temp:
            base, upstream, local = self.fixture(Path(temp))
            (local / 'helper.py').write_text('local = True\n')
            (upstream / 'helper.py').write_text('source = True\n')
            with self.assertRaisesRegex(ValueError, 'conflict'):
                update_skill.merge_skill_dir(str(upstream), str(local), {}, baseline=str(base))
            self.assertEqual((local / 'helper.py').read_text(), 'local = True\n')
            (upstream / 'helper.py').unlink()
            with self.assertRaisesRegex(ValueError, 'conflict'):
                update_skill.merge_skill_dir(str(upstream), str(local), {}, baseline=str(base))

    def test_clean_upstream_deletion_and_missing_source_file_are_reconciled(self):
        with tempfile.TemporaryDirectory() as temp:
            base, upstream, local = self.fixture(Path(temp))
            (upstream / 'helper.py').unlink()
            (base / 'missing-mode.md').write_text('# Required mode\n')
            (upstream / 'missing-mode.md').write_text('# Required mode\n')
            update_skill.merge_skill_dir(str(upstream), str(local), {}, baseline=str(base))
            self.assertFalse((local / 'helper.py').exists())
            self.assertTrue((local / 'missing-mode.md').exists())

    def test_equal_commit_is_not_proof_of_complete_installed_content(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            live = root / 'sample'
            live.mkdir()
            original = '---\nname: sample\ndescription: Sample\nmetadata:\n  github_url: https://github.com/example/skills\n  github_hash: ' + 'a' * 40 + '\n---\n# Full mode\n'
            (live / 'SKILL.md').write_text(original)
            def download(_url, _ref, destination):
                Path(destination, 'SKILL.md').write_text('---\nname: sample\ndescription: Sample\n---\n# Full mode\n')
                Path(destination, 'required-mode.md').write_text('# Required upstream mode\n')
                return True
            with mock.patch.object(core, 'resolve_direct_path', return_value=(str(live), None)), \
                    mock.patch.object(update_skill, 'BACKUP_ROOT', str(root / 'backups')), \
                    mock.patch.object(update_skill, 'latest_release', return_value=('v1.0.0', 'a' * 40)), \
                    mock.patch.object(update_skill, 'download_repo', side_effect=download), \
                    mock.patch.object(update_skill, 'get_commit_date', return_value=None):
                self.assertTrue(update_skill.update_direct_skill('sample'))
            self.assertTrue((live / 'required-mode.md').exists())
            self.assertTrue((live / 'upstream-merge.json').exists())


class PluginUpdateTests(unittest.TestCase):
    def run_fixture(self, root, modified=False, same_commit=False, concurrent=False):
        claude = root / '.claude'
        installed = claude / 'plugins/cache/market/demo/original'
        (installed / '.claude-plugin').mkdir(parents=True)
        baseline = {'.claude-plugin/plugin.json': '{"name":"demo","version":"1.0.0"}',
                    'helper.py': 'BASELINE = True\n'}
        for name, text in baseline.items():
            (installed / name).write_text(text)
        if modified:
            (installed / 'helper.py').write_text('LOCAL_CUSTOMIZATION = True\n')
        registry = claude / 'plugins/installed_plugins.json'
        original = json.dumps({'plugins': {'demo@market': [{'installPath': str(installed), 'gitCommitSha': 'a' * 40, 'version': '1.0.0'}]}})
        registry.write_text(original)
        markets = claude / 'plugins/known_marketplaces.json'
        markets.write_text(json.dumps({'market': {'source': {'repo': 'example/skills'}}}))
        def download(_url, ref, destination):
            if concurrent and ref == 'b' * 40:
                changed = json.loads(original)
                changed['other_registration'] = 'preserve this concurrent change'
                registry.write_text(json.dumps(changed))
            files = baseline if ref == 'a' * 40 else {**baseline, 'new-mode.md': '# New capability\n'}
            for name, text in files.items():
                path = Path(destination) / name
                path.parent.mkdir(exist_ok=True, parents=True)
                path.write_text(text)
            return True
        with mock.patch.object(update_skill, 'INSTALLED_PLUGINS_JSON', str(registry)), \
                mock.patch.object(update_skill, 'KNOWN_MARKETPLACES_JSON', str(markets)), \
                mock.patch.object(update_skill, 'CLAUDE_DIR', str(claude)), \
                mock.patch.object(update_skill, 'get_remote_hash', return_value=('a' if same_commit else 'b') * 40), \
                mock.patch.object(update_skill, 'download_repo', side_effect=download):
            result = update_skill.update_plugin('demo@market')
        return result, installed, registry, original

    def test_unmodified_plugin_updates_with_complete_source_files(self):
        with tempfile.TemporaryDirectory() as temp:
            success, original, registry, _ = self.run_fixture(Path(temp))
            self.assertTrue(success)
            new = Path(json.loads(registry.read_text())['plugins']['demo@market'][0]['installPath'])
            self.assertTrue((new / 'new-mode.md').is_file())
            self.assertTrue((new / 'helper.py').is_file())
            self.assertTrue(original.is_dir())

    def test_local_modifications_block_replacement_and_false_same_commit_success(self):
        for same_commit in (False, True):
            with self.subTest(same_commit=same_commit), tempfile.TemporaryDirectory() as temp:
                success, installed, registry, original = self.run_fixture(Path(temp), modified=True, same_commit=same_commit)
                self.assertFalse(success)
                self.assertEqual(registry.read_text(), original)
                self.assertEqual((installed / 'helper.py').read_text(), 'LOCAL_CUSTOMIZATION = True\n')

    def test_concurrent_registry_change_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            success, installed, registry, _original = self.run_fixture(Path(temp), concurrent=True)
            self.assertFalse(success)
            self.assertIn('other_registration', json.loads(registry.read_text()))
            self.assertEqual(json.loads(registry.read_text())['plugins']['demo@market'][0]['installPath'], str(installed))


if __name__ == '__main__':
    unittest.main()
