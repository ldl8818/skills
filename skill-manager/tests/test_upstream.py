import copy
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import audit_upstream as audit


class UpstreamCoverageTests(unittest.TestCase):
    def routing_fixture(self, root):
        source, info = self.fixture(root)
        source['SKILL.md'] = source['SKILL.md'].replace(b'metadata:\n',
            b'when_to_use: "debug, crash, regression"\ndispatch_intent: "Error, crash, regression"\nmetadata:\n')
        (root / 'SKILL.md').write_bytes(source['SKILL.md'])
        return source, info

    def test_routing_additions_may_precede_follow_or_split_original_items(self):
        for value in ('local trigger, debug, crash, regression',
                      'debug, local trigger, crash, regression',
                      'debug, crash, regression, local trigger'):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                source, info = self.routing_fixture(root)
                entry = root / 'SKILL.md'
                entry.write_bytes(source['SKILL.md'].replace(b'debug, crash, regression', value.encode()))
                receipt = audit.make_receipt(root, source, info, {'SKILL.md': ['Add a local trigger without changing source text.']})
                self.assertEqual(audit.verify(root, receipt, source), [])
                self.assertEqual(audit.verify(root, receipt), [])

    def test_routing_rewrite_cannot_be_excused_by_an_adaptation_reason(self):
        for field, before, after in (
                ('description', 'Synthetic fixture', 'A local summary'),
                ('when_to_use', 'debug, crash, regression', 'debug, regression'),
                ('when_to_use', 'debug, crash, regression', 'crash, debug, regression'),
                ('when_to_use', 'debug, crash, regression', '运行故障场景：debug, crash, regression'),
                ('when_to_use', 'debug, crash, regression', 'debug、crash、regression'),
                ('dispatch_intent', 'Error, crash, regression', '运行故障、崩溃与回归')):
            with self.subTest(field=field, after=after), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                source, info = self.routing_fixture(root)
                (root / 'SKILL.md').write_bytes(source['SKILL.md'].replace(before.encode(), after.encode()))
                with self.assertRaisesRegex(ValueError, 'upstream routing'):
                    audit.make_receipt(root, source, info, {'SKILL.md': ['Local customization.']})

    def test_offline_receipt_cannot_omit_the_upstream_field_contract(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, info = self.routing_fixture(root)
            receipt = audit.make_receipt(root, source, info, {})
            self.assertIn('upstream_fields', receipt['files']['SKILL.md'])
            receipt['files']['SKILL.md'].pop('upstream_fields')
            self.assertTrue(audit.verify(root, receipt))

    def test_resigning_local_hashes_cannot_hide_a_routing_rewrite(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, info = self.routing_fixture(root)
            receipt = audit.make_receipt(root, source, info, {})
            rewritten = source['SKILL.md'].replace(b'debug, crash, regression', b'debug, regression')
            (root / 'SKILL.md').write_bytes(rewritten)
            receipt['files']['SKILL.md'].update(local_sha256=audit.digest(rewritten),
                status='adapted', reason=['Local customization.'],
                changes=audit.changes(source['SKILL.md'], rewritten))
            self.assertTrue(any('upstream routing' in error for error in audit.verify(root, receipt)))

    def test_repository_all_github_frozen_skills_have_valid_receipts(self):
        repo = Path(__file__).resolve().parents[2]
        checked = []
        for entry in repo.glob('*/SKILL.md'):
            meta = audit.core.parse_skill_md(str(entry))
            if meta.get('github_url') and meta.get('update_policy') == 'frozen':
                receipt = __import__('json').loads((entry.parent / audit.RECEIPT).read_text())
                self.assertEqual(audit.verify(entry.parent, receipt), [], entry.parent.name)
                checked.append(entry.parent.name)
        self.assertTrue(checked)

    def fixture(self, root):
        entry = b'---\nname: sample\ndescription: Synthetic fixture\nmetadata:\n  github_hash: ' + b'a' * 40 + b'\n---\n# Full capability\nKeep this mode.\n'
        source = {'SKILL.md': entry, 'references/mode.md': b'# Mode\nComplete behavior.\n'}
        for name, data in source.items():
            path = root / name
            path.parent.mkdir(exist_ok=True, parents=True)
            path.write_bytes(data)
        return source, dict(commit='a' * 40, repository='https://github.com/example/skills', source_path='skills/sample')

    def test_exact_snapshot_and_local_adapter_are_accounted_for(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, info = self.fixture(root)
            (root / 'adapter.py').write_text('print("synthetic local behavior")\n')
            receipt = audit.make_receipt(root, source, info, {})
            self.assertEqual(audit.verify(root, receipt, source), [])
            self.assertEqual(len(receipt['files']), 2)
            self.assertIn('adapter.py', receipt['local_only'])
            (root / 'adapter.py').unlink()
            self.assertTrue(audit.verify(root, receipt, source))

    def test_missing_upstream_mode_cannot_be_recorded(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, info = self.fixture(root)
            (root / 'references/mode.md').unlink()
            with self.assertRaisesRegex(ValueError, 'missing upstream files'):
                audit.make_receipt(root, source, info, {})

    def test_silent_entry_simplification_and_unexplained_edits_fail(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, info = self.fixture(root)
            receipt = audit.make_receipt(root, source, info, {})
            entry = root / 'SKILL.md'
            entry.write_bytes(source['SKILL.md'].replace(b'# Full capability\nKeep this mode.\n', b'# Short summary\n'))
            self.assertTrue(audit.verify(root, receipt, source))
            with self.assertRaisesRegex(ValueError, 'unexplained upstream adaptation'):
                audit.make_receipt(root, source, info, {})
            with self.assertRaisesRegex(ValueError, 'missing upstream sections'):
                audit.make_receipt(root, source, info, {'SKILL.md': ['Keep local customizations.']})

    def test_explicit_adaptation_is_reproducible_and_bound_to_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, info = self.fixture(root)
            path = root / 'references/mode.md'
            path.write_bytes(source['references/mode.md'] + b'Honor an explicit read-only request.\n')
            receipt = audit.make_receipt(root, source, info, {'references/mode.md': ['Preserve local read-only policy.']})
            self.assertEqual(audit.verify(root, receipt, source), [])
            self.assertTrue(receipt['files']['references/mode.md']['changes'])
            changed_source = {**source, 'new-mode.md': b'New upstream capability\n'}
            self.assertTrue(audit.verify(root, receipt, changed_source))
            forged = copy.deepcopy(receipt)
            forged['files']['references/mode.md']['status'] = 'identical'
            self.assertTrue(audit.verify(root, forged, source))

    def test_empty_receipts_and_symlinks_never_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, info = self.fixture(root)
            self.assertTrue(audit.verify(root, {'schema': 1, 'commit': 'a' * 40, 'files': {}}))
            (root / 'external').symlink_to(root.parent)
            with self.assertRaisesRegex(ValueError, 'symlink'):
                audit.make_receipt(root, source, info, {})

    def test_explicit_fixture_path_adaptation_retains_source_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, info = self.fixture(root)
            source['fixture/.env'] = b'EXAMPLE_ENDPOINT=https://example.invalid\n'
            target = root / 'fixture/.env.example'
            target.parent.mkdir()
            target.write_bytes(source['fixture/.env'])
            receipt = audit.make_receipt(root, source, info, {
                'fixture/.env': dict(local_path='fixture/.env.example', reason=['Ship synthetic environment examples only.'])})
            self.assertEqual(audit.verify(root, receipt, source), [])
            self.assertEqual(receipt['files']['fixture/.env']['local_path'], 'fixture/.env.example')


if __name__ == '__main__':
    unittest.main()
