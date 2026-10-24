#!/usr/bin/env python3
"""Verify complete pinned OpenCLI sources and read original guides on demand."""
import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'upstream'


class SourceError(RuntimeError):
    pass


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def metadata():
    return json.loads((SOURCE / 'opencli.json').read_text())


def source_files(payload, manifest, kind='source'):
    record = manifest if kind == 'source' else manifest['package']
    expected = record['archive_sha256'] if kind == 'source' else record['sha256']
    if sha256(payload) != expected:
        raise SourceError('archive_changed')
    if kind == 'package' and ('sha512-' + base64.b64encode(hashlib.sha512(payload).digest()).decode()
                              != record['integrity']):
        raise SourceError('package_integrity_changed')
    files, inventory = {}, {}
    total = 0
    with tarfile.open(fileobj=io.BytesIO(payload), mode='r:gz') as archive:
        for member in archive.getmembers():
            path = PurePosixPath(member.name)
            if path.is_absolute() or '..' in path.parts or member.issym() or member.islnk():
                raise SourceError('unsafe_source_member')
            if member.isdir():
                continue
            if not member.isfile() or len(path.parts) < 2:
                raise SourceError('unsupported_source_member')
            total += member.size
            if total > 128 * 1024 * 1024:
                raise SourceError('source_too_large')
            name = PurePosixPath(*path.parts[1:]).as_posix()
            if name in files:
                raise SourceError('duplicate_source_member')
            data = archive.extractfile(member).read()
            files[name] = data
            inventory[name] = {'sha256': sha256(data), 'size': len(data), 'mode': member.mode}
    if inventory != record['files']:
        raise SourceError('source_inventory_changed')
    return files


def cached_files(manifest):
    root = Path(os.environ.get('XDG_CACHE_HOME', str(Path.home() / '.cache')))
    if not root.is_absolute():
        raise SourceError('cache_home_must_be_absolute')
    root = root.resolve()
    directory = root / 'lookup/opencli' / manifest['commit']
    current = root
    for part in directory.relative_to(root).parts:
        current /= part
        if current.is_symlink():
            raise SourceError('source_cache_symlink')
    target = directory / 'source.tar.gz'
    if target.is_symlink():
        raise SourceError('source_cache_symlink')
    if target.is_file():
        payload = target.read_bytes()
        return source_files(payload, manifest)
    request = urllib.request.Request(manifest['archive_url'], headers={'User-Agent': 'Lookup-source-reader'})
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = response.read(32 * 1024 * 1024 + 1)
    if len(payload) > 32 * 1024 * 1024:
        raise SourceError('source_download_too_large')
    files = source_files(payload, manifest)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=directory, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
        try:
            # Publish without replacing a file created by another invocation.
            os.link(temporary, target)
        except FileExistsError:
            if target.is_symlink():
                raise SourceError('source_cache_symlink')
            return source_files(target.read_bytes(), manifest)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return files


def contract(binary, capabilities=None, env=None):
    """Check all baseline public commands without invoking a site or browser."""
    capabilities = capabilities or json.loads((SOURCE / 'opencli-capabilities.json').read_text())
    expected = {**capabilities['site_commands'], **capabilities['builtin_commands']}
    found, offset = {}, 0
    deadline = time.monotonic() + 60
    for _ in range(100):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise SourceError('registry_deadline_exceeded')
        result = subprocess.run([str(binary), 'list', '--limit', '100', '--offset', str(offset), '-f', 'json'],
                                env=env, text=True, capture_output=True, timeout=min(15, remaining), check=True)
        response = json.loads(result.stdout)
        if response.get('ok') is not True or not isinstance(response.get('data'), dict):
            raise SourceError('registry_invalid')
        page = response['data']
        for item in page['commands']:
            name = item['command']
            if name in found:
                raise SourceError('registry_duplicate')
            found[name] = item
        following = page.get('nextOffset')
        if following is None:
            if page.get('total') is not None and page['total'] != len(found):
                raise SourceError('registry_pagination_incomplete')
            break
        if not isinstance(following, int) or following <= offset:
            raise SourceError('registry_pagination_invalid')
        offset = following
    else:
        raise SourceError('registry_pagination_incomplete')
    missing = sorted(set(expected) - found.keys())
    access_changed = sorted(name for name, item in expected.items() if name in found
                            and item.get('access') in ('read', 'write')
                            and item['access'] != found[name].get('access'))
    if missing or access_changed:
        raise SourceError(json.dumps({'missing_commands': missing, 'access_changed': access_changed}))
    guides = sorted(name for name in capabilities.get('skills', {}) if name.startswith('opencli-'))
    if guides:
        result = subprocess.run([str(binary), 'skills', 'list', '-f', 'json'], env=env, text=True,
                                capture_output=True, timeout=15, check=True)
        response = json.loads(result.stdout)
        if response.get('ok') is not True or not isinstance(response.get('data'), list):
            raise SourceError('skill_registry_invalid')
        available = {item['name'] for item in response['data']}
        if set(guides) - available:
            raise SourceError('bundled_guides_missing:' + ','.join(sorted(set(guides) - available)))
        for name in guides:
            result = subprocess.run([str(binary), 'skills', 'read', name, '-f', 'plain'], env=env,
                                    text=True, capture_output=True, timeout=15, check=True)
            if not result.stdout.strip() or 'name: ' + name not in result.stdout:
                raise SourceError('bundled_guide_invalid:' + name)
    return {'ok': True, 'baseline_commands': len(expected), 'actual_commands': len(found),
            'extra_commands': sorted(found.keys() - expected.keys()), 'bundled_guides': guides,
            'business_verified': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    item = sub.add_parser('verify', help='Verify a complete local source or npm archive, offline')
    item.add_argument('--archive', type=Path, required=True)
    item.add_argument('--kind', choices=('source', 'package'), default='source')
    sub.add_parser('fetch', help='Cache complete pinned official sources; does not install or execute them')
    item = sub.add_parser('reference', help='Read one original source document without registering its Skill')
    item.add_argument('path', help='Exact source path, e.g. skills/opencli-usage/SKILL.md')
    item = sub.add_parser('contract', help='Check complete paginated public command registry')
    item.add_argument('--binary', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        manifest = metadata()
        if args.action == 'reference' and (args.path not in manifest['files'] or not args.path.endswith('.md')):
            raise SourceError('unknown_reference')
        if args.action == 'contract':
            with tempfile.TemporaryDirectory(prefix='lookup-opencli-contract-') as temporary:
                env = dict(os.environ, HOME=temporary, OPENCLI_CONFIG_DIR=str(Path(temporary) / 'config'), CI='1')
                result = contract(args.binary, env=env)
        else:
            files = (source_files(args.archive.read_bytes(), manifest, args.kind)
                     if args.action == 'verify' else cached_files(manifest))
            if args.action == 'reference':
                if args.path not in files or not args.path.endswith('.md'):
                    raise SourceError('unknown_reference')
                print('lookup execution reference. Routing, permissions, fees, retries and resource ownership '
                      'follow lookup. Original source follows; its triggers are not active.\n')
                print(files[args.path].decode())
                return 0
            result = {'ok': True, 'commit': manifest['commit'], 'version': manifest['version'], 'files': len(files)}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (SourceError, OSError, ValueError, KeyError, tarfile.TarError, subprocess.SubprocessError) as error:
        print(json.dumps({'ok': False, 'error': str(error)}, ensure_ascii=False), file=sys.stderr)
        return 78


if __name__ == '__main__':
    raise SystemExit(main())
