"""Update only lookup's source tree; never pull or reset its containing repository."""
from contextlib import contextmanager
import hashlib
import io
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tarfile
import tempfile


REPOSITORY = 'https://github.com/ldl8818/skills.git'
SOURCE_PATH = 'lookup'
CHANNEL = 'main'


class SourceError(ValueError):
    pass


def git(*args, cwd=None, binary=False):
    result = subprocess.run(['git', *map(str, args)], cwd=cwd, capture_output=True,
                            text=not binary, timeout=60,
                            env={**os.environ, 'GIT_TERMINAL_PROMPT': '0'})
    if result.returncode:
        raise SourceError('LOOKUP_SOURCE_GIT_FAILED')
    return result.stdout if binary else result.stdout.strip()


def official(url):
    return url.rstrip('/').removesuffix('.git') in (
        REPOSITORY.removesuffix('.git'), 'git' + '@' + 'github.com:ldl8818/skills')


def version(root):
    entry = Path(root) / 'SKILL.md'
    if not entry.exists():
        entry = Path(root) / 'SKILL.md.disabled'
    text = entry.read_text()
    front = text.split('---', 2)[1] if text.startswith('---\n') else ''
    match = re.search(r'^\s+version:\s*[\"\']?(\d+\.\d+\.\d+)[\"\']?\s*$', front, re.M)
    if not re.search(r'^name:\s*[\"\']?lookup[\"\']?\s*$', front, re.M) or not match:
        raise SourceError('LOOKUP_SOURCE_IDENTITY_INVALID')
    return match[1]


def number(value):
    return tuple(map(int, value.split('.')))


def source_files(root, audit):
    result = audit.files(root)
    if 'SKILL.md.disabled' in result:
        if 'SKILL.md' in result:
            raise SourceError('LOOKUP_SOURCE_AMBIGUOUS_SKILL_ENTRY')
        result['SKILL.md'] = result.pop('SKILL.md.disabled')
    return result


def archive(checkout, revision, destination):
    payload = git('archive', revision + ':' + SOURCE_PATH, cwd=checkout, binary=True)
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(payload)) as bundle:
        for member in bundle:
            path = PurePosixPath(member.name)
            if path.is_absolute() or '..' in path.parts or not (member.isdir() or member.isfile()):
                raise SourceError('LOOKUP_SOURCE_ARCHIVE_REJECTED')
            target = destination.joinpath(*path.parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.extractfile(member) as stream:
                    target.write_bytes(stream.read())
                target.chmod(0o755 if member.mode & 0o111 else 0o644)


def baseline(store, root, destination, audit, remote, revision):
    record = store.read('self-source.json')
    if record:
        source = Path(record.get('snapshot', ''))
        if (record.get('root') != str(root) or record.get('repository') != REPOSITORY
                or record.get('channel') != CHANNEL or source.is_symlink()
                or not source.is_relative_to(store.root)
                or audit.fingerprint(source) != record.get('fingerprint')):
            raise SourceError('LOOKUP_SOURCE_BASELINE_CHANGED')
        audit.copy_source(source, destination)
        return destination
    try:
        checkout = Path(git('rev-parse', '--show-toplevel', cwd=root)).resolve()
    except SourceError:
        return None
    if root != checkout / SOURCE_PATH:
        return None
    if not official(git('config', '--get', 'remote.origin.url', cwd=checkout)):
        raise SourceError('LOOKUP_SOURCE_OWNER_MISMATCH')
    # A local HEAD may contain committed customizations. Use only an ancestor
    # actually present in the selected official channel, and read its bytes there.
    official_commits = set(git('rev-list', revision, cwd=remote).splitlines())
    local_commits = git('rev-list', 'HEAD', '--', SOURCE_PATH, cwd=checkout).splitlines()
    shared = next((commit for commit in local_commits if commit in official_commits), None)
    if shared is None:
        return None
    archive(remote, shared, destination)
    return destination


@contextmanager
def source(store, root, audit):
    """Pin a full source snapshot in an isolated checkout, preserving the selected owner."""
    with tempfile.TemporaryDirectory(prefix='lookup-source-') as temporary:
        area = Path(temporary)
        checkout = area / 'repository'
        git('clone', '--quiet', '--filter=blob:none', '--sparse',
            '--branch', CHANNEL, '--', REPOSITORY, checkout)
        git('sparse-checkout', 'set', '--', SOURCE_PATH, cwd=checkout)
        revision = git('rev-parse', 'HEAD', cwd=checkout)
        base = baseline(store, root, area / 'base', audit, checkout, revision)
        upstream = checkout / SOURCE_PATH
        version(upstream)
        yield base, upstream, revision


def remember(store, root, upstream, revision, audit):
    snapshot = store.root / ('self-base-' + revision)
    if snapshot.exists():
        if audit.files(snapshot) != audit.files(upstream):
            raise SourceError('LOOKUP_SOURCE_BASELINE_CHANGED')
    else:
        audit.copy_source(upstream, snapshot)
    store.write('self-source.json', {'root': str(root), 'repository': REPOSITORY,
                'channel': CHANNEL, 'revision': revision, 'snapshot': str(snapshot),
                'fingerprint': audit.fingerprint(snapshot)})


def unconfirmed(store, root):
    previous = store.read('self-transaction.json')
    if previous.get('root') == str(root) and (previous.get('status') == 'prepared'
            or (previous.get('status') == 'failed' and not previous.get('current_preserved'))):
        return {'dependency': 'lookup', 'status': 'outcome_unknown',
                'reason': 'LOOKUP_SOURCE_INTERRUPTED_SWITCH', 'recovery': previous.get('recovery')}
    return None


def inspect(store, root, audit):
    root = Path(root).resolve()
    pending = unconfirmed(store, root)
    if pending:
        return pending
    with source(store, root, audit) as (base, upstream, revision):
        current, latest = version(root), version(upstream)
        same = source_files(root, audit) == audit.files(upstream)
        unchanged_source = base is not None and audit.files(base) == audit.files(upstream)
        status = ('local_ahead' if number(current) > number(latest) and unchanged_source else
                  'up_to_date' if same or unchanged_source else 'update_available')
        return {'dependency': 'lookup', 'status': status, 'current': current,
                'latest': latest, 'revision': revision, 'channel': CHANNEL,
                'baseline_known': base is not None or same}


def complete_state(root):
    """Include ignored user files in the switch guard, without logging their contents."""
    result = {}
    for directory, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d != '__pycache__')
        for name in dirs + sorted(names):
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                result[relative] = ('link', os.readlink(path))
            elif path.is_file():
                result[relative] = (path.stat().st_mode & 0o777,
                                    hashlib.sha256(path.read_bytes()).hexdigest())
            elif path.is_dir():
                result[relative] = ('directory', path.stat().st_mode & 0o777)
    return result


