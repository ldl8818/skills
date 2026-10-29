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
        with tempfile.TemporaryDirectory() as temporary:
            package = self.write_package(Path(temporary))
            result = reach.package_contract(package)
        self.assertEqual(set(result['channels']), set(capabilities['native_channels']))
        self.assertEqual(len(result['channels']), 14)
        self.assertEqual(result['native_actions'], 40)
        self.assertEqual(set(result['commands']), set(capabilities['cli']))
        self.assertIn('rss', capabilities['lookup_routes'])
        self.assertIn('exa_search', capabilities['lookup_routes'])
        for channel in capabilities['channels'].values():
            self.assertIn(channel['reference'], reach.REFERENCES)
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
            self.assertEqual(len(reach.package_contract(package)['channels']), 14)
            registry = package / 'channels/__init__.py'
            registry.write_text('\n'.join(line for line in registry.read_text().splitlines()
                                          if not any(name in line for name in
                                                     ('BossChannel', 'FacebookChannel', 'InstagramChannel'))) + '\n')
            with self.assertRaisesRegex(reach.IntegrationError, 'missing_channels'):
                reach.package_contract(package)
            self.assertIn('__version__ = "1.6.0"', (package / '__init__.py').read_text())

    def test_dependency_candidate_requires_complete_references(self):
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary) / 'agent_reach'
            for name, content in self.files.items():
                if name.startswith('agent_reach/'):
                    target = package / name.removeprefix('agent_reach/')
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(content)
            (package / 'skill/references/maintenance.md').unlink()
            with self.assertRaisesRegex(reach.IntegrationError, 'missing_references'):
                reach.package_contract(package)

    def test_unknown_candidate_layout_returns_contract_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            package = self.write_package(Path(temporary))
            path = package / 'channels/web.py'
            path.write_text(path.read_text().replace('name = "web"', 'renamed = "web"'))
            with self.assertRaisesRegex(reach.IntegrationError, 'candidate_contract_unknown'):
                reach.package_contract(package)

    def test_every_category_returns_the_entire_original_reference(self):
        for category, source in reach.REFERENCES.items():
            with self.subTest(category=category), contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(reach.main(['reference', category]), 0)
                self.assertTrue(output.getvalue().endswith(self.files[source].decode() + '\n'))

    def test_raw_routing_fields_are_preserved_without_discoverable_skill(self):
        self.assertIn('只读', self.files['agent_reach/skill/SKILL.md'].decode())
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
            manifest['files'].pop('agent_reach/skill/references/maintenance.md')
            (source / 'agent-reach.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(reach.IntegrationError, 'inventory_changed'):
                reach.source_files(source)

    def test_only_recorded_functions_are_adapted_and_original_is_intact(self):
        adapted = reach.adapted_files(self.manifest, self.files)
        changed = {name for name in self.files if self.files[name] != adapted[name]}
        self.assertEqual(changed, {'agent_reach/runtime/manage.py', 'agent_reach/runtime/browser.py',
                                   'agent_reach/runtime/session_reuse.py', 'agent_reach/channels/v2ex.py'})
        for name in changed:
            before, after = ast.parse(self.files[name]), ast.parse(adapted[name])
            self.assertEqual([node.name for node in before.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))],
                             [node.name for node in after.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))])
        self.assertEqual(len(self.files), len(self.manifest['files']))
        self.assertGreater(len(self.files), 100)



    def test_v2ex_reply_failure_and_first_page_are_explicitly_partial(self):
        code = reach.adapted_files(self.manifest, self.files)['agent_reach/channels/v2ex.py']
        node = next(n for n in ast.walk(ast.parse(code)) if isinstance(n, ast.FunctionDef) and n.name == '_api_read')
        for total, returned, fails in [(2, 2, False), (150, 100, False), (2, 0, True), (0, 0, True), (0, 0, False)]:
            def get_json(url):
                if 'replies/show' in url:
                    if fails:
                        raise RuntimeError('synthetic unavailable replies')
                    return [{'content': 'reply'} for _ in range(returned)]
                return [{'id': 12, 'replies': total, 'content': 'topic'}]
            namespace = {'_get_json': get_json, '_v2ex_url': lambda path, **kw: path,
                         '_parse_topic_id': lambda target: 12, 'ReachError': RuntimeError, 'NOT_FOUND': 'NOT_FOUND',
                         '_topic_item': lambda topic, **kw: {'title': 'topic', **kw}}
            exec(compile(ast.Module(body=[node], type_ignores=[]), '<native-v2ex>', 'exec'), namespace)
            raw = namespace['_api_read'](None, target='12', timeout=10)[0]['raw']
            with self.subTest(total=total, returned=returned, fails=fails):
                self.assertEqual(raw.get('replies_complete'), not fails and returned >= total)
                self.assertEqual(raw['replies_error'], 'RuntimeError' if fails else None)
                self.assertEqual(len(raw['replies']), returned)

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

    def test_mcp_runs_status_adapter_in_verified_runtime_without_installing(self):
        with patch.object(reach, 'runtime_status', return_value={'ready':True,'python':'/synthetic/python'}), \
             patch.object(reach.subprocess, 'call', return_value=3) as call:
            self.assertEqual(reach.main(['mcp']), 3)
        self.assertEqual(call.call_args.args[0], ['/synthetic/python','-I','-B',str(ROOT / 'scripts/reach_mcp.py')])

    def test_missing_mcp_runtime_never_installs(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, XDG_DATA_HOME=temporary), \
             patch.object(reach.subprocess, 'call') as call, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(reach.main(['mcp']), 78)
            self.assertEqual(list(Path(temporary).iterdir()), [])
        call.assert_not_called()

    def test_missing_or_incompatible_mcp_sdk_does_not_suggest_replacing_engine(self):
        code = (ROOT / 'scripts/reach_mcp.py').read_bytes()
        tree = ast.parse(code)
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'create_server')
        namespace = {'HAS_MCP':False, 'sys':sys}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'<mcp-dependency>','exec'), namespace)
        with contextlib.redirect_stderr(io.StringIO()) as error, self.assertRaises(SystemExit):
            namespace['create_server']()
        self.assertIn('>=1.0,<2', error.getvalue())
        self.assertNotIn('archive/main', error.getvalue())


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

    def write_package(self, root):
        package = root / 'agent_reach'
        for name, content in self.files.items():
            if name.startswith('agent_reach/'):
                target = package / name.removeprefix('agent_reach/')
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
        return package


    def test_selected_channel_installer_rejects_browser_before_any_install(self):
        import types
        code = reach.adapted_files(self.manifest, self.files)['agent_reach/runtime/manage.py']
        node = next(n for n in ast.parse(code).body if isinstance(n, ast.FunctionDef) and n.name == '_install_channel')
        calls = []
        namespace = {'List': list, 'NEED_SETUP': 'NEED_SETUP', 'ReachError': RuntimeError,
                     '_uses_browser': lambda ch: ch.browser,
                     'channel_tools': lambda ch: ['selected-tool'],
                     'tools': types.SimpleNamespace(ensure=lambda name, **kw: calls.append(name) or name)}
        exec(compile(ast.Module(body=[node], type_ignores=[]), '<native-install>', 'exec'), namespace)
        with self.assertRaises(RuntimeError):
            namespace['_install_channel'](types.SimpleNamespace(browser=True))
        self.assertEqual(calls, [])
        ch = types.SimpleNamespace(browser=False, on_add=lambda: calls.append('selected-on-add'))
        self.assertEqual(namespace['_install_channel'](ch), ['selected-tool'])
        self.assertEqual(calls, ['selected-tool', 'selected-on-add'])


    def test_doctor_reports_local_state_without_live_channel_probes(self):
        import types
        node = next(n for n in ast.parse(self.files['agent_reach/runtime/manage.py']).body
                    if isinstance(n, ast.FunctionDef) and n.name == 'doctor')
        node.body = [n for n in node.body if not isinstance(n, ast.ImportFrom)]
        channel = types.SimpleNamespace(name='synthetic', level='default')
        calls = []
        namespace = {'state': types.SimpleNamespace(load=lambda: {'checks': {}}),
                     '_channels': lambda: [channel], 'fresh_actions': lambda *args: {},
                     'channel_status': lambda ch, data: {'status': 'unverified'},
                     'regressed': lambda x: False, '__version__': 'synthetic',
                     'tools': types.SimpleNamespace(recorded=lambda: []),
                     'capability_summary': lambda channels, rows: calls.append(rows) or {}}
        exec(compile(ast.Module(body=[node], type_ignores=[]), '<native-doctor>', 'exec'), namespace)
        result = namespace['doctor']()
        self.assertEqual(result['channels'], [{'channel': 'synthetic', 'level': 'default',
                                               'status': 'unverified', 'regressed': False}])
        self.assertEqual(len(calls), 1)


    def test_candidate_cannot_drop_native_resources_actions_or_public_python_api(self):
        with tempfile.TemporaryDirectory() as temporary:
            package = self.write_package(Path(temporary))
            result = reach.package_contract(package)
            self.assertGreater(result['python_api_symbols'], 20)
            (package / 'skill/references/sessions.md').unlink()
            (package / 'scripts/transcribe_xiaoyuzhou.sh').unlink()
            (package / 'channels/web.py').write_text((package / 'channels/web.py').read_text()
                                                    .replace('def read(', 'def removed_read(')
                                                    .replace('"search",', '"removed-search",'))
            with self.assertRaises(reach.IntegrationError) as error:
                reach.package_contract(package)
            self.assertIn('sessions', str(error.exception))
            self.assertIn('transcribe_xiaoyuzhou.sh', str(error.exception))
            self.assertIn('WebChannel.read', str(error.exception))
            self.assertIn('web:search', str(error.exception))


    def test_browser_login_and_native_upgrader_cannot_bypass_lookup(self):
        for args in [['browser', 'setup'], ['login', 'xiaohongshu'], ['logout', 'twitter'], ['update']]:
            with self.subTest(args=args), patch.object(reach, 'runtime_status') as status:
                with self.assertRaises(reach.IntegrationError):
                    reach.run_native(args, self.manifest, self.files)
                status.assert_not_called()


    def test_implicit_browser_and_cookie_copy_fail_before_side_effects(self):
        import types
        modules = types.ModuleType('guard_fixture')
        modules.NEED_SETUP = 'NEED_SETUP'
        modules.ReachError = RuntimeError
        with patch.dict(sys.modules, {'guard_fixture': modules}):
            for name, functions in [('browser', ['ensure_chrome', 'start', 'ensure_running', 'setup', 'open_url']),
                                    ('session_reuse', ['prepare'])]:
                code = reach.adapted_files(self.manifest, self.files)[f'agent_reach/runtime/{name}.py']
                for node in ast.parse(code).body:
                    if not isinstance(node, ast.FunctionDef) or node.name not in functions:
                        continue
                    # Execute the actual guarded entry with imports bound to a no-side-effect exception module.
                    for item in ast.walk(node):
                        if isinstance(item, ast.ImportFrom):
                            item.module, item.level = 'guard_fixture', 0
                    namespace = {}
                    node.returns = None
                    for argument in node.args.args + node.args.kwonlyargs:
                        argument.annotation = None
                    exec(compile(ast.Module(body=[node], type_ignores=[]), '<browser-guard>', 'exec'), namespace)
                    with self.subTest(function=node.name), self.assertRaises(RuntimeError):
                        args = ('synthetic',) if node.name in ('open_url', 'prepare') else ()
                        namespace[node.name](*args)




if __name__ == '__main__':
    unittest.main()
