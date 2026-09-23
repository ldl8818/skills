#!/usr/bin/env python3
"""Link repository-owned frozen Skills without downloading or overwriting."""
import argparse
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import core

NAMES = ('check', 'health', 'hunt', 'ui', 'write')
ENTRY_ROOTS = ('.agents/skills', '.claude/skills', '.codex/skills')


def install(repo, home, clients=('claude', 'codex')):
    if not clients or not set(clients) <= {'claude', 'codex'}:
        raise ValueError('invalid clients')
    roots = ('.agents/skills',) + tuple(f'.{client}/skills' for client in dict.fromkeys(clients))
    repo, home = repo.resolve(), home.resolve()
    pending = []
    # Preflight the complete set before mutating any entry.
    for name in NAMES:
        source = repo / name
        if source.is_symlink() or not (source / 'SKILL.md').is_file():
            raise ValueError(f'{name}: repository source missing or indirect')
        meta = core.parse_skill_md(str(source / 'SKILL.md'))
        if meta.get('name') != name or meta.get('update_policy') != 'frozen':
            raise ValueError(f'{name}: expected a frozen named Skill')
        for relative in roots:
            entry = home / relative / name
            # A client root may be a symlink, but must remain inside the supplied HOME.
            try:
                entry.parent.resolve().relative_to(home)
            except ValueError:
                raise ValueError(f'{relative}: entry root escapes HOME')
            if entry.is_symlink():
                raw = Path(os.readlink(entry))
                target = raw if raw.is_absolute() else entry.parent / raw
                if Path(os.path.abspath(target)) == source and entry.resolve() == source:
                    continue
                raise ValueError(f'{relative}/{name}: existing link conflicts')
            if entry.exists():
                raise ValueError(f'{relative}/{name}: existing directory or file conflicts')
            pending.append((entry, source))
    created = []
    try:
        for entry, source in pending:
            entry.parent.mkdir(parents=True, exist_ok=True)
            entry.symlink_to(source, target_is_directory=True)
            created.append(entry)
    except OSError:
        for entry in reversed(created):
            entry.unlink()
        raise
    return len(created)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True, type=Path)
    parser.add_argument('--home', type=Path, default=Path.home(), help='Target home; default current user')
    parser.add_argument('--clients', default='claude,codex', help='Comma-separated claude,codex; shared Agent links are always installed')
    args = parser.parse_args()
    try:
        count = install(args.repo, args.home, tuple(args.clients.split(',')))
    except (OSError, ValueError) as error:
        print(f'Frozen Skill install blocked: {error}', file=sys.stderr)
        return 1
    print(f'Frozen Skills ready: {len(NAMES)} sources; {count} links created; no downloads')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
