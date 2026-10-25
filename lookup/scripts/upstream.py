#!/usr/bin/env python3
"""Bounded upstream notices and maintenance with customization review. Standard library only."""
import argparse
import base64
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import tarfile
import time
import urllib.request
import zipfile
from urllib.parse import urlsplit

try:
    import fcntl
except ImportError:
    fcntl = None

ROOT = Path(__file__).resolve().parents[1]
_review_spec = importlib.util.spec_from_file_location('lookup_customization', Path(__file__).with_name('customization.py'))
customization = importlib.util.module_from_spec(_review_spec)
_review_spec.loader.exec_module(customization)
_self_spec = importlib.util.spec_from_file_location('lookup_self_update', Path(__file__).with_name('self_update.py'))
self_update = importlib.util.module_from_spec(_self_spec)
_self_spec.loader.exec_module(self_update)
_process_spec = importlib.util.spec_from_file_location('lookup_owned_process', Path(__file__).with_name('owned_process.py'))
owned_process = importlib.util.module_from_spec(_process_spec)
_process_spec.loader.exec_module(owned_process)
PACKAGE = '@jackwener/opencli'
REGISTRY = 'https://registry.npmjs.org/'
SOURCES = {
    'opencli': REGISTRY + '@jackwener%2fopencli',
    'agent-reach': 'https://api.github.com/repos/Panniantong/Agent-Reach/releases/latest',
}
DEPENDENCIES = ('opencli', 'ego-browser', 'agent-reach', 'web-access')
UPDATE_DEPENDENCIES = ('opencli', 'agent-reach', 'ego-browser')
TTL = 86400
RETRY = 3600


class MaintenanceError(Exception):
    pass


def version_tuple(value):
    match = re.fullmatch(r'v?(\d+(?:\.\d+){2,3})', value.strip())
    if not match:
        raise MaintenanceError('VERSION_UNRECOGNIZED')
    parts = tuple(int(p) for p in match[1].split('.'))
    return parts + (0,) * (4 - len(parts))


def supported(value):
    return (2, 0, 2, 0) <= version_tuple(value) < (3, 0, 0, 0)


def state_root():
    base = Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state')))
    if not base.is_absolute():
        raise MaintenanceError('STATE_PATH_NOT_ABSOLUTE')
    return base / 'lookup/upstream'


class Store:
    def __init__(self, root=None):
        self.root = Path(root) if root is not None else state_root()
        if self.root.is_symlink():
            raise MaintenanceError('STATE_SYMLINK_REJECTED')
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if hasattr(os, 'getuid') and self.root.stat().st_uid != os.getuid():
            raise MaintenanceError('STATE_OWNER_MISMATCH')
        self.root.chmod(0o700)

    def read(self, name):
        path = self.root / name
        if path.is_symlink():
            raise MaintenanceError('STATE_SYMLINK_REJECTED')
        try:
            value = json.loads(path.read_text())
        except FileNotFoundError:
            return {}
        except (ValueError, OSError) as error:
            raise MaintenanceError('STATE_UNREADABLE') from error
        if not isinstance(value, dict):
            raise MaintenanceError('STATE_INVALID')
        if name == 'state.json':
            mappings = ('observed', 'checks', 'policies', 'scheduled', 'local_changes')
            if (any(not isinstance(value.get(key, {}), dict) for key in mappings)
                    or any(not isinstance(value.get(key, []), list) for key in ('notified', 'failed_versions'))):
                raise MaintenanceError('STATE_INVALID')
        return value

    def write(self, name, value):
        if (self.root / name).is_symlink():
            raise MaintenanceError('STATE_SYMLINK_REJECTED')
        fd, temporary = tempfile.mkstemp(prefix='.write-', dir=self.root)
        try:
            with os.fdopen(fd, 'w') as handle:
                json.dump(value, handle, ensure_ascii=False)
                handle.write('\n')
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.root / name)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @contextmanager
    def lock(self, name, shared=False, blocking=True):
        if fcntl is None:
            raise MaintenanceError('LOCK_PLATFORM_UNSUPPORTED')
        path = self.root / (name + '.lock')
        fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        try:
            flags = fcntl.LOCK_SH if shared else fcntl.LOCK_EX
            try:
                fcntl.flock(fd, flags | (0 if blocking else fcntl.LOCK_NB))
            except BlockingIOError as error:
                raise MaintenanceError('DEPENDENCY_BUSY') from error
            yield fd
        finally:
            os.close(fd)


def command(argv, timeout=10, env=None, include_stderr=False):
    """Timeouts terminate only the process group created for this command."""
    process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               env=env, start_new_session=True, text=True)
    handlers = {}
    def interrupted(signum, frame):
        raise KeyboardInterrupt
    for signum in (signal.SIGTERM, signal.SIGHUP):
        handlers[signum] = signal.signal(signum, interrupted)
    try:
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except BaseException as error:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.communicate()
            if isinstance(error, subprocess.TimeoutExpired):
                raise MaintenanceError('COMMAND_TIMEOUT') from error
            raise
    finally:
        for signum, handler in handlers.items():
            signal.signal(signum, handler)
    if process.returncode:
        raise MaintenanceError('COMMAND_FAILED')
    return '\n'.join(part for part in (stdout, stderr) if part.strip()) if include_stderr else stdout


def read_version(binary, dependency):
    lines = command([str(binary), '--version'], timeout=4, include_stderr=True).splitlines()
    if not lines:
        raise MaintenanceError('VERSION_OUTPUT_EMPTY')
    output = lines[0].strip()
    if dependency == 'opencli':
        version_tuple(output)
        return output.removeprefix('v')
    match = re.search(r'\b(v?\d+(?:\.\d+){2,3})\b', output)
    if not match:
        raise MaintenanceError('VERSION_UNRECOGNIZED')
    return match[1].removeprefix('v')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def resolve_opencli(store):
    active = store.read('active.json')
    if active.get('binary'):
        binary = Path(active['binary'])
        if not binary.resolve().is_relative_to((store.root / 'versions').resolve()):
            raise MaintenanceError('ACTIVE_PATH_REJECTED')
        if digest(binary) != active.get('sha256'):
            raise MaintenanceError('ACTIVE_CONTENT_CHANGED')
        return str(binary.resolve())
    return shutil.which('opencli')


def installed(store, dependency):
    if dependency == 'web-access':
        return {'status': 'reference_only'}
    if dependency == 'opencli':
        binary = resolve_opencli(store)
    elif dependency == 'ego-browser':
        local = Path.home() / '.local/bin/ego-browser'
        binary = os.environ.get('EGO_BROWSER_BIN') or (str(local) if local.exists() else shutil.which(dependency))
        if binary and not Path(binary).is_absolute():
            binary = shutil.which(binary)
    else:
        binary = shutil.which(dependency)
    if not binary:
        return {'status': 'not_installed'}
    return {'status': 'installed', 'current': read_version(binary, dependency), 'binary': binary}


def fetch_json(url):
    request = urllib.request.Request(url, headers={
        'User-Agent': 'lookup-upstream', 'Accept': 'application/json'})
    with urllib.request.urlopen(request, timeout=4) as response:
        payload = response.read(8 * 1024 * 1024 + 1)
    if len(payload) > 8 * 1024 * 1024:
        raise MaintenanceError('METADATA_TOO_LARGE')
    return json.loads(payload)


def latest(dependency):
    document = fetch_json(SOURCES[dependency])
    if dependency == 'opencli':
        target = document['dist-tags']['latest']
        release = document['versions'][target]
        if release['name'] != PACKAGE or release['version'] != target:
            raise MaintenanceError('PACKAGE_IDENTITY_MISMATCH')
        dist = release['dist']
        if (not dist['tarball'].startswith(REGISTRY + PACKAGE + '/-/')
                or not dist.get('integrity', '').startswith('sha512-')):
            raise MaintenanceError('PACKAGE_SOURCE_REJECTED')
        result = {'latest': target, 'published_at': document.get('time', {}).get(target),
                  'url': 'https://www.npmjs.com/package/' + PACKAGE,
                  'tarball': dist['tarball'], 'integrity': dist['integrity']}
    else:
        if document.get('draft') or document.get('prerelease'):
            raise MaintenanceError('RELEASE_NOT_STABLE')
        result = {'latest': document['tag_name'].removeprefix('v'),
                  'published_at': document.get('published_at'),
                  'url': document['html_url']}
    version_tuple(result['latest'])
    return result


def observe(store, dependency, observation):
    with store.lock('state'):
        state = store.read('state.json')
        prior = state.setdefault('observed', {}).get(dependency, {})
        if (dependency == 'ego-browser' and prior.get('current')
                and observation.get('current') and prior['current'] != observation['current']):
            state.setdefault('local_changes', {})[dependency] = observation['current']
        state['observed'][dependency] = observation
        store.write('state.json', state)


