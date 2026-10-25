"""Maintain lark-cli with the installed on-demand guide bridge and private receipts."""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile

import core

LARK_SOURCE = 'https://github.com/larksuite/cli'


class NativeError(RuntimeError):
    pass


def run(argv, timeout=30):
    with core.maintenance_signals(), subprocess.Popen(
            argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, start_new_session=True) as proc:
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except BaseException:
            # Only terminate the process group created for this invocation.
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(proc.pid, signal.SIGKILL)
                proc.communicate()
            raise
    if proc.returncode:
        raise NativeError('NATIVE_COMMAND_FAILED')
    return stdout


def official_skills(binary):
    data = json.loads(run([binary, 'skills', 'list']))
    if (not isinstance(data, dict) or data.get('ok') is not True
            or not isinstance(data.get('skills'), list)):
        raise NativeError('INVALID_OFFICIAL_SKILL_LIST')
    names = [row.get('name') if isinstance(row, dict) else None for row in data['skills']]
    if (not names or any(not isinstance(name, str)
                        or not re.fullmatch(r'lark-[a-z0-9-]+', name) for name in names)
            or len(names) != len(set(names))):
        raise NativeError('INVALID_OFFICIAL_SKILL_LIST')
    return names


def no_link_parents(path):
    for parent in (path, *path.parents):
        if not parent.is_symlink():
            continue
        # macOS exposes its ordinary temporary directories through these
        # system aliases. User-controlled redirects remain disallowed.
        if (sys.platform == 'darwin' and str(parent) in ('/var', '/tmp', '/etc')
                and parent.resolve() == Path('/private') / parent.name):
            continue
        raise NativeError('REDIRECTED_MAINTENANCE_PATH')


def entries(names):
    found = []
    for _, root_name in core.global_skill_roots():
        root = Path(root_name)
        if not root.exists():
            continue
        no_link_parents(root)
        candidates = set(names) | {path.name for path in root.glob('lark-*')}
        for name in sorted(candidates):
            entry = root / name
            if os.path.lexists(entry):
                found.append(entry)
    return found


def fingerprint(path):
    if not path.is_dir():
        raise NativeError('UNSUPPORTED_SKILL_ENTRY')
    result = {}
    for item in sorted(path.rglob('*')):
        key = item.relative_to(path).as_posix()
        if item.is_symlink():
            raise NativeError('REDIRECTED_SKILL_FILE')
        elif item.is_file():
            result[key] = hashlib.sha256(item.read_bytes()).hexdigest()
        elif not item.is_dir():
            raise NativeError('UNSUPPORTED_SKILL_FILE')
    return {'link': os.readlink(path) if path.is_symlink() else None, 'files': result}


def read_record(path, error):
    no_link_parents(path)
    try:
        data = core.read_json(str(path), {})
    except SystemExit:
        raise NativeError(error) from None
    if not isinstance(data, dict):
        raise NativeError(error)
    return data


def read_state(path):
    data = read_record(path, 'INVALID_NATIVE_STATE')
    if path.exists() and (
            not isinstance(data.get('status'), str)
            or any(key in data and not isinstance(data[key], bool)
                   for key in ('native_invoked', 'config_unchanged'))):
        raise NativeError('INVALID_NATIVE_STATE')
    return data


def source_files(source, names):
    no_link_parents(source)
    files = {}
    for name in names:
        no_link_parents(source / name)
        files.update({name + '/' + relative: digest
                      for relative, digest in fingerprint(source / name)['files'].items()})
    return files


def managed_source(state_root):
    """Validate the manifest, source identity and full tree in one pass."""
    manifest = state_root / 'resources.json'
    if not os.path.lexists(manifest):
        return None
    active = read_record(manifest, 'INVALID_RESOURCE_RECEIPT')
    runtime = active.get('runtime')
    match = (re.fullmatch(r'lark-cli version (\d+\.\d+\.\d+)', runtime)
             if isinstance(runtime, str) else None)
    if (active.get('schema_version') != 1 or not match
            or not isinstance(active.get('root'), str)
            or not isinstance(active.get('files'), dict) or not active['files']):
        raise NativeError('INVALID_RESOURCE_RECEIPT')
    source = Path(active['root'])
    no_link_parents(source)
    if (not source.is_absolute() or source.name != 'skills'
            or not source.parent.resolve().is_relative_to(state_root.resolve())):
        raise NativeError('INVALID_RESOURCE_SOURCE')
    receipt = read_record(source.parent / 'source-receipt.json', 'INVALID_SOURCE_RECEIPT')
    names = receipt.get('skills')
    if (receipt.get('version') != match[1] or receipt.get('url') != LARK_SOURCE
            or not isinstance(receipt.get('commit'), str)
            or not re.fullmatch(r'[0-9a-f]{40}', receipt['commit'])
            or not isinstance(names, list) or not names
            or any(not isinstance(name, str) or not re.fullmatch(r'lark-[a-z0-9-]+', name)
                   for name in names) or len(names) != len(set(names))):
        raise NativeError('INVALID_SOURCE_RECEIPT')
    actual = source_files(source, names)
    if actual != active['files']:
        raise NativeError('MANAGED_RESOURCES_CHANGED')
    return source, actual, names, match[1]


