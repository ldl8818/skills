"""Customization preservation and host-reviewed merge lifecycle, without network or model calls."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/upstream.py'
spec = importlib.util.spec_from_file_location('lookup_customization_tests', SCRIPT)
upstream = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upstream)
review = upstream.customization


def write(root, name, content):
    path = Path(root) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='lookup-customization-test-')
        self.base = Path(self.temporary.name)
        self.store = upstream.Store(self.base / 'state/lookup/upstream')
        self.old = self.base / 'old'
        self.local = self.base / 'local'
        self.new = self.base / 'new'
        for tree in (self.old, self.local, self.new):
            tree.mkdir()
        write(self.old, 'absorbed.py', 'def value(): return "old"\n')
        write(self.old, 'preserved.py', 'def value(): return "base"\n')
        shutil.copytree(self.old, self.local, dirs_exist_ok=True)
        write(self.local, 'absorbed.py', 'def value(): return "upstream now supports custom A"\n')
        write(self.local, 'preserved.py', 'def value(): return "custom B"\n')
        write(self.new, 'absorbed.py', 'def value():\n    return "upstream now supports custom A"\n')
        write(self.new, 'preserved.py', 'def value(): return "new base"\n')
        write(self.new, 'added.py', 'NEW_UPSTREAM = True\n')

    def tearDown(self):
        self.temporary.cleanup()

    def prepare(self, base_known=True):
        return review.create(self.store, 'opencli', '2.0.3', [
            {'name': 'package', 'live': self.local, 'base': self.old if base_known else None,
             'upstream': self.new}])

    def decisions(self, root):
        shutil.copy2(self.local / 'preserved.py', root / '0/merged/preserved.py')
        value = {'target': '2.0.3', 'decisions': [
            {'scope': 'package', 'path': 'absorbed.py', 'disposition': 'absorbed',
             'reason': 'New upstream implements custom A with its own formatting.',
             'evidence': 'upstream/absorbed.py:value returns the same value as local.',
             'validation': 'Python invocation of value() returned the expected custom A result.'},
            {'scope': 'package', 'path': 'preserved.py', 'disposition': 'preserved',
             'reason': 'New upstream still lacks custom B.',
             'evidence': 'local/preserved.py implements B; upstream returns new base.',
             'validation': 'Python invocation of merged value() returned custom B.'},
        ], 'adaptations': [{'scope': 'package', 'path': 'preserved.py',
                            'reason': 'Keep custom B because it is absent upstream.'}]}
        path = self.base / 'decisions.json'
        path.write_text(json.dumps(value))
        return path, value

    def test_absorbed_uses_upstream_and_unsupported_customization_remains(self):
        root = self.prepare()
        decision, _ = self.decisions(root)
        review.accept(self.store, 'opencli', decision)
        approved_root, request, _ = review.approved(self.store, 'opencli', '2.0.3')
        merged = approved_root / '0/merged'
        self.assertEqual((merged/'absorbed.py').read_bytes(), (self.new/'absorbed.py').read_bytes())
        self.assertEqual((merged/'preserved.py').read_bytes(), (self.local/'preserved.py').read_bytes())
        self.assertTrue((merged/'added.py').exists())
        output = subprocess.check_output([sys.executable, '-c',
            'import runpy,sys; print(runpy.run_path(sys.argv[1])["value"]())', str(merged/'preserved.py')], text=True)
        self.assertEqual(output.strip(), 'custom B')
        self.assertEqual(request['scopes'][0]['customizations'], ['absorbed.py', 'preserved.py'])

    def test_incomplete_decisions_or_unexplained_cross_file_edits_are_rejected(self):
        root = self.prepare()
        decision, value = self.decisions(root)
        value['decisions'].pop()
        decision.write_text(json.dumps(value))
        with self.assertRaisesRegex(review.ReviewError, 'REVIEW_INCOMPLETE'):
            review.accept(self.store, 'opencli', decision)
        decision, _ = self.decisions(root)
        write(root/'0/merged', 'added.py', 'NEW_UPSTREAM = False\n')
        with self.assertRaisesRegex(review.ReviewError, 'ADAPTATIONS_INCOMPLETE'):
            review.accept(self.store, 'opencli', decision)

    def test_absorbed_claim_cannot_keep_a_shadowing_local_patch(self):
        root = self.prepare()
        decision, _ = self.decisions(root)
        shutil.copy2(self.local/'absorbed.py', root/'0/merged/absorbed.py')
        with self.assertRaisesRegex(review.ReviewError, 'MUST_USE_UPSTREAM'):
            review.accept(self.store, 'opencli', decision)

    def test_unknown_baseline_is_not_blessed_by_a_review_flag(self):
        root = self.prepare(False)
        decision, _ = self.decisions(root)
        with self.assertRaisesRegex(review.ReviewError, 'BASELINE_UNKNOWN'):
            review.accept(self.store, 'opencli', decision)

    def test_changed_live_inputs_or_approved_output_reject_resume(self):
        root = self.prepare()
        decision, _ = self.decisions(root)
        review.accept(self.store, 'opencli', decision)
        write(root/'0/merged', 'added.py', 'drift\n')
        with self.assertRaisesRegex(review.ReviewError, 'APPROVED_RESULT_CHANGED'):
            review.approved(self.store, 'opencli', '2.0.3')
        write(self.local, 'preserved.py', 'concurrent user edit\n')
        with self.assertRaisesRegex(review.ReviewError, 'CHANGED_DURING_REVIEW'):
            review.approved(self.store, 'opencli', '2.0.3')

    def test_symlink_escape_is_rejected(self):
        (self.local/'outside').symlink_to(self.old)
        with self.assertRaisesRegex(review.ReviewError, 'SYMLINK'):
            self.prepare()

    def test_source_replacement_handles_file_and_directory_transitions(self):
        for old_name, new_name in (('module.py', 'module.py/read.py'),
                                   ('module/read.py', 'module')):
            with self.subTest(old=old_name, new=new_name):
                source = self.base / ('transition-source-' + str(len(old_name)))
                destination = self.base / ('transition-live-' + str(len(old_name)))
                write(destination, old_name, 'old implementation\n')
                write(source, new_name, 'new implementation\n')
                review.replace_source(source, destination)
                self.assertEqual(review.files(destination), review.files(source))
                self.assertEqual((destination / new_name).read_text(), 'new implementation\n')

    def test_directory_transition_preserves_runtime_files_before_any_removal(self):
        source = self.base / 'transition-source'
        destination = self.base / 'transition-live'
        write(source, 'module', 'new implementation\n')
        previous = write(destination, 'module/read.py', 'old implementation\n')
        private = write(destination, 'module/.env', 'SYNTHETIC_ONLY=retained\n')
        with self.assertRaisesRegex(review.ReviewError, 'RUNTIME_PATH_CONFLICT'):
            review.replace_source(source, destination)
        self.assertEqual(previous.read_text(), 'old implementation\n')
        self.assertEqual(private.read_text(), 'SYNTHETIC_ONLY=retained\n')

    def test_acceptance_reads_each_merged_file_a_bounded_number_of_times(self):
        for index in range(24):
            name = f'changed-{index}.py'
            write(self.old, name, 'old\n')
            write(self.local, name, 'local\n')
            write(self.new, name, 'new\n')
        root = self.prepare()
        _, request = review.load(self.store, 'opencli')
        decision = self.base / 'bounded-review.json'
        decision.write_text(json.dumps({'target': '2.0.3', 'decisions': [
            {'scope': 'package', 'path': name, 'disposition': 'absorbed',
             'reason': 'Use the complete new implementation.',
             'evidence': 'Synthetic old, local and new inputs differ.',
             'validation': 'The merged snapshot equals the new snapshot.'}
            for name in request['scopes'][0]['customizations']], 'adaptations': []}))
        original = Path.read_bytes
        reads = {}
        merged = root / '0/merged'
        def counted(path):
            if path.is_relative_to(merged):
                reads[path] = reads.get(path, 0) + 1
            return original(path)
        with patch.object(Path, 'read_bytes', counted):
            review.accept(self.store, 'opencli', decision)
        self.assertTrue(reads)
        self.assertLessEqual(max(reads.values()), 4, reads)

    def test_changed_merge_during_routing_validation_is_not_approved(self):
        header = '---\nname: example\ndescription: Synthetic guide.\n---\n'
        for tree in (self.old, self.local, self.new):
            write(tree, 'SKILL.md', header)
        root = self.prepare()
        decision, _ = self.decisions(root)
        def drift(source, merged):
            (root / '0/merged/added.py').write_text('concurrent change\n')
        with patch.object(review, 'validate_skill_routing', side_effect=drift):
            with self.assertRaisesRegex(review.ReviewError, 'APPROVED_RESULT_CHANGED'):
                review.accept(self.store, 'opencli', decision)
        self.assertFalse((root / 'accepted.json').exists())

    def test_upstream_skill_routing_fields_use_existing_manager_validation(self):
        source = write(self.new, 'SKILL.md', '---\nname: example\ndescription: Original description.\nwhen_to_use: "original, trigger"\ndispatch_intent: "read, search"\n---\nNew body.\n')
        merged = write(self.local, 'SKILL.md', source.read_text()+'Local body.\n')
        review.validate_skill_routing(source, merged)
        merged.write_text(merged.read_text().replace('Original description.', 'Local summary.'))
        with self.assertRaisesRegex(review.ReviewError, 'ROUTING_FIELDS_CHANGED'):
            review.validate_skill_routing(source, merged)

    def test_no_customization_avoids_review_and_target_drift_is_rejected(self):
        scope = {'name': 'package', 'live': self.old, 'base': self.old, 'upstream': self.new}
        self.assertIsNone(upstream.customization_gate(self.store, 'opencli', '2.0.3', [scope]))
        root = self.prepare()
        decision, _ = self.decisions(root)
        review.accept(self.store, 'opencli', decision)
        with self.assertRaisesRegex(review.ReviewError, 'TARGET_CHANGED'):
            review.approved(self.store, 'opencli', '2.0.4')

    def test_real_cli_can_seal_review_in_clean_home_without_model_api(self):
        root = self.prepare()
        decision, _ = self.decisions(root)
        home = self.base/'home'
        home.mkdir()
        install_spec = importlib.util.spec_from_file_location('lookup_install_review', SCRIPT.with_name('install-cli.py'))
        installer = importlib.util.module_from_spec(install_spec)
        install_spec.loader.exec_module(installer)
        binary = installer.install(home)
        env = dict(os.environ, HOME=str(home), XDG_STATE_HOME=str(self.base/'state'), CI='1')
        result = subprocess.run([str(binary), 'review', 'opencli', '--accept', str(decision)],
                                env=env, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((root/'accepted.json').exists())

    def test_real_cli_rejects_malformed_decision_shapes_without_side_effects(self):
        root = self.prepare()
        decision, valid = self.decisions(root)
        home = self.base / 'invalid-decision-home'
        home.mkdir()
        env = dict(os.environ, HOME=str(home), XDG_STATE_HOME=str(self.base / 'state'), CI='1')
        before = review.files(self.local)
        request_before = (root / 'request.json').read_bytes()
        cases = [('root-list', [], 'CUSTOMIZATION_REVIEW_INCOMPLETE'),
                 ('root-null', None, 'CUSTOMIZATION_REVIEW_INCOMPLETE')]
        for value in (None, {}, 'invalid', [None], ['invalid'],
                      [{'scope': [], 'path': 'absorbed.py'}],
                      [{'scope': 'package', 'path': {}}]):
            cases.append(('decisions-' + repr(value), {**valid, 'decisions': value},
                          'CUSTOMIZATION_REVIEW_INCOMPLETE'))
        for value in (None, {}, 'invalid', [None], ['invalid'],
                      [{'scope': [], 'path': 'preserved.py'}],
                      [{'scope': 'package', 'path': {}}]):
            cases.append(('adaptations-' + repr(value), {**valid, 'adaptations': value},
                          'CUSTOMIZATION_ADAPTATIONS_INCOMPLETE'))
        for label, value, error in cases:
            with self.subTest(case=label):
                decision.write_text(json.dumps(value))
                result = subprocess.run([sys.executable, str(SCRIPT.with_name('lookup')),
                                         'review', 'opencli', '--accept', str(decision)],
                                        env=env, text=True, capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 78, result.stderr)
                self.assertEqual(result.stdout, '')
                self.assertEqual(json.loads(result.stderr), {'status': 'error', 'error': error})
                self.assertFalse((root / 'accepted.json').exists())
                self.assertEqual(review.files(self.local), before)
                self.assertEqual((root / 'request.json').read_bytes(), request_before)


class OpenCLIMergeTests(unittest.TestCase):
    def setUp(self):
        from test_upstream import cli, CONTRACT
        self.temporary = tempfile.TemporaryDirectory(prefix='lookup-merge-lifecycle-')
        self.base = Path(self.temporary.name)
        self.home = self.base/'home'
        self.home.mkdir()
        self.old, self.local, self.new = (self.base/name for name in ('old', 'local', 'new'))
        for tree, version in ((self.old, '2.0.2'), (self.new, '2.0.3')):
            cli(tree/'dist/src/main.js', version)
            write(tree, 'package.json', json.dumps({'name': upstream.PACKAGE, 'version': version}))
            write(tree, 'clis/sample/read.js', 'base adapter\n')
            write(tree, 'feature.py', 'def value(): return "base"\n')
        shutil.copytree(self.old, self.local)
        (self.base/'bin').mkdir()
        (self.base/'bin/opencli').symlink_to(self.local/'dist/src/main.js')
        self.environment = patch.dict(os.environ, HOME=str(self.home), XDG_STATE_HOME=str(self.base/'state'),
            PATH=str(self.base/'bin')+os.pathsep+os.environ['PATH'], CI='1')
        self.environment.start()
        self.store = upstream.Store()
        root = self.base/'lookup'
        write(root, 'references/providers.json', json.dumps(CONTRACT))
        self.patches = [patch.object(upstream, 'ROOT', root),
                        patch.object(upstream, 'opencli_baseline', return_value=self.old),
                        patch.object(upstream, 'latest', return_value={
                            'latest': '2.0.3', 'published_at': '2026-01-01T00:00:00Z',
                            'url': 'https://www.npmjs.com/package/@jackwener/opencli'}),
                        patch.object(upstream, 'prepare_candidate', side_effect=self.candidate)]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.environment.stop()
        self.temporary.cleanup()

    def candidate(self, store, release):
        package = self.store.root/'versions/2.0.3/node_modules/@jackwener/opencli'
        shutil.copytree(self.new, package, dirs_exist_ok=True)
        binary = package/'dist/src/main.js'
        return {'binary': str(binary), 'version': '2.0.3', 'source': str(self.new),
                'sha256': upstream.digest(binary), 'validation': upstream.isolated_qualification(binary, '2.0.3')}

    def seal(self, scope, path, disposition, merged_content=None):
        root, request = review.load(self.store, 'opencli')
        index = next(i for i, s in enumerate(request['scopes']) if s['name'] == scope)
        if merged_content is not None:
            write(root/str(index)/'merged', path, merged_content)
        adaptations = [{'scope': s['name'], 'path': name, 'reason': 'Preserve unsupported customized behavior.'}
                       for i, s in enumerate(request['scopes'])
                       for name in review.differences(s['upstream'], review.files(root/str(i)/'merged'))]
        decision = self.base/'decisions.json'
        decision.write_text(json.dumps({'target': '2.0.3', 'decisions': [
            {'scope': scope, 'path': path, 'disposition': disposition,
             'reason': 'Compare exact original, local behavior and new implementation.',
             'evidence': 'Upstream and local behavior examined in the isolated fixture.',
             'validation': 'Customized return value or adapter content checked.'}], 'adaptations': adaptations}))
        review.accept(self.store, 'opencli', decision)

    def test_direct_package_patch_is_merged_before_activation(self):
        write(self.local, 'feature.py', 'def value(): return "custom"\n')
        before = review.files(self.local)
        result = upstream.update(self.store, 'opencli')
        self.assertEqual(result['status'], 'manual_review')
        self.assertEqual(review.files(self.local), before)
        self.assertEqual(upstream.installed(self.store, 'opencli')['current'], '2.0.2')
        self.seal('package', 'feature.py', 'preserved', 'def value(): return "custom"\n')
        result = upstream.update(self.store, 'opencli')
        self.assertEqual(result['status'], 'updated', result)
        package = upstream.opencli_package(upstream.resolve_opencli(self.store))
        self.assertIn('custom', (package/'feature.py').read_text())
        self.assertEqual(review.files(self.local), before)

    def test_upstream_absorbed_override_is_removed_and_restored_on_rollback(self):
        override = write(self.home/'.opencli/clis', 'sample/read.js', 'custom adapter\n')
        write(self.new, 'clis/sample/read.js', 'custom adapter\n')
        self.assertEqual(upstream.update(self.store, 'opencli')['status'], 'manual_review')
        self.seal('clis', 'sample/read.js', 'absorbed')
        self.assertEqual(upstream.update(self.store, 'opencli')['status'], 'updated')
        self.assertFalse(override.exists())
        self.assertEqual(upstream.rollback(self.store)['status'], 'rolled_back')
        self.assertEqual(override.read_text(), 'custom adapter\n')

    def test_concurrent_customization_change_rejects_activation(self):
        write(self.local, 'feature.py', 'custom\n')
        upstream.update(self.store, 'opencli')
        self.seal('package', 'feature.py', 'preserved', 'custom\n')
        write(self.local, 'feature.py', 'later user change\n')
        result = upstream.update(self.store, 'opencli')
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['error'], 'CUSTOMIZATION_CHANGED_DURING_REVIEW')
        self.assertEqual(upstream.installed(self.store, 'opencli')['current'], '2.0.2')
        self.assertEqual((self.local/'feature.py').read_text(), 'later user change\n')
        old_review = review.load(self.store, 'opencli')[0]
        replanned = review.restart(self.store, 'opencli')
        self.assertTrue(old_review.exists())
        self.assertNotEqual(Path(replanned['directory']), old_review)
        self.seal('package', 'feature.py', 'preserved', 'later user change\n')
        self.assertEqual(upstream.update(self.store, 'opencli')['status'], 'updated')
        package = upstream.opencli_package(upstream.resolve_opencli(self.store))
        self.assertEqual((package/'feature.py').read_text(), 'later user change\n')

    def test_clean_package_updates_without_semantic_review(self):
        result = upstream.update(self.store, 'opencli')
        self.assertEqual(result['status'], 'updated', result)
        self.assertEqual(result['customizations'], 'no_local_differences')

    def test_rollback_rejects_changed_original_package_beyond_main_executable(self):
        self.assertEqual(upstream.update(self.store, 'opencli')['status'], 'updated')
        write(self.local, 'feature.py', 'modified by another maintainer\n')
        with self.assertRaisesRegex(upstream.MaintenanceError, 'ROLLBACK_TARGET_CHANGED'):
            upstream.rollback(self.store)
        self.assertEqual(upstream.installed(self.store, 'opencli')['current'], '2.0.3')

    def test_failed_rollback_keeps_active_pointer_and_active_overrides_together(self):
        override = write(self.home / '.opencli/clis', 'sample/read.js', 'custom adapter\n')
        write(self.new, 'clis/sample/read.js', 'custom adapter\n')
        self.assertEqual(upstream.update(self.store, 'opencli')['status'], 'manual_review')
        self.seal('clis', 'sample/read.js', 'absorbed')
        self.assertEqual(upstream.update(self.store, 'opencli')['status'], 'updated')
        active = self.store.read('active.json')
        original = self.store.write
        def failed_pointer(name, value):
            if name == 'active.json' and value == active.get('previous', {}):
                raise OSError('synthetic pointer write failure')
            return original(name, value)
        with patch.object(self.store, 'write', side_effect=failed_pointer):
            with self.assertRaises(OSError):
                upstream.rollback(self.store)
        self.assertEqual(self.store.read('active.json'), active)
        self.assertFalse(override.exists())
        self.assertEqual(upstream.installed(self.store, 'opencli')['current'], '2.0.3')

    def test_partial_override_restore_failure_recovers_active_content(self):
        override = write(self.home / '.opencli/clis', 'sample/read.js', 'custom adapter\n')
        write(self.new, 'clis/sample/read.js', 'custom adapter\n')
        self.assertEqual(upstream.update(self.store, 'opencli')['status'], 'manual_review')
        self.seal('clis', 'sample/read.js', 'absorbed')
        self.assertEqual(upstream.update(self.store, 'opencli')['status'], 'updated')
        active = self.store.read('active.json')
        backup = Path(active['customization_recovery'][0]['backup'])
        original = review.replace_source
        broken = self.home / '.opencli/clis/partial.js'
        def partial_copy(source, destination):
            if Path(source) == backup:
                write(destination, 'partial.js', 'incomplete restore\n')
                raise OSError('synthetic override copy failure')
            return original(source, destination)
        with patch.object(review, 'replace_source', side_effect=partial_copy):
            with self.assertRaises(OSError):
                upstream.rollback(self.store)
        self.assertEqual(self.store.read('active.json'), active)
        self.assertFalse(override.exists())
        self.assertFalse(broken.exists())
        self.assertEqual(list(self.store.root.glob('rollback-exchange-*')), [])

    def test_failed_rollback_recovery_retains_its_snapshot(self):
        override = write(self.home / '.opencli/clis', 'sample/read.js', 'old customization\n')
        self.assertEqual(upstream.update(self.store, 'opencli')['status'], 'manual_review')
        self.seal('clis', 'sample/read.js', 'preserved', 'adapted customization\n')
        self.assertEqual(upstream.update(self.store, 'opencli')['status'], 'updated')
        active = self.store.read('active.json')
        original_write, original_replace = self.store.write, review.replace_source
        def failed_pointer(name, value):
            if name == 'active.json' and value == active.get('previous', {}):
                raise OSError('synthetic pointer write failure')
            return original_write(name, value)
        def failed_restore(source, destination):
            if Path(source).parent.name.startswith('rollback-exchange-'):
                raise OSError('synthetic recovery copy failure')
            return original_replace(source, destination)
        with patch.object(self.store, 'write', side_effect=failed_pointer), \
             patch.object(review, 'replace_source', side_effect=failed_restore):
            with self.assertRaisesRegex(upstream.MaintenanceError, 'ROLLBACK_RECOVERY_FAILED:') as caught:
                upstream.rollback(self.store)
        area = Path(str(caught.exception).split(':', 1)[1])
        self.assertTrue(area.is_dir())
        self.assertEqual((area / '0/sample/read.js').read_text(), 'adapted customization\n')
        self.assertEqual(self.store.read('active.json'), active)
        self.assertEqual(override.read_text(), 'old customization\n')

    def test_merged_plugin_dependent_candidate_resumes_after_busy_deferral(self):
        script = self.local/'dist/src/main.js'
        text = script.read_text()
        # Only the customized candidate needs its retained plugin for --help.
        text = text.replace('import json,sys,time', 'import json,sys,time,os,pathlib')
        text = text.replace('elif "--help" in sys.argv:',
                            'elif "--help" in sys.argv and not (pathlib.Path.home()/".opencli/plugins/marker").exists(): raise SystemExit(1)\n'
                            'elif "--help" in sys.argv:')
        script.write_text(text)
        plugin = write(self.home/'.opencli/plugins', 'marker', 'plugin required\n')
        self.assertEqual(upstream.update(self.store, 'opencli')['status'], 'manual_review')
        root, request = review.load(self.store, 'opencli')
        shutil.copy2(script, root/'0/merged/dist/src/main.js')
        decision = self.base/'plugin-decisions.json'
        decision.write_text(json.dumps({'target': '2.0.3', 'decisions': [
            {'scope': 'package', 'path': 'dist/src/main.js', 'disposition': 'preserved',
             'reason': 'Candidate retains plugin integration.', 'evidence': 'Local startup checks plugin marker.',
             'validation': 'Help passes in a HOME with the retained plugin.'},
            {'scope': 'plugins', 'path': 'marker', 'disposition': 'preserved',
             'reason': 'Keep the required plugin.', 'evidence': 'No upstream plugin.',
             'validation': 'Plugin marker present in qualification HOME.'}], 'adaptations': [
            {'scope': 'package', 'path': 'dist/src/main.js', 'reason': 'Retain plugin startup behavior.'},
            {'scope': 'plugins', 'path': 'marker', 'reason': 'Required plugin.'}]}))
        # Preserve the candidate's new version while merging the startup patch.
        merged = root/'0/merged/dist/src/main.js'
        merged.write_text(merged.read_text().replace("'2.0.2'", "'2.0.3'"))
        review.accept(self.store, 'opencli', decision)
        with self.store.lock('usage', shared=True):
            self.assertEqual(upstream.update(self.store, 'opencli')['status'], 'deferred')
        result = upstream.update(self.store, 'opencli')
        self.assertEqual(result['status'], 'updated', result)
        self.assertEqual(plugin.read_text(), 'plugin required\n')


if __name__ == '__main__':
    unittest.main()