def refresh(store, dependency, current, force=False):
    with store.lock('check-' + dependency, blocking=False):
        with store.lock('state'):
            state = store.read('state.json')
            previous = state.setdefault('checks', {}).get(dependency, {})
            interval = RETRY if previous.get('status') == 'check_failed' else TTL
            age = time.time() - previous.get('checked_at', 0)
            if not force and previous.get('current') == current and 0 <= age < interval:
                return {**previous, 'cached': True}
        try:
            result = latest(dependency)
            result.update(current=current, checked_at=time.time(),
                          status=('update_available' if version_tuple(result['latest'])
                                  > version_tuple(current) else 'up_to_date'))
        except (OSError, ValueError, KeyError, TypeError, MaintenanceError):
            result = {'status': 'check_failed', 'current': current, 'checked_at': time.time(),
                      'error': 'OFFICIAL_METADATA_UNAVAILABLE'}
        with store.lock('state'):
            state = store.read('state.json')
            state.setdefault('checks', {})[dependency] = result
            store.write('state.json', state)
        return result


def check(store, dependency, background=False, force=False, current=None):
    observation = ({'status': 'installed', 'current': current} if current
                   else installed(store, dependency))
    if observation.get('current'):
        version_tuple(observation['current'])
    observe(store, dependency, observation)
    if observation['status'] != 'installed':
        return observation
    if dependency not in SOURCES:
        return {**observation, 'status': 'native_updater', 'remote_checked': False}
    if not background:
        return refresh(store, dependency, observation['current'], force)
    with store.lock('state'):
        state = store.read('state.json')
        previous = state.get('checks', {}).get(dependency, {})
        interval = RETRY if previous.get('status') == 'check_failed' else TTL
        age = time.time() - previous.get('checked_at', 0)
        if not force and previous.get('current') == observation['current'] and 0 <= age < interval:
            return {**previous, 'cached': True}
        scheduled = state.setdefault('scheduled', {}).get(dependency, 0)
        if 0 <= time.time() - scheduled < 60:
            return {'status': 'checking'}
        state['scheduled'][dependency] = time.time()
        store.write('state.json', state)
    subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '_refresh', dependency,
                      '--current', observation['current'], *(['--force'] if force else [])],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)
    return {'status': 'scheduled'}


def notices(store, dependencies):
    messages = []
    with store.lock('state'):
        state = store.read('state.json')
        reported = state.setdefault('notified', [])
        for dependency in dependencies:
            observation = state.get('observed', {}).get(dependency, {})
            result = state.get('checks', {}).get(dependency, {})
            changed = state.get('local_changes', {}).get(dependency)
            target = changed if dependency == 'ego-browser' else result.get('latest')
            key = dependency + ':' + str(target)
            if not target or observation.get('status') != 'installed':
                continue
            if changed:
                if key in reported:
                    continue
                event = {'dependency': dependency, 'latest': changed, 'action': 'reload_guide',
                         'message': f'ego-browser 本机版本已变为{changed}，需重新加载官方指南并核对封装。'}
            else:
                if (result.get('status') != 'update_available'
                        or version_tuple(target) <= version_tuple(observation['current'])):
                    continue
                auto = state.get('policies', {}).get(dependency) == 'auto'
                pending_auto = (auto and dependency == 'opencli'
                                and auto_ready(result, state)
                                and time.time() - max(state.get('auto_attempted_at', 0),
                                                      state.get('auto_requested_at', 0)) >= RETRY)
                if key in reported and not pending_auto:
                    continue
                event = {'dependency': dependency, 'current': observation['current'],
                         'latest': target, 'url': result['url'],
                         'action': 'maintain' if pending_auto else 'notify',
                         'already_notified': key in reported,
                         'message': f'{dependency} 有新的稳定版本：{observation["current"]} → {target}。'
                                    + ('已开启托管，将在当前任务结束后检查更新条件。' if auto else
                                       '可运行 lookup upgrade ' + dependency + ' 维护。')}
                if pending_auto:
                    state['auto_requested_at'] = time.time()
            messages.append(event)
            if key not in reported:
                reported.append(key)
        state['notified'] = reported[-100:]
        store.write('state.json', state)
    return messages


def auto_ready(release, state):
    try:
        age = time.time() - datetime.fromisoformat(release['published_at'].replace('Z', '+00:00')).timestamp()
        return (supported(release['latest']) and age >= TTL
                and release['latest'] not in state.get('failed_versions', []))
    except (KeyError, TypeError, ValueError, AttributeError, MaintenanceError):
        return False


def policy(store, dependency, mode):
    if mode == 'auto' and dependency != 'opencli':
        raise MaintenanceError('AUTOMATION_NOT_SUPPORTED')
    with store.lock('state'):
        state = store.read('state.json')
        state.setdefault('policies', {})[dependency] = mode
        store.write('state.json', state)
    return {'dependency': dependency, 'policy': mode}


def qualify(binary, version, env=None):
    if read_version(binary, 'opencli') != version or not supported(version):
        raise MaintenanceError('CANDIDATE_VERSION_UNSUPPORTED')
    guide = command([str(binary), 'skills', 'read', 'opencli-browser', '-f', 'plain'], env=env)
    if not guide.strip() or 'opencli-browser' not in guide:
        raise MaintenanceError('EXECUTION_GUIDE_UNAVAILABLE')
    complete = full_opencli_contract(binary, env)
    providers = json.loads((ROOT / 'references/providers.json').read_text())
    checked, absent = [], []
    for action in providers['actions'].values():
        for spec in action['providers']:
            if spec.get('type') != 'opencli' or spec.get('status') not in ('active', 'conditional'):
                continue
            site, name = spec['command'].split('/', 1)
            help_data = json.loads(command([str(binary), site, name, '--help', '-f', 'json'], env=env))
            missing = ((help_data.get('site') == site and 'commands' in help_data
                        and all(c['name'] != name for c in help_data['commands']))
                       or (help_data.get('name') == 'opencli'
                           and site not in help_data.get('site_adapters', {}).get('sites', [site])))
            if missing and spec['status'] == 'conditional':
                absent.append(spec['command'])
                continue
            args = (help_data.get('positionals', []) + help_data.get('command_options', [])
                    + help_data.get('browser_common_options', []))
            valid = (help_data.get('site') == site and help_data.get('name') == name
                     and help_data.get('access') == spec['required_access']
                     and set(spec.get('required_args', [])) <= {a['name'] for a in args}
                     and set(spec.get('required_columns', [])) <= set(help_data.get('columns', []))
                     and all(any(a['name'] == p['name'] and not a.get('positional')
                                 and p['value'] in a.get('choices', []) for a in args)
                             for p in spec.get('policy_args', [])))
            if not valid:
                raise MaintenanceError('COMMAND_CONTRACT_CHANGED:' + spec['command'])
            checked.append(spec['command'])
    if not checked:
        raise MaintenanceError('NO_CONTRACTS_CHECKED')
    return {'contracts': checked, 'conditional_absent': absent, 'business_verified': False,
            'complete_registry': complete}


def full_opencli_contract(binary, env=None):
    script = ROOT / 'scripts/opencli-source.py'
    if not script.is_file():
        return None
    spec = importlib.util.spec_from_file_location('lookup_opencli_source', script)
    source = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(source)
    try:
        return source.contract(binary, env=env)
    except Exception as error:
        raise MaintenanceError('OPENCLI_COMPLETE_CONTRACT_CHANGED: ' + str(error)) from error


def isolated_qualification(binary, version):
    # Native help rewrites its user-runtime package link, so candidate probes
    # must never run against the user's real HOME.
    with tempfile.TemporaryDirectory(prefix='lookup-qualification-') as temporary:
        env = dict(os.environ, HOME=temporary, CI='1')
        return qualify(binary, version, env=env)


def prepare_candidate(store, release):
    versions = store.root / 'versions'
    if versions.is_symlink():
        raise MaintenanceError('STATE_SYMLINK_REJECTED')
    versions.mkdir(exist_ok=True, mode=0o700)
    candidate = Path(tempfile.mkdtemp(prefix=release['latest'] + '-', dir=versions))
    try:
        archive = candidate / 'package.tgz'
        with urllib.request.urlopen(release['tarball'], timeout=10) as response:
            payload = response.read(32 * 1024 * 1024 + 1)
        if len(payload) > 32 * 1024 * 1024:
            raise MaintenanceError('PACKAGE_TOO_LARGE')
        expected = release['integrity'].removeprefix('sha512-')
        if base64.b64encode(hashlib.sha512(payload).digest()).decode() != expected:
            raise MaintenanceError('PACKAGE_INTEGRITY_MISMATCH')
        archive.write_bytes(payload)
        source = candidate / 'source'
        unpack_opencli(payload, source)
        npm = shutil.which('npm')
        if not npm:
            raise MaintenanceError('NPM_UNAVAILABLE')
        config = candidate / 'user.npmrc'
        global_config = candidate / 'global.npmrc'
        config.write_text('')
        global_config.write_text('')
        command([npm, 'install', '--prefix', str(candidate), '--ignore-scripts', '--no-audit',
                 '--no-fund', '--package-lock=false', '--userconfig', str(config),
                 '--globalconfig', str(global_config), '--registry', REGISTRY, str(archive)], timeout=120)
        binary = candidate / 'node_modules/@jackwener/opencli/dist/src/main.js'
        validation = isolated_qualification(binary, release['latest'])
        # These are owned staging inputs, not installed runtime or recovery material.
        archive.unlink()
        config.unlink()
        global_config.unlink()
        return {'binary': str(binary), 'version': release['latest'], 'sha256': digest(binary),
                'integrity': release['integrity'], 'validation': validation, 'source': str(source)}
    except BaseException:
        shutil.rmtree(candidate)
        raise


