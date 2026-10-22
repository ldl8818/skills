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
        self.env = dict(BASE_ENV, HOME=str(self.home), CI='1',
                        XDG_STATE_HOME=str(self.base/'state'),
                        PATH=str(self.bin) + os.pathsep + os.environ['PATH'])
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


MOCK_OPENCLI = r"""
import json,os,pathlib,sys,time
base=pathlib.Path(os.environ['FAKE_BASE'])
if sys.argv[1:]==['--version']:
    print(os.environ.get('FAKE_VERSION','2.0.2'));raise SystemExit(0)
with (base/'dispatch').open('a') as log: log.write(json.dumps(sys.argv[1:])+'\n')
if os.environ.get('FAKE_NEVER')=='1': time.sleep(10)
time.sleep(float(os.environ.get('FAKE_DELAY','0')))
if sys.argv[1:]==['doctor']:
    print(os.environ.get('FAKE_DOCTOR','{"ok":true,"data":{"daemonRunning":true,"extensionConnected":true,"connectivity":{"ok":true}}}'))
elif os.environ.get('FAKE_PROFILE')=='1':
    print(json.dumps({'profile':os.environ.get('OPENCLI_PROFILE'),'cleanup':os.environ.get('OPENCLI_CLOSE_OWNED_TAB')}))
else:
    print('{"ok":true,"data":[{"text":"late result"}]}')
    print('upstream diagnostic',file=sys.stderr)
raise SystemExit(int(os.environ.get('FAKE_EXIT','0')))
"""

class RunnerTests(Fixture):
    def setUp(self):
        super().setUp()
        write(self.bin/'opencli', '#!'+sys.executable+'\n'+MOCK_OPENCLI, True)
        self.env['FAKE_BASE']=str(self.base)
        self.command=[REAL_NODE,str(ROOT/'scripts/opencli-run.mjs')]

    def test_native_delayed_result_and_exit_are_preserved(self):
        code,out,err=self.run_cmd(self.command+['example','read'],FAKE_DELAY='0.2',FAKE_EXIT='7')
        self.assertEqual(code,7)
        self.assertEqual(json.loads(out)['data'][0]['text'],'late result')
        self.assertIn('upstream diagnostic',err)
        self.assertEqual(len((self.base/'dispatch').read_text().splitlines()),1)

    def test_literal_arguments_are_not_shell_source(self):
        args=['example','read','a b; $(touch never) & "quoted"']
        code,_,_=self.run_cmd(self.command+args)
        self.assertEqual(code,0)
        self.assertEqual(json.loads((self.base/'dispatch').read_text()),args)

    def test_profile_and_owned_cleanup_are_explicit(self):
        code,out,_=self.run_cmd(self.command+['--profile','work','example','read'],
            LOOKUP_OPENCLI_PROFILE='work',OPENCLI_PROFILE='unrelated',FAKE_PROFILE='1')
        self.assertEqual(code,0)
        self.assertEqual(json.loads(out),{'profile':'work','cleanup':'1'})

    def test_conflicting_profile_and_transport_fail_before_dispatch(self):
        cases=[(['--profile','chrome'],{}),(['--profile=chrome','--profile=ego-lite'],{}),
               (['--profile'],{}),([] ,{'OPENCLI_CDP_ENDPOINT':'http://127.0.0.1:9222'}),
               ([],{'OPENCLI_DAEMON_PORT':'19825'})]
        for args,env in cases:
            with self.subTest(args=args,env=env):
                code,_,err=self.run_cmd(self.command+args,**env)
                self.assertEqual(code,78)
                self.assertFalse(json.loads(err)['outcome_unknown'])
                self.assertFalse((self.base/'dispatch').exists())

    def test_old_and_unknown_major_versions_fail_closed(self):
        for version in ['1.8.8','2.0.1','3.0.0','2.0.2-beta','garbage']:
            code,_,err=self.run_cmd(self.command,FAKE_VERSION=version)
            self.assertEqual(code,78)
            self.assertIn('OPENCLI_VERSION_UNSUPPORTED',err)
        self.assertFalse((self.base/'dispatch').exists())

    def test_auth_requires_explicit_sites(self):
        for args in [['auth','status'],['--profile','ego-lite','auth','refresh'],['--','auth','status'],
                     ['auth','status','--site','example','--site= , ']]:
            code,_,err=self.run_cmd(self.command+args)
            self.assertEqual(code,78)
            self.assertIn('OPENCLI_AUTH_SITE_REQUIRED',err)
        code,_,_=self.run_cmd(self.command+['auth','status','--site','example'])
        self.assertEqual(code,0)

    def test_interrupt_reports_unknown_and_stops_owned_child(self):
        child=self.spawn(self.command+['example','read'],env=dict(self.env,FAKE_NEVER='1'))
        self.assertTrue(wait_for(lambda:(self.base/'dispatch').exists()))
        child.send_signal(signal.SIGTERM)
        code,_,err=self.collect(child)
        self.assertEqual(code,143)
        self.assertTrue(json.loads(err)['outcome_unknown'])
        self.assertEqual(len((self.base/'dispatch').read_text().splitlines()),1)

    def test_deadline_does_not_redispatch(self):
        code,_,err=self.run_cmd(self.command+['example','read'],FAKE_NEVER='1',LOOKUP_OPENCLI_TIMEOUT_MS='1200')
        self.assertEqual(code,75)
        self.assertTrue(json.loads(err)['outcome_unknown'])
        self.assertFalse(json.loads(err)['retryable'])
        self.assertEqual(len((self.base/'dispatch').read_text().splitlines()),1)

    def test_invalid_budget_rejected(self):
        code,_,err=self.run_cmd(self.command,LOOKUP_OPENCLI_TIMEOUT_MS='NaN')
        self.assertEqual(code,78)
        self.assertFalse((self.base/'dispatch').exists())


