#!/usr/bin/env python3
"""Keep lookup as the sole generic web Skill; preserve displaced sources."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import uuid

CLIENTS = ('.agents', '.codex', '.claude', '.gemini', '.grok', '.workbuddy-ai',
           '.gemini/config', '.gemini/antigravity', '.gemini/antigravity-cli')
INTERNAL = ('agent-reach', 'opencli', 'opencli-browser', 'opencli-usage',
            'opencli-adapter-author', 'opencli-autofix', 'smart-search', 'ego-browser', 'web-access')


class EntryError(RuntimeError):
    pass


def existing(path):
    return path.exists() or path.is_symlink()


def internal_entry(root, name):
    entry = root / name
    if not existing(entry):
        return False
    # The generic name is also used by unrelated packages. Only recognize the
    # OpenCLI guide, including locally customized copies that retain its origin.
    if name == 'smart-search':
        guide = entry / 'SKILL.md'
        return guide.is_file() and 'opencli' in guide.read_text().lower()
    return True


def inventory(home, lookup):
    result = []
    for client in CLIENTS:
        root = home / client / 'skills'
        if not root.is_dir():
            continue
        entry = root / 'lookup'
        competing = [name for name in INTERNAL if internal_entry(root, name)]
        result.append({'client': client, 'root': str(root), 'competing': competing,
                       'lookup': 'ready' if entry.is_dir() and entry.resolve() == lookup
                       else ('conflict' if existing(entry) else 'missing')})
    return result


def migrate(home, lookup, storage, *, create_lookup=True):
    # All callers for this HOME share an inode lock, including maintenance and
    # direct CLI invocations. A crash releases it without a stale lock file.
    fd = os.open(home, os.O_RDONLY)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise EntryError('migration_in_progress_no_changes') from error
        return _migrate(home, lookup, storage, create_lookup=create_lookup)
    finally:
        os.close(fd)


def _prune_dangling(receipt):
    kept = []
    pruned = 0
    for record in receipt['entries']:
        preserved = Path(record['preserved'])
        if record.get('original_link') is not None and preserved.is_symlink() and not preserved.exists():
            preserved.unlink(missing_ok=True)
            pruned += 1
        else:
            kept.append(record)
    receipt['entries'] = kept
    return pruned


def _migrate(home, lookup, storage, *, create_lookup=True):
    relative_storage = storage.relative_to(home)
    home, lookup = home.resolve(), lookup.resolve()
    storage = home / relative_storage
    if not (lookup / 'SKILL.md').is_file():
        raise EntryError('lookup_source_missing')
    rows = inventory(home, lookup)
    if not rows:
        rows = [{'client': '.agents', 'root': str(home / '.agents/skills'),
                 'competing': [], 'lookup': 'missing'}]
    if create_lookup and any(row['lookup'] == 'conflict' for row in rows):
        raise EntryError('lookup_entry_conflict_no_changes')
    for row in rows:
        current = home
        for part in Path(row['root']).relative_to(home).parts:
            current /= part
            if current.is_symlink():
                raise EntryError('client_directory_symlink_no_changes')
    current = home
    for part in storage.relative_to(home).parts:
        current /= part
        if current.is_symlink():
            raise EntryError('execution_storage_symlink')
    receipt_path = storage / 'entries.json'
    if receipt_path.is_symlink():
        raise EntryError('execution_receipt_symlink')
    receipt = json.loads(receipt_path.read_text()) if receipt_path.is_file() else {'schema_version': 1, 'entries': []}
    if (not isinstance(receipt, dict) or receipt.get('schema_version') != 1
            or not isinstance(receipt.get('entries'), list)
            or any(not isinstance(record, dict) or not isinstance(record.get('preserved'), str)
                   or not record['preserved'] for record in receipt['entries'])):
        raise EntryError('execution_receipt_invalid')
    managed = {record['preserved'] for record in receipt['entries']}
    archived_live_links = set()
    for record in receipt['entries']:
        preserved = Path(record['preserved'])
        if (record.get('original_link') is not None and preserved.is_symlink()
                and (preserved / 'SKILL.md').is_file()):
            archived_live_links.add((record.get('original'), str(preserved.resolve())))
    relocating_dirs = []
    for row in rows:
        for name in row['competing']:
            entry = Path(row['root']) / name
            if not entry.is_symlink() and entry.is_dir():
                relocating_dirs.append(entry.resolve())
    moves = []
    dedups = []
    for row in rows:
        for name in row['competing']:
            entry = Path(row['root']) / name
            if not entry.is_symlink() and not entry.is_dir():
                raise EntryError('unsupported_skill_entry_no_changes')
            guide = entry / 'SKILL.md'
            if not guide.is_file():
                raise EntryError('unidentified_skill_entry_no_changes')
            header = guide.read_text().split('---', 2)
            declared = re.search(r'^name:\s*[\"\']?([a-z0-9-]+)[\"\']?\s*$', header[1], re.M) if len(header) == 3 else None
            if not declared or declared.group(1) != name:
                raise EntryError('skill_identity_mismatch_no_changes')
            if entry.is_symlink():
                resolved_path = entry.resolve()
                points_into_relocating = any(
                    resolved_path == rel_dir or resolved_path.is_relative_to(rel_dir)
                    for rel_dir in relocating_dirs
                )
                if not points_into_relocating and (str(entry), str(resolved_path)) in archived_live_links:
                    dedups.append({'original': str(entry), 'original_link': os.readlink(entry), 'target': str(resolved_path)})
                    continue
            destination = storage / row['client'].replace('/', '-') / name
            if existing(destination):
                if str(destination) not in managed:
                    raise EntryError('execution_destination_conflict_no_changes')
                destination = destination.with_name(name + '-' + uuid.uuid4().hex[:12])
                if existing(destination):
                    raise EntryError('execution_destination_conflict_no_changes')
            moves.append({'original': str(entry), 'preserved': str(destination),
                          'original_link': os.readlink(entry) if entry.is_symlink() else None,
                          'target': str(entry.resolve()) if entry.is_symlink() else None})
    relocated = {Path(record['original']): Path(record['preserved'])
                 for record in moves if record['original_link'] is None}
    for record in moves:
        if record['target']:
            target = Path(record['target'])
            for original in sorted(relocated, key=lambda path: len(path.parts), reverse=True):
                if target.is_relative_to(original):
                    target = relocated[original] / target.relative_to(original)
                    break
            record['archive_target'] = str(target)
    storage.mkdir(parents=True, exist_ok=True, mode=0o700)
    storage.chmod(0o700)
    migrated = []
    deduplicated = []
    created = []
    pruned = 0
    try:
        for record in dedups:
            Path(record['original']).unlink()
            deduplicated.append(record)
        for record in moves:
            entry, destination = Path(record['original']), Path(record['preserved'])
            destination.parent.mkdir(parents=True, exist_ok=True)
            entry.rename(destination)
            migrated.append(record)
            if record['target']:
                # Resolve every link before moving its shared source. Replace
                # atomically so a failed rewrite still has its original link.
                temporary = destination.with_name('.link-' + uuid.uuid4().hex)
                try:
                    temporary.symlink_to(record['archive_target'], target_is_directory=True)
                    temporary.replace(destination)
                finally:
                    temporary.unlink(missing_ok=True)
        if any(not (Path(record['preserved']) / 'SKILL.md').is_file() for record in migrated):
            raise EntryError('archived_source_unreadable')
        if create_lookup:
            antigravity_shared = (
                any(r['client'] == '.gemini/config' and r['lookup'] == 'ready' for r in rows)
                or (home / '.gemini/config/skills/lookup').exists()
            )
            for row in rows:
                if row['client'] == '.codex' and (
                    any(r['client'] == '.agents' and r['lookup'] == 'ready' for r in rows)
                    or (home / '.agents/skills/lookup').exists()
                ):
                    continue
                if row['client'] in ('.gemini/antigravity', '.gemini/antigravity-cli') and antigravity_shared:
                    continue
                if row['lookup'] == 'missing':
                    entry = Path(row['root']) / 'lookup'
                    entry.parent.mkdir(parents=True, exist_ok=True)
                    entry.symlink_to(lookup, target_is_directory=True)
                    created.append(entry)
        pruned = _prune_dangling(receipt)
        receipt['entries'].extend(migrated)
        with tempfile.NamedTemporaryFile(mode='w', dir=storage, prefix='entries-', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n')
        try:
            temporary.replace(receipt_path)
        finally:
            temporary.unlink(missing_ok=True)
    except BaseException:
        for entry in reversed(created):
            if entry.is_symlink() and entry.resolve() == lookup:
                entry.unlink()
        for record in reversed(migrated):
            entry, destination = Path(record['original']), Path(record['preserved'])
            if record['original_link'] is not None:
                entry.symlink_to(record['original_link'], target_is_directory=True)
                destination.unlink(missing_ok=True)
            else:
                shutil.move(str(destination), str(entry))
        for record in reversed(deduplicated):
            entry = Path(record['original'])
            if not existing(entry):
                entry.symlink_to(record['original_link'], target_is_directory=True)
        raise
    return {'migrated': len(migrated), 'deduplicated': len(deduplicated), 'pruned': pruned,
            'lookup_created': len(created), 'receipt': str(receipt_path), 'clients': inventory(home, lookup)}


def is_clean(rows):
    shared_ready = any(r['client'] == '.agents' and r['lookup'] == 'ready' for r in rows)
    antigravity_shared = any(r['client'] == '.gemini/config' and r['lookup'] == 'ready' for r in rows)
    return bool(rows) and all(
        not row['competing'] and (
            row['lookup'] == 'ready'
            or (row['client'] == '.codex' and row['lookup'] == 'missing' and shared_ready)
            or (row['client'] in ('.gemini/antigravity', '.gemini/antigravity-cli')
                and row['lookup'] == 'missing' and antigravity_shared)
        ) for row in rows
    )


def watch_paths_for(home):
    home = home.resolve()
    paths = []
    for client in CLIENTS:
        skills_dir = home / client / 'skills'
        client_dir = home / client
        if skills_dir.is_dir():
            paths.append(str(skills_dir))
        elif client_dir.is_dir():
            paths.append(str(client_dir))
    ego_dir = home / '.local/share/ego'
    if ego_dir.exists() or (home / '.local/share').is_dir():
        paths.append(str(ego_dir))
    return list(dict.fromkeys(paths))


def install_guard(home, lookup, *, load=True):
    import plistlib
    import subprocess
    home, lookup = home.resolve(), lookup.resolve()
    if not (lookup / 'SKILL.md').is_file():
        raise EntryError('lookup_source_missing')
    guard_dir = home / '.local/share/lookup/entry-guard'
    state_dir = home / '.local/state/lookup'
    guard_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    label = 'com.lookup.技能入口守卫'
    script_path = guard_dir / 'lookup-技能入口守卫'
    plist_src = guard_dir / f'{label}.plist'
    log_path = state_dir / 'entry-guard.log'
    err_path = state_dir / 'entry-guard.err.log'
    python_bin = Path(sys.executable).resolve()
    script_body = (
        '#!/bin/zsh\n'
        'set -euo pipefail\n'
        f'LOOKUP_ROOT={json.dumps(str(lookup))}\n'
        f'LOG_FILE={json.dumps(str(log_path))}\n'
        'mkdir -p "$(dirname "$LOG_FILE")"\n'
        f'out=$({json.dumps(str(python_bin))} -B "$LOOKUP_ROOT/scripts/entrypoints.py" guard --lookup-root "$LOOKUP_ROOT" --quiet 2>&1) || {{\n'
        '  rc=$?\n'
        '  printf \'[%s] ERROR rc=%s %s\\n\' "$(TZ=Asia/Shanghai date \'+%Y-%m-%d %H:%M:%S\')" "$rc" "$out" >> "$LOG_FILE"\n'
        '  exit "$rc"\n'
        '}\n'
        'if [[ -n "$out" ]]; then\n'
        '  printf \'[%s] CLEANED %s\\n\' "$(TZ=Asia/Shanghai date \'+%Y-%m-%d %H:%M:%S\')" "$(printf \'%s\' "$out" | tr \'\\n\' \' \')" >> "$LOG_FILE"\n'
        'fi\n'
    )
    script_path.write_text(script_body, encoding='utf-8')
    script_path.chmod(0o755)
    watch = watch_paths_for(home)
    plist_data = {
        'Label': label,
        'ProgramArguments': [str(script_path)],
        'RunAtLoad': True,
        'ThrottleInterval': 5,
        'WatchPaths': watch,
        'StandardErrorPath': str(err_path),
    }
    plist_src.write_bytes(plistlib.dumps(plist_data))
    plist_src.chmod(0o644)
    launch_link = home / 'Library/LaunchAgents' / f'{label}.plist'
    loaded = False
    if sys.platform == 'darwin':
        launch_link.parent.mkdir(parents=True, exist_ok=True)
        if launch_link.is_symlink() or launch_link.exists():
            launch_link.unlink()
        launch_link.symlink_to(plist_src)
        if load:
            uid = str(os.getuid())
            subprocess.run(['launchctl', 'bootout', f'gui/{uid}/{label}'],
                           capture_output=True, check=False)
            res = subprocess.run(['launchctl', 'bootstrap', f'gui/{uid}', str(launch_link)],
                                 capture_output=True, text=True, check=False)
            if res.returncode != 0:
                raise EntryError(f'launchctl_bootstrap_failed: {res.stderr.strip()}')
            loaded = True
    return {'ok': True, 'label': label, 'script': str(script_path),
            'plist': str(plist_src), 'launch_agent': str(launch_link),
            'watch_paths': watch, 'loaded': loaded}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('audit', 'apply', 'guard', 'install-guard'))
    parser.add_argument('--home', type=Path, default=Path.home())
    parser.add_argument('--lookup-root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--quiet', action='store_true', help='Suppress output when guard makes no changes')
    parser.add_argument('--no-load', action='store_true', help='Generate guard files without launchctl bootstrap')
    args = parser.parse_args(argv)
    home, lookup = args.home.resolve(), args.lookup_root.resolve()
    if not home.is_dir() or not (lookup / 'SKILL.md').is_file():
        parser.error('existing HOME and lookup source are required')
    storage = home / '.local/share/lookup/execution-skills'
    try:
        if args.action == 'apply':
            result = migrate(home, lookup, storage, create_lookup=True)
        elif args.action == 'guard':
            rows = inventory(home, lookup)
            if not any(row['competing'] for row in rows):
                result = {'ok': True, 'changed': False, 'migrated': 0, 'deduplicated': 0, 'pruned': 0, 'lookup_created': 0}
                if not args.quiet:
                    print(json.dumps(result, ensure_ascii=False, indent=2))
                return 0
            try:
                migrated = migrate(home, lookup, storage, create_lookup=False)
            except EntryError as error:
                if str(error) == 'migration_in_progress_no_changes':
                    return 0
                raise
            changed = bool(migrated['migrated'] or migrated['deduplicated'] or migrated['pruned'])
            result = {'ok': True, 'changed': changed, **migrated}
            if changed or not args.quiet:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        elif args.action == 'install-guard':
            result = install_guard(home, lookup, load=not args.no_load)
        else:
            rows = inventory(home, lookup)
            result = {'clients': rows, 'ok': is_clean(rows)}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get('ok', True) else 3
    except (EntryError, OSError, ValueError) as error:
        print(json.dumps({'ok': False, 'error': str(error)}), file=sys.stderr)
        return 78


if __name__ == '__main__':
    raise SystemExit(main())
