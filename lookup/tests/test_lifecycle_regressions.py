"""Synthetic cascades across maintenance, source publication and runtime dispatch."""
from contextlib import contextmanager, redirect_stderr, redirect_stdout
import fcntl
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import venv

import test_entrypoints as entry_fixture
import test_total_update as source_fixture
import test_upstream as update_fixture


ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


@contextmanager
def fixture(case):
    instance = case()
    instance.setUp()
    try:
        yield instance
    finally:
        instance.tearDown()
        instance.doCleanups()


class SourcePublicationTests(unittest.TestCase):
    def test_edit_between_pristine_check_and_publish_is_preserved(self):
        own, audit = source_fixture.own, source_fixture.audit
        for disabled in (False, True):
            with self.subTest(disabled=disabled), fixture(source_fixture.SourceUpdateTests) as f:
                if disabled:
                    (f.live / 'SKILL.md').rename(f.live / 'SKILL.md.disabled')
                original = own.publish

                def edit_then_publish(*args, **kwargs):
                    (f.live / 'scripts/read.py').write_text('concurrent edit\n')
                    return original(*args, **kwargs)

                with f.remote(), patch.object(own, 'publish', side_effect=edit_then_publish):
                    with self.assertRaisesRegex(own.SourceError, 'CHANGED_BEFORE_SWITCH'):
                        own.update(f.store, f.live, audit)
                self.assertEqual((f.live / 'scripts/read.py').read_text(), 'concurrent edit\n')
                self.assertEqual(own.version(f.live), '1.0.0')
                self.assertEqual(f.store.read('self-transaction.json'), {})

    def test_edit_after_approval_check_is_not_published_over(self):
        own, audit = source_fixture.own, source_fixture.audit
        with fixture(source_fixture.SourceUpdateTests) as f, f.remote():
            text = 'def read(value):\n    return value\n'
            (f.live / 'scripts/read.py').write_text(text)
            (f.new / 'scripts/read.py').write_text(text)
            self.assertEqual(own.update(f.store, f.live, audit)['status'], 'manual_review')
            decision = f.root / 'decision.json'
            decision.write_text(json.dumps({'target': f.revision, 'decisions': [{
                'scope': 'lookup', 'path': 'scripts/read.py', 'disposition': 'absorbed',
                'reason': 'Upstream implements the local value-preserving function.',
                'evidence': 'The complete three-way function sources were compared.',
                'validation': 'Equivalent source preserves None and text values.'}], 'adaptations': []}))
            audit.accept(f.store, 'lookup', decision)
            original = audit.approved

            def edit_after_approval(*args, **kwargs):
                result = original(*args, **kwargs)
                (f.live / 'scripts/read.py').write_text('concurrent approved edit\n')
                return result

            with patch.object(audit, 'approved', side_effect=edit_after_approval):
                with self.assertRaisesRegex(own.SourceError, 'CHANGED_BEFORE_SWITCH'):
                    own.update(f.store, f.live, audit)
            self.assertEqual((f.live / 'scripts/read.py').read_text(), 'concurrent approved edit\n')
            self.assertEqual(own.version(f.live), '1.0.0')


