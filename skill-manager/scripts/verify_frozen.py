#!/usr/bin/env python3
"""Validate repository-managed Skills, retired removals, and local Markdown references."""
import argparse
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import core
import audit_upstream
from install_frozen import NAMES

RETIRED = ('learn', 'read', 'health', 'hunt', 'think')


def verify(repo):
    errors = []
    for retired in RETIRED:
        if (repo / retired).exists():
            errors.append(f'{retired}: retired source still present')
    for name in NAMES:
        root = repo / name
        meta = core.parse_skill_md(str(root / 'SKILL.md'))
        policy = meta.get('update_policy')
        is_local = meta.get('source') == 'local'
        if meta.get('name') != name or (policy != 'frozen' and not is_local):
            errors.append(f'{name}: invalid identity or ownership policy')
        if not meta.get('description'):
            errors.append(f'{name}: missing routing description')
        if not (root / 'LICENSE').is_file():
            errors.append(f'{name}: missing license')
        if policy == 'frozen':
            if not re.fullmatch(r'[0-9a-f]{40}', str(meta.get('github_hash', ''))):
                errors.append(f'{name}: missing source evidence')
            try:
                receipt = json.loads((root / audit_upstream.RECEIPT).read_text())
                errors.extend(f'{name}: upstream coverage: {error}'
                              for error in audit_upstream.verify(root, receipt))
            except (OSError, ValueError, KeyError, TypeError) as error:
                errors.append(f'{name}: upstream coverage unavailable: {error}')
        for path in root.rglob('*.md'):
            if 'evals' in path.relative_to(root).parts:
                continue
            text = path.read_text()
            for match in re.finditer(r'\[[^\]]*\]\(([^)]+)\)', text):
                target = match.group(1).split('#')[0]
                if not target or '://' in target:
                    continue
                resolved = (path.parent / target).resolve()
                if not resolved.is_relative_to(root.resolve()) or not resolved.exists():
                    errors.append(f'{path.relative_to(repo)}: missing or escaping reference {target}')
            if '🥷' in text:
                errors.append(f'{path.relative_to(repo)}: retired runtime instruction')
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    args = parser.parse_args()
    errors = verify(args.repo.resolve())
    print('\n'.join(errors) if errors else f'Repository Skill structure and references: PASS ({len(NAMES)} Skills)')
    return bool(errors)


if __name__ == '__main__':
    raise SystemExit(main())
