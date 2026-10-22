#!/usr/bin/env python3
"""Read the complete pinned Agent Reach source and run its isolated integration."""
import argparse
import ast
from contextlib import contextmanager
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'upstream'
REFERENCES = {name: f'agent_reach/skill/references/{name}.md'
              for name in ('search', 'social', 'career', 'dev', 'web', 'video', 'finance')}
REFERENCES.update(install='docs/install.md', update='docs/update.md')
REFERENCES.update({f'setup-{name}': f'agent_reach/guides/setup-{name}.md'
                   for name in ('exa', 'groq', 'reddit', 'twitter', 'xiaohongshu')})


class IntegrationError(RuntimeError):
    pass


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def source_files(source=SOURCE):
    manifest = json.loads((source / 'agent-reach.json').read_text())
    payload = (source / manifest['archive']).read_bytes()
    if sha256(payload) != manifest['archive_sha256']:
        raise IntegrationError('source_archive_changed')
    files = {}
    modes = {}
    with tarfile.open(fileobj=io.BytesIO(payload), mode='r:gz') as archive:
        for member in archive.getmembers():
            path = PurePosixPath(member.name)
            if path.is_absolute() or '..' in path.parts or member.issym() or member.islnk():
                raise IntegrationError('unsafe_source_member')
            if member.isdir():
                continue
            if not member.isfile() or len(path.parts) < 2:
                raise IntegrationError('unsupported_source_member')
            name = PurePosixPath(*path.parts[1:]).as_posix()
            if name in files:
                raise IntegrationError('duplicate_source_member')
            files[name] = archive.extractfile(member).read()
            modes[name] = member.mode
    actual = {name: {'sha256': sha256(data), 'size': len(data), 'mode': modes[name]} for name, data in files.items()}
    if actual != manifest['files']:
        raise IntegrationError('source_inventory_changed')
    return manifest, files


def adapted_files(manifest, files):
    result = dict(files)
    for change in manifest['adaptations']:
        original = result[change['file']].decode()
        if original.count(change['anchor']) != 1:
            raise IntegrationError('adaptation_anchor_changed')
        replacement = change['replacement'] if 'replacement' in change else change['anchor'] + change['insert']
        result[change['file']] = original.replace(change['anchor'], replacement, 1).encode()
    return result


def package_contract(package, capabilities=None):
    """Offline candidate contract shared with dependency maintenance."""
    capabilities = capabilities or json.loads((SOURCE / 'capabilities.json').read_text())
    registry = ast.parse((package / 'channels/__init__.py').read_text())
    imports = {alias.name: node.module for node in registry.body if isinstance(node, ast.ImportFrom)
               for alias in node.names}
    calls = next((node.value.elts for node in registry.body if isinstance(node, ast.AnnAssign)
                  and isinstance(node.target, ast.Name) and node.target.id == 'ALL_CHANNELS'
                  and isinstance(node.value, ast.List)), None)
    if calls is None:
        raise IntegrationError('candidate_registry_unknown')
    names = set()
    for call in calls:
        if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name) or call.func.id not in imports:
            raise IntegrationError('candidate_registry_unknown')
        module = imports[call.func.id]
        tree = ast.parse((package / 'channels' / (module + '.py')).read_text())
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == call.func.id)
        names.add(next(node.value.value for node in cls.body if isinstance(node, ast.Assign)
                       and isinstance(node.value, ast.Constant)
                       and any(isinstance(target, ast.Name) and target.id == 'name' for target in node.targets)))
    cli = ast.parse((package / 'cli.py').read_text())
    commands = {node.args[0].value for node in ast.walk(cli) if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute) and node.func.attr == 'add_parser'
                and isinstance(node.func.value, ast.Name) and node.func.value.id == 'sub'
                and node.args and isinstance(node.args[0], ast.Constant)}
    missing_channels = sorted(set(capabilities['channels']) - names)
    missing_commands = sorted(set(capabilities['cli']) - commands)
    missing_references = [name for name in capabilities['source_references']
                          if not (package / 'skill/references' / (name + '.md')).is_file()]
    missing_resources = [name for name in capabilities.get('runtime_resources', [])
                         if not (package / name.removeprefix('agent_reach/')).is_file()]
    missing_api = []
    for name, expected in capabilities.get('python_api', {}).items():
        path = package / name
        actual = set()
        if path.is_file():
            for node in ast.parse(path.read_text()).body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    actual.add(node.name)
                elif isinstance(node, ast.ClassDef):
                    actual.update(node.name + '.' + child.name for child in node.body
                                  if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)))
        missing_api.extend(name + ':' + symbol for symbol in set(expected) - actual)
    if missing_channels or missing_commands or missing_references or missing_resources or missing_api:
        raise IntegrationError(json.dumps({'candidate_contract_failed': True,
                              'missing_channels': missing_channels, 'missing_commands': missing_commands,
                              'missing_references': missing_references, 'missing_resources': missing_resources,
                              'missing_python_api': sorted(missing_api)}))
    return {'ok': True, 'channels': sorted(names), 'commands': sorted(commands),
            'reference_categories': capabilities['source_references'],
            'runtime_resources': capabilities.get('runtime_resources', []),
            'python_api_symbols': sum(map(len, capabilities.get('python_api', {}).values())),
            'business_verified': False}


