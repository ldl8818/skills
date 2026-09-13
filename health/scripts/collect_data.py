#!/usr/bin/env python3
"""Collect bounded structural Agent evidence without executing project code."""
import argparse
import json
import os
from pathlib import Path
import stat

MAX_BYTES = 1_000_000
CONFIGS = ('.claude/settings.json', '.claude/settings.local.json', '.mcp.json',
           '.codex/config.toml', '.codex/hooks.json')
INSTRUCTIONS = ('AGENTS.md', 'CLAUDE.md', '.codex/AGENTS.md', '.claude/CLAUDE.md')


def file_summary(path, scope):
    """Reject escaping links and nonregular files; never return file contents."""
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(scope)
        fd = os.open(resolved, os.O_RDONLY | os.O_NONBLOCK | getattr(os, 'O_NOFOLLOW', 0))
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode):
                return {'status': 'nonregular'}
            if info.st_size > MAX_BYTES:
                return {'status': 'too_large'}
            data = stream.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            return {'status': 'too_large'}
        result = {'status': 'present', 'bytes': len(data)}
        if path.suffix == '.json':
            obj = json.loads(data)
            result['valid_json'] = True
            if isinstance(obj, dict):
                for key in ('hooks', 'mcpServers', 'permissions', 'enabledPlugins'):
                    value = obj.get(key)
                    if isinstance(value, (dict, list)):
                        result[key + '_entries'] = len(value)
        elif path.suffix == '.toml':
            try:
                import tomllib
            except ImportError:
                result['toml_validation'] = 'unavailable'
            else:
                tomllib.loads(data.decode('utf-8'))
                result['valid_toml'] = True
        else:
            result['lines'] = len(data.splitlines())
        return result
    except FileNotFoundError:
        return {'status': 'missing'}
    except (ValueError, RuntimeError):
        return {'status': 'invalid_or_outside_scope'}
    except OSError:
        return {'status': 'unreadable'}


def collect(root, include_global=False, history=None):
    result = {'schema': 1, 'project': {}, 'global': 'excluded',
              'history': 'excluded', 'mcp_live': 'not_run'}
    for relative in INSTRUCTIONS + CONFIGS:
        result['project'][relative] = file_summary(root / relative, root)
    # Names and content of Skills/configured commands are private by default.
    result['project']['skill_entries'] = {}
    for relative in ('.agents/skills', '.claude/skills', '.codex/skills'):
        path = root / relative
        try:
            path.resolve().relative_to(root)
            count = 0
            with os.scandir(path) as entries:
                for entry in entries:
                    count += 1
                    if count > 1000:
                        break
            result['project']['skill_entries'][relative] = {'count': min(count, 1000), 'truncated': count > 1000}
        except (OSError, ValueError):
            result['project']['skill_entries'][relative] = {'status': 'unavailable'}
    if include_global:
        home = Path.home().resolve()
        result['global'] = {p: file_summary(home / p, home) for p in INSTRUCTIONS[2:] + CONFIGS if p != '.mcp.json'}
    if history is not None:
        # Opt-in grants metadata inspection of this exact file, not siblings.
        try:
            if history.is_symlink():
                result['history'] = {'status': 'symlink_rejected'}
            else:
                info = history.stat()
                result['history'] = {'status': 'metadata_only', 'bytes': info.st_size} if stat.S_ISREG(info.st_mode) else {'status': 'nonregular'}
        except OSError:
            result['history'] = {'status': 'unavailable'}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--include-global', action='store_true')
    parser.add_argument('--include-history', action='store_true')
    parser.add_argument('--history-path', type=Path)
    args = parser.parse_args()
    if args.include_history != bool(args.history_path):
        parser.error('--include-history and --history-path must be supplied together')
    root = args.root.resolve()
    if not root.is_dir():
        parser.error('root must be an existing directory')
    print(json.dumps(collect(root, args.include_global, args.history_path), indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