class ReachImportTests(unittest.TestCase):
    def test_verified_runtime_wins_over_cwd_and_pythonpath_for_cli_and_mcp(self):
        reach = module('reach')
        with tempfile.TemporaryDirectory(prefix='lookup-import-') as temporary:
            home = Path(temporary).resolve()
            env = dict(os.environ, HOME=str(home), XDG_DATA_HOME=str(home / 'data'),
                       PYTHONDONTWRITEBYTECODE='1', CI='1')
            manifest = {'commit': 'a' * 40, 'archive_sha256': 'b' * 64,
                        'version': '1.0.0', 'adaptations': []}
            files = {'agent_reach/__init__.py': b'',
                     'agent_reach/runtime/__init__.py': b''}
            for name in ('cli.py', 'runtime/manage.py'):
                files['agent_reach/' + name] = (
                    'import json,sys\nfrom pathlib import Path\n'
                    'print(json.dumps({"source":str(Path(__file__).resolve()),"args":sys.argv[1:]}))\nraise SystemExit(0)\n'
                ).encode()
            with patch.dict(os.environ, env):
                directory = reach.runtime_dir(manifest)
                venv.EnvBuilder(with_pip=False, symlinks=True).create(directory / 'venv')
                python = reach.python_path(directory)
                site = subprocess.check_output(
                    [str(python), '-I', '-c', 'import sysconfig;print(sysconfig.get_path("purelib"))'],
                    text=True).strip()
                package = Path(site) / 'agent_reach'
                for name, content in files.items():
                    path = package / name.removeprefix('agent_reach/')
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(content)
                (directory / 'receipt.json').write_text(json.dumps({
                    'commit': manifest['commit'], 'source_sha256': manifest['archive_sha256'],
                    'integration_id': reach.integration_id(manifest),
                    'package': str(package.relative_to(directory))}))
                self.assertTrue(reach.runtime_status(manifest, files)['ready'])
                wrapper = home / 'invoke.py'
                wrapper.write_text(
                    'import runpy,sys\n'
                    f'm=runpy.run_path({str(ROOT / "scripts/reach.py")!r})\n'
                    f'm["main"].__globals__["source_files"]=lambda:({manifest!r},{files!r})\n'
                    'raise SystemExit(m["main"](sys.argv[1:]))\n')
                neutral = home / 'neutral'
                neutral.mkdir()
                shadow = home / 'workspace'
                for name in files:
                    path = shadow / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text('print("UNVERIFIED_WORKSPACE_PACKAGE")\n')
                for action, name in ((['run', 'version'], 'cli.py'),
                                     (['mcp'], 'runtime/manage.py')):
                    for cwd, pythonpath in ((neutral, ''), (shadow, ''), (neutral, str(shadow)),
                                            (shadow, str(shadow))):
                        with self.subTest(action=action, cwd=cwd.name, pythonpath=bool(pythonpath)):
                            result = subprocess.run([sys.executable, '-B', str(wrapper), *action],
                                env=dict(env, PYTHONPATH=pythonpath), cwd=cwd,
                                capture_output=True, text=True, timeout=10)
                            self.assertEqual(result.returncode, 0, result.stderr)
                            self.assertNotIn('UNVERIFIED_WORKSPACE_PACKAGE', result.stdout)
                            self.assertEqual(json.loads(result.stdout)['source'], str(package / name))
                self.assertTrue(reach.runtime_status(manifest, files)['ready'])
                self.assertEqual(list(package.rglob('*.pyc')), [])


class ArchiveLinkTests(unittest.TestCase):
    def shared_sources(self, f):
        source = f.shared / 'agent-reach'
        source.mkdir()
        (source / 'SKILL.md').write_text('---\nname: agent-reach\n---\noriginal')
        links = []
        for client, target in (('.codex', '../../.agents/skills/agent-reach'),
                               ('.claude', '../../.codex/skills/agent-reach')):
            link = f.home / client / 'skills/agent-reach'
            link.parent.mkdir(parents=True)
            link.symlink_to(target)
            links.append(link)
        return source, links

    def test_shared_source_links_stay_on_archived_generation_after_reregistration(self):
        entries = entry_fixture.entries
        with fixture(entry_fixture.EntryTests) as f:
            source, links = self.shared_sources(f)
            self.assertEqual(entries.migrate(f.home, f.lookup, f.storage)['migrated'], 3)
            receipt = json.loads((f.storage / 'entries.json').read_text())
            archived = [Path(row['preserved']) for row in receipt['entries']]
            for path in archived:
                self.assertEqual((path / 'SKILL.md').read_text(),
                                 '---\nname: agent-reach\n---\noriginal')
            self.assertEqual(entries.migrate(f.home, f.lookup, f.storage)['migrated'], 0)
            source.mkdir()
            (source / 'SKILL.md').write_text('---\nname: agent-reach\n---\nreplacement')
            links[0].symlink_to(source)
            self.assertEqual(entries.migrate(f.home, f.lookup, f.storage)['migrated'], 2)
            for path in archived:
                self.assertTrue((path / 'SKILL.md').read_text().endswith('original'))
            self.assertEqual(entries.migrate(f.home, f.lookup, f.storage)['migrated'], 0)

    def test_link_or_receipt_failure_restores_original_links_and_allows_retry(self):
        entries = entry_fixture.entries
        for failure in ('link', 'receipt'):
            with self.subTest(failure=failure), fixture(entry_fixture.EntryTests) as f:
                source, links = self.shared_sources(f)
                originals = [os.readlink(link) for link in links]
                symlink, replace = Path.symlink_to, Path.replace

                def fail_link(path, target, **kwargs):
                    if path.is_relative_to(f.storage):
                        raise OSError('synthetic link failure')
                    return symlink(path, target, **kwargs)

                def fail_receipt(path, target):
                    if Path(target).name == 'entries.json':
                        raise OSError('synthetic receipt failure')
                    return replace(path, target)

                with patch.object(Path, 'symlink_to', fail_link if failure == 'link' else symlink), \
                     patch.object(Path, 'replace', fail_receipt if failure == 'receipt' else replace):
                    with self.assertRaises(OSError):
                        entries.migrate(f.home, f.lookup, f.storage)
                self.assertTrue((source / 'SKILL.md').read_text().endswith('original'))
                self.assertEqual([os.readlink(link) for link in links], originals)
                self.assertFalse((f.storage / 'entries.json').exists())
                self.assertEqual(entries.migrate(f.home, f.lookup, f.storage)['migrated'], 3)
                for row in json.loads((f.storage / 'entries.json').read_text())['entries']:
                    self.assertTrue((Path(row['preserved']) / 'SKILL.md').is_file())


