import os
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import core
import update_skill


class CoreContractTests(unittest.TestCase):
    def test_safe_component_rejects_traversal(self):
        for value in ("..", "../x", "a/b", "/tmp/x", "a\\b", ""):
            with self.subTest(value=value), self.assertRaises(ValueError):
                core.safe_component(value)

    def test_contained_path_rejects_escape(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(ValueError):
                core.contained_path(root, "..", "outside")

    def test_read_json_distinguishes_missing_from_corrupt(self):
        with tempfile.TemporaryDirectory() as root:
            missing = os.path.join(root, "missing.json")
            self.assertEqual(core.read_json(missing, {"default": True}), {"default": True})
            broken = os.path.join(root, "broken.json")
            Path(broken).write_text("{", encoding="utf-8")
            # 损坏必须硬失败（不许空表顶上），且报错要指名是哪个文件坏了
            with self.assertRaises(SystemExit) as ctx:
                core.read_json(broken, {})
            self.assertIn(broken, str(ctx.exception))

    def test_write_json_is_complete_and_leaves_no_temp_file(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "state.json")
            core.write_json(path, {"ok": "值"})
            self.assertEqual(core.read_json(path), {"ok": "值"})
            self.assertEqual(os.listdir(root), ["state.json"])

    def test_metadata_fields_are_flattened_for_runtime(self):
        text = "---\nname: demo\ndescription: demo\nmetadata:\n  version: \"2.0.0\"\n  source: local\n---\n"
        self.assertEqual(core.parse_frontmatter(text)["version"], "2.0.0")
        self.assertEqual(core.parse_frontmatter(text)["source"], "local")

    def test_writer_puts_managed_fields_under_metadata(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "SKILL.md")
            Path(path).write_text("---\nname: demo\ndescription: demo\n---\n", encoding="utf-8")
            core.set_frontmatter_field(path, "version", "1.2.3")
            text = Path(path).read_text(encoding="utf-8")
            self.assertIn("metadata:\n  version: \"1.2.3\"", text)

    def test_writer_migrates_legacy_top_level_managed_field(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "SKILL.md")
            Path(path).write_text(
                "---\nname: demo\ndescription: demo\nversion: 1.0.0\n---\n", encoding="utf-8")
            core.set_frontmatter_field(path, "version", "1.0.1")
            text = Path(path).read_text(encoding="utf-8")
            self.assertNotIn("\nversion:", text)
            self.assertIn("metadata:\n  version: \"1.0.1\"", text)

    def test_download_rejects_shell_metacharacter_url(self):
        with tempfile.TemporaryDirectory() as root, self.assertRaises(ValueError):
            update_skill.download_repo("https://$(touch bad)@github.com/a/b", "a" * 40, root)

    def test_download_rejects_untrusted_ref(self):
        with tempfile.TemporaryDirectory() as root, self.assertRaises(ValueError):
            update_skill.download_repo("https://github.com/a/b", "$(touch bad)", root)

    def test_find_skill_source_rejects_github_path_escape(self):
        with tempfile.TemporaryDirectory() as root, self.assertRaises(ValueError):
            update_skill.find_skill_source(root, "demo", "../../outside")

    def test_direct_update_failure_keeps_live_directory_unchanged(self):
        with tempfile.TemporaryDirectory() as root:
            skills = Path(root) / "skills"
            live = skills / "demo"
            live.mkdir(parents=True)
            original = "---\nname: demo\ndescription: old\nmetadata:\n  github_url: \"https://github.com/a/b\"\n---\n"
            (live / "SKILL.md").write_text(original, encoding="utf-8")
            backup = Path(root) / "backups"

            def fake_download(_url, _ref, dest):
                Path(dest, "SKILL.md").write_text(
                    "---\nname: demo\ndescription: new\n---\n", encoding="utf-8")
                return True

            def fail_merge(_src, stage, _fields):
                Path(stage, "SKILL.md").write_text("partial", encoding="utf-8")
                raise OSError("simulated disk failure")

            with mock.patch.object(update_skill, "SKILLS_DIR", str(skills)), \
                    mock.patch.object(update_skill, "BACKUP_ROOT", str(backup)), \
                    mock.patch.object(update_skill, "latest_release", return_value=("v1.0.0", "a" * 40)), \
                    mock.patch.object(update_skill, "download_repo", side_effect=fake_download), \
                    mock.patch.object(update_skill, "get_commit_date", return_value="07-13"), \
                    mock.patch.object(update_skill, "merge_skill_dir", side_effect=fail_merge):
                self.assertFalse(update_skill.update_direct_skill("demo"))
            self.assertEqual((live / "SKILL.md").read_text(encoding="utf-8"), original)


if __name__ == "__main__":
    unittest.main()