def data_root():
    root = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share')))
    if not root.is_absolute():
        raise IntegrationError('data_home_must_be_absolute')
    return root.resolve() / 'lookup/agent-reach'


def private_directory(path):
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if current.is_symlink():
            raise IntegrationError('runtime_symlink_rejected')
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if hasattr(os, 'getuid') and path.stat().st_uid != os.getuid():
        raise IntegrationError('runtime_owner_mismatch')
    path.chmod(0o700)


def integration_id(manifest):
    return sha256(json.dumps(manifest['adaptations'], sort_keys=True).encode())[:12]


def runtime_dir(manifest):
    return data_root() / (manifest['commit'] + '-' + integration_id(manifest))


def python_path(directory):
    return directory / ('venv/Scripts/python.exe' if os.name == 'nt' else 'venv/bin/python')


def runtime_status(manifest, files):
    directory = runtime_dir(manifest)
    receipt = directory / 'receipt.json'
    if directory.is_symlink() or receipt.is_symlink():
        raise IntegrationError('runtime_symlink_rejected')
    if not receipt.is_file():
        return {'ready': False, 'reason': 'runtime_not_prepared', 'commit': manifest['commit']}
    saved = json.loads(receipt.read_text())
    if (saved.get('commit') != manifest['commit'] or saved.get('source_sha256') != manifest['archive_sha256']
            or saved.get('integration_id') != integration_id(manifest)):
        raise IntegrationError('runtime_source_mismatch')
    package = directory / saved['package']
    if not package.is_relative_to(directory) or package.is_symlink():
        raise IntegrationError('runtime_package_path_changed')
    expected = {name.removeprefix('agent_reach/'): sha256(content)
                for name, content in adapted_files(manifest, files).items()
                if name.startswith('agent_reach/')}
    for name, digest in expected.items():
        target = package / name
        if not target.is_file() or target.is_symlink() or sha256(target.read_bytes()) != digest:
            raise IntegrationError('runtime_package_changed')
    if not python_path(directory).is_file():
        raise IntegrationError('runtime_python_missing')
    return {'ready': True, 'commit': manifest['commit'], 'version': manifest['version'],
            'python': str(python_path(directory)), 'source_files': len(files),
            'integration_id': integration_id(manifest), 'registration': 'lookup_only'}


@contextmanager
def preparation_lock(root):
    private_directory(root)
    lock = root / 'prepare.lock'
    try:
        fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as error:
        raise IntegrationError('runtime_preparation_in_progress') from error
    try:
        os.write(fd, str(os.getpid()).encode())
        yield
    finally:
        os.close(fd)
        lock.unlink()