class ResultContractTests(unittest.TestCase):
    def test_unknown_single_and_batch_results_explicitly_forbid_retry(self):
        api = update_fixture.upstream
        for status in ('pending', 'outcome_unknown', 'interrupted'):
            for args in (['upgrade', 'opencli'], ['upgrade']):
                with self.subTest(status=status, args=args), fixture(update_fixture.UpdateTests), \
                     patch.object(api, 'UPDATE_DEPENDENCIES', ('opencli',)), \
                     patch.object(api, 'update', return_value={'status': status}), \
                     redirect_stdout(io.StringIO()) as output:
                    self.assertNotEqual(api.main(args), 0)
                result = json.loads(output.getvalue())
                item = result['results'][0] if result['status'] == 'batch' else result
                self.assertEqual(item.get('dependency'), 'opencli')
                self.assertIs(item.get('retry_safe'), False)
                self.assertIs(item.get('outcome_unknown'), True)

    def test_real_uninstalled_entry_and_selected_error_keep_dependency(self):
        with tempfile.TemporaryDirectory(prefix='lookup-result-home-') as home:
            result = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/upstream.py'),
                                     'upgrade', 'opencli'], capture_output=True, text=True, timeout=10,
                env=dict(os.environ, HOME=home, XDG_STATE_HOME=home + '/state', PATH='', CI='1'))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout),
                             {'dependency': 'opencli', 'status': 'not_installed'})
        api = update_fixture.upstream
        with fixture(update_fixture.UpdateTests), \
             patch.object(api, 'update', side_effect=api.MaintenanceError('DEPENDENCY_BUSY')), \
             redirect_stderr(io.StringIO()) as output:
            self.assertEqual(api.main(['upgrade', 'opencli']), 75)
        self.assertEqual(json.loads(output.getvalue())['dependency'], 'opencli')

    def test_automatic_observation_deferral_is_incomplete_without_installing(self):
        api = update_fixture.upstream
        with fixture(update_fixture.UpdateTests) as f:
            api.policy(f.store, 'opencli', 'auto')
            recent = {**f.release, 'published_at': api.datetime.now(api.timezone.utc).isoformat()}
            with patch.object(api, 'latest', return_value=recent), \
                 patch.object(api, 'prepare_candidate') as prepare, redirect_stdout(io.StringIO()) as output:
                self.assertNotEqual(api.main(['upgrade', 'opencli', '--auto']), 0)
            result = json.loads(output.getvalue())
            self.assertEqual(result['dependency'], 'opencli')
            self.assertEqual(result['reason'], 'RELEASE_OBSERVATION_PERIOD')
            prepare.assert_not_called()

    def test_formal_notices_do_not_hide_unknown_runner_outcome(self):
        normalize = module('normalize-result').normalize
        envelope = json.dumps({'error': {'code': 'OUTCOME_UNKNOWN',
            'original_code': 'OPENCLI_RUN_DEADLINE_EXCEEDED'}, 'phase': 'action',
            'outcome_unknown': True, 'retryable': False})
        notice = 'LOOKUP_UPSTREAM_NOTICE ' + json.dumps({
            'dependency': 'opencli', 'action': 'notify', 'latest': '2.0.3',
            'message': 'Synthetic update available.'})
        for stderr in (envelope, envelope + '\n' + notice, notice + '\n' + envelope,
                       'native banner\n' + envelope + '\n' + notice):
            with self.subTest(stderr=stderr):
                result = normalize({'provider': 'opencli/sample/read', 'exit_code': 75,
                                    'stdout': '', 'stderr': stderr})
                self.assertEqual(result['error']['code'], 'OUTCOME_UNKNOWN')
                self.assertTrue(result['error']['outcome_unknown'])

    def test_invalid_notice_lines_and_ambiguous_envelopes_are_not_trusted(self):
        normalize = module('normalize-result').normalize
        error = {'error': {'code': 'AUTH_REQUIRED', 'original_code': 'OPENCLI_AUTH'},
                 'phase': 'entry', 'outcome_unknown': False, 'retryable': False}
        for suffix in ('LOOKUP_UPSTREAM_NOTICE broken', 'LOOKUP_UPSTREAM_NOTICE []',
                       'LOOKUP_UPSTREAM_NOTICE {"dependency":"opencli"}',
                       'LOOKUP_UPSTREAM_NOTICE {"dependency":"opencli","action":[]}',
                       'prefix LOOKUP_UPSTREAM_NOTICE {}', 'ordinary trailing log'):
            result = normalize({'provider': 'opencli/sample/read', 'exit_code': 1, 'stdout': '',
                                'stderr': json.dumps(error) + '\n' + suffix})
            self.assertEqual(result['error']['code'], 'UNKNOWN')
        ambiguous = json.dumps(error) + '\n' + json.dumps({**error,
            'error': {'code': 'BROWSER_CONNECT', 'original_code': 'OPENCLI_CONNECT'}})
        result = normalize({'provider': 'opencli/sample/read', 'exit_code': 1,
                            'stdout': '', 'stderr': ambiguous})
        self.assertEqual(result['error']['code'], 'UNKNOWN')
        unknown = {**error, 'outcome_unknown': True,
                   'error': {'code': 'OUTCOME_UNKNOWN', 'original_code': 'OPENCLI_RUN_INTERRUPTED'}}
        result = normalize({'provider': 'opencli/sample/read', 'exit_code': 75, 'stdout': '',
                            'stderr': json.dumps(unknown) + '\n' + json.dumps(error)})
        self.assertTrue(result['error']['outcome_unknown'])
        success = normalize({'provider': 'opencli/sample/read', 'exit_code': 0,
                             'stdout': '[{"text":"content"}]',
                             'stderr': 'LOOKUP_UPSTREAM_NOTICE {"dependency":"opencli"}'})
        self.assertEqual(success['status'], 'ok')

    def test_manual_busy_single_and_batch_fail_then_resume(self):
        api = update_fixture.upstream
        with fixture(update_fixture.UpdateTests) as f, \
             patch.object(api, 'latest', return_value=f.release), \
             patch.object(api, 'prepare_candidate', side_effect=f.candidate), \
             patch.object(api, 'UPDATE_DEPENDENCIES', ('opencli',)):
            for args in (['upgrade', 'opencli'], ['upgrade']):
                output = io.StringIO()
                with f.store.lock('usage', shared=True), redirect_stdout(output):
                    code = api.main(args)
                result = json.loads(output.getvalue())
                item = result['results'][0] if result['status'] == 'batch' else result
                self.assertEqual(item['status'], 'deferred')
                self.assertNotEqual(code, 0)
                self.assertEqual(item.get('dependency'), 'opencli')
                self.assertEqual(api.installed(f.store, 'opencli')['current'], '2.0.2')
            with redirect_stdout(io.StringIO()):
                self.assertEqual(api.main(['upgrade', 'opencli']), 0)
            self.assertEqual(api.installed(f.store, 'opencli')['current'], '2.0.3')

    def test_selected_dependency_is_present_on_noop_success_and_error(self):
        api = update_fixture.upstream
        with fixture(update_fixture.UpdateTests) as f:
            latest = {**f.release, 'latest': '2.0.2'}
            with patch.object(api, 'latest', return_value=latest), redirect_stdout(io.StringIO()) as output:
                self.assertEqual(api.main(['upgrade', 'opencli']), 0)
            self.assertEqual(json.loads(output.getvalue()).get('dependency'), 'opencli')
            f.baseline.unlink()
            with patch.dict(os.environ, PATH=''), redirect_stdout(io.StringIO()) as output:
                self.assertEqual(api.main(['upgrade', 'opencli']), 0)
            self.assertEqual(json.loads(output.getvalue()).get('dependency'), 'opencli')
            update_fixture.cli(f.baseline)
            with patch.object(api, 'latest', return_value=f.release), \
                 patch.object(api, 'prepare_candidate', side_effect=f.candidate), \
                 redirect_stdout(io.StringIO()) as output:
                self.assertEqual(api.main(['upgrade', 'opencli']), 0)
            self.assertEqual(json.loads(output.getvalue()).get('dependency'), 'opencli')


