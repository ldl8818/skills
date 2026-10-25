"""Real CLI lifecycle flows with an offline synthetic upstream transport."""
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest


SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
ENTRY = '---\nname: demo\ndescription: Demo\n---\n# Usage\n'
OLD, NEW = 'a' * 40, 'b' * 40


class OfflineLifecycleCliTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='manager-cli-review-')
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name).resolve()
        transport = self.home / 'transport'
        transport.mkdir()
        for commit, value in ((OLD, 1), (NEW, 2)):
            with tarfile.open(transport / (commit + '.tar.gz'), 'w:gz') as archive:
                for name, data, mode in (
                        ('SKILL.md', ENTRY.encode(), 0o644),
                        ('run.sh', f'#!/bin/sh\nprintf "{value}"\n'.encode(), 0o755)):
                    member = tarfile.TarInfo('repo/' + name)
                    member.mode, member.size = mode, len(data)
                    archive.addfile(member, io.BytesIO(data))
        # Only the external transport is substituted. The actual CLI resolves
        # targets, extracts tar, merges, verifies receipts and switches dirs.
        (transport / 'sitecustomize.py').write_text(
            'import io,json,urllib.request\nfrom pathlib import Path\n'
            'def offline(request, *args, **kwargs):\n'
            '    url = getattr(request, "full_url", request)\n'
            '    prefix = "https://github.com/example/demo/archive/"\n'
            '    if url.startswith(prefix):\n'
            '        name = url[len(prefix):]\n'
            f'        if name in {[OLD + ".tar.gz", NEW + ".tar.gz"]!r}:\n'
            '            return io.BytesIO(Path(__file__).with_name(name).read_bytes())\n'
            f'    if url == "https://api.github.com/repos/example/demo/commits/{NEW}":\n'
            '        return io.BytesIO(json.dumps({"commit":{"committer":'
            '{"date":"2026-01-01T00:00:00Z"}}}).encode())\n'
            '    raise AssertionError("Unexpected external request: " + url)\n'
            'urllib.request.urlopen = offline\n')
        git = transport / 'git'
        git.write_text(
            '#!' + sys.executable + '\nimport sys\n'
            'if sys.argv[1:2] == ["ls-remote"]:\n'
            f'    print("{NEW}\\t" + ("refs/tags/v1.1.0" if "--tags" in sys.argv else "HEAD"))\n'
            'else:\n    raise SystemExit("Unexpected git operation")\n')
        git.chmod(0o755)
        self.env = {**os.environ, 'HOME': str(self.home), 'USERPROFILE': str(self.home),
                    'SKILL_MANAGER_HOME': str(self.home / 'state'),
                    'XDG_CONFIG_HOME': str(self.home / 'config'),
                    'PYTHONPATH': str(transport), 'PYTHONDONTWRITEBYTECODE': '1',
                    'PATH': str(transport) + os.pathsep + os.environ.get('PATH', '')}
        self.global_skill = self.install(self.home)
        self.project = self.home / 'project with spaces'
        self.project_skill = self.install(self.project)
        state = self.home / 'state/data'
        state.mkdir(parents=True)
        (state / 'projects.json').write_text(json.dumps(
            {'projects': {str(self.project): {}}}))

    def install(self, scope):
        directory = scope / '.agents/skills/demo'
        directory.mkdir(parents=True)
        (directory / 'SKILL.md').write_text(ENTRY.replace(
            '---\n# Usage', 'metadata:\n  github_url: https://github.com/example/demo\n'
            f'  github_hash: {OLD}\n---\n# Usage'))
        script = directory / 'run.sh'
        script.write_text('#!/bin/sh\nprintf "1"\n')
        script.chmod(0o755)
        return directory

    def cli(self, script, *arguments, success=True):
        result = subprocess.run(
            [sys.executable, '-B', str(SCRIPTS / script), *arguments],
            cwd=self.home, env=self.env, capture_output=True, text=True, timeout=20)
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def test_project_update_toggle_and_bare_name_ambiguity(self):
        self.cli('update_skill.py', 'demo', '--project', str(self.project))
        self.assertIn(NEW, (self.project_skill / 'SKILL.md').read_text())
        self.assertIn(OLD, (self.global_skill / 'SKILL.md').read_text())
        executed = subprocess.run([str(self.project_skill / 'run.sh')],
                                  capture_output=True, text=True, timeout=5)
        self.assertEqual((executed.returncode, executed.stdout), (0, '2'))
        self.cli('toggle_skill.py', 'disable', 'demo', '--project', str(self.project))
        self.cli('update_skill.py', 'demo', '--project', str(self.project))
        self.assertTrue((self.project_skill / 'SKILL.md.disabled').is_file())
        self.assertTrue((self.global_skill / 'SKILL.md').is_file())
        self.cli('toggle_skill.py', 'enable', 'demo', '--project', str(self.project))
        other = self.home / '.claude/skills/demo'
        shutil.copytree(self.global_skill, other)
        for script, args in (('update_skill.py', ('demo',)),
                             ('toggle_skill.py', ('disable', 'demo'))):
            result = self.cli(script, *args, success=False)
            self.assertIn(str(other), result.stdout)
            self.assertIn(str(self.global_skill), result.stdout)
        self.assertIn(OLD, (other / 'SKILL.md').read_text())
        self.assertTrue((self.global_skill / 'SKILL.md').is_file())

    def test_batch_updates_both_scopes_and_deduplicates_aliases(self):
        alias = self.home / '.codex/skills/demo'
        alias.parent.mkdir(parents=True)
        alias.symlink_to(self.global_skill, target_is_directory=True)
        checked = self.cli('scan_and_check.py', '--json')
        rows = json.loads(checked.stdout)
        self.assertEqual(len(rows), 2)
        self.assertEqual({row['target_path'] for row in rows},
                         {str(self.global_skill), str(self.project_skill)})
        self.cli('update_skill.py')
        for directory in (self.global_skill, self.project_skill):
            self.assertIn(NEW, (directory / 'SKILL.md').read_text())
            self.assertEqual((directory / 'run.sh').stat().st_mode & 0o7777, 0o755)
            self.assertTrue((directory / 'upstream-merge.json').is_file())
        self.assertTrue(alias.is_symlink())
        backups = self.home / 'state/archive/update-backups'
        self.assertEqual(len(list(backups.iterdir())), 2)


if __name__ == '__main__':
    unittest.main()
