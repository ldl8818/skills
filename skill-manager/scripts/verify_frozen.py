#!/usr/bin/env python3
"""Validate the repository's frozen Skill set and local Markdown references."""
import argparse
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import core
from install_frozen import NAMES


def verify(repo):
    errors = []
    for retired in ('think', 'learn', 'read'):
        if (repo / retired).exists():
            errors.append(f'{retired}: retired source still present')
    for name in NAMES:
        root = repo / name
        meta = core.parse_skill_md(str(root / 'SKILL.md'))
        if meta.get('name') != name or meta.get('update_policy') != 'frozen':
            errors.append(f'{name}: invalid identity or freeze policy')
        if not meta.get('description') or not re.fullmatch(r'[0-9a-f]{40}', str(meta.get('github_hash', ''))):
            errors.append(f'{name}: missing routing or source evidence')
        if not (root / 'LICENSE').is_file():
            errors.append(f'{name}: missing upstream license')
        for path in root.rglob('*.md'):
            text = path.read_text()
            for match in re.finditer(r'\[[^\]]*\]\(([^)]+)\)', text):
                target = match.group(1).split('#')[0]
                if not target or '://' in target:
                    continue
                resolved = (path.parent / target).resolve()
                if not resolved.is_relative_to(root.resolve()) or not resolved.exists():
                    errors.append(f'{path.relative_to(repo)}: missing or escaping reference {target}')
            if '🥷' in text or 'durable-context.md' in text:
                errors.append(f'{path.relative_to(repo)}: retired runtime instruction')
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    args = parser.parse_args()
    errors = verify(args.repo.resolve())
    print('\n'.join(errors) if errors else 'Frozen Skill structure and references: PASS (5 Skills)')
    return bool(errors)


if __name__ == '__main__':
    raise SystemExit(main())
