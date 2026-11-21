#!/usr/bin/env python3
"""Remove cache-only directories and client symlinks for retired Skills after Git updates."""

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
CLIENT_SKILL_ROOTS = (
    Path('.agents/skills'),
    Path('.claude/skills'),
    Path('.gemini/skills'),
    Path('.grok/skills'),
    Path('.gemini/config/skills'),
    Path('.gemini/antigravity/skills'),
    Path('.gemini/antigravity-cli/skills'),
    Path('.codex/skills'),
    Path('.workbuddy-ai/skills'),
)


def git(*args, cwd=None):
    return subprocess.check_output(['git', *args], cwd=cwd, text=True).strip()


def has_skill_entry(root):
    return (root / 'SKILL.md').is_file() or (root / 'SKILL.md.disabled').is_file()


def clean(repo, home=None):
    tracked = git('ls-files', '--', *RETIRED, cwd=repo).splitlines()
    committed = git('ls-tree', '--name-only', 'HEAD', '--', *RETIRED, cwd=repo).splitlines()
    protected = set(committed) | {path.split('/', 1)[0] for path in tracked}
    repo_root = repo.resolve()
    retired_targets = {}
    for name in RETIRED:
        if name in protected:
            continue
        root = repo / name
        if root.exists() or root.is_symlink():
            if not remove_caches(root):
                print(f'{name}: preserved directory with unrecognized contents', file=sys.stderr)
        if not has_skill_entry(root):
            retired_targets[repo_root / name] = name
    clean_symlinks(retired_targets, Path.home() if home is None else Path(home))


def clean_symlinks(retired_targets, home):
    if not retired_targets:
        return
    home_root = home.expanduser().resolve()
    seen_dirs = set()
    matches = []
    # Resolve all candidates first so removing a shared link does not break multi-hop links.
    for relative in CLIENT_SKILL_ROOTS:
        skills_dir = home_root / relative
        try:
            if not skills_dir.is_dir():
                continue
            resolved_dir = skills_dir.resolve()
        except OSError:
            continue
        if not resolved_dir.is_relative_to(home_root) or resolved_dir in seen_dirs:
            continue
        seen_dirs.add(resolved_dir)
        try:
            entries = sorted(skills_dir.iterdir())
        except OSError:
            continue
        for entry in entries:
            if not entry.is_symlink():
                continue
            try:
                target = entry.resolve(strict=False)
            except (OSError, RuntimeError):
                continue
            name = retired_targets.get(target)
            if name is not None:
                matches.append((name, relative / entry.name, entry))
    for name, display_path, entry in matches:
        entry.unlink(missing_ok=True)
        print(f'{name}: removed retired Skill symlink ~/{display_path}')


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
        home = Path.home()
    else:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument('--install', action='store_true', help='register this script with local Git')
        parser.add_argument('--home', type=Path, default=Path.home(), help='target home for client Skill symlinks')
        args = parser.parse_args()
        install_hooks = args.install
        home = args.home
    try:
        repo = Path(git('rev-parse', '--show-toplevel'))
        if install_hooks:
            install(repo)
        clean(repo, home=home)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f'retired Skill cleanup: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
