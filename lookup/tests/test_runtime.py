#!/usr/bin/env python3
"""Offline runtime regressions. No browser, platform request, or real daemon.
All fixtures have bounded lifetimes; cleanup targets only child handles or
exact mock executable paths under this test's unique temporary directory.
"""
import fcntl
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

ROOT = Path(__file__).resolve().parents[1]
REAL_NODE = shutil.which('node')
BASE_ENV = {key: value for key, value in os.environ.items()
            if not key.startswith(('OPENCLI_', 'LOOKUP_OPENCLI_', 'FAKE_'))}


def write(path, content, executable=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    if executable:
        path.chmod(0o700)


def wait_for(predicate, seconds=2):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return bool(predicate())


def pid_exists(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='lookup-runtime-test-')
        self.base = Path(self.temp.name)
        self.bin = self.base / 'bin'
        self.home = self.base / 'home'
        self.bin.mkdir()
        self.home.mkdir()
        self.env = dict(BASE_ENV, HOME=str(self.home), PATH=str(self.bin) + os.pathsep + os.environ['PATH'])
        self.children = []

    def spawn(self, args, **kwargs):
        child = subprocess.Popen(args, env=kwargs.pop('env', self.env), stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True, close_fds=True, **kwargs)
        self.children.append(child)
        return child

    def collect(self, child, timeout=6):
        try:
            out, err = child.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            child.kill()
            out, err = child.communicate(timeout=2)
            self.fail('owned fixture exceeded its deadline: ' + (err or out)[-300:])
        return child.returncode, out, err

    def run_cmd(self, args, timeout=6, **env):
        return self.collect(self.spawn(args, env=dict(self.env, **env)), timeout)

    def tearDown(self):
        try:
            for child in self.children:
                if child.poll() is None:
                    child.terminate()
                    try:
                        child.communicate(timeout=0.3)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.communicate(timeout=1)
            # Detached mocks observe only this fixture's private stop marker.
            # No ps/process-name scans and no signals to unowned numeric PIDs.
            (self.base / 'stop-request').touch()
            for record in self.base.glob('mock-pid-*'):
                pid = int(record.read_text())
                exited = self.base / ('mock-exited-' + str(pid))
                self.assertTrue(wait_for(lambda: exited.exists() or not pid_exists(pid), 1),
                                'owned mock did not acknowledge fixture cleanup')
        finally:
            self.temp.cleanup()


MOCK_DAEMON = r"""
import atexit, json, os, pathlib, signal, time
base = pathlib.Path(os.environ['FAKE_BASE'])
(base / ('mock-pid-' + str(os.getpid()))).write_text(str(os.getpid()))
atexit.register(lambda: (base / ('mock-exited-' + str(os.getpid()))).write_text('yes'))
with (base / 'starts').open('a') as log: log.write(str(os.getpid()) + '\n')
(base / 'spawned-pid').write_text(str(os.getpid()))
def stop(_sig, _frame):
    (base / 'term-seen').write_text('yes')
    if os.environ.get('FAKE_IGNORE_TERM') != '1':
        raise SystemExit(0)
signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
if os.environ.get('FAKE_START_FAIL') == '1':
    raise SystemExit(1)
started = time.monotonic()
delay = float(os.environ.get('FAKE_START_DELAY', '0'))
reconnect_delay = float(os.environ.get('FAKE_RECONNECT_DELAY', '0'))
lifetime = float(os.environ.get('FAKE_DAEMON_LIFETIME', '8'))
while time.monotonic() - started < lifetime:
    if (base / 'stop-request').exists(): break
    if time.monotonic() - started >= delay:
        (base / 'ready-pid').write_text(str(os.getpid()))
    if time.monotonic() - started >= reconnect_delay:
        (base / 'extension-ready').touch()
    if os.environ.get('FAKE_EXIT_AFTER_STATUS') == '1' and (base / 'disconnected-seen').exists():
        raise SystemExit(1)
    time.sleep(.02)
"""

MOCK_CURL = r"""
import atexit, json, os, pathlib, sys, time
from urllib.parse import urlparse, parse_qs
base = pathlib.Path(os.environ['FAKE_BASE'])
(base / ('mock-pid-' + str(os.getpid()))).write_text(str(os.getpid()))
atexit.register(lambda: (base / ('mock-exited-' + str(os.getpid()))).write_text('yes'))
url = sys.argv[-1]
with (base / 'calls').open('a') as log: log.write(url + '\n')
mode = os.environ.get('FAKE_MODE', 'ready')
count = len((base / 'calls').read_text().splitlines())
if mode == 'hang' or (mode == 'blocked-second' and count >= 2):
    (base / 'probe-blocked').write_text(str(os.getpid()))
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline and not (base / 'stop-request').exists(): time.sleep(.02)
    raise SystemExit(28)
if mode in ('refused', 'blocked-second'):
    raise SystemExit(7)
if mode == 'invalid':
    print('not-json')
    raise SystemExit(0)
pid = int(os.environ.get('FAKE_EXISTING_PID', str(os.getppid())))
if mode.startswith('cold') or mode == 'reconnect':
    try:
        ready_pid = int((base / 'ready-pid').read_text())
        pid = int(os.environ.get('FAKE_REPLACEMENT_PID') or ready_pid)
        os.kill(pid, 0)
    except (OSError, ValueError):
        raise SystemExit(7)
    if os.environ.get('FAKE_REPLACEMENT_PID'):
        pid = int(os.environ['FAKE_REPLACEMENT_PID'])
context = parse_qs(urlparse(url).query).get('contextId', [''])[0]
status = dict(ok=True, pid=pid, daemonVersion='1.8.8', extensionVersion='fixture',
              extensionConnected=True, contextId=context)
if mode in ('disconnected', 'cold-disconnected'):
    status.update(extensionConnected=False)
if mode in ('required', 'cold-required'):
    status.update(profileRequired=True)
if mode == 'profile-disconnected':
    status.update(extensionConnected=False, profileDisconnected=True)
if mode == 'cold-delayed-profile' and not (base / 'extension-ready').exists():
    # Read a daemon-owned marker: macOS Python 3.9 monotonic clocks are
    # process-local, so separate fixture processes must not compare them.
    status.update(extensionConnected=False, profileDisconnected=True)
    (base / 'disconnected-seen').touch()
if mode == 'wrong-profile':
    status.update(contextId='unrelated-context')
if mode == 'reconnect':
    ready_count = base / 'ready-count'
    n = int(ready_count.read_text()) + 1 if ready_count.exists() else 1
    ready_count.write_text(str(n))
    if n == 1:
        status.update(extensionConnected=False, profileDisconnected=True)
print(json.dumps(status))
"""


class HealthTests(Fixture):
    def setUp(self):
        super().setUp()
        self.env.update(FAKE_BASE=str(self.base), OPENCLI_CONFIG_DIR=str(self.base / 'config'))
        self.config = self.base / 'config' / 'browser-profiles.json'
        write(self.config, json.dumps({'aliases': {'ego-lite': 'ego', 'work': 'work-context'}}))
        write(self.bin / 'opencli', '#!/bin/sh\nexit 99\n', True)
        write(self.bin / 'node', '#!' + sys.executable + '\nimport os,sys\nos.execv(sys.executable,[sys.executable,*sys.argv[1:]])\n', True)
        write(self.bin / 'daemon.js', MOCK_DAEMON)
        write(self.bin / 'curl', '#!' + sys.executable + '\n' + MOCK_CURL, True)
        self.command = ['bash', str(ROOT / 'scripts/opencli-health.sh')]

    def health(self, mode='ready', timeout=6, **env):
        start = time.monotonic()
        code, out, err = self.run_cmd(self.command, timeout=timeout, FAKE_MODE=mode, **env)
        self.wall = time.monotonic() - start
        self.assertFalse(err, err)
        return code, json.loads(out)

    def lock_available(self):
        lock = self.home / 'tmp/lookup-runtime/opencli-health-daemon.v2.flock'
        with lock.open('a') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def daemon_alive(self):
        if not (self.base / 'spawned-pid').exists():
            return False
        pid = int((self.base / 'spawned-pid').read_text())
        return pid_exists(pid) and not (self.base / ('mock-exited-' + str(pid))).exists()

    def test_ready_is_status_only_and_profile_scoped(self):
        code, result = self.health()
        self.assertEqual(code, 0)
        self.assertTrue(result['ok'])
        self.assertFalse(result['started_daemon'])
        self.assertEqual(result['profile'], 'ego-lite')
        self.assertEqual(result['fault_scope'], 'bridge_profile')
        self.assertEqual(len((self.base / 'calls').read_text().splitlines()), 1)

    def test_cold_start_retains_healthy_daemon_and_releases_lock(self):
        code, result = self.health('cold-ready')
        self.assertEqual(code, 0)
        self.assertTrue(result['started_daemon'])
        self.assertFalse(result['restored_daemon'])
        self.assertTrue(self.daemon_alive())
        self.lock_available()

    def test_cold_start_waits_for_profile_reconnect(self):
        code, result = self.health('reconnect')
        self.assertEqual(code, 0)
        self.assertTrue(result['ok'])
        self.assertGreaterEqual(int((self.base / 'ready-count').read_text()), 2)

    def test_cold_start_waits_through_extension_backoff(self):
        # Installed extension retry can take 15s plus jitter. A 16s fixture
        # verifies the real cold-start failure without a browser or network.
        code, result = self.health('cold-delayed-profile', timeout=21,
                                   FAKE_RECONNECT_DELAY='16', FAKE_DAEMON_LIFETIME='24')
        self.assertEqual((code, result['state']), (0, 'ready'))
        self.assertTrue(result['started_daemon'])
        self.assertFalse(result['restored_daemon'])
        self.assertTrue(self.daemon_alive())
        self.assertLess(self.wall, 21)
        self.lock_available()

    def test_cold_reconnect_timeout_remains_bounded_and_cleans_own_daemon(self):
        code, result = self.health('cold-delayed-profile', timeout=23,
                                   FAKE_RECONNECT_DELAY='60', FAKE_DAEMON_LIFETIME='24')
        self.assertEqual((code, result['state']), (78, 'profile_disconnected'))
        self.assertGreaterEqual(self.wall, 17)
        self.assertLess(self.wall, 22)
        self.assertTrue(result['restored_daemon'])
        self.assertFalse(self.daemon_alive())
        self.lock_available()

    def test_daemon_exit_during_reconnect_does_not_reuse_old_profile_status(self):
        code, result = self.health('cold-delayed-profile', FAKE_RECONNECT_DELAY='60',
                                   FAKE_EXIT_AFTER_STATUS='1')
        self.assertTrue((self.base / 'disconnected-seen').exists())
        self.assertEqual((code, result['state']), (69, 'daemon_start_failed'))
        self.assertEqual(result['daemon'], 'stopped')
        self.assertLess(self.wall, 3)
        self.assertTrue(result['restored_daemon'])
        self.assertFalse(self.daemon_alive())

    def test_existing_disconnected_daemon_is_not_touched(self):
        existing = self.spawn([sys.executable, '-c', 'import time; time.sleep(8)'])
        code, result = self.health('disconnected', FAKE_EXISTING_PID=str(existing.pid))
        self.assertEqual(code, 69)
        self.assertEqual(result['state'], 'extension_disconnected')
        self.assertFalse(result['started_daemon'])
        self.assertIsNone(existing.poll())

    def test_existing_profile_errors_do_not_start_daemon(self):
        for mode, state in [('required', 'profile_required'), ('profile-disconnected', 'profile_disconnected'),
                            ('wrong-profile', 'profile_mismatch')]:
            with self.subTest(mode=mode):
                code, result = self.health(mode)
                self.assertEqual((code, result['state']), (78, state))
                self.assertFalse(result['started_daemon'])

    def test_unbound_profile_fails_before_probe(self):
        self.config.unlink()
        code, result = self.health()
        self.assertEqual((code, result['state']), (78, 'profile_unbound'))
        self.assertFalse((self.base / 'calls').exists())

    def test_custom_profile_and_port_override_inherited_profile(self):
        code, result = self.health(LOOKUP_OPENCLI_PROFILE='work', OPENCLI_PROFILE='unrelated',
                                   OPENCLI_DAEMON_PORT='19833')
        self.assertEqual(code, 0)
        self.assertEqual(result['profile'], 'work')
        self.assertEqual(result['daemon_port'], 19833)
        self.assertIn('127.0.0.1:19833/status?contextId=work-context', (self.base / 'calls').read_text())

    def test_invalid_transport_profile_and_port_do_not_probe(self):
        for env, state in [({'OPENCLI_CDP_ENDPOINT': 'http://127.0.0.1:9222'}, 'unsupported_transport'),
                           ({'LOOKUP_OPENCLI_PROFILE': ''}, 'invalid_profile'),
                           ({'OPENCLI_DAEMON_PORT': '0'}, 'invalid_daemon_port')]:
            with self.subTest(state=state):
                code, result = self.health(**env)
                self.assertEqual((code, result['state']), (78, state))
                self.assertFalse((self.base / 'calls').exists())

    def test_case9_real_wall_clock_timeout_and_exact_child_cleanup(self):
        code, result = self.health('cold-ready', FAKE_START_DELAY='6', FAKE_IGNORE_TERM='1')
        self.assertEqual((code, result['state']), (75, 'daemon_timeout'))
        self.assertLess(self.wall, 5.0)
        self.assertLess(result['elapsed_ms'], 5000)
        self.assertTrue(result['restored_daemon'])
        self.assertFalse(self.daemon_alive())
        print('\nhealth_case9_wall_ms=' + str(round(self.wall * 1000)), flush=True)

    def test_cold_failure_does_not_kill_replacement_daemon(self):
        existing = self.spawn([sys.executable, '-c', 'import time; time.sleep(8)'])
        code, result = self.health('cold-required', FAKE_REPLACEMENT_PID=str(existing.pid), FAKE_IGNORE_TERM='1')
        self.assertEqual((code, result['state']), (78, 'profile_required'))
        self.assertTrue(result['restored_daemon'])
        self.assertFalse(self.daemon_alive())
        self.assertIsNone(existing.poll())
        self.assertEqual(result['daemon'], 'running')

    def test_failed_start_is_reaped(self):
        code, result = self.health('cold-ready', FAKE_START_FAIL='1')
        self.assertEqual((code, result['state']), (69, 'daemon_start_failed'))
        self.assertTrue(result['restored_daemon'])
        self.assertFalse(self.daemon_alive())

    def test_invalid_existing_status_is_not_claimed(self):
        code, result = self.health('invalid')
        self.assertEqual((code, result['state']), (75, 'daemon_unresponsive'))
        self.assertFalse(result['started_daemon'])

    def test_hanging_curl_has_external_subprocess_deadline(self):
        code, result = self.health('hang')
        self.assertEqual((code, result['state']), (75, 'daemon_unresponsive'))
        self.assertLess(self.wall, 2)
        pid = int((self.base / 'probe-blocked').read_text())
        self.assertFalse(pid_exists(pid))

    def test_concurrent_cold_starts_have_one_owner(self):
        first = self.spawn(self.command, env=dict(self.env, FAKE_MODE='cold-ready', FAKE_START_DELAY='.2'))
        second = self.spawn(self.command, env=dict(self.env, FAKE_MODE='cold-ready', FAKE_START_DELAY='.2'))
        results = [self.collect(first), self.collect(second)]
        self.assertEqual([row[0] for row in results], [0, 0])
        self.assertEqual(len((self.base / 'starts').read_text().splitlines()), 1)
        self.assertEqual(sum(json.loads(row[1])['started_daemon'] for row in results), 1)
        self.lock_available()

    def test_repeated_signal_restores_only_spawned_daemon(self):
        child = self.spawn(self.command, env=dict(self.env, FAKE_MODE='cold-ready',
                                                 FAKE_START_DELAY='6', FAKE_IGNORE_TERM='1'))
        self.assertTrue(wait_for(lambda: (self.base / 'spawned-pid').exists()))
        child.send_signal(signal.SIGTERM)
        time.sleep(.04)
        if child.poll() is None:
            child.send_signal(signal.SIGTERM)
        code, _, _ = self.collect(child, 2)
        self.assertEqual(code, 130)
        self.assertFalse(self.daemon_alive())
        self.lock_available()

    def test_sigkill_releases_lock_while_child_is_alive(self):
        child = self.spawn(self.command, env=dict(self.env, FAKE_MODE='cold-ready', FAKE_START_DELAY='6'))
        self.assertTrue(wait_for(lambda: (self.base / 'spawned-pid').exists()))
        child.kill()
        self.collect(child, 2)
        self.lock_available()
        self.assertTrue(self.daemon_alive())  # teardown owns this exact mock.

    def test_probe_child_cannot_extend_kernel_lock(self):
        child = self.spawn(self.command, env=dict(self.env, FAKE_MODE='blocked-second'))
        self.assertTrue(wait_for(lambda: (self.base / 'probe-blocked').exists()))
        child.kill()
        self.collect(child, 2)
        self.lock_available()

    def test_symlink_runtime_parent_fails_closed(self):
        target = self.base / 'unrelated'
        target.mkdir()
        (self.home / 'tmp').symlink_to(target)
        code, result = self.health('refused')
        self.assertEqual(code, 78)
        self.assertEqual(result['state'], 'lock_unavailable')
        self.assertFalse((self.base / 'starts').exists())


COMMANDER = r"""
import fs from 'node:fs'
export class Command {
  parseAsync() {
    fs.appendFileSync(process.env.FAKE_DISPATCH_LOG, 'dispatch\n')
    if (process.env.FAKE_NEVER === '1') return new Promise(() => {})
    if (process.env.FAKE_DELAY_MS) return new Promise(resolve => setTimeout(() => {
      process.stdout.write('delayed-result\n'); resolve()
    }, Number(process.env.FAKE_DELAY_MS)))
    return { then(resolve) { process.stdout.write('async-result\n'); resolve() } }
  }
  parse() { this.parseAsync(); return this }
}
"""
CLI = """import { Command } from 'commander'
function createProgram() { return new Command() }
export function runCli(BUILTIN_CLIS, USER_CLIS) {
    createProgram(BUILTIN_CLIS, USER_CLIS).parse();
}
"""
MAIN = """import { runCli } from './cli.js'
import fs from 'node:fs'
fs.writeFileSync(process.env.FAKE_ENTRY_LOG, 'entered')
if (process.env.FAKE_IMPORT_NEVER === '1') await new Promise(() => {})
if (process.env.FAKE_PRINT_PROFILE === '1') console.log('profile=' + process.env.OPENCLI_PROFILE)
runCli()
"""


class RunnerTests(Fixture):
    def setUp(self):
        super().setUp()
        self.package = self.base / 'package'
        self.manifest = {'name': '@jackwener/opencli', 'version': '1.8.8', 'type': 'module',
                         'bin': {'opencli': 'main.js'}}
        write(self.package / 'package.json', json.dumps(self.manifest))
        write(self.package / 'node_modules/commander/package.json',
              json.dumps({'type': 'module', 'exports': './index.js'}))
        write(self.package / 'node_modules/commander/index.js', COMMANDER)
        write(self.package / 'cli.js', CLI)
        write(self.package / 'main.js', MAIN, True)
        (self.bin / 'opencli').symlink_to(self.package / 'main.js')
        self.env.update(FAKE_DISPATCH_LOG=str(self.base / 'dispatch'), FAKE_ENTRY_LOG=str(self.base / 'entry'))
        self.command = [REAL_NODE, str(ROOT / 'scripts/opencli-run.mjs')]

    def test_awaits_action_result_that_direct_parse_loses(self):
        direct = self.run_cmd([REAL_NODE, str(self.package / 'main.js')])
        wrapped = self.run_cmd(self.command)
        self.assertEqual(direct[:2], (0, ''))
        self.assertEqual(wrapped[:2], (0, 'async-result\n'))

    def test_import_timeout_does_not_cut_off_dispatched_action(self):
        code, out, err = self.run_cmd(self.command, FAKE_DELAY_MS='350',
                                      OPENCLI_RUN_IMPORT_TIMEOUT_MS='200', LOOKUP_OPENCLI_TIMEOUT_MS='2000')
        self.assertEqual((code, out, err), (0, 'delayed-result\n', ''))

    def test_import_timeout_covers_pending_top_level_import(self):
        code, _, err = self.run_cmd(self.command, FAKE_IMPORT_NEVER='1', OPENCLI_RUN_IMPORT_TIMEOUT_MS='100')
        self.assertEqual(code, 75)
        self.assertIn('OPENCLI_RUN_IMPORT_TIMEOUT', err)
        self.assertIn('no automatic redispatch', err)
        self.assertEqual(json.loads(err)['error']['code'], 'OUTCOME_UNKNOWN')
        self.assertEqual(json.loads(err)['phase'], 'entry')
        self.assertFalse((self.base / 'dispatch').exists())

    def test_legacy_import_timeout_alias_remains_supported(self):
        code, _, err = self.run_cmd(self.command, FAKE_IMPORT_NEVER='1', OPENCLI_RUN_HARD_TIMEOUT_MS='100')
        self.assertEqual(code, 75)
        self.assertIn('OPENCLI_RUN_IMPORT_TIMEOUT', err)

    def test_business_deadline_reports_unknown_and_dispatches_once(self):
        code, out, err = self.run_cmd(self.command, FAKE_NEVER='1', LOOKUP_OPENCLI_TIMEOUT_MS='200')
        self.assertEqual((code, out), (75, ''))
        self.assertIn('OPENCLI_RUN_DEADLINE_EXCEEDED', err)
        self.assertIn('phase=action; outcome=unknown', err)
        envelope = json.loads(err)
        self.assertEqual(envelope['error']['code'], 'OUTCOME_UNKNOWN')
        self.assertTrue(envelope['outcome_unknown'])
        self.assertFalse(envelope['retryable'])
        self.assertEqual((self.base / 'dispatch').read_text(), 'dispatch\n')

    def test_profile_override_is_explicit_and_consistent(self):
        code, out, _ = self.run_cmd(self.command + ['--profile', 'work'], LOOKUP_OPENCLI_PROFILE='work',
                                    OPENCLI_PROFILE='unrelated', FAKE_PRINT_PROFILE='1')
        self.assertEqual(code, 0)
        self.assertIn('profile=work', out)

    def test_mismatched_or_duplicate_profile_is_rejected_before_entry(self):
        for args in [['--profile', 'chrome'], ['--profile=chrome', '--profile=ego-lite'], ['--profile']]:
            with self.subTest(args=args):
                code, _, err = self.run_cmd(self.command + args)
                self.assertEqual(code, 78)
                self.assertIn('OPENCLI_PROFILE_REJECTED', err)
                self.assertFalse((self.base / 'entry').exists())

    def test_cdp_endpoint_cannot_bypass_profile_gate(self):
        code, _, err = self.run_cmd(self.command, OPENCLI_CDP_ENDPOINT='http://127.0.0.1:9222')
        self.assertEqual(code, 78)
        self.assertIn('OPENCLI_TRANSPORT_REJECTED', err)
        self.assertEqual(json.loads(err)['error']['code'], 'OPENCLI_TRANSPORT_REJECTED')
        self.assertFalse(json.loads(err)['outcome_unknown'])
        self.assertFalse((self.base / 'entry').exists())

    def test_changed_version_or_sync_feature_requires_requalification(self):
        self.manifest['version'] = '1.9.0'
        write(self.package / 'package.json', json.dumps(self.manifest))
        code, _, err = self.run_cmd(self.command)
        self.assertEqual(code, 78)
        self.assertIn('OPENCLI_RUN_COMPAT_UNVERIFIED', err)
        self.assertFalse((self.base / 'entry').exists())
        self.manifest['version'] = '1.8.8'
        write(self.package / 'package.json', json.dumps(self.manifest))
        write(self.package / 'cli.js', CLI.replace('.parse()', '.parseAsync()'))
        code, _, err = self.run_cmd(self.command)
        self.assertEqual(code, 78)
        self.assertIn('retire the workaround', err)
        self.assertFalse((self.base / 'entry').exists())

    def test_auth_batch_always_requires_explicit_sites(self):
        for args in [['auth', 'status'], ['--profile', 'ego-lite', '--', 'auth', 'status'],
                     ['--profile', 'ego-lite', 'auth', '--', 'status'], ['auth', '--', 'refresh']]:
            with self.subTest(args=args):
                code, _, err = self.run_cmd(self.command + args)
                self.assertEqual(code, 78)
                self.assertIn('OPENCLI_AUTH_SITE_REQUIRED', err)
                self.assertFalse((self.base / 'entry').exists())

    def test_invalid_timeout_configuration_fails_before_entry(self):
        code, _, err = self.run_cmd(self.command, LOOKUP_OPENCLI_TIMEOUT_MS='NaN')
        self.assertEqual(code, 78)
        self.assertIn('OPENCLI_RUN_CONFIG_INVALID', err)


class EgoTests(Fixture):
    def setUp(self):
        super().setUp()
        self.command = [REAL_NODE, str(ROOT / 'scripts/ego-spaces.mjs')]
        self.env['FAKE_BASE'] = str(self.base)
        write(self.bin / 'pgrep', '#!' + sys.executable + """
import atexit,os,pathlib,time
base=pathlib.Path(os.environ['FAKE_BASE'])
(base/'pgrep-called').touch()
(base/('mock-pid-'+str(os.getpid()))).write_text(str(os.getpid()))
atexit.register(lambda: (base/('mock-exited-'+str(os.getpid()))).write_text('yes'))
if os.environ.get('FAKE_PGREP_HANG') == '1': time.sleep(4)
raise SystemExit(int(os.environ.get('FAKE_PGREP_STATUS','0')))
""", True)
        write(self.home / '.local/bin/ego-browser', '#!' + sys.executable + """
import os,pathlib,sys,json
base=pathlib.Path(os.environ['FAKE_BASE'])
script=sys.stdin.read()
(base/'ego-script').write_text(script)
print('@@LOOKUP_SPACES@@'+json.dumps([
 {'id':11,'name':'synthetic other task','ownership':'agent'},
 {'id':12,'name':'synthetic user task','ownership':'user'}]))
""", True)

    def test_legacy_hooks_are_inert_even_with_old_state(self):
        old = self.home / '.agents/data/ego-spaces/last-touch'
        write(old, '1')
        for command in ('hook-stop', 'hook-session-start'):
            code, out, err = self.run_cmd(self.command + [command])
            self.assertEqual((code, out, err), (0, '', ''))
        self.assertEqual(old.read_text(), '1')
        self.assertFalse((self.base / 'pgrep-called').exists())
        self.assertFalse((self.base / 'ego-script').exists())

    def test_legacy_mutations_fail_without_browser_calls(self):
        for command in ('close', 'keep', 'unkeep'):
            code, _, err = self.run_cmd(self.command + [command, '11'])
            self.assertEqual(code, 78)
            self.assertIn('EGO_SESSION_OWNERSHIP_UNVERIFIED', err)
        self.assertFalse((self.base / 'pgrep-called').exists())

    def test_list_does_not_start_a_stopped_browser(self):
        code, _, err = self.run_cmd(self.command + ['list'], FAKE_PGREP_STATUS='1')
        self.assertEqual(code, 1)
        self.assertIn('EGO_NOT_RUNNING', err)
        self.assertFalse((self.base / 'ego-script').exists())

    def test_list_never_claims_session_ownership(self):
        code, out, err = self.run_cmd(self.command + ['list'])
        self.assertEqual((code, err), (0, ''))
        result = json.loads(out)
        self.assertFalse(result['cleanupEligible'])
        self.assertEqual(result['sessionOwnership'], 'unknown')
        self.assertEqual(len(result['spaces']), 2)
        self.assertTrue(all(not space['cleanupEligible'] for space in result['spaces']))
        self.assertEqual((self.base / 'ego-script').read_text(),
                         'console.log("@@LOOKUP_SPACES@@" + JSON.stringify(await listTaskSpaces()))')

    def test_browser_presence_check_is_bounded(self):
        started = time.monotonic()
        code, _, _ = self.run_cmd(self.command + ['list'], timeout=4, FAKE_PGREP_HANG='1')
        self.assertEqual(code, 1)
        self.assertLess(time.monotonic() - started, 3)
        self.assertFalse((self.base / 'ego-script').exists())


class SelftestTests(Fixture):
    def setUp(self):
        super().setUp()
        self.fixture = self.base / 'skill'
        scripts = self.fixture / 'scripts'
        scripts.mkdir(parents=True)
        for name in ('selftest.sh', 'flock-holder.py'):
            shutil.copyfile(ROOT / 'scripts' / name, scripts / name)
        write(scripts / 'fetch.sh', '#!/bin/sh\nexit 0\n')
        write(scripts / 'fetch_local.py', '')
        for name in ('find-url.mjs', 'match-site.mjs', 'ego-spaces.mjs'):
            write(scripts / name, '')
        self.registry = [{'site': 'example', 'name': 'search', 'access': 'read',
                          'args': [{'name': 'query', 'positional': True}], 'columns': ['title']}]
        self.providers = {'version': 5, 'actions': {'example/search': {'providers': [
            {'id': 'primary', 'type': 'opencli', 'status': 'active', 'command': 'example/search',
             'required_access': 'read', 'auth': 'none', 'required_args': ['query'], 'required_columns': ['title']},
            {'id': 'optional', 'type': 'opencli', 'status': 'conditional', 'command': 'optional/search',
             'required_access': 'read', 'auth': 'none', 'required_args': ['query'], 'required_columns': []},
            {'id': 'optional-cli', 'type': 'cli', 'status': 'conditional', 'bin': 'lookup-fixture-uninstalled'},
        ]}}}
        self.providers_file = self.fixture / 'references/providers.json'
        write(self.providers_file, json.dumps(self.providers))
        write(self.base / 'registry.json', json.dumps(self.registry))
        self.env['FAKE_REGISTRY'] = str(self.base / 'registry.json')
        write(self.bin / 'opencli', '#!/bin/sh\nexit 0\n', True)
        write(scripts / 'opencli-run.mjs', """
import fs from 'node:fs'
const arg=process.argv[2]
if(arg==='--version') console.log('1.8.8')
else if(arg==='list') { console.log(fs.readFileSync(process.env.FAKE_REGISTRY,'utf8'));console.error('Update available: fixture') }
else if(arg==='verify') process.exit(0)
else process.exit(99)
""")
        write(scripts / 'opencli-health.sh', '#!/bin/sh\nprintf \'%s\\n\' \'{"ok":true,"state":"ready","profile":"ego-lite"}\'\n', True)
        self.command = ['bash', str(scripts / 'selftest.sh')]

    def test_shipped_provider_schema_is_accepted(self):
        shutil.copyfile(ROOT / 'references/providers.json', self.providers_file)
        _, out, _ = self.run_cmd(self.command, timeout=12)
        # The mocked registry need not implement real platforms, but the shipped
        # policy must pass the actual selftest schema gate.
        self.assertIn('schema 与 OpenCLI 合约字段完整', out)
        self.assertNotIn('schema 错误', out)

    def test_optional_providers_skip_and_stderr_does_not_pollute_registry(self):
        code, out, _ = self.run_cmd(self.command, timeout=12)
        self.assertEqual(code, 0, out[-1800:])
        self.assertIn('opencli list 返回 1 条结构化命令', out)
        self.assertIn('optional/search', out)
        self.assertIn('lookup-fixture-uninstalled', out)
        self.assertEqual((self.home / 'tmp/lookup-runtime').stat().st_mode & 0o777, 0o700)

    def test_unknown_schema_and_missing_contract_are_rejected(self):
        for mutation in ('version', 'required_access'):
            with self.subTest(mutation=mutation):
                policy = json.loads(json.dumps(self.providers))
                if mutation == 'version':
                    policy['version'] = 999
                else:
                    del policy['actions']['example/search']['providers'][0]['required_access']
                write(self.providers_file, json.dumps(policy))
                code, out, _ = self.run_cmd(self.command, timeout=12)
                self.assertEqual(code, 1)
                self.assertIn('schema 错误', out)

    def test_existing_conditional_write_drift_still_fails(self):
        self.registry.append({'site': 'optional', 'name': 'search', 'access': 'write',
                              'args': [{'name': 'query'}], 'columns': []})
        write(self.base / 'registry.json', json.dumps(self.registry))
        code, out, _ = self.run_cmd(self.command, timeout=12)
        self.assertEqual(code, 1)
        self.assertIn('optional/search 缺失、变为写操作', out)

    def test_kernel_lock_blocks_only_parallel_selftest(self):
        lock = self.home / 'tmp/lookup-runtime/lookup-selftest.v2.flock'
        lock.parent.mkdir(parents=True)
        with lock.open('a') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            code, out, _ = self.run_cmd(self.command, timeout=4)
        self.assertEqual(code, 2)
        self.assertIn('已有 selftest 在跑', out)


if __name__ == '__main__':
    unittest.main(verbosity=2)
