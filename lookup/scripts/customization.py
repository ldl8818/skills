"""Offline, hash-bound customization review. Semantic decisions belong to the host Agent."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


class ReviewError(ValueError):
    pass


IGNORED = {'.git', '__pycache__', 'node_modules', '.DS_Store'}


def files(root):
    root = Path(root)
    if root.is_symlink():
        raise ReviewError('CUSTOMIZATION_SYMLINK_REQUIRES_REVIEW')
    result = {}
    if not root.exists():
        return result
    if not root.is_dir():
        raise ReviewError('CUSTOMIZATION_DIRECTORY_REQUIRED')
    for directory, directories, names in os.walk(root, followlinks=False):
        directories[:] = sorted(d for d in directories if d not in IGNORED)
        for name in directories + sorted(names):
            path = Path(directory) / name
            relative = path.relative_to(root)
            if name in IGNORED or path.suffix == '.pyc':
                continue
            if (name == '.env' or name.startswith('.env.')) and not name.endswith('.example'):
                continue
            if path.is_symlink():
                raise ReviewError('CUSTOMIZATION_SYMLINK_REQUIRES_REVIEW:' + str(relative))
            if path.is_file():
                result[relative.as_posix()] = {
                    'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                    'mode': path.stat().st_mode & 0o777,
                }
    return result


def fingerprint(root):
    return hashlib.sha256(json.dumps(files(root), sort_keys=True).encode()).hexdigest()


def copy_source(source, destination):
    """Copy only audited source files, never dependency trees, links or caches."""
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    for name, entry in files(source).items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(Path(source) / name, target)
        target.chmod(entry['mode'])


def replace_source(source, destination):
    """Apply an approved complete tree, keeping ignored runtime artifacts outside its scope."""
    source, destination = Path(source), Path(destination)
    incoming, current = files(source), files(destination)
    for name in current.keys() - incoming.keys():
        (destination / name).unlink()
    copy_source(source, destination)
    if files(destination) != incoming:
        raise ReviewError('CUSTOMIZATION_APPLY_FAILED')


def differences(base, local):
    return [name for name in sorted(base.keys() | local.keys()) if base.get(name) != local.get(name)]


def validate_skill_routing(source, merged):
    original = Path(source).read_text()
    if Path(merged).is_file() and Path(merged).read_text() == original:
        return
    if not original.startswith('---\n'):
        return  # Non-Skill fixture or plain supporting document.
    candidates = [Path(__file__).resolve().parents[2] / 'skill-manager/scripts',
                  Path.home() / '.agents/skills/skill-manager/scripts']
    scripts = next((p for p in candidates if (p / 'audit_upstream.py').is_file()), None)
    if scripts is None:
        raise ReviewError('SKILL_ROUTING_VALIDATOR_UNAVAILABLE')
    program = '''import json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import audit_upstream as a
original=Path(sys.argv[2]).read_text()
merged=Path(sys.argv[3]).read_text() if Path(sys.argv[3]).is_file() else ''
errors=a.routing_field_errors(merged,a.routing_field_blocks(original))
print(json.dumps(errors))
raise SystemExit(bool(errors))'''
    result = subprocess.run([sys.executable, '-c', program, str(scripts), str(source), str(merged)],
                            capture_output=True, text=True, timeout=15)
    if result.returncode:
        raise ReviewError('UPSTREAM_SKILL_ROUTING_FIELDS_CHANGED')


def create(store, dependency, target, scopes):
    """scopes: name/live/base/upstream; base=None means provenance still needs recovery."""
    root = Path(tempfile.mkdtemp(prefix=dependency + '-review-', dir=store.root))
    records = []
    try:
        for index, scope in enumerate(scopes):
            area = root / str(index)
            for label in ('local', 'base', 'upstream', 'merged'):
                (area / label).mkdir(parents=True)
            copy_source(scope.get('local', scope['live']), area / 'local')
            if scope.get('base') is not None:
                copy_source(scope['base'], area / 'base')
            if scope.get('upstream') is not None:
                copy_source(scope['upstream'], area / 'upstream')
                copy_source(scope['upstream'], area / 'merged')
            if scope.get('observed') is not None:
                copy_source(scope['observed'], area / 'observed-after-install')
            base, local = files(area / 'base'), files(area / 'local')
            custom = differences(base, local)
            # Local additions are retained in the draft. Modified/deleted files
            # still require semantic reconciliation; a clean textual merge is
            # only a draft and never seals a review.
            for name in local.keys() - base.keys():
                target_path = area / 'merged' / name
                if not target_path.exists():
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(area / 'local' / name, target_path)
            records.append({'name': scope['name'], 'live': str(Path(scope['live']).absolute()),
                            'live_state': files(scope['live']),
                            'base_known': scope.get('base') is not None,
                            'upstream_known': scope.get('upstream') is not None,
                            'local': local, 'base': base, 'upstream': files(area / 'upstream'),
                            'customizations': custom})
            if scope.get('observed') is not None:
                records[-1]['observed-after-install'] = files(area / 'observed-after-install')
        request = {'schema': 1, 'dependency': dependency, 'target': target, 'scopes': records,
                   'status': 'needs_review'}
        (root / 'request.json').write_text(json.dumps(request, ensure_ascii=False, indent=2) + '\n')
        store.write('review-' + dependency + '.json', {'directory': str(root)})
        return root
    except BaseException:
        shutil.rmtree(root)
        raise


def load(store, dependency):
    path = store.read('review-' + dependency + '.json').get('directory')
    if not path:
        raise ReviewError('CUSTOMIZATION_REVIEW_MISSING')
    root = Path(path)
    if root.is_symlink() or root.parent.resolve() != store.root.resolve():
        raise ReviewError('CUSTOMIZATION_REVIEW_PATH_REJECTED')
    request = json.loads((root / 'request.json').read_text())
    if request.get('schema') != 1 or request.get('dependency') != dependency:
        raise ReviewError('CUSTOMIZATION_REVIEW_INVALID')
    return root, request


def assert_inputs(root, request, check_live=True):
    for index, scope in enumerate(request['scopes']):
        area = root / str(index)
        for label in ('base', 'local', 'upstream'):
            if files(area / label) != scope[label]:
                raise ReviewError('CUSTOMIZATION_REVIEW_INPUT_CHANGED')
        if ('observed-after-install' in scope and
                files(area / 'observed-after-install') != scope['observed-after-install']):
            raise ReviewError('CUSTOMIZATION_REVIEW_INPUT_CHANGED')
        if check_live and files(scope['live']) != scope['live_state']:
            raise ReviewError('CUSTOMIZATION_CHANGED_DURING_REVIEW')


def accept(store, dependency, decision_file):
    root, request = load(store, dependency)
    assert_inputs(root, request)
    decision = json.loads(Path(decision_file).read_text())
    if decision.get('target') != request['target']:
        raise ReviewError('CUSTOMIZATION_REVIEW_TARGET_CHANGED')
    expected = {(scope['name'], name) for scope in request['scopes'] for name in scope['customizations']}
    items = decision.get('decisions', [])
    keys = [(item.get('scope'), item.get('path')) for item in items]
    if len(keys) != len(set(keys)) or set(keys) != expected:
        raise ReviewError('CUSTOMIZATION_REVIEW_INCOMPLETE')
    for item in items:
        if (item.get('disposition') not in ('absorbed', 'preserved')
                or not isinstance(item.get('reason'), str) or not item['reason'].strip()
                or not isinstance(item.get('evidence'), str) or not item['evidence'].strip()
                or not isinstance(item.get('validation'), str) or not item['validation'].strip()):
            raise ReviewError('CUSTOMIZATION_DECISION_EVIDENCE_REQUIRED')
        index = next(i for i, s in enumerate(request['scopes']) if s['name'] == item['scope'])
        area = root / str(index)
        merged = files(area / 'merged')
        upstream = request['scopes'][index]['upstream']
        if item['disposition'] == 'absorbed' and merged.get(item['path']) != upstream.get(item['path']):
            raise ReviewError('ABSORBED_CUSTOMIZATION_MUST_USE_UPSTREAM')
    # Every adaptation to the new upstream also needs a decision, including
    # cross-file fixes made while resolving a customization.
    adaptations = decision.get('adaptations', [])
    actual = {(s['name'], name) for i, s in enumerate(request['scopes'])
              for name in differences(s['upstream'], files(root / str(i) / 'merged'))}
    adaptation_keys = [(a.get('scope'), a.get('path')) for a in adaptations]
    if (len(adaptation_keys) != len(set(adaptation_keys)) or set(adaptation_keys) != actual
            or any(not isinstance(a.get('reason'), str) or not a['reason'].strip() for a in adaptations)):
        raise ReviewError('CUSTOMIZATION_ADAPTATIONS_INCOMPLETE')
    for index, scope in enumerate(request['scopes']):
        area = root / str(index)
        for name in scope['upstream']:
            if Path(name).name == 'SKILL.md':
                validate_skill_routing(area / 'upstream' / name, area / 'merged' / name)
    receipt = {'target': request['target'], 'decisions': items, 'adaptations': adaptations,
               'merged': [files(root / str(i) / 'merged') for i in range(len(request['scopes']))]}
    # Unknown baselines cannot be converted to known by an approval flag.
    if any(not s['base_known'] for s in request['scopes']):
        raise ReviewError('CUSTOMIZATION_BASELINE_UNKNOWN')
    if any(not s['upstream_known'] for s in request['scopes']):
        raise ReviewError('CUSTOMIZATION_NEW_SOURCE_UNKNOWN')
    (root / 'accepted.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n')
    return {'status': 'reviewed', 'dependency': dependency, 'directory': str(root)}


def recover_baseline(store, dependency, scope_name, source, provenance, label='base'):
    """The host recovers a missing *original* source; never bless local as upstream."""
    if not provenance.startswith('https://'):
        raise ReviewError('CUSTOMIZATION_BASELINE_PROVENANCE_REQUIRED')
    root, request = load(store, dependency)
    assert_inputs(root, request)
    index = next((i for i, s in enumerate(request['scopes']) if s['name'] == scope_name), None)
    known = 'base_known' if label == 'base' else 'upstream_known'
    if label not in ('base', 'upstream') or index is None or request['scopes'][index][known]:
        raise ReviewError('CUSTOMIZATION_BASELINE_RECOVERY_NOT_APPLICABLE')
    if not files(source):
        raise ReviewError('CUSTOMIZATION_BASELINE_EMPTY')
    area = root / str(index)
    copy_source(source, area / label)
    scope = request['scopes'][index]
    scope[label] = files(area / label)
    scope[known] = True
    scope[label + '_provenance'] = {'url': provenance, 'fingerprint': fingerprint(area / label)}
    if label == 'base':
        scope['customizations'] = differences(scope['base'], scope['local'])
    else:
        replace_source(area / 'upstream', area / 'merged')
    (root / 'request.json').write_text(json.dumps(request, ensure_ascii=False, indent=2) + '\n')
    return {'status': 'baseline_recovered', 'scope': scope_name, 'directory': str(root)}


def restart(store, dependency):
    """Re-snapshot changed local inputs without discarding any prior evidence."""
    root, request = load(store, dependency)
    assert_inputs(root, request, check_live=False)
    scopes = []
    for index, scope in enumerate(request['scopes']):
        area = root / str(index)
        item = {'name': scope['name'], 'live': scope['live'],
                'base': area / 'base' if scope['base_known'] else None,
                'upstream': area / 'upstream' if scope['upstream_known'] else None}
        if 'observed-after-install' in scope:
            item['observed'] = area / 'observed-after-install'
        if scope['name'] == 'clis' and dependency == 'opencli':
            # A clis scope is an effective overlay, while live contains only
            # shadow files. Reconstruct it from the original built-in tree.
            with tempfile.TemporaryDirectory(prefix='lookup-overlay-replan-') as temporary:
                effective = Path(temporary)
                copy_source(area / 'base', effective)
                copy_source(scope['live'], effective)
                # Persist the new effective source until create has consumed it.
                item['local'] = root / 'replanned-overlay'
                replace_source(effective, item['local'])
        scopes.append(item)
    new_root = create(store, dependency, request['target'], scopes)
    return {'status': 'replanned', 'dependency': dependency, 'directory': str(new_root),
            'request': str(new_root / 'request.json'), 'previous_review': str(root)}


def approved(store, dependency, target, check_live=True):
    root, request = load(store, dependency)
    assert_inputs(root, request, check_live=check_live)
    if request['target'] != target:
        raise ReviewError('CUSTOMIZATION_REVIEW_TARGET_CHANGED')
    receipt = json.loads((root / 'accepted.json').read_text())
    if receipt.get('target') != target or receipt.get('merged') != [
            files(root / str(i) / 'merged') for i in range(len(request['scopes']))]:
        raise ReviewError('CUSTOMIZATION_APPROVED_RESULT_CHANGED')
    return root, request, receipt


def pending(store, dependency):
    root, request = load(store, dependency)
    return {'status': 'manual_review', 'dependency': dependency, 'reason': 'CUSTOMIZATION_REVIEW_REQUIRED',
            'directory': str(root), 'request': str(root / 'request.json'),
            'target': request['target'], 'current_preserved': True}