class HealthTests(Fixture):
    def setUp(self):
        super().setUp()
        write(self.bin/'opencli', '#!'+sys.executable+'\n'+MOCK_OPENCLI, True)
        self.env['FAKE_BASE']=str(self.base)
    def health(self,report):
        return self.run_cmd(['bash',str(ROOT/'scripts/opencli-health.sh')],FAKE_DOCTOR=json.dumps(report))

    def test_native_doctor_success(self):
        code,out,_=self.health({'ok':True,'data':{'daemonRunning':True,'extensionConnected':True,'connectivity':{'ok':True}}})
        self.assertEqual(code,0)
        self.assertEqual(json.loads(out)['state'],'ready')
        self.assertEqual(json.loads((self.base/'dispatch').read_text()),['doctor'])

    def test_zero_exit_does_not_mean_connected(self):
        for data in [{}, {'daemonRunning':True,'extensionConnected':True,'connectivity':{'ok':False}},
                     {'daemonRunning':True,'extensionConnected':True,'connectivity':{'ok':True},'daemonStale':True}]:
            code,out,_=self.health({'ok':True,'data':data})
            self.assertEqual(code,78)
            self.assertFalse(json.loads(out)['ok'])

    def test_malformed_report_fails(self):
        code,out,_=self.run_cmd(['bash',str(ROOT/'scripts/opencli-health.sh')],FAKE_DOCTOR='not json')
        self.assertEqual(code,78)
        self.assertEqual(json.loads(out)['state'],'invalid_health_report')


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