def validate(candidate):
    current = version(candidate)
    for name in ('scripts/lookup', 'scripts/upstream.py', 'scripts/customization.py',
                 'scripts/self_update.py', 'scripts/owned_process.py'):
        if not (candidate / name).is_file():
            raise SourceError('LOOKUP_SOURCE_ENTRY_MISSING')
    for path in (candidate / 'scripts').rglob('*.py'):
        try:
            compile(path.read_bytes(), str(path), 'exec')
        except SyntaxError as error:
            raise SourceError('LOOKUP_SOURCE_SYNTAX_INVALID') from error
    # Execute help in isolation: text mentions alone cannot prove an interface.
    with tempfile.TemporaryDirectory(prefix='lookup-source-help-') as temporary:
        environment = {**os.environ, 'HOME': temporary, 'USERPROFILE': temporary,
                       'XDG_STATE_HOME': str(Path(temporary) / 'state'),
                       'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONNOUSERSITE': '1', 'CI': '1'}
        for arguments, required in ((['--help'], ('update', 'upgrade')),
                                    (['update', '--help'], ('--self-only',)),
                                    (['upgrade', '--help'], ('opencli', 'agent-reach', 'ego-browser'))):
            result = subprocess.run([os.sys.executable, str(candidate / 'scripts/upstream.py'), *arguments],
                                    capture_output=True, text=True, timeout=10, env=environment)
            if result.returncode or any(word not in result.stdout for word in required):
                raise SourceError('LOOKUP_SOURCE_UPDATE_INTERFACE_UNSUPPORTED')
    return {'version': current, 'source_compiled': True, 'maintenance_help_verified': True,
            'business_verified': False}


