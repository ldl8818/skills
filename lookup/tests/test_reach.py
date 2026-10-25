import ast
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('lookup_reach', ROOT / 'scripts/reach.py')
reach = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reach)


class SourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest, cls.files = reach.source_files()

    def test_complete_channel_registry_and_cli_are_mapped(self):
        capabilities = json.loads((ROOT / 'upstream/capabilities.json').read_text())
        tree = ast.parse(self.files['agent_reach/channels/__init__.py'])
        classes = next(node.value.elts for node in tree.body if isinstance(node, ast.AnnAssign)
                       and node.target.id == 'ALL_CHANNELS')
        names = set()
        for call in classes:
            for name, content in self.files.items():
                if name.startswith('agent_reach/channels/') and name.endswith('.py'):
                    for node in ast.parse(content).body:
                        if isinstance(node, ast.ClassDef) and node.name == call.func.id:
                            names.add(next(item.value.value for item in node.body
                                           if isinstance(item, ast.Assign)
                                           and any(isinstance(t, ast.Name) and t.id == 'name' for t in item.targets)))
        self.assertEqual(names, set(capabilities['channels']))
        self.assertEqual(len(names), 16)
        cli = ast.parse(self.files['agent_reach/cli.py'])
        commands = {node.args[0].value for node in ast.walk(cli) if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute) and node.func.attr == 'add_parser'
                    and isinstance(node.func.value, ast.Name) and node.func.value.id == 'sub'}
        self.assertEqual(commands, set(capabilities['cli']))
        for channel in capabilities['channels'].values():
            self.assertIn(channel['reference'], capabilities['source_references'])
            self.assertTrue(channel['actions'])
            for reference in channel['lookup_references']:
                self.assertTrue((ROOT / reference).is_file(), reference)

    def test_dependency_candidate_cannot_hide_missing_channels_at_same_version(self):
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary) / 'agent_reach'
            for name, content in self.files.items():
                if name.startswith('agent_reach/'):
                    target = package / name.removeprefix('agent_reach/')
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(content)
            self.assertEqual(len(reach.package_contract(package)['channels']), 16)
            registry = package / 'channels/__init__.py'
            registry.write_text('\n'.join(line for line in registry.read_text().splitlines()
                                          if not any(name in line for name in
                                                     ('BossChannel', 'FacebookChannel', 'InstagramChannel'))) + '\n')
            with self.assertRaisesRegex(reach.IntegrationError, 'missing_channels'):
                reach.package_contract(package)
            self.assertIn('__version__ = "1.5.0"', (package / '__init__.py').read_text())

    def test_dependency_candidate_requires_complete_references(self):
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary) / 'agent_reach'
            for name, content in self.files.items():
                if name.startswith('agent_reach/'):
                    target = package / name.removeprefix('agent_reach/')
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(content)
            (package / 'skill/references/career.md').unlink()
            with self.assertRaisesRegex(reach.IntegrationError, 'missing_references'):
                reach.package_contract(package)

    def test_every_category_returns_the_entire_original_reference(self):
        for category, source in reach.REFERENCES.items():
            with self.subTest(category=category), contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(reach.main(['reference', category]), 0)
                self.assertTrue(output.getvalue().endswith(self.files[source].decode() + '\n'))

    def test_raw_routing_fields_are_preserved_without_discoverable_skill(self):
        self.assertIn('MUST USE', self.files['agent_reach/skill/SKILL.md'].decode())
        self.assertIn('agent_reach/skill/SKILL_en.md', self.files)
        self.assertEqual([path.relative_to(ROOT).as_posix() for path in ROOT.rglob('SKILL.md')], ['SKILL.md'])

    def test_changed_archive_and_changed_file_inventory_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            manifest = copy.deepcopy(self.manifest)
            original = (ROOT / 'upstream/agent-reach.tar.gz').read_bytes()
            (source / 'agent-reach.tar.gz').write_bytes(original + b'changed')
            (source / 'agent-reach.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(reach.IntegrationError, 'archive_changed'):
                reach.source_files(source)
            manifest['archive_sha256'] = hashlib.sha256(original + b'changed').hexdigest()
            manifest['files'].pop('agent_reach/skill/references/career.md')
            (source / 'agent-reach.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(reach.IntegrationError, 'inventory_changed'):
                reach.source_files(source)

    def test_only_recorded_functions_are_adapted_and_original_is_intact(self):
        adapted = reach.adapted_files(self.manifest, self.files)
        changed = [name for name in self.files if self.files[name] != adapted[name]]
        self.assertEqual(set(changed), {'agent_reach/cli.py', 'agent_reach/doctor.py', 'agent_reach/channels/v2ex.py',
                                        'agent_reach/integrations/mcp_server.py', 'pyproject.toml'})
        self.assertIn(b'"mcp[cli]>=1.0,<2"', adapted['pyproject.toml'])
        self.assertIn(b'"mcp[cli]>=1.0"', self.files['pyproject.toml'])
        original = ast.parse(self.files['agent_reach/cli.py'])
        candidate = ast.parse(adapted['agent_reach/cli.py'])
        old = {node.name: node for node in original.body if isinstance(node, ast.FunctionDef)}
        new = {node.name: node for node in candidate.body if isinstance(node, ast.FunctionDef)}
        for name in old.keys() - {'_install_skill', '_cmd_install'}:
            self.assertEqual(ast.dump(old[name]), ast.dump(new[name]), name)
        self.assertIsInstance(new['_install_skill'].body[1], ast.Return)
        self.assertTrue(new['_install_skill'].body[1].value.value)
        self.assertEqual(len(self.files), 121)

    def test_selected_channel_installer_keeps_unrelated_setup_and_probes_out(self):
        import types
        for selected, expected in [('boss', []), ('', ['core', 'exa']), ('all', ['core', 'exa'])]:
            with self.subTest(selected=selected), tempfile.TemporaryDirectory() as temporary, \
                 patch.dict(os.environ, {'HOME': temporary}):
                tree = ast.parse(reach.adapted_files(self.manifest, self.files)['agent_reach/cli.py'])
                node = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == '_cmd_install')
                node.body = [item for item in node.body if not isinstance(item, ast.ImportFrom)]
                calls, probes = [], []
                names = ['twitter','xiaoyuzhou','xhs','reddit','bili','boss','opencli']
                namespace = {'sys': sys, 'Config': lambda **kwargs: None,
                             'check_all': lambda config, **kwargs: probes.append(kwargs.get('channels')) or {},
                             'format_report': lambda results: '', '_install_skill': lambda: True,
                             '_install_system_deps': lambda: calls.append('core'),
                             '_install_mcporter': lambda: calls.append('exa')}
                namespace.update({'_install_'+name+'_deps': lambda: True for name in names})
                exec(compile(ast.Module(body=[node], type_ignores=[]), '<source-install>', 'exec'), namespace)
                with contextlib.redirect_stdout(io.StringIO()):
                    namespace['_cmd_install'](types.SimpleNamespace(env='local',system=True,safe=False,
                                                                    dry_run=False,channels=selected,proxy=''))
                self.assertEqual(calls, expected)
                self.assertEqual(probes, [{'boss'}] if selected == 'boss' else [None])

    def test_filtered_doctor_only_probes_requested_channels(self):
        import types
        code = reach.adapted_files(self.manifest, self.files)['agent_reach/doctor.py']
        node = next(node for node in ast.parse(code).body if isinstance(node, ast.FunctionDef) and node.name == 'check_all')
        calls = []
        def channel(name):
            return types.SimpleNamespace(name=name,description=name,tier=1,backends=['fixture'],
                                         active_backend='fixture',check=lambda config:(calls.append(name) or ('ok','ready')))
        namespace = {'Dict': dict, 'Config': object, 'get_all_channels': lambda:[channel('boss'),channel('twitter')],
                     'scrub_url_credentials': lambda value:value}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'<source-doctor>','exec'),namespace)
        self.assertEqual(set(namespace['check_all'](None,channels={'boss'})), {'boss'})
        self.assertEqual(calls,['boss'])
        calls.clear()
        self.assertEqual(namespace['check_all'](None,channels=set()), {})
        self.assertEqual(calls,[])
        self.assertEqual(set(namespace['check_all'](None)), {'boss','twitter'})

    def test_v2ex_reply_failure_and_first_page_are_explicitly_partial(self):
        from urllib.parse import quote
        code = reach.adapted_files(self.manifest, self.files)['agent_reach/channels/v2ex.py']
        tree = ast.parse(code)
        node = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == 'get_topic')
        for total, returned, fails in [(2, 2, False), (150, 100, False), (2, 0, True), (0, 0, True), (0, 0, False)]:
            def get_json(url):
                if 'replies/show' in url:
                    if fails:
                        raise RuntimeError('synthetic unavailable replies')
                    return [{'content': 'reply'} for _ in range(returned)]
                return [{'id': 12, 'replies': total, 'content': 'topic'}]
            namespace = {'_get_json': get_json, '_v2ex_url': lambda path, **kw: path,
                         '_API_BASE': 'https://example.com', 'quote': quote}
            exec(compile(ast.Module(body=[node], type_ignores=[]), '<source-get-topic>', 'exec'), namespace)
            result = namespace['get_topic'](None, 12)
            with self.subTest(total=total, returned=returned, fails=fails):
                self.assertEqual(result['replies_complete'], not fails and returned >= total)
                self.assertEqual(result['replies_error'], 'RuntimeError' if fails else None)
                self.assertEqual(len(result['replies']), returned)

    def test_missing_runtime_never_installs_implicitly(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {'XDG_DATA_HOME': temporary}):
            with contextlib.redirect_stderr(io.StringIO()) as output:
                self.assertEqual(reach.main(['run', 'version']), 78)
            self.assertIn('runtime_not_prepared', output.getvalue())
            self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_registration_is_rejected_before_any_runtime_or_write(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {'XDG_DATA_HOME': temporary}):
            with self.assertRaisesRegex(reach.IntegrationError, 'registration_owned'):
                reach.run_native(['skill', '--install'], self.manifest, self.files)
            self.assertEqual(list(Path(temporary).iterdir()), [])
            with self.assertRaisesRegex(reach.IntegrationError, 'registration_owned'):
                reach.run_native(['--verbose', 'skill', '--uninstall'], self.manifest, self.files)

    def test_native_leading_options_and_separator_are_forwarded(self):
        for argv, expected in [(['run', '--version'], ['--version']),
                               (['run', '--', '--version'], ['--version']),
                               (['run', '-v', 'doctor', '--json'], ['-v', 'doctor', '--json'])]:
            with self.subTest(argv=argv), patch.object(reach, 'run_native', return_value=0) as run:
                self.assertEqual(reach.main(argv), 0)
                self.assertEqual(run.call_args.args[0], expected)

    def test_mcp_runs_original_module_in_verified_runtime_without_installing(self):
        with patch.object(reach, 'runtime_status', return_value={'ready':True,'python':'/synthetic/python'}), \
             patch.object(reach.subprocess, 'call', return_value=3) as call:
            self.assertEqual(reach.main(['mcp']), 3)
        self.assertEqual(call.call_args.args[0], ['/synthetic/python','-I','-B','-m','agent_reach.integrations.mcp_server'])

    def test_missing_mcp_runtime_never_installs(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, XDG_DATA_HOME=temporary), \
             patch.object(reach.subprocess, 'call') as call, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(reach.main(['mcp']), 78)
            self.assertEqual(list(Path(temporary).iterdir()), [])
        call.assert_not_called()

    def test_missing_or_incompatible_mcp_sdk_does_not_suggest_replacing_engine(self):
        code = reach.adapted_files(self.manifest, self.files)['agent_reach/integrations/mcp_server.py']
        tree = ast.parse(code)
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'create_server')
        namespace = {'HAS_MCP':False, 'sys':sys}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'<mcp-dependency>','exec'), namespace)
        with contextlib.redirect_stderr(io.StringIO()) as error, self.assertRaises(SystemExit):
            namespace['create_server']()
        self.assertIn('>=1.0,<2', error.getvalue())
        self.assertNotIn('archive/main', error.getvalue())

    def test_candidate_cannot_drop_setup_guides_mcp_or_public_python_api(self):
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary) / 'agent_reach'
            for name, content in self.files.items():
                if name.startswith('agent_reach/'):
                    target = package / name.removeprefix('agent_reach/')
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(content)
            result = reach.package_contract(package)
            self.assertGreater(result['python_api_symbols'], 20)
            (package/'guides/setup-groq.md').unlink()
            (package/'integrations/mcp_server.py').unlink()
            (package/'channels/web.py').write_text((package/'channels/web.py').read_text().replace('def read(', 'def removed_read('))
            with self.assertRaises(reach.IntegrationError) as error:
                reach.package_contract(package)
            self.assertIn('setup-groq.md', str(error.exception))
            self.assertIn('mcp_server.py', str(error.exception))
            self.assertIn('WebChannel.read', str(error.exception))

    def test_failed_preparation_preserves_other_data_and_removes_its_environment(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {'XDG_DATA_HOME': temporary}):
            unrelated = Path(temporary) / 'other-data'
            unrelated.write_text('keep')
            with patch.object(reach.shutil, 'which', return_value='/synthetic/uv'), \
                 patch.object(reach.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, ['uv'])):
                with self.assertRaises(subprocess.CalledProcessError):
                    reach.prepare(self.manifest, self.files)
            self.assertEqual(unrelated.read_text(), 'keep')
            self.assertFalse(reach.runtime_dir(self.manifest).exists())
            self.assertFalse((reach.data_root() / 'prepare.lock').exists())

    def test_existing_partial_runtime_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {'XDG_DATA_HOME': temporary}):
            directory = reach.runtime_dir(self.manifest)
            directory.mkdir(parents=True)
            (directory / 'unknown').write_text('keep')
            with patch.object(reach.shutil, 'which', return_value='/synthetic/uv'):
                with self.assertRaisesRegex(reach.IntegrationError, 'incomplete_runtime_preserved'):
                    reach.prepare(self.manifest, self.files)
            self.assertEqual((directory / 'unknown').read_text(), 'keep')

    def test_preparation_lock_is_released_after_process_is_killed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            script = '''import importlib.util, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location('reach_child', sys.argv[1])
reach = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reach)
with reach.preparation_lock(Path(sys.argv[2])):
    print('locked', flush=True)
    sys.stdin.readline()
'''
            child = subprocess.Popen([sys.executable, '-c', script, str(ROOT / 'scripts/reach.py'), str(root)],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                self.assertEqual(child.stdout.readline().strip(), 'locked')
                with self.assertRaisesRegex(reach.IntegrationError, 'preparation_in_progress'):
                    with reach.preparation_lock(root):
                        self.fail('concurrent preparation acquired the lock')
            finally:
                child.kill()
                child.communicate(timeout=5)
            with reach.preparation_lock(root):
                pass

    def test_runtime_receipt_cannot_escape_through_parent_paths_or_symlinks(self):
        for escaped in ('parent', 'symlink'):
            with self.subTest(escaped=escaped), tempfile.TemporaryDirectory() as temporary, \
                 patch.dict(os.environ, XDG_DATA_HOME=temporary):
                directory = reach.runtime_dir(self.manifest)
                directory.mkdir(parents=True)
                outside = directory.parent / 'outside'
                package = outside / 'agent_reach'
                for name, content in reach.adapted_files(self.manifest, self.files).items():
                    if name.startswith('agent_reach/'):
                        target = package / name.removeprefix('agent_reach/')
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(content)
                python = reach.python_path(directory)
                python.parent.mkdir(parents=True)
                python.write_text('synthetic interpreter')
                if escaped == 'parent':
                    saved_package = '../outside/agent_reach'
                else:
                    (directory / 'linked').symlink_to(outside, target_is_directory=True)
                    saved_package = 'linked/agent_reach'
                (directory / 'receipt.json').write_text(json.dumps({
                    'commit': self.manifest['commit'], 'source_sha256': self.manifest['archive_sha256'],
                    'integration_id': reach.integration_id(self.manifest), 'package': saved_package}))
                with self.assertRaisesRegex(reach.IntegrationError, 'runtime_package_path_changed'):
                    reach.runtime_status(self.manifest, self.files)

    def test_runtime_verification_accepts_original_files_and_rejects_later_changes(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, XDG_DATA_HOME=temporary):
            directory = reach.runtime_dir(self.manifest)
            package = directory / 'venv/lib/site-packages/agent_reach'
            for name, content in reach.adapted_files(self.manifest, self.files).items():
                if name.startswith('agent_reach/'):
                    target = package / name.removeprefix('agent_reach/')
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(content)
            python = reach.python_path(directory)
            python.parent.mkdir(parents=True, exist_ok=True)
            python.write_text('synthetic interpreter')
            (directory / 'receipt.json').write_text(json.dumps({
                'commit': self.manifest['commit'], 'source_sha256': self.manifest['archive_sha256'],
                'integration_id': reach.integration_id(self.manifest),
                'package': str(package.relative_to(directory))}))
            self.assertTrue(reach.runtime_status(self.manifest, self.files)['ready'])
            (package / 'cli.py').write_text('changed after preparation')
            with self.assertRaisesRegex(reach.IntegrationError, 'runtime_package_changed'):
                reach.runtime_status(self.manifest, self.files)
            (package / 'cli.py').write_bytes(reach.adapted_files(self.manifest, self.files)['agent_reach/cli.py'])
            outside = directory.parent / 'outside-channels'
            (package / 'channels').rename(outside)
            (package / 'channels').symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(reach.IntegrationError, 'runtime_package_changed'):
                reach.runtime_status(self.manifest, self.files)

    def test_malformed_runtime_receipt_returns_a_structured_error(self):
        valid = {'commit': self.manifest['commit'], 'source_sha256': self.manifest['archive_sha256'],
                 'integration_id': reach.integration_id(self.manifest)}
        for saved in ([], valid, {**valid, 'package': []}):
            with self.subTest(saved=saved), tempfile.TemporaryDirectory() as temporary, \
                 patch.dict(os.environ, XDG_DATA_HOME=temporary):
                directory = reach.runtime_dir(self.manifest)
                directory.mkdir(parents=True)
                receipt = directory / 'receipt.json'
                original = json.dumps(saved)
                receipt.write_text(original)
                with contextlib.redirect_stderr(io.StringIO()) as error:
                    self.assertEqual(reach.main(['status']), 78)
                self.assertEqual(json.loads(error.getvalue())['error'], 'runtime_receipt_invalid')
                self.assertEqual(receipt.read_text(), original)

    def test_arguments_remain_single_argv_values(self):
        status = {'ready': True, 'python': '/synthetic/python'}
        query = 'https://example.com/?q=$(touch unsafe);echo hidden'
        with patch.object(reach, 'runtime_status', return_value=status), \
             patch.object(reach.subprocess, 'call', return_value=3) as call:
            self.assertEqual(reach.run_native(['transcribe', query], self.manifest, self.files), 3)
        self.assertEqual(call.call_args.args[0], ['/synthetic/python', '-I', '-B', '-m', 'agent_reach.cli', 'transcribe', query])
        self.assertNotIn('shell', call.call_args.kwargs)


if __name__ == '__main__':
    unittest.main()