def unpack_opencli(payload, destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(payload), mode='r:gz') as archive:
        size = 0
        for member in archive.getmembers():
            name = Path(member.name)
            if (not name.parts or name.parts[0] != 'package' or name.is_absolute()
                    or '..' in name.parts or member.issym() or member.islnk()):
                raise MaintenanceError('PACKAGE_ARCHIVE_PATH_REJECTED')
            if not member.isfile():
                if not member.isdir():
                    raise MaintenanceError('PACKAGE_ARCHIVE_TYPE_REJECTED')
                continue
            size += member.size
            if size > 128 * 1024 * 1024:
                raise MaintenanceError('PACKAGE_EXPANDED_TOO_LARGE')
            path = destination.joinpath(*name.parts[1:])
            if path.exists():
                raise MaintenanceError('PACKAGE_ARCHIVE_DUPLICATE')
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(archive.extractfile(member).read())
            path.chmod(member.mode & 0o777)


def opencli_package(binary):
    for directory in Path(binary).resolve().parents:
        manifest = directory / 'package.json'
        if manifest.is_file():
            try:
                if json.loads(manifest.read_text()).get('name') == PACKAGE:
                    return directory
            except (OSError, ValueError):
                pass
    raise MaintenanceError('OPENCLI_PACKAGE_BASELINE_UNRECOGNIZED')


def opencli_baseline(store, version):
    root = store.root / ('opencli-source-' + version)
    receipt = store.read('opencli-source-' + version + '.json')
    if root.exists():
        if not receipt or customization.fingerprint(root) != receipt.get('fingerprint'):
            raise MaintenanceError('UPSTREAM_BASELINE_CHANGED')
        return root
    document = fetch_json(SOURCES['opencli'] + '/' + version)
    dist = document['dist']
    if (document.get('name') != PACKAGE or document.get('version') != version
            or not dist['tarball'].startswith(REGISTRY + PACKAGE + '/-/')
            or not dist.get('integrity', '').startswith('sha512-')):
        raise MaintenanceError('PACKAGE_SOURCE_REJECTED')
    with urllib.request.urlopen(dist['tarball'], timeout=10) as response:
        payload = response.read(32 * 1024 * 1024 + 1)
    if (len(payload) > 32 * 1024 * 1024
            or base64.b64encode(hashlib.sha512(payload).digest()).decode() != dist['integrity'][7:]):
        raise MaintenanceError('PACKAGE_INTEGRITY_MISMATCH')
    try:
        unpack_opencli(payload, root)
        store.write('opencli-source-' + version + '.json',
                    {'version': version, 'integrity': dist['integrity'],
                     'fingerprint': customization.fingerprint(root)})
    except BaseException:
        if root.exists():
            shutil.rmtree(root)
        raise
    return root


def customization_gate(store, dependency, target, scopes):
    """A host-reviewed merge is reusable only for these exact three inputs."""
    pointer = store.read('review-' + dependency + '.json')
    if pointer:
        root, request = customization.load(store, dependency)
        if request['target'] == target:
            customization.assert_inputs(root, request)
            if len(scopes) != len(request['scopes']) or any(
                    s['name'] != r['name'] or customization.files(s['upstream']) != r['upstream']
                    or customization.files(s['base']) != r['base']
                    or customization.files(s.get('local', s['live'])) != r['local']
                    for s, r in zip(scopes, request['scopes'])):
                raise MaintenanceError('CUSTOMIZATION_REVIEW_INPUT_CHANGED')
            if (root / 'accepted.json').exists():
                return customization.approved(store, dependency, target)
            return customization.pending(store, dependency)
    if not any(customization.files(s.get('local', s['live'])) != customization.files(s['base']) for s in scopes):
        return None
    customization.create(store, dependency, target, scopes)
    return customization.pending(store, dependency)


def opencli_customizations(store, current, candidate):
    package = opencli_package(current['binary'])
    baseline = opencli_baseline(store, current['current'])
    new = Path(candidate['source'])
    scopes = [{'name': 'package', 'live': package, 'base': baseline, 'upstream': new}]
    # User adapters shadow built-ins. Compare their effective implementation
    # against both complete releases, rather than assuming every override is
    # either obsolete or a new user file.
    with tempfile.TemporaryDirectory(prefix='lookup-customizations-') as temporary:
        effective = Path(temporary) / 'clis'
        customization.copy_source(baseline / 'clis', effective)
        customization.copy_source(Path.home() / '.opencli/clis', effective)
        empty = Path(temporary) / 'empty'
        empty.mkdir()
        scopes.extend([
            {'name': 'clis', 'live': Path.home() / '.opencli/clis', 'local': effective,
             'base': baseline / 'clis', 'upstream': new / 'clis'},
            {'name': 'plugins', 'live': Path.home() / '.opencli/plugins', 'base': empty, 'upstream': empty},
        ])
        result = customization_gate(store, 'opencli', candidate['version'], scopes)
    guards = {str(s['live']): customization.files(s['live']) for s in scopes}
    return result, guards


def reviewed_outputs(review):
    root, request, _ = review
    return {scope['name']: root / str(index) / 'merged' for index, scope in enumerate(request['scopes'])}


def override_output(merged, upstream, destination):
    """Only differences need shadowing; absorbed adapters disappear from overrides."""
    incoming, source = customization.files(merged), customization.files(upstream)
    removed = source.keys() - incoming.keys()
    if removed:
        raise MaintenanceError('ADAPTER_REMOVAL_REQUIRES_PACKAGE_ADAPTATION')
    Path(destination).mkdir(parents=True, exist_ok=True)
    for name in customization.differences(source, incoming):
        path = Path(destination) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(Path(merged) / name, path)


