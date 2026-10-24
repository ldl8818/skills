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


def migrate(home, lookup, storage):
    # All callers for this HOME share an inode lock, including maintenance and
    # direct CLI invocations. A crash releases it without a stale lock file.
    fd = os.open(home, os.O_RDONLY)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise EntryError('migration_in_progress_no_changes') from error
        return _migrate(home, lookup, storage)
    finally:
        os.close(fd)


def _migrate(home, lookup, storage):
    relative_storage = storage.relative_to(home)
    home, lookup = home.resolve(), lookup.resolve()
    storage = home / relative_storage
    if not (lookup / 'SKILL.md').is_file():
        raise EntryError('lookup_source_missing')
    rows = inventory(home, lookup)
    if not rows:
        rows = [{'client': '.agents', 'root': str(home / '.agents/skills'),
                 'competing': [], 'lookup': 'missing'}]
    if any(row['lookup'] == 'conflict' for row in rows):
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
    moves = []
    for row in rows:
        for name in row['competing']:
            entry = Path(row['root']) / name
            destination = storage / row['client'].replace('/', '-') / name
            if existing(destination):
                if str(destination) not in managed:
                    raise EntryError('execution_destination_conflict_no_changes')
                destination = destination.with_name(name + '-' + uuid.uuid4().hex[:12])
                if existing(destination):
                    raise EntryError('execution_destination_conflict_no_changes')
            if not entry.is_symlink() and not entry.is_dir():
                raise EntryError('unsupported_skill_entry_no_changes')
            guide = entry / 'SKILL.md'
            if not guide.is_file():
                raise EntryError('unidentified_skill_entry_no_changes')
            header = guide.read_text().split('---', 2)
            declared = re.search(r'^name:\s*[\"\']?([a-z0-9-]+)[\"\']?\s*$', header[1], re.M) if len(header) == 3 else None
            if not declared or declared.group(1) != name:
                raise EntryError('skill_identity_mismatch_no_changes')
            moves.append((entry, destination))
    storage.mkdir(parents=True, exist_ok=True, mode=0o700)
    storage.chmod(0o700)
    migrated = []
    created = []
    try:
        for entry, destination in moves:
            destination.parent.mkdir(parents=True, exist_ok=True)
            original_link = os.readlink(entry) if entry.is_symlink() else None
            target = str(entry.resolve()) if entry.is_symlink() else None
            record = {'original': str(entry), 'preserved': str(destination),
                      'original_link': original_link, 'target': target}
            entry.rename(destination)
            migrated.append(record)
            if target:
                # Relative links would break after a plain rename.
                destination.unlink()
                destination.symlink_to(target, target_is_directory=True)
        for row in rows:
            if row['lookup'] == 'missing':
                entry = Path(row['root']) / 'lookup'
                entry.parent.mkdir(parents=True, exist_ok=True)
                entry.symlink_to(lookup, target_is_directory=True)
                created.append(entry)
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
        raise
    return {'migrated': len(migrated), 'lookup_created': len(created),
            'receipt': str(receipt_path), 'clients': inventory(home, lookup)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('audit', 'apply'))
    parser.add_argument('--home', type=Path, default=Path.home())
    parser.add_argument('--lookup-root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    home, lookup = args.home.resolve(), args.lookup_root.resolve()
    if not home.is_dir() or not (lookup / 'SKILL.md').is_file():
        parser.error('existing HOME and lookup source are required')
    storage = home / '.local/share/lookup/execution-skills'
    try:
        if args.action == 'apply':
            result = migrate(home, lookup, storage)
        else:
            rows = inventory(home, lookup)
            result = {'clients': rows, 'ok': bool(rows) and all(
                row['lookup'] == 'ready' and not row['competing'] for row in rows)}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get('ok', True) else 3
    except (EntryError, OSError, ValueError) as error:
        print(json.dumps({'ok': False, 'error': str(error)}), file=sys.stderr)
        return 78


if __name__ == '__main__':
    raise SystemExit(main())
