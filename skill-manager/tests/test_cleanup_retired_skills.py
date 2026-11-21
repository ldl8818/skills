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
        self.home = self.root / 'home'
        self.home.mkdir()
        self.env = dict(os.environ, HOME=str(self.home),
                        GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
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

    def test_pull_removes_direct_relative_and_multihop_retired_symlinks(self):
        self.cleanup('--install')
        agents = self.home / '.agents/skills'
        claude = self.home / '.claude/skills'
        antigravity = self.home / '.gemini/config/skills'
        for directory in (agents, claude, antigravity):
            directory.mkdir(parents=True)
        # Absolute link, relative link, and two-hop link via shared .agents/skills.
        direct = agents / 'download-video'
        direct.symlink_to(self.retired)
        relative = claude / 'download-video'
        relative.symlink_to(os.path.relpath(self.retired, claude))
        chained = antigravity / 'download-video'
        chained.symlink_to(direct)
        # Already-dangling retired links (e.g. think, health removed in earlier commits).
        dangling_think = agents / 'think'
        dangling_think.symlink_to(self.local / 'think')
        dangling_health = claude / 'health'
        dangling_health.symlink_to(os.path.relpath(self.local / 'health', claude))
        # Active Skill symlink must remain intact.
        active = agents / 'video-downloader'
        active.symlink_to(self.local / 'video-downloader')

        result = self.git(self.local, 'pull', '--ff-only')
        combined = result.stdout + result.stderr
        self.assertIn('removed retired Skill symlink ~/.agents/skills/download-video', combined)
        self.assertIn('removed retired Skill symlink ~/.claude/skills/download-video', combined)
        self.assertIn('removed retired Skill symlink ~/.gemini/config/skills/download-video', combined)
        self.assertIn('removed retired Skill symlink ~/.agents/skills/think', combined)
        self.assertIn('removed retired Skill symlink ~/.claude/skills/health', combined)
        for link in (direct, relative, chained, dangling_think, dangling_health):
            self.assertFalse(link.is_symlink())
            self.assertFalse(link.exists())
        self.assertTrue(active.is_symlink())
        self.assertEqual(active.resolve(), (self.local / 'video-downloader').resolve())

    def test_symlink_cleanup_preserves_real_dirs_foreign_links_and_protected_skills(self):
        agents = self.home / '.agents/skills'
        claude = self.home / '.claude/skills'
        codex = self.home / '.codex/skills'
        agents.mkdir(parents=True)
        claude.mkdir(parents=True)
        # 1. Real directory with a retired name must never be removed.
        real_think = agents / 'think'
        real_think.mkdir()
        (real_think / 'SKILL.md').write_text('local custom think')
        # 2. Symlink pointing to an unrelated repo must never be removed.
        other_repo = self.root / 'other-skills/health'
        other_repo.mkdir(parents=True)
        foreign_health = claude / 'health'
        foreign_health.symlink_to(other_repo)
        # 3. Symlink to a still-committed retired Skill must remain until retired in HEAD.
        still_active = agents / 'download-video'
        still_active.symlink_to(self.retired)
        # 4. Client skills root escaping HOME via symlink must be skipped.
        escaped_root = self.root / 'escaped-skills'
        escaped_root.mkdir()
        escaped_link = escaped_root / 'hunt'
        escaped_link.symlink_to(self.local / 'hunt')
        codex.parent.mkdir(parents=True)
        codex.symlink_to(escaped_root)
        # 5. Symlink loop inside client skills dir must not break cleanup.
        loop_a = agents / 'loop-a'
        loop_b = agents / 'loop-b'
        loop_a.symlink_to(loop_b)
        loop_b.symlink_to(loop_a)

        self.cleanup('--home', str(self.home))
        self.assertTrue((real_think / 'SKILL.md').is_file())
        self.assertTrue(foreign_health.is_symlink())
        self.assertTrue(still_active.is_symlink())
        self.assertTrue(escaped_link.is_symlink())
        self.assertTrue(loop_a.is_symlink())

        # After pull retires download-video, its symlink is cleaned while others stay preserved.
        self.git(self.local, 'pull', '--ff-only')
        self.cleanup('--home', str(self.home))
        self.assertFalse(still_active.is_symlink())
        self.assertTrue((real_think / 'SKILL.md').is_file())
        self.assertTrue(foreign_health.is_symlink())
        self.assertTrue(escaped_link.is_symlink())


if __name__ == '__main__':
    unittest.main()
