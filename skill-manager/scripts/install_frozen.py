#!/usr/bin/env python3
"""Link repository-owned Skills without downloading or overwriting."""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import core
import audit_upstream

NAMES = ('check', 'ui', 'write', 'neat-freak')
CLIENT_ROOTS = {
    'codex': None,  # Codex uses the shared ~/.agents/skills root directly.
    'claude': '.claude/skills',
    'antigravity': '.gemini/config/skills',
    'workbuddy': '.workbuddy-ai/skills',
}
ENTRY_ROOTS = ('.agents/skills', '.claude/skills', '.gemini/config/skills', '.workbuddy-ai/skills')


def _target_roots(clients):
    if not clients or not set(clients) <= set(CLIENT_ROOTS):
        raise ValueError('invalid clients')
    roots = ['.agents/skills']
    for client in dict.fromkeys(clients):
        root = CLIENT_ROOTS[client]
        if root and root not in roots:
            roots.append(root)
    return tuple(roots)


def install(repo, home, clients=('claude', 'codex', 'antigravity', 'workbuddy')):
    roots = _target_roots(clients)
    repo, home = repo.resolve(), home.resolve()
    pending = []
    # Preflight the complete set before mutating any entry.
    for name in NAMES:
        source = repo / name
        if source.is_symlink() or not (source / 'SKILL.md').is_file():
            raise ValueError(f'{name}: repository source missing or indirect')
        meta = core.parse_skill_md(str(source / 'SKILL.md'))
        if meta.get('name') != name:
            raise ValueError(f'{name}: unexpected Skill identity')
        policy = meta.get('update_policy')
        is_local = meta.get('source') == 'local'
        if policy == 'frozen':
            receipt = json.loads((source / audit_upstream.RECEIPT).read_text())
            errors = audit_upstream.verify(source, receipt)
            if errors:
                raise ValueError(f'{name}: incomplete upstream merge: ' + '; '.join(errors))
        elif not is_local:
            raise ValueError(f'{name}: expected a local or frozen repository Skill')
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
    parser.add_argument(
        '--clients',
        default='claude,codex,antigravity,workbuddy',
        help='Comma-separated claude,codex,antigravity,workbuddy; shared .agents/skills links are always installed',
    )
    args = parser.parse_args()
    try:
        count = install(args.repo, args.home, tuple(c for c in args.clients.split(',') if c))
    except (OSError, ValueError) as error:
        print(f'Repository Skill install blocked: {error}', file=sys.stderr)
        return 1
    print(f'Repository Skills ready: {len(NAMES)} sources; {count} links created; no downloads')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
