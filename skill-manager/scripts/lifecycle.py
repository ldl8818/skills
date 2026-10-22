"""Delegate Lookup maintenance to its resolved installation, independent of PATH."""
import json
import importlib.util
from pathlib import Path
import subprocess
import sys

import core


def lookup_root(path):
    root = Path(path).resolve()
    entry = root / 'SKILL.md'
    if not entry.is_file():
        entry = root / 'SKILL.md.disabled'
    if entry.is_file() and core.parse_frontmatter(entry.read_text()).get('name') == 'lookup':
        return root
    return None


def invoke(root, action='update', self_only=False, upstream_only=False, dry_run=False):
    root = Path(root).resolve()
    entries = ('upstream.py', 'self_update.py', 'owned_process.py')
    if (root / 'scripts').is_symlink() or any((root / 'scripts' / name).is_symlink() for name in entries):
        return {'status': 'error', 'error': 'LOOKUP_MAINTENANCE_ENTRY_REDIRECTED',
                'root': str(root)}, 1
    command = [sys.executable, str(root / 'scripts/upstream.py'),
               'upgrade' if upstream_only else action]
    if self_only:
        command.append('--self-only')
    if dry_run:
        return {'status': 'plan', 'root': str(root), 'command': command,
                'scope': 'self' if self_only else 'dependencies' if upstream_only else 'all',
                'remote_checked': False}, 0
    if not all((root / 'scripts' / name).is_file() for name in entries):
        return {'status': 'error', 'error': 'LOOKUP_MAINTENANCE_INTERFACE_UNAVAILABLE',
                'root': str(root)}, 1
    try:
        spec = importlib.util.spec_from_file_location('lookup_owned_process', root / 'scripts/owned_process.py')
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        result = runner.run(command, timeout=1200)
        payload = json.loads(result.stdout or result.stderr)
        if not isinstance(payload, dict) or not isinstance(payload.get('status'), str):
            raise ValueError('invalid maintenance result')
        if result.returncode == 0:
            items = payload.get('results', []) if payload['status'] == 'batch' else [payload]
            names = [item.get('dependency') for item in items if isinstance(item, dict)]
            scoped = (len(names) == len(items) and all(isinstance(name, str) for name in names)
                      and len(set(names)) == len(names))
            if self_only:
                scoped = scoped and names == ['lookup']
            elif upstream_only:
                scoped = scoped and payload['status'] == 'batch' and 'lookup' not in names
            else:
                scoped = scoped and payload['status'] == 'batch' and 'lookup' in names
            if not scoped:
                return {'status': 'outcome_unknown', 'error': 'LOOKUP_MAINTENANCE_SCOPE_MISMATCH',
                        'root': str(root), 'reported': payload, 'retry_safe': False}, 1
        def incomplete(item):
            if item.get('status') == 'batch':
                return any(incomplete(child) for child in item.get('results', []))
            return item.get('status') in ('failed', 'error', 'manual_review', 'pending',
                                           'outcome_unknown', 'interrupted', 'check_failed')
        return payload, result.returncode or int(incomplete(payload))
    except subprocess.TimeoutExpired:
        return {'status': 'outcome_unknown', 'error': 'LOOKUP_MAINTENANCE_TIMEOUT',
                'root': str(root), 'retry_safe': False}, 1
    except (OSError, ValueError):
        return {'status': 'error', 'error': 'LOOKUP_MAINTENANCE_RESULT_UNAVAILABLE',
                'root': str(root)}, 1


def update(root, self_only=False, upstream_only=False):
    payload, code = invoke(root, self_only=self_only, upstream_only=upstream_only)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return code == 0


def check(root):
    payload, code = invoke(root, action='check')
    items = payload.get('results', [])
    errors = code != 0 or any(i.get('status') in ('failed', 'error', 'check_failed') for i in items)
    outdated = any(i.get('status') in ('update_available', 'local_changed') for i in items)
    return {'status': 'error' if errors else 'outdated' if outdated else 'current',
            'message': 'Lookup 本体与已安装上游分项检查；Ego 远端版本仍以原生维护回执为准。',
            'managed_update': True, 'maintenance_root': str(root), 'components': payload}
