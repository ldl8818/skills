import os
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


class FrozenTests(unittest.TestCase):
    def fixture(self, root):
        repo = root / 'repo'
        for name in install_frozen.NAMES:
            source = repo / name
            source.mkdir(parents=True)
            (source / 'SKILL.md').write_text(f'---\nname: {name}\ndescription: Test fixture\nmetadata:\n  version: "4.0.0"\n  update_policy: frozen\n  github_url: https://github.com/example/skills\n---\n')
        return repo

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


if __name__ == '__main__':
    unittest.main()