def update(store, dependency, automatic=False, retry=False):
    if dependency in ('agent-reach', 'ego-browser'):
        if automatic:
            raise MaintenanceError('AUTOMATION_NOT_SUPPORTED')
        return native_update(store, dependency, retry=retry)
    if dependency != 'opencli':
        return {'status': 'reference_only', 'dependency': dependency, 'updated': False}
    with store.lock('maintenance', blocking=False):
        prior = store.read('transaction.json')
        if prior.get('status') == 'preparing':
            return {'status': 'interrupted', 'reason': 'INSPECT_PRIOR_INSTALLATION',
                    'version': prior.get('version')}
        current = installed(store, dependency)
        if current['status'] != 'installed':
            return current
        if prior.get('status') == 'qualified' and prior.get('candidate'):
            active = store.read('active.json')
            candidate = prior['candidate']
            if active.get('binary') == candidate['binary']:
                if (active.get('version') != current['current']
                        or digest(candidate['binary']) != candidate['sha256']):
                    return {'status': 'interrupted', 'reason': 'ACTIVATION_STATE_UNVERIFIED'}
                prior['status'] = 'updated'
                prior['recovered_after_interrupt'] = True
                store.write('transaction.json', prior)
        if automatic:
            state = store.read('state.json')
            if state.get('policies', {}).get(dependency) != 'auto':
                raise MaintenanceError('AUTO_NOT_AUTHORIZED')
        release = check(store, dependency, force=True)
        if release['status'] != 'update_available':
            return release
        if not supported(release['latest']):
            return {**release, 'status': 'manual_review', 'reason': 'UNSUPPORTED_MAJOR'}
        if automatic:
            try:
                age = time.time() - datetime.fromisoformat(release['published_at'].replace('Z', '+00:00')).timestamp()
            except (KeyError, TypeError, ValueError, AttributeError):
                age = -1
            if age < TTL:
                return {'status': 'deferred', 'reason': 'RELEASE_OBSERVATION_PERIOD'}
            if release['latest'] in store.read('state.json').get('failed_versions', []):
                return {'status': 'deferred', 'reason': 'VERSION_PREVIOUSLY_FAILED'}
            with store.lock('state'):
                state = store.read('state.json')
                state['auto_attempted_at'] = time.time()
                store.write('state.json', state)
        before = store.read('active.json')
        recovery = {'binary': str(Path(current['binary']).resolve()),
                    'version': current['current'], 'sha256': digest(current['binary'])}
        transaction = {'status': 'preparing', 'version': release['latest'], 'before': before,
                       'recovery': recovery,
                       'started_at': datetime.now(timezone.utc).isoformat()}
        store.write('transaction.json', transaction)
        try:
            reusable = (prior.get('status') in ('qualified', 'deferred', 'manual_review')
                        and prior.get('version') == release['latest'] and prior.get('before') == before
                        and prior.get('candidate'))
            if reusable:
                candidate = prior['candidate']
                if digest(candidate['binary']) != candidate['sha256']:
                    raise MaintenanceError('CANDIDATE_CONTENT_CHANGED')
                if not candidate.get('customized'):
                    candidate['validation'] = isolated_qualification(candidate['binary'], candidate['version'])
            else:
                candidate = prepare_candidate(store, release)
            review, guards = opencli_customizations(store, current, candidate)
            package_guard = next((path for path in guards
                                  if Path(current['binary']).resolve().is_relative_to(Path(path).resolve())), None)
            if package_guard:
                recovery.update(source_root=package_guard,
                                source_fingerprint=customization.fingerprint(package_guard))
            if isinstance(review, dict):
                transaction.update(status='manual_review', candidate=candidate, review=review)
                store.write('transaction.json', transaction)
                return review
            outputs = reviewed_outputs(review) if review else {}
            if outputs:
                customization.replace_source(outputs['package'], opencli_package(candidate['binary']))
                candidate['sha256'] = digest(candidate['binary'])
                candidate['customized'] = True
                with tempfile.TemporaryDirectory(prefix='lookup-custom-validation-') as temporary:
                    home = Path(temporary)
                    root, request, _ = review
                    clis_index = next(i for i, s in enumerate(request['scopes']) if s['name'] == 'clis')
                    override_output(outputs['clis'], root / str(clis_index) / 'upstream', home / '.opencli/clis')
                    customization.copy_source(outputs['plugins'], home / '.opencli/plugins')
                    candidate['validation'] = qualify(candidate['binary'], candidate['version'],
                                                       env=dict(os.environ, HOME=str(home), CI='1'))
            transaction.update(status='qualified', candidate=candidate)
            store.write('transaction.json', transaction)
            with store.lock('usage', blocking=False):
                if any(customization.files(path) != value for path, value in guards.items()):
                    raise MaintenanceError('CUSTOMIZATION_CHANGED_DURING_UPDATE')
                if automatic and store.read('state.json').get('policies', {}).get(dependency) != 'auto':
                    raise MaintenanceError('AUTO_AUTHORIZATION_CHANGED')
                if store.read('active.json') != before or installed(store, dependency) != current:
                    raise MaintenanceError('INSTALLATION_CHANGED')
                if digest(current['binary']) != recovery['sha256']:
                    raise MaintenanceError('INSTALLATION_CHANGED')
                active = {**candidate, 'previous': before, 'recovery': recovery}
                try:
                    if outputs:
                        # The accepted request's live snapshots are exact recovery
                        # material, not merely a backup used to skip semantic review.
                        root, request, receipt = review
                        restores = []
                        for index, scope in enumerate(request['scopes']):
                            if scope['name'] == 'package':
                                continue
                            area = root / str(index)
                            live_backup = area / 'live-backup'
                            customization.copy_source(scope['live'], live_backup)
                            restores.append({'live': scope['live'], 'backup': str(live_backup)})
                            output = outputs[scope['name']]
                            if scope['name'] == 'clis':
                                output = area / 'overrides'
                                override_output(outputs['clis'], area / 'upstream', output)
                            customization.replace_source(output, scope['live'])
                            restores[-1]['expected'] = customization.files(scope['live'])
                        active['customization_recovery'] = restores
                        active['customization_review'] = str(root)
                    store.write('active.json', active)
                    if read_version(resolve_opencli(store), dependency) != candidate['version']:
                        raise MaintenanceError('ACTIVATION_VERIFY_FAILED')
                except BaseException:
                    store.write('active.json', before)
                    for entry in locals().get('restores', []):
                        customization.replace_source(entry['backup'], entry['live'])
                    raise
            transaction.update(status='updated', validation=candidate['validation'])
            store.write('transaction.json', transaction)
            observe(store, dependency, {'status': 'installed', 'current': candidate['version'],
                                        'binary': candidate['binary']})
            return {'status': 'updated', 'dependency': dependency, 'current': candidate['version'],
                    'validation': candidate['validation'], 'system_installation_changed': False,
                    'customizations': 'reviewed' if review else 'no_local_differences'}
        except Exception as error:
            code = str(error) if isinstance(error, (MaintenanceError, customization.ReviewError)) else type(error).__name__
            transaction.update(status='deferred' if code == 'DEPENDENCY_BUSY' else 'failed', error=code)
            store.write('transaction.json', transaction)
            if code != 'DEPENDENCY_BUSY':
                with store.lock('state'):
                    state = store.read('state.json')
                    state.setdefault('failed_versions', []).append(release['latest'])
                    store.write('state.json', state)
            return {'status': transaction['status'], 'error': code, 'current_preserved': store.read('active.json') == before}


def agent_reach_environment(binary):
    executable = Path(binary).resolve()
    python = executable.parent / 'python'
    if not python.exists():
        first = executable.read_text().splitlines()[0]
        parts = shlex.split(first[2:]) if first.startswith('#!') else []
        if len(parts) != 1 or not Path(parts[0]).is_absolute():
            raise MaintenanceError('AGENT_REACH_INTERPRETER_UNKNOWN')
        python = Path(parts[0])
    script = '''import importlib.metadata as m,json,sys,hashlib,base64
d=m.distribution('agent-reach')
origin=json.loads(d.read_text('direct_url.json') or '{}')
record={}
changed=[]
for f in d.files or []:
 if str(f).endswith('.pyc') or '__pycache__' in f.parts:
  continue
 if str(f).startswith('agent_reach/') or str(f).endswith('/bin/agent-reach'):
  p=d.locate_file(f)
  if not f.hash or f.hash.mode!='sha256':
   changed.append(str(f));continue
  record[str(f)]=f.hash.value
  if not p.is_file() or base64.urlsafe_b64encode(hashlib.sha256(p.read_bytes()).digest()).decode().rstrip('=')!=f.hash.value:
   changed.append(str(f))
print(json.dumps({'prefix':sys.prefix,'base_prefix':sys.base_prefix,
 'version':d.version,'origin':origin,'skill_root':str(d.locate_file('agent_reach/skill')),
 'package_root':str(d.locate_file('agent_reach')),'record':record,'changed':changed}))'''
    info = json.loads(command([str(python), '-c', script]))
    prefix = Path(info['prefix'])
    if (info['prefix'] == info['base_prefix'] or not executable.is_relative_to(prefix)
            or executable.parent != prefix / 'bin'):
        raise MaintenanceError('AGENT_REACH_ISOLATED_ENVIRONMENT_REQUIRED')
    origin = info.get('origin', {})
    if origin.get('dir_info', {}).get('editable') or 'dir_info' in origin:
        raise MaintenanceError('AGENT_REACH_LOCAL_SOURCE_PROTECTED')
    url = origin.get('url', '')
    if url:
        parsed = urlsplit(url.removeprefix('git+'))
        if (parsed.scheme != 'https' or parsed.hostname != 'github.com'
                or parsed.username or parsed.password
                or not re.match(r'^/panniantong/agent-reach(?:\.git|/|$)', parsed.path, re.I)):
            raise MaintenanceError('AGENT_REACH_SOURCE_UNRECOGNIZED')
    if (prefix / 'uv-receipt.toml').is_file():
        if prefix.name != 'agent-reach':
            raise MaintenanceError('AGENT_REACH_MANAGER_TARGET_UNRECOGNIZED')
        manager = shutil.which('uv')
        argv = [manager, 'tool', 'upgrade', 'agent-reach'] if manager else None
        kind = 'uv'
        manager_env = {'UV_TOOL_DIR': str(prefix.parent),
                       'UV_TOOL_BIN_DIR': str(Path(binary).absolute().parent)}
    elif (prefix / 'pipx_metadata.json').is_file():
        if prefix.name != 'agent-reach' or prefix.parent.name != 'venvs':
            raise MaintenanceError('AGENT_REACH_MANAGER_TARGET_UNRECOGNIZED')
        manager = shutil.which('pipx')
        argv = [manager, 'upgrade', 'agent-reach'] if manager else None
        kind = 'pipx'
        manager_env = {'PIPX_HOME': str(prefix.parent.parent),
                       'PIPX_BIN_DIR': str(Path(binary).absolute().parent)}
    else:
        argv = [str(python), '-m', 'pip', 'install', '--upgrade']
        kind = 'venv'
        manager_env = {}
    if argv is None:
        raise MaintenanceError('AGENT_REACH_INSTALLER_UNAVAILABLE')
    return {**info, 'python': str(python), 'prefix': str(prefix), 'manager': kind,
            'argv': argv, 'manager_env': manager_env}


def agent_source(store, version):
    root = store.root / ('agent-reach-source-' + version)
    receipt = store.read('agent-reach-source-' + version + '.json')
    if root.exists():
        if customization.fingerprint(root) != receipt.get('fingerprint'):
            raise MaintenanceError('UPSTREAM_BASELINE_CHANGED')
        return root
    url = 'https://github.com/Panniantong/Agent-Reach/archive/refs/tags/v' + version + '.zip'
    with urllib.request.urlopen(url, timeout=15) as response:
        payload = response.read(32 * 1024 * 1024 + 1)
    if len(payload) > 32 * 1024 * 1024:
        raise MaintenanceError('PACKAGE_TOO_LARGE')
    root.mkdir()
    try:
        total = 0
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            for item in archive.infolist():
                parts = Path(item.filename).parts
                if len(parts) < 3 or parts[1] != 'agent_reach' or item.is_dir():
                    continue
                if '..' in parts or Path(item.filename).is_absolute() or (item.external_attr >> 16) & 0o170000 == 0o120000:
                    raise MaintenanceError('PACKAGE_ARCHIVE_PATH_REJECTED')
                total += item.file_size
                if total > 128 * 1024 * 1024:
                    raise MaintenanceError('PACKAGE_EXPANDED_TOO_LARGE')
                path = root.joinpath(*parts[2:])
                if path.exists():
                    raise MaintenanceError('PACKAGE_ARCHIVE_DUPLICATE')
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(archive.read(item))
                path.chmod((item.external_attr >> 16) & 0o777 or 0o644)
        if not (root / '__init__.py').is_file():
            raise MaintenanceError('AGENT_REACH_SOURCE_INCOMPLETE')
        store.write('agent-reach-source-' + version + '.json',
                    {'source': url, 'sha256': hashlib.sha256(payload).hexdigest(),
                     'fingerprint': customization.fingerprint(root)})
    except BaseException:
        shutil.rmtree(root)
        raise
    return root


