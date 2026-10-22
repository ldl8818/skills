import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('lookup_entries', ROOT / 'scripts/entrypoints.py')
entries = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(entries)


class EntryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name).resolve()
        self.lookup = self.home / 'source/lookup'
        self.lookup.mkdir(parents=True)
        (self.lookup / 'SKILL.md').write_text('---\nname: lookup\n---\n')
        self.storage = self.home / '.local/share/lookup/execution-skills'
        self.shared = self.home / '.agents/skills'
        self.shared.mkdir(parents=True)

    def test_relative_source_link_is_preserved_and_only_lookup_is_discovered(self):
        original = self.home / 'source/ego-browser'
        original.mkdir()
        (original / 'SKILL.md').write_text('---\nname: ego-browser\n---\noriginal')
        link = self.shared / 'ego-browser'
        link.symlink_to('../../source/ego-browser')
        result = entries.migrate(self.home, self.lookup, self.storage)
        self.assertEqual(result['migrated'], 1)
        self.assertFalse(entries.existing(link))
        self.assertEqual((self.shared / 'lookup').resolve(), self.lookup)
        preserved = self.storage / '.agents/ego-browser'
        self.assertEqual(preserved.resolve(), original)
        self.assertEqual((preserved / 'SKILL.md').read_text(), '---\nname: ego-browser\n---\noriginal')
        self.assertEqual(entries.inventory(self.home, self.lookup)[0]['competing'], [])
        self.assertFalse((self.home / '.claude').exists())
        again = entries.migrate(self.home, self.lookup, self.storage)
        self.assertEqual(again['migrated'], 0)
        self.assertEqual(again['lookup_created'], 0)
        self.assertEqual(len(json.loads((self.storage / 'entries.json').read_text())['entries']), 1)

    def test_real_skill_directory_is_preserved_and_unrelated_skill_is_untouched(self):
        skill = self.shared / 'agent-reach'
        skill.mkdir()
        (skill / 'SKILL.md').write_text('---\nname: agent-reach\n---\noriginal')
        other = self.shared / 'some-domain'
        other.mkdir()
        (other / 'SKILL.md').write_text('keep')
        entries.migrate(self.home, self.lookup, self.storage)
        self.assertEqual((self.storage / '.agents/agent-reach/SKILL.md').read_text(),
                         '---\nname: agent-reach\n---\noriginal')
        self.assertEqual((other / 'SKILL.md').read_text(), 'keep')

    def test_conflicting_lookup_prevents_all_changes(self):
        other = self.home / 'other-lookup'
        other.mkdir()
        (self.shared / 'lookup').symlink_to(other)
        internal = self.shared / 'ego-browser'
        internal.mkdir()
        with self.assertRaisesRegex(entries.EntryError, 'lookup_entry_conflict'):
            entries.migrate(self.home, self.lookup, self.storage)
        self.assertTrue(internal.is_dir())
        self.assertFalse(self.storage.exists())
        self.assertEqual((self.shared / 'lookup').resolve(), other)

    def test_existing_preserved_source_is_not_overwritten(self):
        internal = self.shared / 'agent-reach'
        internal.mkdir()
        (internal / 'SKILL.md').write_text('---\nname: agent-reach\n---\n')
        preserved = self.storage / '.agents/agent-reach'
        preserved.mkdir(parents=True)
        (preserved / 'unique').write_text('keep')
        with self.assertRaisesRegex(entries.EntryError, 'destination_conflict'):
            entries.migrate(self.home, self.lookup, self.storage)
        self.assertTrue(internal.is_dir())
        self.assertEqual((preserved / 'unique').read_text(), 'keep')
        self.assertFalse(entries.existing(self.shared / 'lookup'))

    def test_later_failure_rolls_back_moved_sources(self):
        from unittest.mock import patch
        internal = self.shared / 'ego-browser'
        internal.mkdir()
        (internal / 'SKILL.md').write_text('---\nname: ego-browser\n---\noriginal')
        original = Path.symlink_to
        def fail_lookup(path, target, **kwargs):
            if path.name == 'lookup':
                raise OSError('synthetic write failure')
            return original(path, target, **kwargs)
        with patch.object(Path, 'symlink_to', fail_lookup):
            with self.assertRaises(OSError):
                entries.migrate(self.home, self.lookup, self.storage)
        self.assertEqual((internal / 'SKILL.md').read_text(), '---\nname: ego-browser\n---\noriginal')
        self.assertFalse((self.storage / 'entries.json').exists())

    def test_same_named_unidentified_source_is_preserved(self):
        internal = self.shared / 'agent-reach'
        internal.mkdir()
        (internal / 'SKILL.md').write_text('---\nname: another-skill\n---\n')
        with self.assertRaisesRegex(entries.EntryError, 'identity_mismatch'):
            entries.migrate(self.home, self.lookup, self.storage)
        self.assertTrue(internal.is_dir())
        self.assertFalse(self.storage.exists())

    def test_symlinked_storage_parent_is_preserved(self):
        outside = self.home / 'outside'
        outside.mkdir()
        (self.home / '.local').symlink_to(outside)
        with self.assertRaisesRegex(entries.EntryError, 'storage_symlink'):
            entries.migrate(self.home, self.lookup, self.storage)
        self.assertEqual(list(outside.iterdir()), [])

    def test_installed_source_directory_is_a_valid_single_source(self):
        import shutil
        source = self.shared / 'lookup'
        shutil.copytree(self.lookup, source)
        result = entries.migrate(self.home, source, self.storage)
        self.assertEqual(result['lookup_created'], 0)
        self.assertEqual(result['clients'][0]['lookup'], 'ready')
        self.assertFalse(source.is_symlink())

    def test_first_install_creates_only_the_shared_entry(self):
        import shutil
        shutil.rmtree(self.shared.parent)
        result = entries.migrate(self.home, self.lookup, self.storage)
        self.assertEqual(result['lookup_created'], 1)
        self.assertEqual((self.shared / 'lookup').resolve(), self.lookup)
        self.assertFalse((self.home / '.codex').exists())
        self.assertFalse((self.home / '.claude').exists())

    def test_upgrader_reintroduced_entry_preserves_both_source_versions(self):
        source = self.shared / 'agent-reach'
        source.mkdir()
        (source / 'SKILL.md').write_text('---\nname: agent-reach\n---\nold')
        entries.migrate(self.home, self.lookup, self.storage)
        source.mkdir()
        (source / 'SKILL.md').write_text('---\nname: agent-reach\n---\nnew')
        result = entries.migrate(self.home, self.lookup, self.storage)
        self.assertEqual(result['migrated'], 1)
        receipt = json.loads((self.storage / 'entries.json').read_text())
        self.assertEqual(len(receipt['entries']), 2)
        self.assertEqual((Path(receipt['entries'][0]['preserved']) / 'SKILL.md').read_text(), '---\nname: agent-reach\n---\nold')
        self.assertEqual((Path(receipt['entries'][1]['preserved']) / 'SKILL.md').read_text(), '---\nname: agent-reach\n---\nnew')
        self.assertFalse(source.exists())

    def test_all_opencli_guides_are_preserved_without_registering_competitors(self):
        for name in ('opencli-usage','opencli-browser','opencli-adapter-author','opencli-autofix','smart-search'):
            path = self.shared / name
            path.mkdir()
            (path/'SKILL.md').write_text(f'---\nname: {name}\ndescription: OpenCLI guide.\n---\nlocal addition\n')
        result = entries.migrate(self.home, self.lookup, self.storage)
        self.assertEqual(result['migrated'], 5)
        self.assertEqual(result['clients'][0]['competing'], [])
        for name in ('opencli-usage','opencli-browser','opencli-adapter-author','opencli-autofix','smart-search'):
            self.assertIn('local addition', (self.storage/'.agents'/name/'SKILL.md').read_text())

    def test_unrelated_same_named_smart_search_is_not_moved(self):
        path = self.shared/'smart-search'
        path.mkdir()
        (path/'SKILL.md').write_text('---\nname: smart-search\n---\nUnrelated source.\n')
        result = entries.migrate(self.home, self.lookup, self.storage)
        self.assertEqual(result['migrated'], 0)
        self.assertTrue(path.is_dir())


if __name__ == '__main__':
    unittest.main()