def official_snapshot(binary, version, recovery, names):
    """Bind the full published tree to the installed binary's embedded guide."""
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise NativeError('UNSUPPORTED_LARK_VERSION')
    active = managed_source(recovery.parent)
    if active and active[3] == version:
        source, files, recorded_names, _ = active
        if set(names) != set(recorded_names):
            raise NativeError('OFFICIAL_SOURCE_BINARY_MISMATCH')
        verify_embedded(binary, source, names)
        return source, files
    commit = core.remote_tags(LARK_SOURCE + '.git').get('v' + version)
    if not commit or not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise NativeError('OFFICIAL_RELEASE_SOURCE_UNAVAILABLE')
    # Reuse the manager's contained archive extraction, not a second extractor.
    import update_skill
    source = recovery / ('source-' + version)
    if os.path.lexists(source):
        raise NativeError('UNPUBLISHED_SOURCE_REQUIRES_REVIEW')
    update_skill.download_repo(LARK_SOURCE, commit, str(source))
    root = source / 'skills'
    verify_embedded(binary, root, names)
    files = source_files(root, names)
    core.write_json(str(source / 'source-receipt.json'),
                    {'url': LARK_SOURCE, 'commit': commit, 'version': version, 'skills': names})
    return root, files


def verify_embedded(binary, root, names):
    for name in names:
        guide = root / name / 'SKILL.md'
        if not guide.is_file() or guide.read_text() != run([binary, 'skills', 'read', name]):
            raise NativeError('OFFICIAL_SOURCE_BINARY_MISMATCH:' + name)


def archive_entries(names, recovery, phase, official, files=None):
    found = entries(names)
    if not found:
        return []
    records = []
    for index, entry in enumerate(found):
        if entry.name not in names:
            raise NativeError('UNSUPPORTED_SUITE_LAYOUT')
        observed = fingerprint(entry)
        expected = ({key.split('/', 1)[1]: digest for key, digest in files.items()
                     if key.startswith(entry.name + '/')} if files is not None
                    else fingerprint(official / entry.name)['files'])
        if observed['files'] != expected:
            raise NativeError('CUSTOM_SKILL_REQUIRES_REVIEW:' + entry.name)
        records.append({'original': str(entry),
                        'preserved': str(recovery / phase / str(index) / entry.name),
                        'link': os.readlink(entry) if entry.is_symlink() else None,
                        'target': str(entry.resolve()) if entry.is_symlink() else None,
                        'fingerprint': observed})
    receipt = recovery / (phase + '.json')
    core.write_json(str(receipt), {'status': 'planned', 'entries': records})
    moved = []
    try:
        # A preserved link must remain readable even if its old target is moved
        # or updated later. Keep its exact content separately from its raw link.
        for row in records:
            if row['link'] is not None:
                snapshot = Path(row['preserved']).with_name('link-content')
                shutil.copytree(row['original'], snapshot, symlinks=True)
                if fingerprint(snapshot)['files'] != row['fingerprint']['files']:
                    raise NativeError('SKILL_CHANGED_DURING_ARCHIVE')
        for row in records:
            source, destination = Path(row['original']), Path(row['preserved'])
            if row['link'] is not None:
                if not source.is_symlink() or os.readlink(source) != row['link']:
                    raise NativeError('SKILL_CHANGED_DURING_ARCHIVE')
                content = Path(row['target'])
                for previous in moved:
                    original = Path(previous['original'])
                    if previous['link'] is None and (content == original or original in content.parents):
                        content = Path(previous['preserved']) / content.relative_to(original)
                        break
                unchanged = fingerprint(content)['files'] == row['fingerprint']['files']
            else:
                unchanged = fingerprint(source) == row['fingerprint']
            if not unchanged:
                raise NativeError('SKILL_CHANGED_DURING_ARCHIVE')
            destination.parent.mkdir(parents=True, exist_ok=True)
            source.rename(destination)
            moved.append(row)
        for row in records:
            if row['link'] is None:
                continue
            destination = Path(row['preserved'])
            destination.unlink()
            destination.symlink_to(destination.with_name('link-content'), target_is_directory=True)
        for row in records:
            if fingerprint(Path(row['preserved']))['files'] != row['fingerprint']['files']:
                raise NativeError('SKILL_CHANGED_DURING_ARCHIVE')
        core.write_json(str(receipt), {'status': 'archived', 'entries': records})
        return records
    except BaseException:
        for row in reversed(moved):
            source, destination = Path(row['original']), Path(row['preserved'])
            if os.path.lexists(source):
                # Preserve a concurrent replacement and its recovery material.
                continue
            if row['link'] is not None:
                source.symlink_to(row['link'], target_is_directory=True)
                destination.unlink(missing_ok=True)
            else:
                destination.rename(source)
        core.write_json(str(receipt), {'status': 'archive_failed', 'entries': records})
        raise