def agent_customizations(store, environment, target):
    live = Path(environment['package_root'])
    actual = customization.files(live)
    record = {name.removeprefix('agent_reach/'): value for name, value in environment['record'].items()
              if name.startswith('agent_reach/') and not name.endswith('.pyc') and '__pycache__' not in Path(name).parts}
    if not record:
        raise MaintenanceError('AGENT_REACH_PACKAGE_BASELINE_UNKNOWN')
    changed = (bool(environment['changed']) or set(actual) != set(record))
    if not changed:
        return None, actual
    if any(not name.startswith('agent_reach/') for name in environment['changed']):
        raise MaintenanceError('AGENT_REACH_CUSTOM_LAUNCHER_REQUIRES_RECONCILIATION')
    base = agent_source(store, environment['version'])
    # A release archive is a valid base only when it matches the original
    # installed artifact's RECORD. A version label alone cannot establish it.
    for name, value in record.items():
        path = base / name
        if (not path.is_file() or base64.urlsafe_b64encode(hashlib.sha256(path.read_bytes()).digest()).decode().rstrip('=') != value):
            raise MaintenanceError('AGENT_REACH_ORIGINAL_SOURCE_NOT_RECOVERED')
    new = agent_source(store, target)
    result = customization_gate(store, 'agent-reach', target,
                                [{'name': 'package', 'live': live, 'base': base, 'upstream': new}])
    return result, actual


def agent_reach_probe(binary):
    current = read_version(binary, 'agent-reach')
    help_text = command([binary, '--help'])
    if 'doctor' not in help_text or 'skill' not in help_text:
        raise MaintenanceError('AGENT_REACH_COMMANDS_CHANGED')
    environment = agent_reach_environment(binary)
    skill_root = Path(environment['skill_root'])
    if not (skill_root / 'SKILL.md').is_file() or not (skill_root / 'references').is_dir():
        raise MaintenanceError('AGENT_REACH_BUNDLED_SKILL_MISSING')
    result = {'current': current, 'bundled_skill': True, 'commands': ['doctor', 'skill'],
              'business_verified': False}
    contract_script = Path(__file__).with_name('reach.py')
    if contract_script.is_file():
        spec = importlib.util.spec_from_file_location('lookup_reach_contract', contract_script)
        contract = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(contract)
        try:
            result['lookup_contract'] = contract.package_contract(skill_root.parent)
        except Exception as error:
            raise MaintenanceError('AGENT_REACH_LOOKUP_CONTRACT_CHANGED: ' + str(error)) from error
    return result


def external_skill_roots(dependency):
    roots = set()
    for directory in ('.agents/skills', '.codex/skills', '.claude/skills', '.gemini/skills',
                      '.grok/skills', '.workbuddy-ai/skills', '.gemini/config/skills',
                      '.gemini/antigravity/skills', '.gemini/antigravity-cli/skills'):
        path = Path.home() / directory / dependency
        if path.exists():
            roots.add(path.resolve())
    if dependency == 'ego-browser':
        vendor = Path.home() / '.local/share/ego/ego-skills'
        if vendor.exists():
            roots.add(vendor.resolve())
    return sorted(roots)


def protect_external_skills(store, dependency, official_old=None, package_root=None):
    roots = [r for r in external_skill_roots(dependency)
             if package_root is None or not r.is_relative_to(Path(package_root).resolve())]
    if not roots:
        return []
    backup = Path(tempfile.mkdtemp(prefix=dependency + '-skills-', dir=store.root))
    result = []
    for index, root in enumerate(roots):
        destination = backup / str(index)
        customization.copy_source(root, destination)
        original = None
        if official_old is not None:
            original = backup / (str(index) + '-base')
            customization.copy_source(official_old, original)
        result.append({'live': str(root), 'backup': str(destination), 'files': customization.files(root),
                       'base': str(original) if original is not None else None})
    return result


def capture_external_skill(item, force=False):
    actual = customization.files(item['live'])
    if not force and actual == item['files']:
        return actual
    signature = hashlib.sha256(json.dumps(actual, sort_keys=True).encode()).hexdigest()
    observations = Path(item['backup']).with_name(Path(item['backup']).name + '-observations')
    snapshot = observations / signature
    if not snapshot.exists():
        customization.copy_source(item['live'], snapshot)
    if customization.files(snapshot) != actual:
        raise MaintenanceError('SKILL_CHANGED_DURING_RECOVERY_SNAPSHOT')
    entry = {'directory': str(snapshot), 'fingerprint': signature}
    if entry not in item.setdefault('observations', []):
        item['observations'].append(entry)
    item['observation_directory'] = str(observations)
    return actual


def restore_external_skills(protected):
    for item in protected:
        actual = capture_external_skill(item)
        if actual != item['files']:
            if customization.files(item['live']) != actual:
                raise MaintenanceError('SKILL_CHANGED_DURING_RECOVERY')
            customization.replace_source(item['backup'], item['live'])


def reconcile_external_skills(store, dependency, target, protected, official_new=None):
    if not protected:
        return None
    # Unchanged local Skill bytes can still shadow a capability newly provided
    # upstream. Review every external Skill unless both official snapshots prove
    # it was pristine. Installer write activity is not a provenance check.
    stages = []
    for index, item in enumerate(protected):
        # Retain installer output as evidence, without asserting that it is a
        # complete official upstream snapshot when its source is unknown.
        capture_external_skill(item, force=True)
        observed = Path(item['observation_directory'])
        stages.append({'name': 'skill-' + str(index), 'live': item['live'],
                       'local': item['backup'], 'base': item.get('base'), 'upstream': official_new,
                       'observed': observed})
    restore_external_skills(protected)
    pristine = (official_new is not None and all(s['base'] is not None
                and customization.files(s['local']) == customization.files(s['base']) for s in stages))
    if pristine:
        for item in protected:
            customization.replace_source(official_new, item['live'])
        return None
    customization.create(store, dependency, target, stages)
    result = customization.pending(store, dependency)
    result.update(current_preserved=False, local_skill_preserved=True)
    return result


def finish_agent_customization(store, environment, target):
    root, request, receipt = customization.approved(store, 'agent-reach', target, check_live=False)
    if len(request['scopes']) != 1 or request['scopes'][0]['live'] != environment['package_root']:
        raise MaintenanceError('CUSTOMIZATION_ENVIRONMENT_CHANGED')
    actual = customization.files(environment['package_root'])
    if actual == receipt['merged'][0]:
        return
    if actual != request['scopes'][0]['upstream']:
        raise MaintenanceError('CUSTOMIZATION_CANDIDATE_SOURCE_MISMATCH')
    customization.replace_source(root / '0/merged', environment['package_root'])


def agent_official_skill(environment, review_directory=None):
    if review_directory:
        return Path(review_directory) / '0/upstream/skill'
    recorded = {name.removeprefix('agent_reach/') for name in environment['record']
                if name.startswith('agent_reach/') and not name.endswith('.pyc')
                and '__pycache__' not in Path(name).parts}
    if environment['changed'] or set(customization.files(environment['package_root'])) != recorded:
        raise MaintenanceError('AGENT_REACH_BUNDLED_SOURCE_UNVERIFIED')
    return Path(environment['skill_root'])


def finish_native_discovery(dependency, result):
    script = Path(__file__).with_name('entrypoints.py')
    if not script.is_file() or result.get('status') not in ('updated', 'up_to_date'):
        return result
    native_status = result['status']
    spec = importlib.util.spec_from_file_location('lookup_entry_policy', script)
    entries = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(entries)
    try:
        discovery = entries.migrate(Path.home(), ROOT, Path.home() / '.local/share/lookup/execution-skills')
    except Exception as error:
        return {**result, 'status': 'manual_review', 'native_status': native_status,
                'discovery_pending': True, 'discovery_error': str(error)}
    return {**result, 'discovery': discovery, 'discovery_pending': False,
            'discovery_error': None}