class EgoRunnerTests(Fixture):
    def setUp(self):
        super().setUp()
        self.command = [REAL_NODE, str(ROOT / 'scripts/ego-run.mjs')]
        self.env['FAKE_BASE'] = str(self.base)
        self.env['EGO_BROWSER_BIN'] = str(self.bin / 'ego-fixture')
        write(self.bin / 'ego-fixture', '#!' + sys.executable + """
import json,os,pathlib,sys
base=pathlib.Path(os.environ['FAKE_BASE'])
(base/'ego-script').write_text(sys.stdin.read())
if os.environ.get('FAKE_NO_RECEIPT') == '1': print('no structured result');sys.exit(0)
result={'ok':os.environ.get('FAKE_FAILED') != '1','cleanup':{'status':'closed'}}
if os.environ.get('FAKE_FINISH') == '1': result={'status':'closed'}
print('@@LOOKUP_TASK@@'+json.dumps(result),file=sys.stderr)
""", True)

    def test_run_uses_json_arguments_and_stderr_receipt(self):
        label = 'synthetic `touch sentinel` $(touch sentinel)'
        code, out, err = self.run_cmd(self.command + ['run', str(self.base / 'lease.json'), label, str(self.base / 'work.mjs')])
        self.assertEqual((code, err), (0, ''))
        self.assertTrue(json.loads(out)['ok'])
        script = (self.base / 'ego-script').read_text()
        self.assertIn(json.dumps(label), script)
        self.assertIn('runOwnedTask', script)
        self.assertFalse((self.base / 'sentinel').exists())

    def test_work_failure_keeps_cleanup_result(self):
        code, out, _ = self.run_cmd(self.command + ['run', str(self.base / 'lease.json'), 'fixture', str(self.base / 'work.mjs')], FAKE_FAILED='1')
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out)['cleanup']['status'], 'closed')

    def test_finish_only_passes_requested_lease(self):
        code, out, err = self.run_cmd(self.command + ['finish', str(self.base / 'lease.json')], FAKE_FINISH='1')
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(json.loads(out)['status'], 'closed')
        self.assertIn('await finishOwnedTask(api, options)', (self.base / 'ego-script').read_text())

    def test_missing_receipt_fails_and_does_not_claim_cleanup(self):
        code, out, err = self.run_cmd(self.command + ['finish', str(self.base / 'lease.json')], FAKE_NO_RECEIPT='1')
        self.assertEqual((code, out), (1, ''))
        self.assertIn('EGO_TASK_RECEIPT_MISSING', err)


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
const args=process.argv.slice(2)
if(args[0]==='--version') console.log('2.0.2')
else if(args.includes('--help')) {
  const rows=JSON.parse(fs.readFileSync(process.env.FAKE_REGISTRY,'utf8'))
  const row=rows.find(r=>r.site===args[0] && r.name===args[1])
  if(!row){
    const commands=rows.filter(r=>r.site===args[0]);const sites=[...new Set(rows.map(r=>r.site))]
    console.log(JSON.stringify(commands.length?{site:args[0],command_count:commands.length,commands}:{name:'opencli',site_adapters:{count:sites.length,sites}}));process.exit(0)
  }
  console.log(JSON.stringify({...row,positionals:row.args.filter(a=>a.positional),command_options:row.args.filter(a=>!a.positional),browser_common_options:[]}))
  console.error('Update available: fixture')
} else if(args[0]==='bilibili' && args[1]==='search') {
  console.log(JSON.stringify({ok:true,data:[{title:'fixture'}]}))
  console.error('Cleanup could not be confirmed: fixture')
} else process.exit(99)
""")
        write(scripts / 'opencli-health.sh', '#!/bin/sh\nprintf \'%s\\n\' \'{"ok":true,"state":"ready","profile":"ego-lite"}\'\n', True)
        self.command = ['bash', str(scripts / 'selftest.sh')]

    def test_search_mode_checks_search_without_browser_or_auth(self):
        write(self.fixture / 'scripts/search-check.py',
              'import sys\nprint("search checker fixture")\nraise SystemExit(7)\n')
        code, out, err = self.run_cmd(self.command + ['--search'])
        self.assertEqual(code, 7)
        self.assertEqual(out.strip(), 'search checker fixture')
        self.assertEqual(err, '')
        self.assertFalse((self.home / 'tmp').exists())

    def test_shipped_provider_schema_is_accepted(self):
        shutil.copyfile(ROOT / 'references/providers.json', self.providers_file)
        _, out, _ = self.run_cmd(self.command, timeout=12)
        # The mocked registry need not implement real platforms, but the shipped
        # policy must pass the actual selftest schema gate.
        self.assertIn('schema 与 OpenCLI 合约字段完整', out)
        self.assertNotIn('schema 错误', out)

    def test_optional_providers_skip_and_stderr_does_not_pollute_help(self):
        code, out, _ = self.run_cmd(self.command, timeout=12)
        self.assertEqual(code, 0, out[-1800:])
        self.assertIn('example/search 只读参数、策略取值与字段合约通过', out)
        self.assertIn('optional/search', out)
        self.assertIn('lookup-fixture-uninstalled', out)
        self.assertEqual((self.home / 'tmp/lookup-runtime').stat().st_mode & 0o777, 0o700)

    def test_live_cleanup_warning_remains_visible(self):
        code,out,err=self.run_cmd(self.command+['--live'],timeout=12)
        self.assertEqual(code,0,out[-1800:])
        self.assertIn('返回有效内容',out)
        self.assertIn('Cleanup could not be confirmed: fixture',err)

    def test_missing_optional_command_in_existing_namespace_skips(self):
        self.registry.append({'site':'optional','name':'another','access':'read','args':[],'columns':[]})
        write(self.base/'registry.json',json.dumps(self.registry))
        code,out,_=self.run_cmd(self.command,timeout=12)
        self.assertEqual(code,0,out[-1800:])
        self.assertIn('optional/search conditional 候选未注册',out)

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