def prepare(manifest, files):
    if sys.version_info < (3, 10):
        raise IntegrationError('python_3_10_required')
    uv = shutil.which('uv')
    if not uv:
        raise IntegrationError('uv_missing_no_automatic_install')
    with preparation_lock(data_root()):
        status = runtime_status(manifest, files)
        if status['ready']:
            return {**status, 'created': False}
        directory = runtime_dir(manifest)
        if directory.exists():
            raise IntegrationError('incomplete_runtime_preserved')
        private_directory(directory)
        try:
            # A real path keeps venv shebangs valid; never rename an installed venv.
            source = directory / 'source'
            source.mkdir()
            for name, content in adapted_files(manifest, files).items():
                target = source / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
                target.chmod(manifest['files'][name]['mode'] & 0o755)
            subprocess.run([uv, 'venv', '--python', sys.executable, str(directory / 'venv')], check=True)
            subprocess.run([uv, 'pip', 'install', '--python', str(python_path(directory)), str(source)], check=True)
            probe = subprocess.run([str(python_path(directory)), '-c',
                                    'import agent_reach; from pathlib import Path; '
                                    'print(Path(agent_reach.__file__).parent)'],
                                   check=True, text=True, capture_output=True)
            package = Path(probe.stdout.strip())
            if not package.is_relative_to(directory):
                raise IntegrationError('runtime_package_outside_environment')
            receipt = {'commit': manifest['commit'], 'source_sha256': manifest['archive_sha256'],
                       'integration_id': integration_id(manifest),
                       'package': str(package.relative_to(directory))}
            (directory / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
            return {**runtime_status(manifest, files), 'created': True}
        except BaseException:
            # This invocation created the directory; it contains no user credentials.
            shutil.rmtree(directory)
            raise


def run_native(args, manifest, files):
    operation = next((item for item in args if not item.startswith('-')), None)
    if operation == 'skill' and '--help' not in args and '-h' not in args:
        raise IntegrationError('skill_registration_owned_by_lookup')
    status = runtime_status(manifest, files)
    if not status['ready']:
        raise IntegrationError('runtime_not_prepared_run_prepare_explicitly')
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
    return subprocess.call([status['python'], '-m', 'agent_reach.cli', *args], env=environment)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('verify', help='Verify every original upstream file, offline')
    item = sub.add_parser('contract', help='Validate an installed or candidate package before maintenance switches it')
    item.add_argument('--package-root', required=True, type=Path, help='Exact agent_reach package directory')
    item = sub.add_parser('reference', help='Read one complete upstream reference after Lookup selects it')
    item.add_argument('category', choices=REFERENCES)
    sub.add_parser('status', help='Read isolated runtime identity without probing platforms')
    sub.add_parser('prepare', help='Explicitly install private Python dependencies; no client registration')
    sub.add_parser('mcp', help='Run the original status MCP over stdio; requires explicitly installed MCP SDK')
    item = sub.add_parser('run', help='Call the integrated Agent Reach CLI; never installs implicitly')
    item.add_argument('args', nargs=argparse.REMAINDER)
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == 'run':
        native = argv[1:]
        if native[:1] == ['--']:
            native = native[1:]
        args = argparse.Namespace(command='run', args=native)
    else:
        args = parser.parse_args(argv)
    try:
        manifest, files = source_files()
        if args.command == 'verify':
            result = {'ok': True, 'commit': manifest['commit'], 'version': manifest['version'],
                      'channel': manifest['channel'], 'files': len(files), 'archive_sha256': manifest['archive_sha256']}
        elif args.command == 'reference':
            print('Lookup execution reference. Routing, authorization, installation, fees and retries '
                  'follow Lookup; the following is the complete pinned upstream reference.\n')
            print(files[REFERENCES[args.category]].decode())
            return 0
        elif args.command == 'status':
            result = runtime_status(manifest, files)
        elif args.command == 'prepare':
            result = prepare(manifest, files)
        elif args.command == 'contract':
            result = package_contract(args.package_root)
        elif args.command == 'mcp':
            status = runtime_status(manifest, files)
            if not status['ready']:
                raise IntegrationError('runtime_not_prepared_run_prepare_explicitly')
            return subprocess.call([status['python'], '-m', 'agent_reach.integrations.mcp_server'],
                                   env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
        else:
            return run_native(args.args, manifest, files)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (IntegrationError, OSError, ValueError, tarfile.TarError, subprocess.CalledProcessError) as error:
        print(json.dumps({'ok': False, 'error': str(error)}, ensure_ascii=False), file=sys.stderr)
        return 78


if __name__ == '__main__':
    raise SystemExit(main())