def config_paths(include_lark=True):
    paths = set()
    if include_lark:
        base = Path(os.environ.get('LARKSUITE_CLI_CONFIG_DIR', str(Path.home() / '.lark-cli')))
        paths.update({base / 'config.json', *base.rglob('config.json')})
    else:
        config = Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config')))
        paths.add(config / 'lookup/opencli-binding.json')
    paths.update(Path.home() / relative for relative in (
        '.claude/settings.json', '.codex/config.toml', '.gemini/settings.json'))
    for path in paths:
        no_link_parents(path)
    return sorted(paths)


def config_snapshot(recovery, phase='before', include_lark=True):
    result = {}
    for index, path in enumerate(config_paths(include_lark)):
        if not path.is_file():
            if path.exists():
                raise NativeError('UNSUPPORTED_CONFIG_PATH')
            result[str(path)] = None
            continue
        backup = recovery / ('config-' + phase) / str(index)
        backup.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with backup.open('xb') as stream:
            os.chmod(backup, 0o600)
            stream.write(path.read_bytes())
        result[str(path)] = {'sha256': hashlib.sha256(backup.read_bytes()).hexdigest(),
                             'backup': str(backup), 'mode': path.stat().st_mode & 0o777}
    core.write_json(str(recovery / ('config-' + phase + '.json')), result)
    return result


def config_changed(before, include_lark=True):
    paths = {str(path) for path in config_paths(include_lark)} | set(before)
    for value in paths:
        path = Path(value)
        previous = before.get(value)
        if previous is None:
            if path.exists():
                return True
        elif (not path.is_file()
              or hashlib.sha256(path.read_bytes()).hexdigest() != previous['sha256']
              or path.stat().st_mode & 0o777 != previous['mode']):
            return True
    return False


def guard_lookup(callback):
    """Protect known client settings and the confirmed browser binding."""
    try:
        return _guard_lookup(callback)
    except (NativeError, OSError, ValueError, TypeError) as error:
        return {'status': 'manual_review', 'error': error_name(error), 'retry_safe': False}, 1


def error_name(error):
    return str(error) if isinstance(error, NativeError) else type(error).__name__


def unsafe_retry(result):
    if not isinstance(result, dict):
        return True
    if (result.get('retry_safe') is False or result.get('outcome_unknown') is True
            or result.get('current_preserved') is False):
        return True
    if result.get('status') == 'batch':
        items = result.get('results')
        return not isinstance(items, list) or not items or any(unsafe_retry(item) for item in items)
    retryable = {'updated', 'up_to_date', 'local_ahead', 'not_installed', 'reference_only',
                 'manual_review', 'deferred', 'failed', 'error', 'check_failed'}
    return bool(result) and result.get('status') not in retryable


