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

    def test_legacy_data_migrates_to_data_dir(self):
        with tempfile.TemporaryDirectory() as home:
            legacy = Path(home) / ".claude" / "skills" / "skill-manager"
            legacy.mkdir(parents=True)
            (legacy / "descriptions_zh.json").write_text('{"demo": "示例"}', encoding="utf-8")
            result = self.run_cli("list_skills.py", home=home)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            moved = Path(home) / ".skill-manager" / "data" / "descriptions_zh.json"
            self.assertEqual(moved.read_text(encoding="utf-8"), '{"demo": "示例"}')
            # 搬家是移动不是复制：旧位置留副本会在下轮被误当权威数据
            self.assertFalse((legacy / "descriptions_zh.json").exists())

    def test_claude_state_migrates_to_neutral_state_directory(self):
        with tempfile.TemporaryDirectory() as home:
            legacy = Path(home) / ".claude" / "data" / "skill-manager"
            legacy.mkdir(parents=True)
            (legacy / "projects.json").write_text('{"projects": {}}', encoding="utf-8")
            result = self.run_cli("list_skills.py", home=home)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            moved = Path(home) / ".skill-manager" / "data" / "projects.json"
            self.assertEqual(moved.read_text(encoding="utf-8"), '{"projects": {}}')
            self.assertFalse((legacy / "projects.json").exists())

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
            skill = project / ".agents" / "skills" / "demo"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("---\nname: demo\ndescription: demo\n---\n")
            result = self.run_cli(
                "toggle_skill.py", "disable", "demo", "--project", str(project), home=home)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue((skill / "SKILL.md.disabled").exists())

    def test_global_agents_skill_can_be_resolved_for_delete_dry_run(self):
        with tempfile.TemporaryDirectory() as home:
            skill = Path(home) / ".agents" / "skills" / "demo"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text(
                "---\nname: demo\ndescription: demo\nmetadata:\n  source: local\n---\n",
                encoding="utf-8")
            result = self.run_cli("delete_skill.py", "demo", "--dry-run", home=home)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn(str(skill), result.stdout)
            self.assertTrue(skill.exists())

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

    def test_list_includes_enabled_codex_plugin(self):
        with tempfile.TemporaryDirectory() as home:
            config = Path(home) / ".codex" / "config.toml"
            config.parent.mkdir(parents=True)
            config.write_text(
                '[plugins."demo@openai-curated"]\nenabled = true\n', encoding="utf-8")
            root = (Path(home) / ".codex" / "plugins" / "cache" / "openai-curated"
                    / "demo" / "abc123")
            skill = root / "skills" / "demo-skill"
            (root / ".codex-plugin").mkdir(parents=True)
            (root / ".codex-plugin" / "plugin.json").write_text(
                '{"name":"demo","version":"1.2.3"}', encoding="utf-8")
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text(
                '---\nname: demo-skill\ndescription: Codex test skill\n---\n', encoding="utf-8")
            result = self.run_cli("list_skills.py", home=home)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("demo-skill", result.stdout)
            self.assertIn("Codex:openai-curated", result.stdout)
            self.assertIn("1.2.3", result.stdout)

    def test_list_separates_codex_system_skill_from_plugins(self):
        with tempfile.TemporaryDirectory() as home:
            skill = Path(home) / ".codex" / "skills" / ".system" / "official"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text(
                "---\nname: official\ndescription: built in\n---\n", encoding="utf-8")
            result = self.run_cli("list_skills.py", home=home)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("Codex 内置生效", result.stdout)
            self.assertIn("official", result.stdout)
            self.assertNotIn("Codex 插件", result.stdout)
            self.assertNotIn("缺中文描述", result.stdout)

    def test_list_classifies_agents_entity_as_shared_global(self):
        with tempfile.TemporaryDirectory() as home:
            source = Path(home) / ".agents" / "skills" / "demo"
            source.mkdir(parents=True)
            (source / "SKILL.md").write_text(
                "---\nname: demo\ndescription: demo\nmetadata:\n  source: local\n---\n",
                encoding="utf-8")
            for runtime in (".claude", ".codex"):
                entry = Path(home) / runtime / "skills" / "demo"
                entry.parent.mkdir(parents=True)
                entry.symlink_to(source, target_is_directory=True)
            result = self.run_cli("list_skills.py", home=home)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            rows = [line for line in result.stdout.splitlines()
                    if line.startswith(" demo ") and "|" in line]
            self.assertEqual(len(rows), 1)
            self.assertIn("全局直装（共享）生效", result.stdout)

    def test_list_includes_project_agents_skill(self):
        with tempfile.TemporaryDirectory() as home:
            project = Path(home) / "project"
            skill = project / ".agents" / "skills" / "demo"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text(
                "---\nname: demo\ndescription: demo\nmetadata:\n  source: local\n---\n",
                encoding="utf-8")
            result = self.run_cli("list_skills.py", str(project), home=home)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("项目级 Skill", result.stdout)
            self.assertIn("demo", result.stdout)

    def test_list_includes_all_client_global_roots(self):
        with tempfile.TemporaryDirectory() as home:
            roots = {
                "claude-demo": Path(home) / ".claude" / "skills",
                "gemini-demo": Path(home) / ".gemini" / "skills",
                "grok-demo": Path(home) / ".grok" / "skills",
                "antigravity-demo": Path(home) / ".gemini" / "config" / "skills",
                "antigravity-ide-demo": Path(home) / ".gemini" / "antigravity" / "skills",
                "antigravity-cli-demo": Path(home) / ".gemini" / "antigravity-cli" / "skills",
                "codex-demo": Path(home) / ".codex" / "skills",
            }
            for name, root in roots.items():
                skill = root / name
                skill.mkdir(parents=True)
                (skill / "SKILL.md").write_text(
                    f"---\nname: {name}\ndescription: demo\nmetadata:\n  source: local\n---\n",
                    encoding="utf-8")
            result = self.run_cli("list_skills.py", home=home)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            for name in roots:
                self.assertIn(name, result.stdout)

    def test_non_claude_client_does_not_create_claude_directory(self):
        with tempfile.TemporaryDirectory() as home:
            skill = Path(home) / ".gemini" / "skills" / "gemini-demo"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text(
                "---\nname: gemini-demo\ndescription: demo\nmetadata:\n  source: local\n---\n",
                encoding="utf-8")
            result = self.run_cli("list_skills.py", home=home)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse((Path(home) / ".claude").exists())
            self.assertTrue((Path(home) / ".skill-manager").is_dir())

    def test_list_includes_all_project_client_roots(self):
        with tempfile.TemporaryDirectory() as home:
            project = Path(home) / "project"
            markers = (".agents", ".claude", ".codex", ".gemini", ".grok", ".agent")
            for marker in markers:
                name = marker.removeprefix(".") + "-demo"
                skill = project / marker / "skills" / name
                skill.mkdir(parents=True)
                (skill / "SKILL.md").write_text(
                    f"---\nname: {name}\ndescription: demo\nmetadata:\n  source: local\n---\n",
                    encoding="utf-8")
            result = self.run_cli("list_skills.py", str(project), home=home)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            for marker in markers:
                self.assertIn(marker.removeprefix(".") + "-demo", result.stdout)


if __name__ == "__main__":
    unittest.main()
