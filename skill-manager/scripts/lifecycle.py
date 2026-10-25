"""Delegate lookup maintenance to its resolved installation, independent of PATH."""
import json
import importlib.util
from pathlib import Path
import subprocess
import sys

import core

TOOL_DEPENDENCIES = {'ego-lite': 'ego-browser', 'ego-browser': 'ego-browser',
                     'opencli': 'opencli', 'agent-reach': 'agent-reach'}
TOOL_NAMES = (*TOOL_DEPENDENCIES, 'lark-cli')


def lookup_root(path):
    root = Path(path).resolve()
    entry = root / 'SKILL.md'
    if not entry.is_file():
        entry = root / 'SKILL.md.disabled'
    if entry.is_file() and core.parse_frontmatter(entry.read_text()).get('name') == 'lookup':
        return root
    return None


def invoke(root, action='update', self_only=False, upstream_only=False, dry_run=False,
           dependency=None):
    if action != 'check' and not dry_run:
        import native_tools
        return native_tools.guard_lookup(lambda: _invoke(
            root, action, self_only, upstream_only, dry_run, dependency))
    return _invoke(root, action, self_only, upstream_only, dry_run, dependency)


def _invoke(root, action='update', self_only=False, upstream_only=False, dry_run=False,
            dependency=None):
    root = Path(root).resolve()
    entries = ('upstream.py', 'self_update.py', 'owned_process.py')
    if (root / 'scripts').is_symlink() or any((root / 'scripts' / name).is_symlink() for name in entries):
        return {'status': 'error', 'error': 'LOOKUP_MAINTENANCE_ENTRY_REDIRECTED',
                'root': str(root)}, 1
    command = [sys.executable, str(root / 'scripts/upstream.py'),
               'upgrade' if upstream_only or dependency else action]
    if dependency:
        if dependency not in TOOL_DEPENDENCIES.values():
            return {'status': 'error', 'error': 'UNKNOWN_LOOKUP_DEPENDENCY'}, 1
        command.append(dependency)
    if self_only:
        command.append('--self-only')
    if dry_run:
        return {'status': 'plan', 'root': str(root), 'command': command,
                'scope': dependency or ('self' if self_only else 'dependencies' if upstream_only else 'all'),
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
        items = payload.get('results') if payload['status'] == 'batch' else [payload]
        if (not isinstance(items, list)
                or any(not isinstance(item, dict) or not isinstance(item.get('status'), str)
                       for item in items)):
            raise ValueError('invalid maintenance items')
        if result.returncode == 0:
            names = [item.get('dependency') for item in items]
            scoped = (all(isinstance(name, str) for name in names)
                      and len(set(names)) == len(names))
            if dependency:
                scoped = scoped and names == [dependency] and payload['status'] != 'batch'
            elif self_only:
                scoped = scoped and names == ['lookup']
            elif upstream_only:
                scoped = scoped and payload['status'] == 'batch' and 'lookup' not in names
            else:
                scoped = scoped and payload['status'] == 'batch' and 'lookup' in names
            if not scoped:
                return {'status': 'outcome_unknown', 'error': 'LOOKUP_MAINTENANCE_SCOPE_MISMATCH',
                        'root': str(root), 'reported': payload, 'retry_safe': False}, 1
        def incomplete(item):
            if not isinstance(item, dict):
                return True
            if item.get('status') == 'batch':
                children = item.get('results')
                return (not isinstance(children, list) or not children
                        or any(incomplete(child) for child in children))
            complete = {'updated', 'up_to_date', 'local_ahead', 'not_installed', 'reference_only'}
            if action == 'check':
                complete |= {'update_available', 'local_changed', 'native_updater', 'installed'}
            return item.get('status') not in complete
        return payload, result.returncode or int(incomplete(payload))
    except subprocess.TimeoutExpired:
        return {'status': 'outcome_unknown', 'error': 'LOOKUP_MAINTENANCE_TIMEOUT',
                'root': str(root), 'retry_safe': False}, 1
    except (OSError, ValueError):
        return {'status': 'error' if action == 'check' else 'outcome_unknown',
                'error': 'LOOKUP_MAINTENANCE_RESULT_UNAVAILABLE',
                'root': str(root), 'retry_safe': action == 'check'}, 1


def invoke_tool(name, dry_run=False):
    if name == 'lark-cli':
        import native_tools
        return native_tools.update_lark(dry_run=dry_run)
    dependency = TOOL_DEPENDENCIES[name]
    path, error = core.resolve_direct_path('lookup')
    root = lookup_root(path) if path and not error else None
    if root is None:
        return {'status': 'error', 'error': error or 'LOOKUP_NOT_INSTALLED',
                'dependency': dependency}, 1
    return invoke(root, dependency=dependency, dry_run=dry_run)


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
            'message': 'lookup 本体与已安装上游分项检查；Ego 远端版本仍以原生维护回执为准。',
            'managed_update': True, 'maintenance_root': str(root), 'components': payload}