def _guard_lookup(callback):
    root = Path(core.STATE_DIR) / 'native/lookup'
    no_link_parents(root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    state = root / 'state.json'
    lock_path = root / 'maintenance.lock'
    no_link_parents(state)
    no_link_parents(lock_path)
    with core.maintenance_lock(root) as acquired:
        if not acquired:
            return {'status': 'deferred', 'error': 'MAINTENANCE_IN_PROGRESS'}, 1
        previous = read_state(state)
        if previous.get('config_unchanged') is False or unsafe_retry(previous):
            return {**previous, 'status': 'manual_review',
                    'error': previous.get('error') or 'INSPECT_PRIOR_LOOKUP_OPERATION',
                    'retry_safe': False}, 1
        recovery = Path(tempfile.mkdtemp(prefix='config-', dir=root))
        try:
            before = config_snapshot(recovery, include_lark=False)
            core.write_json(str(state), {'status': 'invoking', 'config_unchanged': False,
                                        'config_recovery': str(recovery)})
            result, code = callback()
            unchanged = not config_changed(before, include_lark=False)
            if not unchanged:
                config_snapshot(recovery, 'after', include_lark=False)
                result = {**result, 'maintenance_status': result.get('status'),
                          'status': 'manual_review', 'error': 'CONFIG_CHANGED_REVIEW_BACKUP'}
                code = 1
            result = {**result, 'config_unchanged': unchanged, 'config_recovery': str(recovery)}
            core.write_json(str(state), result)
            return result, code
        except (NativeError, OSError, ValueError, TypeError, KeyboardInterrupt) as error:
            result = {'status': 'manual_review', 'error': error_name(error),
                      'config_recovery': str(recovery), 'config_unchanged': False}
            try:
                config_snapshot(recovery, 'after', include_lark=False)
            except (NativeError, OSError) as snapshot_error:
                result['config_verification_error'] = error_name(snapshot_error)
            core.write_json(str(state), result)
            return result, 1


def publish_resources(binary, source, names, state_root, files=None):
    """Publish a verified on-demand source without registering any Skill."""
    version = run([binary, '--version']).strip()
    no_link_parents(source)
    if files is None:
        files = source_files(source, names)
    receipt = {'schema_version': 1, 'runtime': version,
               'root': str(source.resolve()), 'files': files}
    destination = state_root / 'resources.json'
    no_link_parents(destination)
    if destination.exists():
        previous = read_record(destination, 'INVALID_RESOURCE_RECEIPT')
        if previous == receipt:
            return
        managed_source(state_root)
    else:
        vendor = Path.home() / '.agents/tools/lark/vendor'
        if vendor.is_dir():
            legacy = fingerprint(vendor)['files']
            differences = [key for key, digest in legacy.items()
                           if not key.endswith('.DS_Store') and files.get(key) != digest]
            if differences:
                review = read_record(state_root / 'legacy-resource-review.json',
                                     'INVALID_LEGACY_RESOURCE_REVIEW')
                if (review.get('files') != legacy or review.get('runtime') != version
                        or not review.get('adaptations') or not review.get('validation')):
                    raise NativeError('LEGACY_RESOURCE_REVIEW_REQUIRED')
    core.write_json(str(destination), receipt)


def update_lark(dry_run=False):
    try:
        return _update_lark(dry_run)
    except (NativeError, OSError, ValueError, KeyError, TypeError,
            subprocess.SubprocessError) as error:
        return {'status': 'manual_review', 'dependency': 'lark-cli',
                'error': error_name(error), 'retry_safe': False}, 1


def _update_lark(dry_run=False):
    binary = shutil.which('lark-cli')
    bridge = Path.home() / '.agents/tools/lark/scripts/read_embedded.py'
    if not binary or not bridge.is_file():
        return {'status': 'error', 'dependency': 'lark-cli',
                'error': 'LARK_ON_DEMAND_MAINTENANCE_UNAVAILABLE'}, 1
    if dry_run:
        return {'status': 'plan', 'dependency': 'lark-cli', 'binary': binary,
                'scope': 'CLI and on-demand guide layout', 'remote_checked': False,
                'steps': ['check', 'archive_entries', 'native_update_if_needed',
                          'reconcile_entries', 'verify_config_and_bridge']}, 0
    root = Path(core.STATE_DIR) / 'native/lark-cli'
    no_link_parents(root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.chmod(0o700)
    state_file = root / 'state.json'
    no_link_parents(state_file)
    lock_path = root / 'maintenance.lock'
    no_link_parents(lock_path)
    with core.maintenance_lock(root) as acquired:
        if not acquired:
            return {'status': 'deferred', 'dependency': 'lark-cli',
                    'error': 'MAINTENANCE_IN_PROGRESS'}, 1
        previous = read_state(state_file)
        if ((previous.get('status') in ('invoking', 'verifying')
                or previous.get('native_invoked') or previous.get('config_unchanged') is False)
                and previous.get('status') not in ('updated', 'up_to_date')):
            return {**previous,
                    'error': 'INSPECT_PRIOR_NATIVE_OPERATION', 'retry_safe': False}, 1
        result = {'status': 'checking', 'dependency': 'lark-cli', 'native_invoked': False}
        protected = None
        recovery = None
        try:
            if run([sys.executable, str(bridge), '--manager-protocol']).strip() != '1':
                raise NativeError('LARK_BRIDGE_PROTOCOL_UNAVAILABLE')
            recovery = Path(tempfile.mkdtemp(prefix='update-', dir=root))
            result['recovery'] = str(recovery)
            protected = config_snapshot(recovery)
            checked = json.loads(run([binary, 'update', '--check', '--json']))
            before_version = run([binary, '--version']).strip()
            if (not isinstance(checked, dict) or checked.get('ok') is not True or checked.get('action') not in
                    ('update_available', 'already_up_to_date')
                    or any(not isinstance(checked.get(key), str)
                           or not re.fullmatch(r'\d+\.\d+\.\d+', checked[key])
                           for key in ('current_version', 'latest_version'))
                    or before_version != 'lark-cli version ' + checked['current_version']):
                raise NativeError('UNVERIFIED_UPDATE_CHECK')
            current_number, target_number = (tuple(map(int, checked[key].split('.')))
                                            for key in ('current_version', 'latest_version'))
            if (target_number < current_number or
                    (checked['action'] == 'update_available') != (target_number > current_number)):
                raise NativeError('UNVERIFIED_UPDATE_CHECK')
            names = official_skills(binary)
            result.update(before_version=checked['current_version'],
                          target=checked['latest_version'])
            # The full old tree is checked independently of the current binary:
            # an external upgrade may have legitimately changed that binary.
            source, files = official_snapshot(binary, checked['current_version'], recovery, names)
            publish_resources(binary, source, names, root, files)
            run([sys.executable, str(bridge), '--doctor'])
            if config_changed(protected):
                raise NativeError('CONFIG_CHANGED_REVIEW_BACKUP')
            before = archive_entries(names, recovery, 'before', source, files)
            result['archived_before'] = len(before)
            core.write_json(str(state_file), result)
            if checked['action'] == 'update_available':
                result.update(status='invoking', native_invoked=True)
                core.write_json(str(state_file), result)
                native = json.loads(run([binary, 'update', '--json'], timeout=900))
                if (not isinstance(native, dict) or native.get('ok') is not True or native.get('action') not in
                        ('updated', 'already_up_to_date')):
                    raise NativeError('NATIVE_RESULT_UNCONFIRMED')
            # Reconcile the actual installed version, even when the updater
            # failed or returned an unexpected result.
            current = run([binary, '--version']).strip()
            if current != 'lark-cli version ' + checked['latest_version']:
                raise NativeError('RUNTIME_TARGET_MISMATCH')
            result.update(status='verifying', current=checked['latest_version'])
            core.write_json(str(state_file), result)
            if result['native_invoked']:
                names = official_skills(binary)
                source, files = official_snapshot(binary, checked['latest_version'], recovery, names)
                publish_resources(binary, source, names, root, files)
            result['archived_after'] = len(archive_entries(
                names, recovery, 'after', source, files))
            if config_changed(protected):
                raise NativeError('CONFIG_CHANGED_REVIEW_BACKUP')
            run([sys.executable, str(bridge), '--doctor'])
            if entries(names):
                raise NativeError('GLOBAL_ENTRIES_REAPPEARED')
            result.update(status='updated' if result['native_invoked'] else 'up_to_date',
                          entry_layout='on_demand', config_unchanged=True,
                          bridge_verified=True, business_verified=False)
            core.write_json(str(state_file), result)
            return result, 0
        except (NativeError, OSError, ValueError, KeyError, TypeError,
                subprocess.SubprocessError, KeyboardInterrupt) as error:
            result.update(status='outcome_unknown' if result['status'] == 'invoking' else 'manual_review',
                          error=str(error) if isinstance(error, NativeError) else type(error).__name__)
            if recovery and result['native_invoked']:
                try:
                    observed = run([binary, '--version']).strip()
                    match = re.fullmatch(r'lark-cli version (\d+\.\d+\.\d+)', observed)
                    if not match:
                        raise NativeError('RUNTIME_VERSION_UNVERIFIED')
                    # Keep different versions in separate source directories.
                    names = official_skills(binary)
                    current_source, files = official_snapshot(binary, match[1], recovery, names)
                    publish_resources(binary, current_source, names, root, files)
                    result['archived_after_failure'] = len(archive_entries(
                        names, recovery, 'failure', current_source, files))
                except (NativeError, OSError, ValueError, KeyError, TypeError,
                        subprocess.SubprocessError) as cleanup_error:
                    result['entry_recovery_error'] = (str(cleanup_error)
                        if isinstance(cleanup_error, NativeError) else type(cleanup_error).__name__)
            if protected is not None:
                try:
                    result['config_unchanged'] = not config_changed(protected)
                    if not result['config_unchanged']:
                        config_snapshot(recovery, 'after')
                except (NativeError, OSError) as config_error:
                    result['config_unchanged'] = False
                    result['config_verification_error'] = type(config_error).__name__
            result['retry_safe'] = not result['native_invoked'] and result.get('config_unchanged') is True
            core.write_json(str(state_file), result)
            return result, 1
