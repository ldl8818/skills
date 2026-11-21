import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path('skill-manager/scripts/cleanup_retired_skills.py')
SOURCE = Path(__file__).resolve().parents[2] / SCRIPT


class RetiredSkillCleanupTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.remote = self.root / 'source'
        self.local = self.root / 'local'
        self.env = dict(os.environ, GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
                        GIT_AUTHOR_NAME='Fixture', GIT_AUTHOR_EMAIL='test@example.com',
                        GIT_COMMITTER_NAME='Fixture', GIT_COMMITTER_EMAIL='test@example.com')
        self.remote.mkdir()
        self.git(self.remote, 'init', '-b', 'main')
        (self.remote / SCRIPT).parent.mkdir(parents=True)
        shutil.copy2(SOURCE, self.remote / SCRIPT)
        (self.remote / '.gitignore').write_text('.DS_Store\n__pycache__/\n*.local\n')
        (self.remote / 'download-video').mkdir()
        (self.remote / 'download-video/SKILL.md').write_text('old Skill')
        self.git(self.remote, 'add', '--', str(SCRIPT), '.gitignore', 'download-video/SKILL.md')
        self.git(self.remote, 'commit', '-m', 'Initial version')
        self.git(self.root, 'clone', str(self.remote), str(self.local))
        self.retired = self.local / 'download-video'
        self.cache = self.retired / 'scripts/__pycache__/download_video.cpython-314.pyc'
        self.cache.parent.mkdir(parents=True)
        self.cache.write_bytes(b'bytecode')
        (self.retired / '.DS_Store').write_bytes(b'finder metadata')
        self.git(self.remote, 'rm', '--', 'download-video/SKILL.md')
        (self.remote / 'video-downloader').mkdir()
        (self.remote / 'video-downloader/SKILL.md').write_text('current Skill')
        self.git(self.remote, 'add', '--', 'video-downloader/SKILL.md')
        self.git(self.remote, 'commit', '-m', 'Retire old Skill')

    def git(self, cwd, *args):
        return subprocess.run(
            ['git', *args], cwd=cwd, env=self.env, capture_output=True, text=True, check=True
        )

    def cleanup(self, *args, check=True):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args], cwd=self.local, env=self.env,
            capture_output=True, text=True, check=check
        )

    def test_fast_forward_pull_removes_cache_only_directory(self):
        self.cleanup('--install')
        self.cleanup('--install')
        self.assertTrue(self.cache.exists())
        result = self.git(self.local, 'pull', '--ff-only')
        self.assertIn('removed retired cache directory', result.stdout + result.stderr)
        self.assertFalse(self.retired.exists())
        self.assertEqual((self.local / 'video-downloader/SKILL.md').read_text(), 'current Skill')
        self.assertEqual(self.git(self.local, 'status', '--porcelain').stdout, '')

    def test_rebase_pull_also_runs_cleanup(self):
        self.cleanup('--install')
        (self.local / 'note.txt').write_text('local change')
        self.git(self.local, 'add', '--', 'note.txt')
        self.git(self.local, 'commit', '-m', 'Local note')
        self.git(self.local, 'pull', '--rebase')
        self.assertFalse(self.retired.exists())
        self.assertEqual((self.local / 'note.txt').read_text(), 'local change')

    def test_manual_cleanup_preserves_unknown_files_and_symlinks(self):
        self.git(self.local, 'pull', '--ff-only')
        self.assertTrue(self.cache.exists())
        notes = self.retired / 'notes.local'
        notes.write_text('keep')
        result = self.cleanup()
        self.assertIn('preserved directory', result.stderr)
        self.assertTrue(self.cache.exists())
        self.assertEqual(notes.read_text(), 'keep')
        notes.unlink()
        outside = self.root / 'outside'
        outside.write_text('keep')
        link = self.retired / 'scripts/.DS_Store'
        link.symlink_to(outside)
        self.cleanup()
        self.assertTrue(link.is_symlink())
        self.assertTrue(self.cache.exists())
        self.assertEqual(outside.read_text(), 'keep')

    def test_cleanup_respects_committed_and_staged_files(self):
        self.git(self.local, 'rm', '--', 'download-video/SKILL.md')
        self.cleanup()
        self.assertTrue(self.cache.exists())
        self.git(self.local, 'commit', '-m', 'Remove old Skill')
        self.git(self.local, 'add', '-f', '--', str(self.cache.relative_to(self.local)))
        self.cleanup()
        self.assertTrue(self.cache.exists())

    def test_install_preserves_existing_hooks(self):
        hooks = self.local / '.git/hooks'
        existing = hooks / 'post-rewrite'
        existing.write_text('existing hook')
        result = self.cleanup('--install', check=False)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(existing.read_text(), 'existing hook')
        self.assertFalse((hooks / 'post-merge').is_symlink())


if __name__ == '__main__':
    unittest.main()