def publish(store, root, candidate, upstream, revision, audit, expected_source):
    """A complete backup and staged directory preserve runtime files and local Git state."""
    before = complete_state(root)
    if source_files(candidate, audit) != expected_source:
        raise SourceError('LOOKUP_SOURCE_APPROVED_CANDIDATE_CHANGED')
    previous_source = store.read('self-source.json')
    area = Path(tempfile.mkdtemp(prefix='self-exchange-', dir=store.root))
    staged, backup = area / 'next', area / 'previous'
    try:
        shutil.copytree(root, staged, symlinks=True)
        audit.replace_source(candidate, staged)
        if (root / 'SKILL.md.disabled').is_file() and (staged / 'SKILL.md').is_file():
            (staged / 'SKILL.md').replace(staged / 'SKILL.md.disabled')
        validation = validate(staged)
        if source_files(staged, audit) != expected_source:
            raise SourceError('LOOKUP_SOURCE_APPROVED_CANDIDATE_CHANGED')
        if complete_state(root) != before:
            raise SourceError('LOOKUP_SOURCE_CHANGED_BEFORE_SWITCH')
        expected = complete_state(staged)
    except BaseException:
        shutil.rmtree(area)
        raise
    store.write('self-transaction.json', {'status': 'prepared', 'root': str(root),
                'revision': revision, 'recovery': str(backup), 'candidate': str(staged)})
    moved = False
    try:
        os.rename(root, backup)
        moved = True
        # Check again after moving; an editor may have changed the old directory.
        if complete_state(backup) != before:
            raise SourceError('LOOKUP_SOURCE_CHANGED_DURING_SWITCH')
        os.rename(staged, root)
        if complete_state(root) != expected:
            raise SourceError('LOOKUP_SOURCE_CHANGED_AFTER_SWITCH')
        remember(store, root, upstream, revision, audit)
        result = {'dependency': 'lookup', 'status': 'updated', 'current': version(root),
                  'revision': revision, 'recovery': str(backup), 'validation': validation}
        store.write('self-transaction.json', {**result, 'root': str(root)})
        return result
    except BaseException:
        restored = False
        # Preserve a different live generation; never overwrite a concurrent edit.
        if moved and (not root.exists() or complete_state(root) == expected):
            if root.exists():
                os.rename(root, area / 'observed-failed')
            os.rename(backup, root)
            restored = True
            store.write('self-source.json', previous_source)
        store.write('self-transaction.json', {'status': 'failed', 'root': str(root),
                    'revision': revision, 'recovery': str(backup), 'restored': restored,
                    'current_preserved': not moved or restored,
                    'observed': str(area / 'observed-failed') if (area / 'observed-failed').exists() else None})
        raise


def update(store, root, audit):
    root = Path(root).resolve()
    with store.lock('maintenance', blocking=False):
        pending = unconfirmed(store, root)
        if pending:
            return pending
        with source(store, root, audit) as (base, upstream, revision):
            current, latest = version(root), version(upstream)
            unchanged_source = base is not None and audit.files(base) == audit.files(upstream)
            if number(current) > number(latest) and unchanged_source:
                return {'dependency': 'lookup', 'status': 'local_ahead', 'current': current,
                        'latest': latest, 'revision': revision, 'current_preserved': True}
            if (source_files(root, audit) == audit.files(upstream)
                    or (base is not None and audit.files(base) == audit.files(upstream))):
                remember(store, root, upstream, revision, audit)
                return {'dependency': 'lookup', 'status': 'up_to_date', 'current': current,
                        'latest': latest, 'channel': CHANNEL, 'local_preserved': True}
            candidate = upstream
            expected_source = audit.files(upstream)
            if base is None or audit.files(base) != source_files(root, audit):
                pending = store.read('review-lookup.json')
                if pending:
                    directory, request = audit.load(store, 'lookup')
                    if request['target'] == revision:
                        if (len(request['scopes']) != 1 or request['scopes'][0]['live'] != str(root)
                                or request['scopes'][0]['name'] != 'lookup'
                                or request['scopes'][0]['upstream'] != audit.files(upstream)):
                            raise SourceError('LOOKUP_SOURCE_REVIEW_TARGET_CHANGED')
                        if not (directory / 'accepted.json').exists():
                            audit.assert_inputs(directory, request)
                            return audit.pending(store, 'lookup')
                        directory, request, receipt = audit.approved(store, 'lookup', revision)
                        candidate = directory / '0/merged'
                        expected_source = receipt['merged'][0]
                    else:
                        pending = None
                if not pending:
                    audit.create(store, 'lookup', revision, [
                        {'name': 'lookup', 'live': root, 'base': base, 'upstream': upstream,
                         'normalize_disabled': True}])
                    return audit.pending(store, 'lookup')
            if number(version(candidate)) < max(number(current), number(latest)):
                raise SourceError('LOOKUP_SOURCE_CANDIDATE_VERSION_MISMATCH')
            return publish(store, root, candidate, upstream, revision, audit, expected_source)
