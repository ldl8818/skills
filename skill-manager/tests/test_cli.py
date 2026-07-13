import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


class CliSmokeTests(unittest.TestCase):
    def run_cli(self, script, *args, home):
        # USERPROFILE 一起盖掉：Windows 的 expanduser 走它，不盖会读写真实 ~/.claude
        env = {**os.environ, "HOME": home, "USERPROFILE": home,
               "PYTHONDONTWRITEBYTECODE": "1"}
        return subprocess.run(
            [sys.executable, str(SCRIPTS / script), *args], env=env,
            cwd=home, text=True, capture_output=True, timeout=20)

    def test_empty_home_list_and_check(self):
        with tempfile.TemporaryDirectory() as home:
            self.assertEqual(self.run_cli("list_skills.py", home=home).returncode, 0)
            result = self.run_cli("scan_and_check.py", "--json", home=home)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout.strip(), "[]")

    def test_help_flag_prints_usage_and_exits_zero(self):
        with tempfile.TemporaryDirectory() as home:
            for script in ("list_skills.py", "scan_and_check.py", "doctor.py",
                           "update_skill.py", "delete_skill.py", "toggle_skill.py",
                           "bump_skill.py", "trace_source.py"):
                with self.subTest(script=script):
                    result = self.run_cli(script, "--help", home=home)
                    self.assertEqual(result.returncode, 0,
                                     result.stdout + result.stderr)
                    self.assertIn("用法", result.stdout)

    def test_corrupt_state_file_fails_with_path_in_message(self):
        with tempfile.TemporaryDirectory() as home:
            sm = Path(home) / ".claude" / "skills" / "skill-manager"
            sm.mkdir(parents=True)
            (sm / "fingerprints.json").write_text("{broken", encoding="utf-8")
            result = self.run_cli("list_skills.py", home=home)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("fingerprints.json", result.stderr)
            self.assertIn("已损坏", result.stderr)

    def test_delete_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as home:
            result = self.run_cli("delete_skill.py", "../../outside", "--dry-run", home=home)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("安全", result.stdout)

    def test_project_toggle_targets_only_requested_project(self):
        with tempfile.TemporaryDirectory() as home:
            project = Path(home) / "project"
            skill = project / ".claude" / "skills" / "demo"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("---\nname: demo\ndescription: demo\n---\n")
            result = self.run_cli(
                "toggle_skill.py", "disable", "demo", "--project", str(project), home=home)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue((skill / "SKILL.md.disabled").exists())

    def test_plugin_delete_rejects_install_path_outside_cache(self):
        with tempfile.TemporaryDirectory() as home:
            plugin_dir = Path(home) / "important" / "version"
            plugin_dir.mkdir(parents=True)
            registry = Path(home) / ".claude" / "plugins" / "installed_plugins.json"
            registry.parent.mkdir(parents=True)
            registry.write_text(
                '{"plugins":{"demo@market":[{"installPath":"' + str(plugin_dir) + '"}]}}',
                encoding="utf-8")
            result = self.run_cli("delete_skill.py", "demo", "--dry-run", home=home)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("越过插件缓存边界", result.stdout)
            self.assertTrue(plugin_dir.exists())


if __name__ == "__main__":
    unittest.main()
