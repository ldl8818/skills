import os
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import install_frozen
import scan_and_check
import verify_frozen
import audit_upstream


class FrozenTests(unittest.TestCase):
    def test_repository_frozen_sources_match_complete_merge_receipts(self):
        repo = SCRIPTS.parents[1]
        self.assertEqual(verify_frozen.verify(repo), [])

    def test_active_think_is_allowed_while_retired_sources_still_fail(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self.fixture(Path(temp))
            (repo / 'think').mkdir()
            (repo / 'think/SKILL.md').write_text('---\nname: think\ndescription: Plan\n---\n')
            self.assertEqual(verify_frozen.verify(repo), [])
            for name in ('learn', 'read'):
                (repo / name).mkdir()
            self.assertEqual(verify_frozen.verify(repo), [
                'learn: retired source still present',
                'read: retired source still present',
            ])

    def test_structural_success_cannot_replace_upstream_coverage(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self.fixture(Path(temp))
            for name in install_frozen.NAMES:
                path = repo / name / 'SKILL.md'
                scan_and_check.core.set_frontmatter_field(str(path), 'github_hash', 'a' * 40)
                (repo / name / 'LICENSE').write_text('Synthetic license fixture')
                (repo / name / audit_upstream.RECEIPT).unlink()
            errors = verify_frozen.verify(repo)
            self.assertTrue(any('upstream' in error for error in errors), errors)

    def test_codex_only_never_creates_claude(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = self.fixture(root)
            home = root / 'home'
            self.assertEqual(install_frozen.install(repo, home, ('codex',)), 10)
            self.assertEqual(install_frozen.install(repo, home, ('codex',)), 0)
            self.assertFalse((home / '.claude').exists())
            with self.assertRaises(ValueError):
                install_frozen.install(repo, home, ('unexpected',))

    def fixture(self, root):
        repo = root / 'repo'
        for name in install_frozen.NAMES:
            source = repo / name
            source.mkdir(parents=True)
            (source / 'SKILL.md').write_text(f'---\nname: {name}\ndescription: Test fixture\nmetadata:\n  version: "4.0.0"\n  update_policy: frozen\n  github_url: https://github.com/example/skills\n  github_hash: {"a" * 40}\n---\n')
            (source / 'LICENSE').write_text('Synthetic license fixture')
            receipt = audit_upstream.make_receipt(source, audit_upstream.local_files(source),
                dict(commit='a' * 40, repository='https://github.com/example/skills'), {})
            (source / audit_upstream.RECEIPT).write_text(json.dumps(receipt))
        return repo

    def test_install_rejects_source_drift_before_creating_any_links(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = self.fixture(root)
            entry = repo / install_frozen.NAMES[-1] / 'SKILL.md'
            entry.write_text(entry.read_text() + '# Undocumented change\n')
            home = root / 'home'
            with self.assertRaisesRegex(ValueError, 'incomplete upstream merge'):
                install_frozen.install(repo, home)
            self.assertFalse(home.exists())

    def test_install_idempotent_and_updates_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            repo = self.fixture(root)
            home = root / 'home'
            self.assertEqual(install_frozen.install(repo, home), 15)
            self.assertEqual(install_frozen.install(repo, home), 0)
            for name in install_frozen.NAMES:
                before = (repo / name / 'SKILL.md').read_bytes()
                for relative in install_frozen.ENTRY_ROOTS:
                    link = home / relative / name
                    self.assertEqual(Path(os.readlink(link)), repo / name)
                result = subprocess.run([sys.executable, str(SCRIPTS / 'update_skill.py'), name, '--ref', 'main'], env={**os.environ, 'HOME': str(home), 'USERPROFILE': str(home)}, capture_output=True, text=True, timeout=15)
                self.assertIn('frozen', result.stdout)
                self.assertEqual(before, (repo / name / 'SKILL.md').read_bytes())

    def test_conflict_preflight_does_not_create_partial_entries(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = self.fixture(root)
            home = root / 'home'
            conflict = home / '.codex/skills/write'
            conflict.mkdir(parents=True)
            with self.assertRaises(ValueError):
                install_frozen.install(repo, home)
            self.assertFalse((home / '.agents').exists())
            self.assertTrue(conflict.is_dir())

    def test_escaping_entry_root_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = self.fixture(root)
            home = root / 'home'
            (home / '.agents').mkdir(parents=True)
            (home / '.agents/skills').symlink_to(repo, target_is_directory=True)
            with self.assertRaises(ValueError):
                install_frozen.install(repo, home)

    def test_frozen_comparison_never_becomes_updatable(self):
        target = ('skill', 'check', 'https://github.com/example/skills', 'a' * 40, {'frozen': True, 'local': '4.0.0'})
        with patch.object(scan_and_check, 'remote_latest', side_effect=AssertionError('network forbidden')):
            self.assertEqual(scan_and_check.check_one(target)['status'], 'frozen')
        for remote, expected in [('a' * 40, 'same'), ('b' * 40, 'different'), (None, 'unknown')]:
            with patch.object(scan_and_check, 'remote_latest', return_value=('v5', remote)):
                result = scan_and_check.check_one(target, True)
                self.assertEqual(result['status'], 'frozen')
                self.assertEqual(result['upstream_comparison'], expected)

    def test_verification_discovery_does_not_run_package_tools(self):
        script = SCRIPTS.parents[1] / 'check/scripts/run-tests.sh'
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'tsconfig.json').write_text('{}')
            (root / 'package.json').write_text('{"scripts":{"test":"exit 99"}}')
            sentinel = root / 'executed'
            for name in ('npx', 'npm', 'cargo', 'pytest'):
                executable = root / name
                executable.write_text('#!/bin/sh\ntouch "' + str(sentinel) + '"\nexit 99\n')
                executable.chmod(0o755)
            result = subprocess.run(['/bin/bash', str(script)], cwd=root, env={**os.environ, 'PATH': str(root) + os.pathsep + os.environ['PATH']}, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('TypeScript', result.stdout)
            self.assertFalse(sentinel.exists())

    def test_explicit_verification_executes_and_preserves_failure_status(self):
        script = SCRIPTS.parents[1] / 'check/scripts/run-tests.sh'
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'package.json').write_text('{"scripts":{"test":"fixture"}}')
            marker = root / 'executed'
            npm = root / 'npm'
            env = {**os.environ, 'PATH': str(root) + os.pathsep + os.environ['PATH']}
            for code in (0, 17):
                npm.write_text('#!/bin/sh\nprintf verified > "' + str(marker) + '"\nexit ' + str(code) + '\n')
                npm.chmod(0o755)
                result = subprocess.run(['/bin/bash', str(script), '--execute'], cwd=root, env=env,
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, code, result.stderr)
                self.assertEqual(marker.read_text(), 'verified')


if __name__ == '__main__':
    unittest.main()
