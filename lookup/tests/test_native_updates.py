"""Native updater contracts in owned virtualenvs and synthetic browser CLIs."""
import importlib.util
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/upstream.py'
spec = importlib.util.spec_from_file_location('lookup_native_updates', SCRIPT)
upstream = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upstream)


def executable(path, code, python=sys.executable):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('#!'+python+'\n'+code)
    path.chmod(0o700)
    return path


def complete_package_fixture(version):
    reach_spec = importlib.util.spec_from_file_location('fixture_reach', SCRIPT.with_name('reach.py'))
    reach = importlib.util.module_from_spec(reach_spec)
    reach_spec.loader.exec_module(reach)
    _, originals = reach.source_files()
    files = {name: data.decode() for name, data in originals.items() if name.startswith('agent_reach/')}
    commands = sorted(json.loads((SCRIPT.parents[1] / 'upstream/capabilities.json').read_text())['cli'])
    cli = 'import argparse\ndef main():\n    p=argparse.ArgumentParser()\n'
    cli += '    p.add_argument("--version",action="version",version="Agent Reach v' + version + '")\n'
    cli += '    sub=p.add_subparsers()\n'
    cli += ''.join('    sub.add_parser(' + repr(name) + ')\n' for name in commands)
    cli += '    p.parse_args()\n'
    files['agent_reach/__init__.py'] = ''
    files['agent_reach/cli.py'] = cli
    return files


class NativeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='lookup-native-updates-')
        self.base = Path(self.temp.name)
        self.home = self.base/'home'
        self.home.mkdir()
        self.bin = self.base/'bin'
        self.bin.mkdir()
        self.env = patch.dict(os.environ, HOME=str(self.home),
                              XDG_STATE_HOME=str(self.base/'state'), CI='1',
                              PATH=str(self.bin)+os.pathsep+os.environ['PATH'])
        self.env.start()
        self.store = upstream.Store()
        self.release = {'latest': '1.5.0', 'published_at': '2026-01-01T00:00:00Z',
                        'url': 'https://github.com/Panniantong/Agent-Reach/releases/tag/v1.5.0'}

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def ego(self, behavior='updated'):
        version = self.base/'ego-version'
        version.write_text('0.6.0.16')
        calls = self.base/'ego-upgrade-calls'
        calls.write_text('')
        binary = executable(self.bin/'ego-browser', f'''import pathlib,sys
version=pathlib.Path({str(version)!r})
args=sys.argv[1:]
if args==['--version']:print('ego-browser '+version.read_text())
elif args==['skill']:print('incomplete guide' if {behavior!r}=='missing-guide' else '[ego-browser:skill] end of guide v2.1.0')
elif args==['upgrade']:
 with pathlib.Path({str(calls)!r}).open('a') as log:log.write('upgrade\\n')
 behavior={behavior!r}
 if behavior in ['updated','missing-guide']:version.write_text('0.6.0.17');print('updated')
 elif behavior=='current':print('already up-to-date')
 elif behavior=='downgrade':version.write_text('0.5.0.1');print('updated')
 elif behavior=='pending':print('waiting for confirmation')
 elif behavior=='error':raise SystemExit(1)
''')
        return binary, version, calls

    def agent(self, manager='uv', outcome='updated', origin=None):
        prefix = (self.base/'agent-reach' if manager=='uv' else
                  self.base/'pipx/venvs/agent-reach' if manager=='pipx' else self.base/'environment')
        subprocess.run([sys.executable, '-m', 'venv', '--without-pip', str(prefix)], check=True,
                       capture_output=True, timeout=15)
        python = prefix/'bin/python'
        site = Path(subprocess.check_output([str(python), '-c', 'import sysconfig;print(sysconfig.get_path("purelib"))'], text=True).strip())
        dist = site/'agent_reach-1.4.0.dist-info'
        dist.mkdir()
        metadata = dist/'METADATA'
        metadata.write_text('Name: agent-reach\nVersion: 1.4.0\n')
        (dist/'direct_url.json').write_text(json.dumps(origin if origin is not None else
            {'url': 'https://github.com/Panniantong/Agent-Reach/archive/main.zip', 'archive_info': {}}))
        skill = site/'agent_reach/skill'
        (skill/'references').mkdir(parents=True)
        (skill/'SKILL.md').write_text('name: agent-reach\n')
        for name, value in complete_package_fixture('1.4.0').items():
            path=site/name; path.parent.mkdir(parents=True,exist_ok=True); path.write_text(value)
        version = prefix/'fixture-version'
        version.write_text('1.4.0')
        script = executable(prefix/'bin/agent-reach', f'''import pathlib,sys
if sys.argv[1:]==['--version']:print('Agent Reach v'+pathlib.Path({str(version)!r}).read_text())
elif sys.argv[1:]==['--help']:print('agent-reach doctor skill')
''', str(python))
        self.write_record(dist, site, script)
        launcher = self.bin/'agent-reach'
        launcher.symlink_to(script)
        calls = self.base/'installer-calls'
        installer_code = f'''import pathlib,sys,os,json
pathlib.Path({str(calls)!r}).write_text(repr(sys.argv[1:]))
pathlib.Path({str(self.base/'manager-environment')!r}).write_text(json.dumps({{k:os.environ.get(k) for k in ['UV_TOOL_DIR','UV_TOOL_BIN_DIR','PIPX_HOME','PIPX_BIN_DIR']}}))
version=pathlib.Path({str(version)!r});metadata=pathlib.Path({str(metadata)!r})
outcome={outcome!r}
if outcome=='updated':
 version.write_text('1.5.0');metadata.write_text('Name: agent-reach\\nVersion: 1.5.0\\n')
elif outcome=='error':
 version.write_text('9.0.0');raise SystemExit(1)
elif outcome=='missing-skill':
 version.write_text('1.5.0');pathlib.Path({str(skill/'SKILL.md')!r}).unlink()
'''
        if manager == 'uv':
            (prefix/'uv-receipt.toml').write_text('[tool]\nrequirements = [{name="agent-reach"}]\n')
            executable(self.bin/'uv', installer_code)
        elif manager == 'pipx':
            (prefix/'pipx_metadata.json').write_text('{"main_package":{"package":"agent-reach"}}')
            executable(self.bin/'pipx', installer_code)
        else:
            (site/'pip').mkdir()
            (site/'pip/__init__.py').write_text('')
            (site/'pip/__main__.py').write_text(installer_code)
        return launcher, prefix, version, calls

    def write_record(self, dist, site, script):
        rows = []
        for file in list((site/'agent_reach').rglob('*')) + [script]:
            if file.is_file():
                value = base64.urlsafe_b64encode(hashlib.sha256(file.read_bytes()).digest()).decode().rstrip('=')
                rows.append(f'{os.path.relpath(file, site)},sha256={value},{file.stat().st_size}')
        (dist/'RECORD').write_text('\n'.join(rows)+'\n')

    def test_ego_update_targets_same_local_install_as_runner(self):
        binary, version, calls = self.ego()
        local = self.home/'.local/bin/ego-browser'
        local.parent.mkdir(parents=True)
        local.symlink_to(binary)
        other = self.base/'another-bin'
        other.mkdir()
        executable(other/'ego-browser', 'print("ego-browser 0.5.0.1")\n')
        with patch.dict(os.environ, PATH=str(other)+os.pathsep+os.environ['PATH']):
            self.assertEqual(upstream.installed(self.store, 'ego-browser')['binary'], str(local))
            self.assertEqual(upstream.update(self.store, 'ego-browser')['status'], 'updated')
        self.assertEqual(version.read_text(), '0.6.0.17')
        self.assertEqual(calls.read_text(), 'upgrade\n')

    def test_ego_explicit_binary_override_is_honored_by_update(self):
        binary, _, calls = self.ego()
        with patch.dict(os.environ, EGO_BROWSER_BIN=str(binary)):
            self.assertEqual(upstream.installed(self.store, 'ego-browser')['binary'], str(binary))
            self.assertEqual(upstream.update(self.store, 'ego-browser')['status'], 'updated')
        self.assertEqual(calls.read_text(), 'upgrade\n')

    def test_ego_changed_local_skill_is_retained_then_merged_without_reupgrade(self):
        header = '---\nname: ego-browser\ndescription: Synthetic browser execution guide.\n---\n'
        binary, _, calls = self.ego()
        skill = self.home/'.agents/skills/ego-browser'
        skill.mkdir(parents=True)
        entry = skill/'SKILL.md'
        entry.write_text(header + 'old guide\nlocal capability\n')
        with binary.open('a') as handle:
            handle.write(f'if args==["upgrade"]:pathlib.Path({str(entry)!r}).write_text({(header + "new guide" + chr(10))!r})\n')
        first = upstream.update(self.store, 'ego-browser')
        self.assertEqual(first['status'], 'manual_review', first)
        self.assertTrue(first['native_runtime_updated'])
        self.assertEqual(entry.read_text(), header + 'old guide\nlocal capability\n')
        self.assertEqual(upstream.update(self.store, 'ego-browser')['status'], 'manual_review')
        root, request = upstream.customization.load(self.store, 'ego-browser')
        original = self.base/'official-old-skill'
        original.mkdir()
        (original/'SKILL.md').write_text(header + 'old guide\n')
        upstream.customization.recover_baseline(self.store, 'ego-browser', 'skill-0', original,
                                                'https://lite.ego.app/synthetic-old-skill')
        new_source = self.base/'official-new-skill'
        new_source.mkdir()
        (new_source/'SKILL.md').write_text(header + 'new guide\n')
        upstream.customization.recover_baseline(self.store, 'ego-browser', 'skill-0', new_source,
                                                'https://lite.ego.app/synthetic-new-skill', label='upstream')
        (root/'0/merged/SKILL.md').write_text(header + 'new guide\nlocal capability\n')
        decision = self.base/'ego-decisions.json'
        decision.write_text(json.dumps({'target': '0.6.0.17', 'decisions': [
            {'scope': 'skill-0', 'path': 'SKILL.md', 'disposition': 'preserved',
             'reason': 'New guide lacks the local capability.', 'evidence': 'All three fixture guides compared.',
             'validation': 'Merged guide retains new guide and local capability.'}],
            'adaptations': [{'scope': 'skill-0', 'path': 'SKILL.md', 'reason': 'Retain local capability.'}]}))
        upstream.customization.accept(self.store, 'ego-browser', decision)
        result = upstream.update(self.store, 'ego-browser')
        self.assertEqual(result['status'], 'updated', result)
        self.assertFalse(result['native_reinvoked'])
        self.assertFalse(entry.exists())
        receipt = json.loads((self.home/'.local/share/lookup/execution-skills/entries.json').read_text())
        preserved = Path(receipt['entries'][0]['preserved'])/'SKILL.md'
        self.assertEqual(preserved.read_text(), header + 'new guide\nlocal capability\n')
        self.assertEqual(calls.read_text(), 'upgrade\n')

    def test_ego_unchanged_external_skill_still_requires_semantic_review(self):
        self.ego()
        skill = self.home/'.agents/skills/ego-browser'
        skill.mkdir(parents=True)
        (skill/'SKILL.md').write_text('old guide\nlocal capability\n')
        result = upstream.update(self.store, 'ego-browser')
        self.assertEqual(result['status'], 'manual_review', result)
        _, request = upstream.customization.load(self.store, 'ego-browser')
        self.assertFalse(request['scopes'][0]['upstream_known'])
        self.assertIn('local capability', (skill/'SKILL.md').read_text())

    def test_ego_pending_upgrade_cannot_be_completed_by_skill_review(self):
        binary, _, calls = self.ego('pending')
        skill = self.home/'.agents/skills/ego-browser'
        skill.mkdir(parents=True)
        entry = skill/'SKILL.md'
        entry.write_text('old guide\nlocal capability\n')
        with binary.open('a') as handle:
            handle.write(f'if args==["upgrade"]:pathlib.Path({str(entry)!r}).write_text("new guide\\n")\n')
        result = upstream.update(self.store, 'ego-browser')
        self.assertEqual(result['status'], 'pending', result)
        self.assertEqual(entry.read_text(), 'old guide\nlocal capability\n')
        self.assertEqual(self.store.read('review-ego-browser.json'), {})
        self.assertEqual(upstream.update(self.store, 'ego-browser')['status'], 'outcome_unknown')
        self.assertEqual(calls.read_text(), 'upgrade\n')
        record = self.store.read('native-ego-browser.json')
        observed = record['protected_skills'][0]['observations']
        self.assertTrue(observed)
        self.assertEqual((Path(observed[-1]['directory'])/'SKILL.md').read_text(), 'new guide\n')

    def test_ego_pending_upgrade_keeps_concurrent_editor_content_in_recovery(self):
        binary, _, _ = self.ego('pending')
        skill = self.home/'.agents/skills/ego-browser'
        skill.mkdir(parents=True)
        entry = skill/'SKILL.md'
        entry.write_text('old guide\nlocal capability\n')
        # A separate editor process writes while the native command is active.
        editor_code = f"from pathlib import Path;Path({str(entry)!r}).write_text('unique concurrent edit\\n')"
        with binary.open('a') as handle:
            handle.write('if args==["upgrade"]:\n import subprocess\n'
                         f' subprocess.run([sys.executable,"-c",{editor_code!r}],check=True)\n')
        result = upstream.update(self.store, 'ego-browser')
        self.assertEqual(result['status'], 'pending', result)
        protected = self.store.read('native-ego-browser.json')['protected_skills']
        recovered = [Path(o['directory'])/'SKILL.md' for item in protected for o in item['observations']]
        self.assertTrue(any(path.read_text() == 'unique concurrent edit\n' for path in recovered))

    def test_agent_modified_package_is_reviewed_before_installer_and_preserved(self):
        launcher, prefix, _, calls = self.agent('uv')
        environment = upstream.agent_reach_environment(str(launcher))
        live = Path(environment['package_root'])
        old, new = self.base/'official-old', self.base/'official-new'
        shutil.copytree(live, old)
        shutil.copytree(live, new)
        (new/'skill/SKILL.md').write_text('new guide\n')
        (live/'skill/SKILL.md').write_text('name: agent-reach\nlocal capability\n')
        with (self.bin/'uv').open('a') as handle:
            handle.write(f'\nimport shutil\nshutil.copytree({str(new)!r},{str(live)!r},dirs_exist_ok=True)\n')
        with patch.object(upstream, 'latest', return_value=self.release), patch.object(upstream, 'agent_source',
                side_effect=lambda store, version: old if version == '1.4.0' else new):
            first = upstream.update(self.store, 'agent-reach')
            self.assertEqual(first['status'], 'manual_review', first)
            self.assertFalse(calls.exists())
            self.assertIn('local capability', (live/'skill/SKILL.md').read_text())
            root, _ = upstream.customization.load(self.store, 'agent-reach')
            (root/'0/merged/skill/SKILL.md').write_text('new guide\nlocal capability\n')
            decision = self.base/'agent-decisions.json'
            decision.write_text(json.dumps({'target': '1.5.0', 'decisions': [
                {'scope': 'package', 'path': 'skill/SKILL.md', 'disposition': 'preserved',
                 'reason': 'New guide still lacks the local capability.', 'evidence': 'Original RECORD matches old source.',
                 'validation': 'Merged guide contains new and local sections.'}],
                'adaptations': [{'scope': 'package', 'path': 'skill/SKILL.md', 'reason': 'Preserve local capability.'}]}))
            upstream.customization.accept(self.store, 'agent-reach', decision)
            result = upstream.update(self.store, 'agent-reach')
        self.assertEqual(result['status'], 'updated', result)
        self.assertEqual((live/'skill/SKILL.md').read_text(), 'new guide\nlocal capability\n')

    def test_agent_unchanged_custom_external_skill_is_not_skipped(self):
        launcher, _, _, _ = self.agent('uv')
        environment = upstream.agent_reach_environment(str(launcher))
        skill = self.home/'.agents/skills/agent-reach'
        shutil.copytree(environment['skill_root'], skill)
        (skill/'SKILL.md').write_text('name: agent-reach\nlocal capability\n')
        with patch.object(upstream, 'latest', return_value=self.release):
            result = upstream.update(self.store, 'agent-reach')
        self.assertEqual(result['status'], 'manual_review', result)
        _, request = upstream.customization.load(self.store, 'agent-reach')
        self.assertTrue(request['scopes'][0]['base_known'])
        self.assertTrue(request['scopes'][0]['upstream_known'])
        self.assertIn('local capability', (skill/'SKILL.md').read_text())

    def test_generated_python_cache_does_not_become_a_source_customization(self):
        launcher, _, _, _ = self.agent('uv')
        environment = upstream.agent_reach_environment(str(launcher))
        package = Path(environment['package_root'])
        cache = package/'__pycache__/example.cpython-314.pyc'
        cache.parent.mkdir()
        cache.write_bytes(b'generated cache')
        site = package.parent
        record = next(site.glob('agent_reach-*.dist-info/RECORD'))
        with record.open('a') as handle:
            handle.write('agent_reach/__pycache__/example.cpython-314.pyc,,\n')
        environment = upstream.agent_reach_environment(str(launcher))
        self.assertEqual(environment['changed'], [])
        decision, _ = upstream.agent_customizations(self.store, environment, '1.5.0')
        self.assertIsNone(decision)

    def test_ego_executes_upgrade_and_verifies_version_and_full_guide(self):
        _, _, calls = self.ego()
        result = upstream.update(self.store, 'ego-browser')
        self.assertEqual(result['status'], 'updated')
        self.assertEqual(result['current'], '0.6.0.17')
        self.assertTrue(result['validation']['guide_complete'])
        self.assertFalse(result['validation']['business_verified'])
        self.assertEqual(calls.read_text(), 'upgrade\n')

    def test_ego_native_current_receipt_is_not_misreported_as_update(self):
        self.ego('current')
        self.assertEqual(upstream.update(self.store, 'ego-browser')['status'], 'up_to_date')

    def test_ego_confirmation_and_unknown_outcome_do_not_blindly_repeat(self):
        for behavior in ('pending', 'error'):
            with self.subTest(behavior=behavior):
                _, _, calls = self.ego(behavior)
                self.store.write('native-ego-browser.json', {})
                first = upstream.update(self.store, 'ego-browser')
                self.assertIn(first['status'], ('pending', 'outcome_unknown'))
                self.assertEqual(upstream.update(self.store, 'ego-browser')['status'], 'outcome_unknown')
                self.assertEqual(calls.read_text(), 'upgrade\n')
                upstream.update(self.store, 'ego-browser', retry=True)
                self.assertEqual(calls.read_text(), 'upgrade\nupgrade\n')

    def test_ego_resume_reconciles_completed_update_without_reinvoking(self):
        _, version, calls = self.ego('pending')
        upstream.update(self.store, 'ego-browser')
        version.write_text('0.6.0.17')
        result = upstream.update(self.store, 'ego-browser')
        self.assertEqual(result['status'], 'updated')
        self.assertTrue(result['recovered_after_interrupt'])
        self.assertEqual(calls.read_text(), 'upgrade\n')

    def test_ego_downgrade_is_not_reported_as_completed_update(self):
        _, _, calls = self.ego('downgrade')
        first = upstream.update(self.store, 'ego-browser')
        self.assertEqual(first['status'], 'pending')
        self.assertEqual(upstream.update(self.store,'ego-browser')['status'], 'outcome_unknown')
        self.assertEqual(calls.read_text(), 'upgrade\n')

    def test_ego_version_change_with_incomplete_guide_is_not_complete(self):
        self.ego('missing-guide')
        result=upstream.update(self.store,'ego-browser')
        self.assertEqual(result['status'],'outcome_unknown')
        self.assertEqual(result['error'],'EGO_EXECUTION_GUIDE_INCOMPLETE')

    @unittest.skipUnless(shutil.which('uv'), 'uv not installed')
    def test_real_uv_updates_only_the_selected_tool_root_and_preserves_other_root(self):
        wheels=self.base/'wheels';wheels.mkdir()
        def wheel(version):
            package='agent_reach-'+version
            files={
                'agent_reach/__init__.py':'',
                'agent_reach/cli.py':f'import sys\ndef main():\n print("Agent Reach v{version}" if "--version" in sys.argv else "agent-reach doctor skill")\n',
                'agent_reach/skill/SKILL.md':'name: agent-reach\n',
                'agent_reach/skill/references/web.md':'synthetic fixture\n',
                package+'.dist-info/METADATA':f'Metadata-Version: 2.1\nName: agent-reach\nVersion: {version}\n',
                package+'.dist-info/WHEEL':'Wheel-Version: 1.0\nGenerator: fixture\nRoot-Is-Purelib: true\nTag: py3-none-any\n',
                package+'.dist-info/entry_points.txt':'[console_scripts]\nagent-reach = agent_reach.cli:main\n',
            }
            files.update(complete_package_fixture(version))
            files[package+'.dist-info/RECORD']=''.join(
                name+',sha256='+base64.urlsafe_b64encode(hashlib.sha256(value.encode()).digest()).decode().rstrip('=')+','+str(len(value.encode()))+'\n'
                for name,value in files.items())
            target=wheels/(package+'-py3-none-any.whl')
            with zipfile.ZipFile(target,'w') as archive:
                for name,value in files.items():archive.writestr(name,value)
        wheel('1.4.0')
        original_root=self.base/'original-tools'
        other_root=self.base/'unrelated-tools';other_root.mkdir()
        sentinel=other_root/'keep';sentinel.write_text('unrelated installation')
        installer=shutil.which('uv')
        env=dict(os.environ,UV_TOOL_DIR=str(original_root),UV_TOOL_BIN_DIR=str(self.bin),
                 UV_CACHE_DIR=str(self.base/'cache'),UV_NO_CONFIG='1')
        subprocess.run([installer,'tool','install','--no-index','--find-links',str(wheels),
                        '--python',sys.executable,'--no-python-downloads','agent-reach'],
                       env=env,capture_output=True,check=True,timeout=30)
        wheel('1.5.0')
        with patch.dict(os.environ,UV_TOOL_DIR=str(other_root),UV_TOOL_BIN_DIR=str(self.base/'unrelated-bin'),
                        UV_CACHE_DIR=str(self.base/'cache'),UV_NO_CONFIG='1'), patch.object(upstream,'latest',return_value=self.release):
            result=upstream.update(self.store,'agent-reach')
        self.assertEqual(result['status'],'updated',result)
        self.assertEqual(result['current'],'1.5.0')
        self.assertEqual(sentinel.read_text(),'unrelated installation')
        self.assertFalse((other_root/'agent-reach').exists())

    def test_agent_reach_preserves_manager_and_verifies_bundled_skill(self):
        for manager in ('uv', 'pipx', 'venv'):
            with self.subTest(manager=manager), tempfile.TemporaryDirectory(prefix='lookup-manager-') as temporary:
                # Each manager fixture owns a separate environment and launchers.
                old_base, old_bin = self.base, self.bin
                self.base = Path(temporary);self.bin = self.base/'bin';self.bin.mkdir()
                with patch.dict(os.environ, PATH=str(self.bin)+os.pathsep+os.environ['PATH']):
                    launcher, prefix, _, calls = self.agent(manager)
                    with patch.object(upstream, 'latest', return_value=self.release):
                        result = upstream.update(self.store, 'agent-reach')
                    self.assertEqual(result['status'], 'updated')
                    self.assertEqual(result['current'], '1.5.0')
                    self.assertTrue(result['validation']['bundled_skill'])
                    self.assertTrue(launcher.is_symlink())
                    args = calls.read_text()
                    self.assertIn('upgrade', args)
                    if manager == 'venv':self.assertIn('/refs/tags/v1.5.0.zip', args)
                    manager_environment=json.loads((self.base/'manager-environment').read_text())
                    if manager=='uv':self.assertEqual(Path(manager_environment['UV_TOOL_DIR']).resolve(),prefix.parent.resolve())
                    if manager=='pipx':self.assertEqual(Path(manager_environment['PIPX_HOME']).resolve(),prefix.parent.parent.resolve())
                self.base, self.bin = old_base, old_bin
                self.store.write('native-agent-reach.json', {})

    def test_agent_failure_restores_original_environment_and_launcher(self):
        launcher, _, version, _ = self.agent(outcome='error')
        original = launcher.readlink()
        with patch.object(upstream, 'latest', return_value=self.release):
            result = upstream.update(self.store, 'agent-reach')
        self.assertEqual(result['status'], 'failed')
        self.assertTrue(result['restored'])
        self.assertEqual(version.read_text(), '1.4.0')
        self.assertEqual(launcher.readlink(), original)
        self.assertTrue(Path(result['recovery']).exists())

    def test_interrupted_agent_update_below_original_target_is_not_complete(self):
        launcher, prefix, version, calls = self.agent()
        version.write_text('1.4.1')
        prior = {'status':'invoking','current':'1.4.0','target':'1.5.0',
                 'environment':str(prefix),'recovery':'synthetic-recovery'}
        self.store.write('native-agent-reach.json',prior)
        result = upstream.update(self.store,'agent-reach')
        self.assertEqual(result['status'],'outcome_unknown')
        self.assertEqual(result['reason'],'PRIOR_TARGET_NOT_VERIFIED')
        self.assertEqual(self.store.read('native-agent-reach.json'),prior)
        self.assertFalse(calls.exists())

    def test_agent_resume_reconciles_exact_target_and_preserves_recovery_receipt(self):
        _,prefix,version,calls=self.agent()
        version.write_text('1.5.0')
        self.store.write('native-agent-reach.json',{'status':'invoking','current':'1.4.0',
                         'target':'1.5.0','environment':str(prefix.resolve()),'recovery':'synthetic-recovery'})
        result=upstream.update(self.store,'agent-reach')
        self.assertEqual(result['status'],'updated')
        record=self.store.read('native-agent-reach.json')
        self.assertEqual(record['target'],'1.5.0')
        self.assertEqual(record['recovery'],'synthetic-recovery')
        self.assertFalse(calls.exists())

    def test_pinned_source_cannot_be_falsely_reported_as_latest(self):
        _, _, version, _ = self.agent(outcome='unchanged')
        with patch.object(upstream, 'latest', return_value=self.release):
            result = upstream.update(self.store, 'agent-reach')
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['error'], 'INSTALLER_DID_NOT_REACH_STABLE_RELEASE')
        self.assertTrue(result['restored'])
        self.assertEqual(version.read_text(), '1.4.0')

    def test_missing_bundled_skill_fails_and_recovers(self):
        _, _, version, _ = self.agent(outcome='missing-skill')
        with patch.object(upstream, 'latest', return_value=self.release):
            result = upstream.update(self.store, 'agent-reach')
        self.assertEqual(result['status'], 'failed')
        self.assertTrue(result['restored'])
        self.assertEqual(version.read_text(), '1.4.0')

    def test_local_editable_installation_is_preserved(self):
        _, _, _, calls = self.agent(origin={'url':'file:///synthetic/source','dir_info':{'editable':True}})
        with patch.object(upstream, 'latest', return_value=self.release):
            with self.assertRaisesRegex(upstream.MaintenanceError, 'LOCAL_SOURCE_PROTECTED'):
                upstream.update(self.store, 'agent-reach')
        self.assertFalse(calls.exists())

    def test_missing_native_dependencies_are_skipped(self):
        with patch.object(upstream.shutil, 'which', return_value=None), patch.object(upstream, 'command') as command:
            for name in ('agent-reach', 'ego-browser'):
                self.assertEqual(upstream.update(self.store, name)['status'], 'not_installed')
        command.assert_not_called()

    def test_default_batch_continues_to_ego_after_agent_failure_and_returns_failure(self):
        def result(store, dependency, automatic=False):
            if dependency=='agent-reach':raise upstream.MaintenanceError('SYNTHETIC_INSTALLER_FAILURE')
            return {'status':'up_to_date','current':'1.5.0'}
        output = io.StringIO()
        with patch.object(upstream, 'update', side_effect=result) as update, redirect_stdout(output):
            self.assertEqual(upstream.main(['upgrade']), 1)
        self.assertEqual([c.args[1] for c in update.call_args_list],list(upstream.UPDATE_DEPENDENCIES))
        self.assertEqual(len(json.loads(output.getvalue())['results']), 3)

    def test_native_auto_is_rejected_without_invoking_installer(self):
        with patch.object(upstream, 'native_update') as update:
            for name in ('agent-reach','ego-browser'):
                with self.assertRaisesRegex(upstream.MaintenanceError,'AUTOMATION_NOT_SUPPORTED'):
                    upstream.update(self.store,name,automatic=True)
        update.assert_not_called()


if __name__ == '__main__':
    unittest.main()