def native_update(store, dependency, retry=False):
    with store.lock('maintenance', blocking=False):
        current = installed(store, dependency)
        if current['status'] != 'installed':
            return {**current, 'dependency': dependency}
        record_name = 'native-' + dependency + '.json'
        prior = store.read(record_name)
        original_version = prior.get('before_version', prior.get('current'))
        if prior.get('discovery_pending'):
            if current['current'] != prior.get('current'):
                return {**prior, 'status': 'outcome_unknown', 'reason': 'DISCOVERY_RUNTIME_CHANGED'}
            result = finish_native_discovery(dependency, {**prior, 'status': prior['native_status'],
                                                          'native_reinvoked': False})
            store.write(record_name, result)
            return result
        if prior.get('status') == 'manual_review':
            native_status = prior.get('native_status')
            runtime_verified = ((native_status == 'updated' and version_tuple(current['current']) > version_tuple(original_version))
                                or (native_status == 'up_to_date' and current['current'] == original_version))
            if not runtime_verified:
                return {'status': 'outcome_unknown', 'dependency': dependency,
                        'current': current['current'], 'reason': 'NATIVE_RUNTIME_NOT_VERIFIED'}
            root, request = customization.load(store, dependency)
            if not (root / 'accepted.json').exists():
                return {**customization.pending(store, dependency), 'native_runtime_updated': native_status == 'updated',
                        'current_preserved': False, 'local_skill_preserved': True}
            root, request, receipt = customization.approved(store, dependency, current['current'])
            # The runtime was already upgraded; only finish the outstanding
            # Skill merge, never invoke the native updater a second time.
            try:
                for index, scope in enumerate(request['scopes']):
                    customization.replace_source(root / str(index) / 'merged', scope['live'])
                validation = native_probe(dependency, current['binary'])
            except BaseException:
                for index, scope in enumerate(request['scopes']):
                    customization.replace_source(root / str(index) / 'local', scope['live'])
                raise
            result = {'status': native_status, 'dependency': dependency, 'current': current['current'],
                      'validation': validation, 'customizations': 'reviewed', 'native_reinvoked': False}
            result = finish_native_discovery(dependency, result)
            store.write(record_name, {**prior, **result})
            return result
        if prior.get('status') in ('invoking', 'pending', 'outcome_unknown') and not retry:
            if original_version != current['current']:
                validation = native_probe(dependency, current['binary'])
                if version_tuple(current['current']) <= version_tuple(original_version):
                    return {'status': 'outcome_unknown', 'dependency': dependency,
                            'current': current['current'], 'reason': 'VERSION_DID_NOT_INCREASE'}
                if dependency == 'agent-reach':
                    environment = agent_reach_environment(current['binary'])
                    if (not prior.get('target')
                            or version_tuple(current['current']) < version_tuple(prior['target'])
                            or environment['prefix'] != prior.get('environment')):
                        return {'status': 'outcome_unknown', 'dependency': dependency,
                                'current': current['current'], 'reason': 'PRIOR_TARGET_NOT_VERIFIED',
                                'recovery': prior.get('recovery')}
                    if prior.get('customization_review'):
                        finish_agent_customization(store, environment, prior['target'])
                        validation = native_probe(dependency, current['binary'])
                    elif environment['changed']:
                        return {'status': 'outcome_unknown', 'dependency': dependency,
                                'reason': 'INSTALLATION_CONTENT_UNVERIFIED', 'recovery': prior.get('recovery')}
                result = {'status': 'updated', 'dependency': dependency,
                          'current': current['current'], 'validation': validation,
                          'recovered_after_interrupt': True}
                official_new = (agent_official_skill(environment, prior.get('customization_review'))
                                if dependency == 'agent-reach' else None)
                external_review = reconcile_external_skills(store, dependency, current['current'],
                                                            prior.get('protected_skills', []), official_new)
                if external_review:
                    result.update(external_review, native_status='updated', native_runtime_updated=True)
                result = finish_native_discovery(dependency, result)
                store.write(record_name, {**prior, **result})
                observe(store, dependency, current)
                return result
            return {'status': 'outcome_unknown', 'dependency': dependency,
                    'current': current['current'], 'reason': 'INSPECT_NATIVE_UPDATER_BEFORE_RETRY'}
        if dependency == 'agent-reach':
            release = check(store, dependency, force=True)
            if release['status'] != 'update_available':
                result = finish_native_discovery(dependency, {**release, 'dependency': dependency})
                if result.get('discovery_pending'):
                    store.write(record_name, result)
                return result
            environment = agent_reach_environment(current['binary'])
            review, package_before = agent_customizations(store, environment, release['latest'])
            if isinstance(review, dict):
                return review
            # uv and pipx retain their existing source, extras and injected packages.
            # A pinned source that cannot reach this release is reported and restored.
            argv = list(environment['argv'])
            if environment['manager'] == 'venv':
                argv.append('https://github.com/Panniantong/Agent-Reach/archive/refs/tags/v'
                            + release['latest'] + '.zip')
            prefix = Path(environment['prefix'])
            if store.root.resolve().is_relative_to(prefix.resolve()):
                raise MaintenanceError('RECOVERY_DIRECTORY_OVERLAPS_ENVIRONMENT')
            recovery = Path(tempfile.mkdtemp(prefix='agent-reach-', dir=store.root))
            backup = recovery / 'environment'
            launcher = Path(current['binary'])
            launcher_backup = recovery / 'launcher'
            try:
                shutil.copytree(prefix, backup, symlinks=True)
                shutil.copy2(launcher, launcher_backup, follow_symlinks=False)
            except BaseException:
                shutil.rmtree(recovery)
                raise
        else:
            argv = [current['binary'], 'upgrade']
        if dependency == 'agent-reach':
            official_old = (review[0] / '0/base/skill' if review else Path(environment['skill_root']))
            protected = protect_external_skills(store, dependency, official_old, environment['package_root'])
        else:
            protected = protect_external_skills(store, dependency)
        record = {'status': 'invoking', 'dependency': dependency, 'current': current['current'],
                  'before_version': current['current'],
                  'started_at': datetime.now(timezone.utc).isoformat(), 'protected_skills': protected}
        if dependency == 'agent-reach':
            record.update(environment=environment['prefix'], recovery=str(recovery),
                          target=release['latest'])
            if prior.get('recovery'):
                record['previous_recovery'] = prior['recovery']
            if review:
                record['customization_review'] = str(review[0])
        store.write(record_name, record)
        try:
            if dependency == 'agent-reach' and customization.files(environment['package_root']) != package_before:
                raise MaintenanceError('CUSTOMIZATION_CHANGED_DURING_UPDATE')
            execution_env = (dict(os.environ, **environment['manager_env'])
                             if dependency == 'agent-reach' else None)
            output = command(argv, timeout=180, env=execution_env)
            after = installed(store, dependency)
            if after['status'] != 'installed':
                raise MaintenanceError('NATIVE_EXECUTABLE_UNAVAILABLE')
            if dependency == 'agent-reach' and review:
                if after['current'] != release['latest']:
                    raise MaintenanceError('CUSTOMIZATION_CANDIDATE_SOURCE_MISMATCH')
                finish_agent_customization(store, environment, release['latest'])
            validation = native_probe(dependency, after['binary'])
            if dependency == 'agent-reach':
                if version_tuple(after['current']) < version_tuple(release['latest']):
                    raise MaintenanceError('INSTALLER_DID_NOT_REACH_STABLE_RELEASE')
                status = 'updated'
            elif version_tuple(after['current']) > version_tuple(current['current']):
                status = 'updated'
            elif after['current'] == current['current'] and re.search(r'up[- ]to[- ]date|already.{0,30}latest|no updates? available|已是最新|已经是最新', output, re.I):
                status = 'up_to_date'
            else:
                status = 'pending'
            result = {'status': status, 'dependency': dependency, 'current': after['current'],
                      'validation': validation}
            if status in ('updated', 'up_to_date'):
                official_new = (agent_official_skill(agent_reach_environment(after['binary']), record.get('customization_review'))
                                if dependency == 'agent-reach' else None)
                external_review = reconcile_external_skills(store, dependency, after['current'], protected, official_new)
                if external_review:
                    result.update(external_review, native_status=status, native_runtime_updated=status == 'updated')
            else:
                restore_external_skills(protected)
            result = finish_native_discovery(dependency, result)
            store.write(record_name, {**record, **result})
            observe(store, dependency, after)
            return result
        except BaseException as error:
            code = str(error) if isinstance(error, (MaintenanceError, customization.ReviewError)) else type(error).__name__
            if dependency == 'agent-reach':
                try:
                    failed = recovery / 'failed-environment'
                    if prefix.exists():
                        shutil.move(str(prefix), failed)
                    shutil.copytree(backup, prefix, symlinks=True)
                    if launcher.is_symlink() or launcher.exists():
                        launcher.unlink()
                    shutil.copy2(launcher_backup, launcher, follow_symlinks=False)
                    restored = read_version(str(launcher), dependency) == current['current']
                except (OSError, MaintenanceError):
                    restored = False
                result = {'status': 'failed', 'dependency': dependency, 'error': code,
                          'restored': restored, 'recovery': str(recovery)}
            else:
                result = {'status': 'outcome_unknown', 'dependency': dependency, 'error': code,
                          'current': current['current']}
            try:
                restore_external_skills(protected)
            except (OSError, ValueError) as restore_error:
                result['skill_recovery_error'] = type(restore_error).__name__
            store.write(record_name, {**record, **result})
            if isinstance(error, (KeyboardInterrupt, SystemExit)):
                raise
            return result


