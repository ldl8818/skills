"""Complete command coverage and source recovery, without accounts or network."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('opencli_sources', ROOT / 'scripts/opencli-source.py')
source = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(source)


def archive_fixture(name='docs/guide.md', data=b'Complete original guide.\n'):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w:gz') as archive:
        entry = tarfile.TarInfo('source/' + name)
        entry.size, entry.mode = len(data), 0o644
        archive.addfile(entry, io.BytesIO(data))
    payload = stream.getvalue()
    manifest = {'commit': 'synthetic', 'version': '2.0.2', 'archive_url': 'https://example.com/source.tar.gz',
                'archive_sha256': source.sha256(payload),
                'files': {name: {'sha256': source.sha256(data), 'size': len(data), 'mode': 0o644}}}
    return manifest, payload


def page(commands, **extra):
    return types.SimpleNamespace(stdout=json.dumps({'ok': True, 'data': {'commands': commands, **extra}}))


class SourceTests(unittest.TestCase):
    def test_complete_snapshot_accounts_for_every_command_and_guide(self):
        manifest = source.metadata()
        capabilities = json.loads((ROOT / 'upstream/opencli-capabilities.json').read_text())
        self.assertEqual(len(manifest['files']), 2346)
        self.assertEqual(len(manifest['package']['files']), 1579)
        self.assertEqual(len(capabilities['sites']), 170)
        self.assertEqual(len(capabilities['site_commands']), 1223)
        self.assertEqual(len(capabilities['builtin_commands']), 66)
        self.assertEqual(len(capabilities['skills']), 5)
        originals = {name for name in manifest['files'] if name.startswith(('docs/', 'skills/')) and name.endswith('.md')}
        self.assertEqual(set(capabilities['references']), originals)
        for command in capabilities['site_commands'].values():
            self.assertIn(command['source'], manifest['files'])
        self.assertEqual(list(ROOT.rglob('SKILL.md')), [ROOT / 'SKILL.md'])

    def test_complete_archive_and_changed_inventory(self):
        manifest, payload = archive_fixture()
        self.assertEqual(source.source_files(payload, manifest)['docs/guide.md'], b'Complete original guide.\n')
        with self.assertRaisesRegex(source.SourceError, 'archive_changed'):
            source.source_files(payload + b'changed', manifest)
        manifest['files'] = {}
        with self.assertRaisesRegex(source.SourceError, 'inventory_changed'):
            source.source_files(payload, manifest)

    def test_parent_traversal_cannot_be_imported(self):
        manifest, payload = archive_fixture('../outside')
        with self.assertRaisesRegex(source.SourceError, 'unsafe_source_member'):
            source.source_files(payload, manifest)

    def test_download_is_verified_and_second_reference_uses_same_complete_source(self):
        manifest, payload = archive_fixture()
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, XDG_CACHE_HOME=temporary), \
             patch.object(source.urllib.request, 'urlopen', return_value=io.BytesIO(payload)) as fetch, \
             patch.object(source, 'metadata', return_value=manifest):
            for _ in range(2):
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(source.main(['reference', 'docs/guide.md']), 0)
                self.assertTrue(output.getvalue().endswith('Complete original guide.\n\n'))
            self.assertEqual(fetch.call_count, 1)
            cached = Path(temporary) / 'lookup/opencli/synthetic/source.tar.gz'
            cached.write_bytes(b'unknown user content')
            with self.assertRaisesRegex(source.SourceError, 'archive_changed'):
                source.cached_files(manifest)
            self.assertEqual(cached.read_bytes(), b'unknown user content')
            self.assertEqual(fetch.call_count, 1)

    def test_unknown_reference_never_downloads(self):
        manifest, _ = archive_fixture()
        with patch.object(source, 'metadata', return_value=manifest), \
             patch.object(source.urllib.request, 'urlopen') as fetch, \
             contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(source.main(['reference', '../private.md']), 78)
        fetch.assert_not_called()

    def test_reference_verifies_the_complete_archive_once_per_invocation(self):
        manifest, payload = archive_fixture()
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, XDG_CACHE_HOME=temporary), \
             patch.object(source.urllib.request, 'urlopen', return_value=io.BytesIO(payload)), \
             patch.object(source, 'metadata', return_value=manifest), \
             patch.object(source, 'source_files', wraps=source.source_files) as verify:
            for _ in range(2):
                verify.reset_mock()
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(source.main(['reference', 'docs/guide.md']), 0)
                self.assertIn('Complete original guide.', output.getvalue())
                self.assertEqual(verify.call_count, 1)

    def test_symlinked_cache_parent_is_rejected_without_download_or_external_write(self):
        manifest, payload = archive_fixture()
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, XDG_CACHE_HOME=temporary), \
             patch.object(source.urllib.request, 'urlopen', return_value=io.BytesIO(payload)) as fetch:
            root = Path(temporary)
            outside = root / 'outside'
            outside.mkdir()
            (root / 'lookup').symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(source.SourceError, 'source_cache_symlink'):
                source.cached_files(manifest)
            fetch.assert_not_called()
            self.assertEqual(list(outside.iterdir()), [])

    def test_cache_file_created_during_download_is_never_overwritten(self):
        manifest, payload = archive_fixture()
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, XDG_CACHE_HOME=temporary):
            target = Path(temporary) / 'lookup/opencli/synthetic/source.tar.gz'
            def concurrent_write(*args, **kwargs):
                target.parent.mkdir(parents=True)
                target.write_bytes(b'concurrent unknown content')
                return io.BytesIO(payload)
            with patch.object(source.urllib.request, 'urlopen', side_effect=concurrent_write):
                with self.assertRaisesRegex(source.SourceError, 'archive_changed'):
                    source.cached_files(manifest)
            self.assertEqual(target.read_bytes(), b'concurrent unknown content')
            self.assertEqual([path.name for path in target.parent.iterdir()], ['source.tar.gz'])

    def test_user_selected_cache_root_can_be_a_symlink(self):
        manifest, payload = archive_fixture()
        with tempfile.TemporaryDirectory() as temporary:
            actual = Path(temporary) / 'actual'
            actual.mkdir()
            configured = Path(temporary) / 'configured'
            configured.symlink_to(actual, target_is_directory=True)
            with patch.dict(os.environ, XDG_CACHE_HOME=str(configured)), \
                 patch.object(source.urllib.request, 'urlopen', return_value=io.BytesIO(payload)):
                self.assertEqual(source.cached_files(manifest)['docs/guide.md'], b'Complete original guide.\n')
            self.assertTrue((actual / 'lookup/opencli/synthetic/source.tar.gz').is_file())

    def test_concurrent_valid_cache_is_reused_and_temporary_file_is_removed(self):
        manifest, payload = archive_fixture()
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, XDG_CACHE_HOME=temporary):
            target = Path(temporary) / 'lookup/opencli/synthetic/source.tar.gz'
            def concurrent_write(*args, **kwargs):
                target.parent.mkdir(parents=True)
                target.write_bytes(payload)
                return io.BytesIO(payload)
            with patch.object(source.urllib.request, 'urlopen', side_effect=concurrent_write):
                self.assertEqual(source.cached_files(manifest)['docs/guide.md'], b'Complete original guide.\n')
            self.assertEqual(target.read_bytes(), payload)
            self.assertEqual([path.name for path in target.parent.iterdir()], ['source.tar.gz'])

    def test_command_pages_preserve_access_and_include_new_commands(self):
        capabilities = {'site_commands': {'example read': {'access': 'read'}},
                        'builtin_commands': {'skills read': {'access': 'unspecified'}}}
        pages = [page([{'command':'example read','access':'read'}], total=3, nextOffset=1),
                 page([{'command':'skills read'}, {'command':'new action','access':'write'}], total=3)]
        with patch.object(source.subprocess, 'run', side_effect=pages) as run:
            result = source.contract('/synthetic/opencli', capabilities)
        self.assertEqual(result['extra_commands'], ['new action'])
        self.assertEqual(run.call_args.args[0], ['/synthetic/opencli','list','--limit','100','--offset','1','-f','json'])

    def test_missing_and_read_to_write_changes_are_rejected(self):
        cap = {'site_commands': {'example read': {'access':'read'}}, 'builtin_commands': {}}
        for commands in ([], [{'command':'example read','access':'write'}]):
            with self.subTest(commands=commands), patch.object(source.subprocess, 'run', return_value=page(commands)):
                with self.assertRaises(source.SourceError):
                    source.contract('/synthetic/opencli', cap)

    def test_incomplete_or_stalled_pagination_is_rejected(self):
        cap = {'site_commands': {}, 'builtin_commands': {}}
        for response in (page([], nextOffset=0), page([], total=1)):
            with patch.object(source.subprocess, 'run', return_value=response):
                with self.assertRaisesRegex(source.SourceError, 'pagination'):
                    source.contract('/synthetic/opencli', cap)

    def test_upgrade_must_keep_every_native_execution_guide(self):
        cap = {'site_commands': {}, 'builtin_commands': {},
               'skills': {'opencli-browser':'skills/opencli-browser/SKILL.md',
                          'smart-search':'skills/smart-search/SKILL.md'}}
        registry = page([],total=0)
        guides = types.SimpleNamespace(stdout=json.dumps({'ok':True,'data':[{'name':'opencli-browser'}]}))
        original = types.SimpleNamespace(stdout='---\nname: opencli-browser\n---\nFull native guide.')
        with patch.object(source.subprocess, 'run', side_effect=[registry,guides,original]):
            self.assertEqual(source.contract('/synthetic/opencli',cap)['bundled_guides'], ['opencli-browser'])
        missing = types.SimpleNamespace(stdout=json.dumps({'ok':True,'data':[]}))
        with patch.object(source.subprocess, 'run', side_effect=[registry,missing]):
            with self.assertRaisesRegex(source.SourceError, 'bundled_guides_missing'):
                source.contract('/synthetic/opencli',cap)
        with patch.object(source.subprocess, 'run', side_effect=[registry,guides,types.SimpleNamespace(stdout='truncated')]):
            with self.assertRaisesRegex(source.SourceError, 'bundled_guide_invalid'):
                source.contract('/synthetic/opencli',cap)


if __name__ == '__main__':
    unittest.main()
