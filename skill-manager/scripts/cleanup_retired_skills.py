#!/usr/bin/env python3
"""Remove cache-only directories for retired Skills after Git updates."""

import argparse
from pathlib import Path
import re
import stat
import subprocess
import sys


RETIRED = ('learn', 'read', 'health', 'hunt', 'think', 'download-video')
HOOKS = ('post-merge', 'post-rewrite')
CACHE_DIRS = {'agents', 'references', 'scripts', 'tests', '__pycache__'}
BYTECODE = re.compile(r'.+\.cpython-\d+(?:\.opt-[12])?\.pyc')


def git(*args, cwd=None):
    return subprocess.check_output(['git', *args], cwd=cwd, text=True).strip()


def clean(repo):
    tracked = git('ls-files', '--', *RETIRED, cwd=repo).splitlines()
    committed = git('ls-tree', '--name-only', 'HEAD', '--', *RETIRED, cwd=repo).splitlines()
    protected = set(committed) | {path.split('/', 1)[0] for path in tracked}
    for name in RETIRED:
        root = repo / name
        if name in protected or not (root.exists() or root.is_symlink()):
            continue
        if not remove_caches(root):
            print(f'{name}: preserved directory with unrecognized contents', file=sys.stderr)


def remove_caches(root):
    if not stat.S_ISDIR(root.lstat().st_mode):
        return False
    pending = [root]
    directories = []
    files = []
    while pending:
        directory = pending.pop()
        directories.append(directory)
        for path in directory.iterdir():
            mode = path.lstat().st_mode
            if stat.S_ISDIR(mode) and path.name in CACHE_DIRS:
                pending.append(path)
            elif stat.S_ISREG(mode) and (
                path.name == '.DS_Store'
                or (directory.name == '__pycache__' and BYTECODE.fullmatch(path.name))
            ):
                files.append(path)
            else:
                return False
    for file in files:
        file.unlink(missing_ok=True)
    for directory in reversed(directories):
        directory.rmdir()
    print(f'{root.name}: removed retired cache directory')
    return True


def install(repo):
    configured = subprocess.run(
        ['git', 'config', '--get', 'core.hooksPath'], cwd=repo, capture_output=True
    )
    if configured.returncode != 1:
        raise RuntimeError('cannot install into custom or unavailable Git hooks path')
    hook_dir = Path(git('rev-parse', '--path-format=absolute', '--git-path', 'hooks', cwd=repo))
    script = Path(__file__).resolve()
    pending = []
    for name in HOOKS:
        hook = hook_dir / name
        if hook.is_symlink() and hook.resolve() == script:
            continue
        if hook.is_symlink() or hook.exists():
            raise RuntimeError(f'an existing {name} hook is installed')
        pending.append(hook)
    hook_dir.mkdir(parents=True, exist_ok=True)
    created = []
    try:
        for hook in pending:
            hook.symlink_to(script)
            created.append(hook)
    except OSError:
        for hook in created:
            hook.unlink()
        raise


def main():
    invoked_as = Path(sys.argv[0]).name
    if invoked_as in HOOKS:
        if invoked_as == 'post-rewrite' and sys.argv[1:] != ['rebase']:
            return 0
        install_hooks = False
    else:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument('--install', action='store_true', help='register this script with local Git')
        install_hooks = parser.parse_args().install
    try:
        repo = Path(git('rev-parse', '--show-toplevel'))
        if install_hooks:
            install(repo)
        clean(repo)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f'retired Skill cleanup: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