def native_probe(dependency, binary):
    if dependency == 'agent-reach':
        return agent_reach_probe(binary)
    guide = command([binary, 'skill'], timeout=15)
    if '[ego-browser:skill] end of guide' not in guide:
        raise MaintenanceError('EGO_EXECUTION_GUIDE_INCOMPLETE')
    return {'current': read_version(binary, dependency), 'guide_complete': True,
            'business_verified': False}


def update_all(store, automatic=False, retry=False):
    results = []
    for dependency in UPDATE_DEPENDENCIES:
        if automatic and dependency != 'opencli':
            continue
        try:
            result = (update(store, dependency, automatic, retry=True) if retry else
                      update(store, dependency, automatic))
            results.append({'dependency': dependency, **result})
        except (MaintenanceError, OSError, ValueError) as error:
            results.append({'dependency': dependency, 'status': 'failed',
                            'error': str(error) if isinstance(error, (MaintenanceError, customization.ReviewError)) else type(error).__name__})
    return {'status': 'batch', 'results': results}


def source_state(store):
    identity = hashlib.sha256(str(ROOT.resolve()).encode()).hexdigest()[:24]
    return Store(store.root / 'self' / identity)


def maintain(store, self_only=False, automatic=False, retry=False):
    """One total-update dispatcher, shared by CLI and Skill Manager."""
    if automatic:
        if self_only:
            raise MaintenanceError('AUTOMATION_NOT_SUPPORTED')
        return update_all(store, automatic=True, retry=retry)
    try:
        with store.lock('maintenance', blocking=False), store.lock('usage', blocking=False):
            own = self_update.update(source_state(store), ROOT, customization)
    except (MaintenanceError, OSError, ValueError, subprocess.SubprocessError) as error:
        own = {'dependency': 'lookup', 'status': 'failed',
               'error': str(error) if isinstance(error, (MaintenanceError, self_update.SourceError,
                                                         customization.ReviewError)) else type(error).__name__}
        transaction = source_state(store).read('self-transaction.json')
        if transaction.get('status') == 'failed':
            own.update({key: transaction[key] for key in ('restored', 'current_preserved', 'recovery')
                        if key in transaction})
    if self_only:
        return own
    if own['status'] == 'outcome_unknown' or own.get('current_preserved') is False:
        return {'status': 'batch', 'results': [own, *[
            {'dependency': name, 'status': 'deferred', 'reason': 'LOOKUP_SOURCE_STATE_UNCONFIRMED'}
            for name in UPDATE_DEPENDENCIES]]}
    if own['status'] == 'updated':
        # Load the newly installed executor, including its new dependency contracts.
        # The source switch has already released its maintenance lock.
        try:
            child = owned_process.run([sys.executable, str(ROOT / 'scripts/upstream.py'), 'upgrade',
                                       *(['--retry'] if retry else [])], timeout=900)
            dependencies = json.loads(child.stdout)
            items = dependencies.get('results') if isinstance(dependencies, dict) else None
            names = [item.get('dependency') for item in items if isinstance(item, dict)] if isinstance(items, list) else []
            if (not isinstance(dependencies, dict) or dependencies.get('status') != 'batch'
                    or not isinstance(items, list) or len(names) != len(items)
                    or any(not isinstance(name, str) or not name for name in names)
                    or len(set(names)) != len(names) or 'lookup' in names
                    or any(not isinstance(item.get('status'), str) for item in items)):
                raise ValueError('invalid child result')
            if child.returncode and not result_failed(dependencies):
                raise ValueError('child exit/result mismatch')
        except (ValueError, TypeError, KeyError, OSError, subprocess.SubprocessError):
            dependencies = {'status': 'batch', 'results': [
                {'dependency': name, 'status': 'outcome_unknown', 'error': 'NEW_EXECUTOR_RESULT_UNAVAILABLE',
                 'retry_safe': False}
                for name in UPDATE_DEPENDENCIES]}
    else:
        dependencies = update_all(store, retry=retry)
    return {'status': 'batch', 'results': [own, *dependencies['results']]}


def inspect_all(store, force=False):
    results = []
    try:
        results.append(self_update.inspect(source_state(store), ROOT, customization))
    except (OSError, ValueError, MaintenanceError, subprocess.SubprocessError) as error:
        results.append({'dependency': 'lookup', 'status': 'check_failed',
                        'error': str(error) if isinstance(error, (self_update.SourceError, MaintenanceError)) else type(error).__name__})
    for dependency in UPDATE_DEPENDENCIES:
        try:
            results.append({'dependency': dependency, **check(store, dependency, force=force)})
        except (OSError, ValueError, MaintenanceError) as error:
            results.append({'dependency': dependency, 'status': 'check_failed',
                            'error': str(error) if isinstance(error, MaintenanceError) else type(error).__name__})
    return {'status': 'batch', 'results': results}


def rollback(store):
    with store.lock('maintenance', blocking=False), store.lock('usage', blocking=False):
        active = store.read('active.json')
        if not active:
            return {'status': 'unchanged', 'reason': 'SYSTEM_INSTALLATION_ACTIVE'}
        before = active.get('previous', {})
        target = before.get('binary') or shutil.which('opencli')
        recovery = active.get('recovery', {})
        if (not target or str(Path(target).resolve()) != recovery.get('binary')
                or digest(target) != recovery.get('sha256')
                or read_version(target, 'opencli') != recovery.get('version')
                or not supported(recovery['version'])):
            raise MaintenanceError('ROLLBACK_TARGET_CHANGED')
        if (recovery.get('source_root') and customization.fingerprint(recovery['source_root'])
                != recovery.get('source_fingerprint')):
            raise MaintenanceError('ROLLBACK_TARGET_CHANGED')
        for entry in active.get('customization_recovery', []):
            if customization.files(entry['live']) != entry.get('expected'):
                raise MaintenanceError('CUSTOMIZATION_CHANGED_BEFORE_ROLLBACK')
        area = Path(tempfile.mkdtemp(prefix='rollback-exchange-', dir=store.root))
        restores, applied = [], []
        try:
            for index, entry in enumerate(active.get('customization_recovery', [])):
                snapshot = area / str(index)
                customization.copy_source(entry['live'], snapshot)
                if (customization.files(snapshot) != entry['expected']
                        or customization.files(entry['live']) != entry['expected']):
                    raise MaintenanceError('CUSTOMIZATION_CHANGED_BEFORE_ROLLBACK')
                restores.append({'live': entry['live'], 'snapshot': snapshot})
            if any(customization.files(entry['live']) != entry['expected']
                   for entry in active.get('customization_recovery', [])):
                raise MaintenanceError('CUSTOMIZATION_CHANGED_BEFORE_ROLLBACK')
            for entry, restore in zip(active.get('customization_recovery', []), restores):
                applied.append(restore)
                customization.replace_source(entry['backup'], entry['live'])
            store.write('active.json', before)
            current = installed(store, 'opencli')
            if current['status'] != 'installed':
                raise MaintenanceError('ROLLBACK_VERSION_UNAVAILABLE')
        except BaseException:
            try:
                if store.read('active.json') != active:
                    store.write('active.json', active)
                for entry in applied:
                    customization.replace_source(entry['snapshot'], entry['live'])
            except BaseException as error:
                raise MaintenanceError('ROLLBACK_RECOVERY_FAILED:' + str(area)) from error
            shutil.rmtree(area)
            raise
        shutil.rmtree(area)
        store.write('transaction.json', {'status': 'rolled_back', 'version': active['version'],
                                         'current': current['current']})
        observe(store, 'opencli', current)
        with store.lock('state'):
            state = store.read('state.json')
            state.setdefault('failed_versions', []).append(active['version'])
            store.write('state.json', state)
        return {'status': 'rolled_back', 'current': current['current']}


def use(store, expected, args):
    with store.lock('usage', shared=True):
        binary = resolve_opencli(store)
        if not binary or Path(binary).resolve() != Path(expected).resolve():
            raise MaintenanceError('EXECUTABLE_CHANGED_BEFORE_DISPATCH')
        return owned_process.call([binary, *args])


