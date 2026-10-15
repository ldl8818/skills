#!/usr/bin/env python3
"""Verify complete upstream file coverage and explicitly recorded local adaptations."""
import argparse
import difflib
import hashlib
import json
import posixpath
from pathlib import Path
import re
import subprocess

import core

RECEIPT = 'upstream-merge.json'
ROUTING_FIELDS = ('description', 'when_to_use', 'dispatch_intent')


def routing_field_blocks(text):
    """Read original top-level YAML blocks without reserializing their text."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != '---':
        raise ValueError('upstream routing: missing frontmatter')
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == '---'), None)
    if end is None:
        raise ValueError('upstream routing: unclosed frontmatter')
    result = {}
    for key in ROUTING_FIELDS:
        starts = [i for i in range(1, end) if lines[i].startswith(key + ':')]
        if len(starts) > 1:
            raise ValueError('upstream routing: duplicate ' + key)
        if starts:
            start = starts[0]
            stop = start + 1
            while stop < end and (not lines[stop].strip() or lines[stop].startswith((' ', '\t'))):
                stop += 1
            result[key] = ''.join(lines[start:stop])
    return result


def routing_field_errors(local_text, source_fields):
    """Require verbatim description and insertion-only, ordered trigger additions."""
    if (not isinstance(source_fields, dict) or 'description' not in source_fields or
            set(source_fields) - set(ROUTING_FIELDS) or
            any(not isinstance(value, str) for value in source_fields.values())):
        return ['upstream routing: missing or invalid original field contract']
    try:
        local = routing_field_blocks(local_text)
        if routing_field_blocks('---\n' + ''.join(source_fields.values()) + '---\n') != source_fields:
            return ['upstream routing: invalid original field blocks']
    except ValueError as error:
        return [str(error)]
    errors = []
    for key, original in source_fields.items():
        current = local.get(key, '')
        if key == 'description':
            valid = current == original
        else:
            # Keep all original characters, including separators and their spacing.
            chars = iter(current)
            unchanged = all(char in chars for char in original)
            def items(block):
                value = core.parse_frontmatter('---\n' + block + '---\n').get(key, '')
                return [item.strip() for item in value.split(',')]
            remaining = iter(items(current))
            # An added qualifier attached to an original item is a rewrite.
            valid = unchanged and all(item in remaining for item in items(original))
        if not valid:
            errors.append('upstream routing: ' + key + ' must retain the complete original field; only separate trigger/intent items may be inserted')
    return errors


def digest(data):
    return hashlib.sha256(data).hexdigest()


def headings(data):
    return set(re.findall(r'^#{1,6} .+$', data.decode('utf-8'), re.M))


def local_files(root):
    files = {}
    for path in sorted(root.rglob('*')):
        if any(part in core.FP_IGNORE_DIRS for part in path.relative_to(root).parts) or path.suffix == '.pyc' or path.name == '.DS_Store':
            continue
        if path.is_symlink():
            raise ValueError('symlink in Skill source: ' + str(path.relative_to(root)))
        if path.is_file() and path != root / RECEIPT:
            name = path.relative_to(root).as_posix()
            name = 'SKILL.md' if name == 'SKILL.md.disabled' else name
            if name in files:
                raise ValueError('duplicate enabled and disabled Skill entry')
            files[name] = path.read_bytes()
    return files


def changes(upstream, local):
    before = upstream.decode('utf-8').splitlines(keepends=True)
    after = local.decode('utf-8').splitlines(keepends=True)
    return [dict(upstream_lines=[a, b], local_lines=[c, d],
                 removed_sha256=digest(''.join(before[a:b]).encode()),
                 added_sha256=digest(''.join(after[c:d]).encode()))
            for tag, a, b, c, d in difflib.SequenceMatcher(
                None, before, after, autojunk=False).get_opcodes() if tag != 'equal']


def make_receipt(root, source, info, adaptations):
    """No upstream file may disappear; every altered file needs an explicit reason."""
    current = local_files(root)
    if not source:
        raise ValueError('empty upstream snapshot')
    locations = {name: adaptations.get(name, {}).get('local_path', name)
                 if isinstance(adaptations.get(name), dict) else name for name in source}
    if len(set(locations.values())) != len(locations):
        raise ValueError('upstream files cannot share one local destination')
    missing = sorted(name for name, target in locations.items() if target not in current)
    if missing:
        raise ValueError('missing upstream files: ' + ', '.join(missing))
    entries = {}
    for name, data in source.items():
        target = locations[name]
        same = data == current[target] and name == target
        adaptation = adaptations.get(name)
        reason = adaptation.get('reason') if isinstance(adaptation, dict) else adaptation
        if not same and not reason:
            raise ValueError('unexplained upstream adaptation: ' + name)
        entries[name] = dict(upstream_sha256=digest(data), local_sha256=digest(current[target]),
                             status='identical' if same else 'adapted')
        if name == 'SKILL.md':
            fields = routing_field_blocks(data.decode('utf-8'))
            errors = routing_field_errors(current[target].decode('utf-8'), fields)
            if errors:
                raise ValueError('; '.join(errors))
            entries[name]['upstream_fields'] = fields
        if target != name:
            entries[name]['local_path'] = target
        if not same:
            entries[name].update(reason=reason, changes=changes(data, current[target]))
        if name.endswith('.md'):
            source_headings, local_headings = headings(data), headings(current[target])
            mapping = adaptation.get('heading_map', {}) if isinstance(adaptation, dict) else {}
            sections = {heading: mapping.get(heading, heading) for heading in sorted(source_headings)}
            if not set(sections.values()) <= local_headings or len(set(sections.values())) != len(sections):
                raise ValueError('missing upstream sections; retain each section or explicitly map its renamed heading: ' + name)
            entries[name]['sections'] = sections
    return dict(schema=2, **info, files=entries,
                local_only={name: digest(data) for name, data in current.items() if name not in locations.values()})


def verify(root, receipt, source=None):
    errors = []
    if not isinstance(receipt, dict) or receipt.get('schema') != 2 or not receipt.get('files'):
        return ['missing current upstream coverage/field receipt; reconcile against the verified source snapshot']
    if not re.fullmatch('[0-9a-f]{40}', receipt.get('commit', '')):
        return ['invalid upstream commit']
    current = local_files(root)
    entries = receipt['files']
    local_only = receipt.get('local_only', {})
    if not isinstance(entries, dict) or not isinstance(local_only, dict) or any(
            not isinstance(entry, dict) for entry in entries.values()):
        return ['invalid upstream coverage inventory']
    locations = {name: entry.get('local_path', name) for name, entry in entries.items()}
    if len(set(locations.values())) != len(locations):
        errors.append('multiple upstream files map to one local file')
    if set(locations.values()) & set(local_only):
        errors.append('overlapping upstream and local-only inventory')
    if set(current) != set(locations.values()) | set(local_only):
        errors.append('current file inventory differs from the merge receipt')
    for name, entry in entries.items():
        data = current.get(locations[name])
        if data is None or digest(data) != entry.get('local_sha256'):
            errors.append(name + ': missing or changed since the recorded merge')
        if name == 'SKILL.md' and data is not None:
            errors.extend(routing_field_errors(data.decode('utf-8'), entry.get('upstream_fields')))
        if name.endswith('.md') and (not isinstance(entry.get('sections'), dict) or (
                data is not None and not set(entry['sections'].values()) <= headings(data))):
            errors.append(name + ': upstream section accounting is missing or incomplete')
        if entry.get('status') == 'identical':
            if entry.get('local_sha256') != entry.get('upstream_sha256'):
                errors.append(name + ': false identical status')
        elif entry.get('status') != 'adapted' or not entry.get('reason') or (
                not entry.get('changes') and locations[name] == name):
            errors.append(name + ': unexplained adaptation')
    for name, expected in local_only.items():
        if name not in current or digest(current[name]) != expected:
            errors.append(name + ': local capability missing or changed')
    if source is not None:
        if set(source) != set(entries):
            errors.append('upstream snapshot inventory differs from the merge receipt')
        for name, data in source.items():
            entry = entries.get(name, {})
            if digest(data) != entry.get('upstream_sha256'):
                errors.append(name + ': upstream source hash differs')
            if name == 'SKILL.md' and entry.get('upstream_fields') != routing_field_blocks(data.decode('utf-8')):
                errors.append(name + ': original routing fields differ from the source snapshot')
            if name.endswith('.md') and set(entry.get('sections', {})) != headings(data):
                errors.append(name + ': source section inventory differs')
            target = locations.get(name, name)
            if target in current and entry.get('status') == 'adapted':
                if changes(data, current[target]) != entry.get('changes'):
                    errors.append(name + ': adaptation ranges differ')
    entry = root / 'SKILL.md'
    if not entry.exists():
        entry = root / 'SKILL.md.disabled'
    meta = core.parse_skill_md(str(entry))
    if meta.get('github_hash') != receipt['commit']:
        errors.append('SKILL.md source commit differs from the merge receipt')
    return errors


def git_snapshot(upstream, source_path):
    def git(*args):
        return subprocess.check_output(['git', '-C', str(upstream), *args])
    commit = git('rev-parse', 'HEAD').decode().strip()
    names = git('ls-tree', '-r', '--name-only', commit, '--', source_path).decode().splitlines()
    prefix = '' if source_path in ('.', '') else source_path.rstrip('/') + '/'
    if not names or any(not name.startswith(prefix) for name in names):
        raise ValueError('invalid upstream Skill path')
    def read_blob(name, seen=()):
        if name in seen or len(seen) >= 32:
            raise ValueError('cyclic upstream symlink: ' + name)
        rows = git('ls-tree', commit, '--', name).decode().splitlines()
        if len(rows) != 1:
            raise ValueError('missing upstream link target: ' + name)
        mode = rows[0].split()[0]
        data = git('show', commit + ':' + name)
        if mode == '120000':
            target = data.decode('utf-8')
            linked = posixpath.normpath(posixpath.join(posixpath.dirname(name), target))
            if target.startswith('/') or linked.startswith('../') or (prefix and not linked.startswith(prefix)):
                raise ValueError('escaping upstream symlink: ' + name)
            return read_blob(linked, (*seen, name))
        if mode not in ('100644', '100755'):
            raise ValueError('nonregular upstream entry: ' + name)
        return data
    files = {name[len(prefix):]: read_blob(name) for name in names}
    return commit, files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--upstream', type=Path, help='Git checkout at the candidate HEAD; no network calls')
    parser.add_argument('--skill', action='append', help='Skill name; default is GitHub-derived frozen Skills, filtered by the supplied upstream repository')
    parser.add_argument('--record', action='store_true', help='Write a receipt after complete reconciliation')
    parser.add_argument('--adaptations', type=Path, help='JSON map of skill/path to adaptation reasons')
    args = parser.parse_args()
    if args.record and (not args.upstream or not args.adaptations):
        parser.error('--record requires --upstream and --adaptations')
    names = args.skill or [path.parent.name for path in sorted(args.repo.glob('*/SKILL.md'))
                          if core.parse_skill_md(str(path)).get('github_url') and
                          core.parse_skill_md(str(path)).get('update_policy') == 'frozen']
    if args.upstream and not args.skill:
        remote = subprocess.check_output(['git', '-C', str(args.upstream), 'remote', 'get-url', 'origin'], text=True).strip()
        def repository_key(url):
            return url.rstrip('/').removesuffix('.git').lower()
        names = [name for name in names if repository_key(core.parse_skill_md(
            str(args.repo / name / 'SKILL.md')).get('github_url', '')) == repository_key(remote)]
    if not names:
        parser.error('no GitHub-derived frozen Skills found; specify --skill for another target')
    reasons = json.loads(args.adaptations.read_text()) if args.adaptations else {}
    failed = False
    for name in names:
        try:
            if not core.safe_component(name):
                raise ValueError('invalid Skill name')
            root = args.repo.resolve() / name
            if root.is_symlink():
                raise ValueError('use the canonical source directory')
            meta = core.parse_skill_md(str(root / 'SKILL.md'))
            source_path = meta.get('github_path', 'skills/' + name)
            commit, source = git_snapshot(args.upstream, source_path) if args.upstream else (None, None)
            path = root / RECEIPT
            if args.record:
                if commit != meta.get('github_hash'):
                    raise ValueError('candidate HEAD differs from SKILL.md merge base')
                info = dict(repository=meta.get('github_url'), commit=commit, source_path=source_path)
                local_reasons = {key[len(name) + 1:]: value for key, value in reasons.items()
                                 if key.startswith(name + '/')}
                receipt = make_receipt(root, source, info, local_reasons)
                core.write_json(str(path), receipt)
            else:
                receipt = json.loads(path.read_text())
            if commit and commit != receipt.get('commit'):
                raise ValueError('candidate HEAD differs from the recorded upstream snapshot')
            errors = verify(root, receipt, source)
            if errors:
                raise ValueError('; '.join(errors))
            counts = {status: sum(e['status'] == status for e in receipt['files'].values())
                      for status in ('identical', 'adapted')}
            print(f'{name}: PASS {receipt["commit"][:12]} upstream={len(receipt["files"])} '
                  f'identical={counts["identical"]} adapted={counts["adapted"]} '
                  f'local-only={len(receipt["local_only"])} '
                  f'({"source snapshot verified" if source is not None else "offline receipt; latest not checked"})')
        except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as error:
            print(f'{name}: FAIL {error}')
            failed = True
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