class UsageLifecycleTests(unittest.TestCase):
    def test_runner_waits_for_owned_group_cleanup_and_releases_usage_lock(self):
        node = shutil.which('node')
        self.assertIsNotNone(node)
        for mode in ('term', 'ignore', 'descendant', 'exited-parent'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory(prefix='lookup-usage-') as temporary:
                base = Path(temporary).resolve()
                home, binaries = base / 'home', base / 'bin'
                home.mkdir()
                binaries.mkdir()
                (binaries / 'python3').symlink_to(sys.executable)
                config = home / '.config/lookup'
                config.mkdir(parents=True)
                (config / 'opencli-binding.json').write_text(json.dumps({
                    'version': 1, 'browser': 'ego-lite', 'context_id': 'synthetic-context'}))
                stop, record = base / 'stop', base / 'pids'
                worker = base / 'worker.py'
                worker.write_text(
                    'import os,signal,subprocess,sys,time\nfrom pathlib import Path\n'
                    f'stop=Path({str(stop)!r});record=Path({str(record)!r})\n'
                    'if sys.argv[1:]==["--version"]: print("2.0.2");sys.exit(0)\n'
                    f'mode={mode!r}\n'
                    'if mode != "term": signal.signal(signal.SIGTERM,signal.SIG_IGN)\n'
                    'child=None\n'
                    'if mode in ("descendant","exited-parent") and "--child" not in sys.argv:\n'
                    ' child=subprocess.Popen([sys.executable,__file__,"--child"])\n'
                    ' if mode=="exited-parent":\n'
                    '  while not record.exists(): time.sleep(0.01)\n'
                    '  sys.exit(0)\n'
                    'with record.open("a") as stream: stream.write(str(os.getpid())+"\\n")\n'
                    'while not stop.exists(): time.sleep(0.02)\n'
                    'if child: child.wait(timeout=3)\n')
                binary = binaries / 'opencli'
                binary.write_text('#!' + sys.executable + '\n' + worker.read_text())
                binary.chmod(0o700)
                env = {k: v for k, v in os.environ.items()
                       if not k.startswith(('OPENCLI_', 'LOOKUP_OPENCLI_'))}
                env.update(HOME=str(home), XDG_CONFIG_HOME=str(home / '.config'),
                           XDG_STATE_HOME=str(base / 'state'), PATH=str(binaries) + ':/usr/bin:/bin',
                           PYTHONDONTWRITEBYTECODE='1', CI='1',
                           LOOKUP_OPENCLI_TIMEOUT_MS='5000' if mode == 'exited-parent' else '1400')
                unrelated = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(30)'])
                process = subprocess.Popen([node, str(ROOT / 'scripts/opencli-run.mjs'), 'sample', 'read'],
                                           env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                try:
                    stdout, stderr = process.communicate(timeout=8)
                    if mode == 'exited-parent':
                        self.assertEqual(process.returncode, 0, stderr)
                    else:
                        self.assertEqual(process.returncode, 75, stderr)
                        self.assertTrue(json.loads(stderr)['outcome_unknown'])
                    self.assertIsNone(unrelated.poll())
                    self.assertTrue(record.exists(), stdout + stderr)
                    with (base / 'state/lookup/upstream/usage.lock').open('a') as lock:
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    for pid in map(int, record.read_text().splitlines()):
                        state = subprocess.run(['ps', '-o', 'stat=', '-p', str(pid)],
                                               capture_output=True, text=True).stdout.strip()
                        self.assertTrue(not state or state.startswith('Z'), (mode, pid, state))
                finally:
                    stop.touch()
                    if process.poll() is None:
                        process.terminate()
                    process.communicate(timeout=5)
                    unrelated.terminate()
                    unrelated.wait(timeout=5)
                    if record.exists():
                        deadline = time.monotonic() + 4
                        for pid in map(int, record.read_text().splitlines()):
                            while time.monotonic() < deadline:
                                state = subprocess.run(['ps', '-o', 'stat=', '-p', str(pid)],
                                    capture_output=True, text=True).stdout.strip()
                                if not state or state.startswith('Z'):
                                    break
                                time.sleep(0.02)
                            else:
                                self.fail('owned synthetic worker did not exit')


if __name__ == '__main__':
    unittest.main()