def human_result(result):
    status = result.get('status')
    dependency = result.get('dependency', 'opencli')
    if status == 'batch':
        return '\n'.join(human_result(item) for item in result['results'])
    if status == 'up_to_date':
        if dependency == 'lookup':
            return f'lookup 本体{result["current"]}已核对 {result.get("channel", "main")} 通道；本地内容保留。'
        return f'{dependency} 当前有效版本{result["current"]}，已是最新稳定版。'
    if status == 'local_ahead':
        return f'lookup 本体{result["current"]}领先源头{result["latest"]}，已保留，不执行降级。'
    if status == 'native_updater':
        return f'{dependency} 本机版本{result["current"]}；未检查远端版本，更新由原生升级器确认。'
    if status == 'update_available':
        if dependency == 'lookup':
            return (f'lookup 源头有新内容待合并；本地版本{result.get("current", "未知")}，'
                    f'源版本{result.get("latest", "未知")}；可运行 lookup update。')
        return f'{dependency} 当前版本{result.get("current", "未知")}，发现新版{result.get("latest", "未知")}；可运行 lookup upgrade {dependency}。'
    if status == 'check_failed':
        return dependency + ' 更新检查未完成：' + str(result.get('error') or result.get('reason') or 'UNKNOWN')
    if status == 'updated':
        if dependency == 'lookup':
            return f'lookup 本体已更新为{result["current"]}；原目录备份：{result["recovery"]}。'
        if dependency == 'ego-browser':
            return f'ego-browser 已更新为{result["current"]}，官方指南完整性已核对；浏览器业务未重验。'
        if dependency == 'agent-reach':
            return f'agent-reach 已更新为{result["current"]}，命令与随包 Skill 已核对；平台业务未重验。'
        return (f'OpenCLI 已更新为{result["current"]}；lookup 命令合约验证通过。'
                '原系统安装保留；真实平台业务仍按任务验证。')
    if status == 'not_installed':
        return f'未安装 {dependency}，已跳过；没有新增依赖。'
    if status == 'native_maintenance_required':
        return f'{result["dependency"]} 需要按官方原生方式维护，尚未执行更新。'
    if status == 'manual_review' and result.get('request'):
        preserved = ('原生运行程序已更新，本地 Skill 保留旧内容，合并尚未完成。'
                     if result.get('native_runtime_updated') else '当前版本已保留。')
        return (f'{dependency} 检测到本地定制，{preserved}由当前 Agent 按上游更新指南完成三方判断：'
                f'{result["request"]}；核验并登记后再次运行 '
                + ('lookup update --self-only' if dependency == 'lookup' else f'lookup upgrade {dependency}') + ' 接续。')
    if status == 'deferred':
        return dependency + ' 更新已延后，当前版本继续可用：' + str(result.get('reason') or result.get('error'))
    if status == 'failed':
        return dependency+' 更新失败：' + str(result.get('error')) + ('；原环境已恢复。' if result.get('restored') else '；恢复状态请核对本机维护回执。')
    if status in ('pending', 'outcome_unknown'):
        if dependency == 'lookup':
            return 'lookup 本体切换结果待核实；保留维护回执，先核对实际目录与恢复材料。'
        return (f'{dependency} 原生升级尚未确认完成；请在浏览器完成或取消原操作。'
                f'确认后可用 lookup upgrade {dependency} --retry 显式重试。')
    return json.dumps(result, ensure_ascii=False)


def maintenance_result(result, dependency=None):
    result = dict(result)
    if dependency:
        result.setdefault('dependency', dependency)
    if result.get('status') == 'batch':
        result['results'] = [maintenance_result(item) for item in result['results']]
    elif (result.get('status') in ('pending', 'outcome_unknown', 'interrupted')
          or result.get('outcome_unknown') is True or result.get('current_preserved') is False):
        result.update(outcome_unknown=True, retry_safe=False)
    return result


def result_failed(result):
    if result.get('status') == 'batch':
        return any(result_failed(item) for item in result['results'])
    return (result.get('outcome_unknown') is True
            or result.get('status') in ('failed', 'error', 'check_failed', 'manual_review', 'deferred',
                                       'interrupted', 'pending', 'outcome_unknown'))


def main(argv=None, human=False):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    for name in ('check', '_refresh'):
        item = sub.add_parser(name)
        item.add_argument('dependency', choices=DEPENDENCIES, **({'nargs': '?'} if name == 'check' else {}))
        item.add_argument('--background', action='store_true')
        item.add_argument('--force', action='store_true')
        item.add_argument('--current')
    item = sub.add_parser('notices')
    item.add_argument('dependencies', nargs='+', choices=DEPENDENCIES)
    item = sub.add_parser('policy')
    item.add_argument('dependency', choices=DEPENDENCIES)
    item.add_argument('mode', choices=('notify', 'auto'))
    for name in ('update', 'upgrade'):
        item = sub.add_parser(name, help=('Update lookup and installed upstream dependencies' if name == 'update'
                                         else 'Upgrade installed upstream dependencies only'))
        item.add_argument('dependency', nargs='?', choices=UPDATE_DEPENDENCIES)
        if name == 'update':
            item.add_argument('--self-only', action='store_true', help='Update lookup source only')
        item.add_argument('--auto', action='store_true')
        item.add_argument('--retry', action='store_true', help='Explicitly retry a previously uncertain native update')
    item = sub.add_parser('rollback')
    item.add_argument('dependency', choices=('opencli',))
    item = sub.add_parser('review', help='Inspect or seal a host Agent customization review')
    item.add_argument('dependency', choices=('lookup', *UPDATE_DEPENDENCIES))
    item.add_argument('--accept', metavar='DECISIONS_JSON')
    item.add_argument('--restart', action='store_true', help='Replan changed local inputs, retaining previous evidence')
    item.add_argument('--baseline', metavar='SOURCE_DIRECTORY')
    item.add_argument('--upstream', metavar='SOURCE_DIRECTORY')
    item.add_argument('--scope')
    item.add_argument('--source', help='Verified original upstream URL for a recovered baseline')
    sub.add_parser('resolve')
    item = sub.add_parser('use')
    item.add_argument('--expected', required=True)
    item.add_argument('args', nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.action == 'update' and args.self_only and (args.dependency or args.auto or args.retry):
        parser.error('--self-only cannot be combined with a dependency, --auto or --retry')
    if args.action == 'check' and args.dependency is None and (args.background or args.current):
        parser.error('--background and --current require a dependency')
    try:
        try:
            store = Store()
        except (MaintenanceError, OSError):
            # A first-use reminder cache failure must not disable the original
            # CLI. Existing managed state still requires explicit inspection.
            if args.action == 'resolve':
                try:
                    (state_root() / 'active.json').lstat()
                except FileNotFoundError:
                    print(json.dumps({'binary': shutil.which('opencli'), 'supervised': False}))
                    return 0
            raise
        if human and args.action in ('update', 'upgrade'):
            own = args.action == 'update' and not args.dependency and not args.auto
            scope = ('lookup 本体' if getattr(args, 'self_only', False) else
                     'lookup 本体与已安装上游' if own else args.dependency or '已安装上游')
            print('正在更新' + (' ' if scope[0].isascii() else '') + scope + '。', file=sys.stderr)
            if not getattr(args, 'self_only', False) and args.dependency in (None, 'ego-browser') and not args.auto:
                print('Ego 原生升级可能重启浏览器或等待界面确认。', file=sys.stderr)
        if args.action == 'use':
            return use(store, args.expected, args.args[1:] if args.args[:1] == ['--'] else args.args)
        if args.action == 'resolve':
            result = {'binary': resolve_opencli(store), 'supervised': fcntl is not None}
        elif args.action == 'check':
            result = (inspect_all(store, args.force) if args.dependency is None else
                      check(store, args.dependency, args.background, args.force, args.current))
        elif args.action == '_refresh':
            result = refresh(store, args.dependency, args.current, args.force)
        elif args.action == 'notices':
            result = {'notices': notices(store, args.dependencies)}
        elif args.action == 'policy':
            result = policy(store, args.dependency, args.mode)
        elif args.action == 'rollback':
            result = rollback(store)
        elif args.action == 'review':
            with store.lock('maintenance', blocking=False):
                review_store = source_state(store) if args.dependency == 'lookup' else store
                if args.restart:
                    if args.accept or args.baseline or args.upstream:
                        raise MaintenanceError('REVIEW_ACTIONS_ARE_EXCLUSIVE')
                    result = customization.restart(review_store, args.dependency)
                elif args.baseline or args.upstream:
                    if args.accept or (args.baseline and args.upstream) or not args.scope or not args.source:
                        raise MaintenanceError('BASELINE_SCOPE_AND_SOURCE_REQUIRED')
                    result = customization.recover_baseline(review_store, args.dependency, args.scope,
                                                            args.baseline or args.upstream, args.source,
                                                            label='base' if args.baseline else 'upstream')
                else:
                    result = (customization.accept(review_store, args.dependency, args.accept) if args.accept
                              else customization.pending(review_store, args.dependency))
        else:
            if args.action == 'update' and args.dependency is None:
                result = maintain(store, args.self_only, args.auto, args.retry)
            elif args.dependency is None:
                result = update_all(store, args.auto, args.retry)
            elif args.retry:
                result = update(store, args.dependency, args.auto, retry=True)
            else:
                result = update(store, args.dependency, args.auto)
        if args.action in ('update', 'upgrade'):
            result = maintenance_result(result, args.dependency)
        print(human_result(result) if human else json.dumps(result, ensure_ascii=False))
        return 1 if result_failed(result) else 0
    except (MaintenanceError, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        code = str(error) if isinstance(error, (MaintenanceError, customization.ReviewError, self_update.SourceError)) else type(error).__name__
        result = {'status': 'error', 'error': code}
        if args.action in ('update', 'upgrade') and args.dependency:
            result['dependency'] = args.dependency
        print(json.dumps(result), file=sys.stderr)
        return 75 if code == 'DEPENDENCY_BUSY' else 78


if __name__ == '__main__':
    def interrupted(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGHUP, interrupted)
    sys.exit(main())
