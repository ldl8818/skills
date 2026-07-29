import io
import os
import sys
import tarfile
import tempfile
import unittest
from unittest import mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import core
import update_skill


class CoreContractTests(unittest.TestCase):
    @staticmethod
    def _tarball(members):
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode="w:gz") as tf:
            for member, content in members:
                if content is None:
                    tf.addfile(member)
                else:
                    tf.addfile(member, io.BytesIO(content.encode("utf-8")))
        return data.getvalue()

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

    def test_codex_plugin_parser_does_not_leak_into_other_toml_tables(self):
        with tempfile.TemporaryDirectory() as root:
            config = Path(root) / "config.toml"
            config.write_text(
                '[plugins."demo@market"]\nenabled = false\n\n[feature]\nenabled = true\n',
                encoding="utf-8")
            self.assertEqual(core.enabled_codex_plugins(str(config)),
                             {"demo@market": False})

    def test_global_discovery_classifies_agents_as_shared_global(self):
        with tempfile.TemporaryDirectory() as root:
            agents = Path(root) / ".agents" / "skills" / "demo"
            agents.mkdir(parents=True)
            (agents / "SKILL.md").write_text(
                "---\nname: demo\ndescription: demo\nmetadata:\n  source: local\n---\n",
                encoding="utf-8")
            for runtime in (".claude", ".codex"):
                target = Path(root) / runtime / "skills" / "demo"
                target.parent.mkdir(parents=True)
                target.symlink_to(agents, target_is_directory=True)
            roots = [
                ("共享", str(agents.parent)),
                ("Claude", str(Path(root) / ".claude" / "skills")),
                ("Codex", str(Path(root) / ".codex" / "skills")),
            ]
            with mock.patch.object(core, "global_skill_roots", return_value=roots):
                fps, touched = {}, []
                skills = core.collect_global_direct({}, fps, touched, {})
                self.assertEqual(len(skills), 1)
                self.assertEqual(skills[0].scope_label, "全局直装（共享）")

    def test_global_root_matrix_covers_common_clients(self):
        self.assertEqual([label for label, _ in core.global_skill_roots()], [
            "共享", "Claude", "Gemini CLI", "Grok", "Antigravity 2.0",
            "Antigravity IDE", "Antigravity CLI", "Codex",
        ])
        suffixes = [Path(path).parts[-3:] for _, path in core.global_skill_roots()]
        self.assertIn((".gemini", "config", "skills"), suffixes)
        self.assertIn((".gemini", "antigravity", "skills"), suffixes)
        self.assertIn((".gemini", "antigravity-cli", "skills"), suffixes)

    def test_project_root_matrix_covers_common_clients_and_antigravity_alias(self):
        roots = dict(core.project_skill_roots("/workspace"))
        self.assertEqual(set(roots), {
            "共享", "Claude", "Codex", "Gemini CLI", "Grok", "Antigravity 旧别名",
        })
        self.assertEqual(roots["Codex"], "/workspace/.codex/skills")
        self.assertEqual(roots["Antigravity 旧别名"], "/workspace/.agent/skills")

    def test_project_detection_accepts_every_supported_project_root(self):
        markers = (
            (".agents", "skills"), (".claude", "skills"),
            (".codex", "skills"), (".gemini", "skills"),
            (".grok", "skills"), (".agent", "skills"),
        )
        for marker in markers:
            with self.subTest(marker=marker), tempfile.TemporaryDirectory() as root:
                project = Path(root) / "project"
                project.joinpath(*marker).mkdir(parents=True)
                self.assertTrue(core.is_project_dir(str(project)))

    def test_project_detection_normalizes_home_symlink_alias(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root) / "home"
            (home / ".claude" / "skills").mkdir(parents=True)
            alias = Path(root) / "alias"
            alias.symlink_to(home, target_is_directory=True)
            with mock.patch.object(core, "HOME", str(home)), \
                    mock.patch.object(core, "CLAUDE_DIR", str(home / ".claude")):
                self.assertFalse(core.is_project_dir(str(alias)))

    def test_project_discovery_includes_agents_and_deduplicates_alias(self):
        with tempfile.TemporaryDirectory() as root:
            project = Path(root) / "project"
            shared = project / ".agents" / "skills" / "demo"
            shared.mkdir(parents=True)
            (shared / "SKILL.md").write_text(
                "---\nname: demo\ndescription: demo\nmetadata:\n  source: local\n---\n",
                encoding="utf-8")
            claude = project / ".claude" / "skills" / "demo"
            claude.parent.mkdir(parents=True)
            claude.symlink_to(shared, target_is_directory=True)
            skills = core.collect_project_direct(str(project), {}, {}, [], {})
            self.assertEqual(len(skills), 1)
            self.assertEqual(skills[0].scope_label, "项目:project")
            self.assertEqual(Path(skills[0].path), shared)

    def test_download_rejects_shell_metacharacter_url(self):
        with tempfile.TemporaryDirectory() as root, self.assertRaises(ValueError):
            update_skill.download_repo("https://$(touch bad)@github.com/a/b", "a" * 40, root)

    def test_download_rejects_untrusted_ref(self):
        with tempfile.TemporaryDirectory() as root, self.assertRaises(ValueError):
            update_skill.download_repo("https://github.com/a/b", "$(touch bad)", root)

    def test_download_materializes_safe_internal_symlink(self):
        source = tarfile.TarInfo("repo/AGENTS.md")
        source.size = len(b"skill instructions")
        link = tarfile.TarInfo("repo/CLAUDE.md")
        link.type = tarfile.SYMTYPE
        link.linkname = "AGENTS.md"
        payload = self._tarball([(source, "skill instructions"), (link, None)])

        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                self.close()

        with tempfile.TemporaryDirectory() as root, \
                mock.patch.object(update_skill.urllib.request, "urlopen",
                                  return_value=Response(payload)):
            self.assertTrue(update_skill.download_repo(
                "https://github.com/a/b", "a" * 40, root))
            self.assertEqual(Path(root, "CLAUDE.md").read_text(encoding="utf-8"),
                             "skill instructions")
            self.assertFalse(Path(root, "CLAUDE.md").is_symlink())

    def test_download_rejects_escape_symlink(self):
        link = tarfile.TarInfo("repo/CLAUDE.md")
        link.type = tarfile.SYMTYPE
        link.linkname = "../../outside"
        payload = self._tarball([(link, None)])

        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                self.close()

        with tempfile.TemporaryDirectory() as root, \
                mock.patch.object(update_skill.urllib.request, "urlopen",
                                  return_value=Response(payload)):
            with self.assertRaises(ValueError):
                update_skill.download_repo("https://github.com/a/b", "a" * 40, root)

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

            def fail_merge(_src, stage, _fields, _md_name="SKILL.md"):
                Path(stage, "SKILL.md").write_text("partial", encoding="utf-8")
                raise OSError("simulated disk failure")

            with mock.patch.object(core, "resolve_direct_path", return_value=(str(live), None)), \
                    mock.patch.object(update_skill, "BACKUP_ROOT", str(backup)), \
                    mock.patch.object(update_skill, "latest_release", return_value=("v1.0.0", "a" * 40)), \
                    mock.patch.object(update_skill, "download_repo", side_effect=fake_download), \
                    mock.patch.object(update_skill, "get_commit_date", return_value="07-13"), \
                    mock.patch.object(update_skill, "merge_skill_dir", side_effect=fail_merge):
                self.assertFalse(update_skill.update_direct_skill("demo"))
            self.assertEqual((live / "SKILL.md").read_text(encoding="utf-8"), original)


class UpdateChannelTests(unittest.TestCase):
    """跟随通道（release / main）与禁用态更新。"""

    URL = "https://github.com/acme/demo"

    def test_default_follows_release_tag(self):
        with mock.patch.object(update_skill, "latest_release",
                               return_value=("v2.0.0", "b" * 40)):
            ref, sha, channel = update_skill.resolve_update_target(self.URL, {})
        self.assertEqual((ref, channel), ("v2.0.0", ""))
        self.assertEqual(sha, "b" * 40)

    def test_ref_main_uses_head(self):
        with mock.patch.object(update_skill, "get_remote_hash",
                               return_value="c" * 40):
            ref, sha, channel = update_skill.resolve_update_target(
                self.URL, {}, "main")
        self.assertEqual((ref, channel), ("main", "main"))
        self.assertEqual(sha, "c" * 40)

    def test_main_channel_is_sticky(self):
        """装过 main 的 skill，无参 update 必须继续跟 main，不能悄悄退回 tag。"""
        with mock.patch.object(update_skill, "get_remote_hash",
                               return_value="d" * 40):
            _, _, channel = update_skill.resolve_update_target(
                self.URL, {"github_ref": "main"})
        self.assertEqual(channel, "main")

    def test_ref_release_leaves_main_channel(self):
        with mock.patch.object(update_skill, "latest_release",
                               return_value=("v2.0.0", "e" * 40)):
            ref, _, channel = update_skill.resolve_update_target(
                self.URL, {"github_ref": "main"}, "release")
        self.assertEqual((ref, channel), ("v2.0.0", ""))

    def test_unknown_ref_rejected(self):
        with self.assertRaises(ValueError):
            update_skill.resolve_update_target(self.URL, {}, "feature/x")

    def _run_update(self, root, original, ref_arg=None, upstream_version=None):
        """跑一次成功的直装更新，返回落盘后的 SKILL.md 文本。"""
        live = Path(root) / "skills" / "demo"
        live.mkdir(parents=True)
        (live / "SKILL.md").write_text(original, encoding="utf-8")

        def fake_download(_url, _ref, dest):
            Path(dest, "SKILL.md").write_text(
                "---\nname: demo\ndescription: new\n---\n", encoding="utf-8")
            if upstream_version:
                Path(dest, "VERSION").write_text(upstream_version,
                                                 encoding="utf-8")
            return True

        with mock.patch.object(core, "resolve_direct_path",
                               return_value=(str(live), None)), \
                mock.patch.object(update_skill, "BACKUP_ROOT",
                                  str(Path(root) / "backups")), \
                mock.patch.object(update_skill, "latest_release",
                                  return_value=("v1.0.0", "a" * 40)), \
                mock.patch.object(update_skill, "get_remote_hash",
                                  return_value="f" * 40), \
                mock.patch.object(update_skill, "download_repo",
                                  side_effect=fake_download), \
                mock.patch.object(update_skill, "get_commit_date",
                                  return_value="07-13"):
            self.assertTrue(update_skill.update_direct_skill(
                "demo", None, ref_arg))
        return (live / "SKILL.md").read_text(encoding="utf-8")

    BASE_MD = ("---\nname: demo\ndescription: old\nmetadata:\n"
               "  github_url: \"https://github.com/a/b\"\n---\n")

    def test_release_channel_writes_no_empty_ref_field(self):
        """跟 release 的 skill 不该平白多一行 github_ref: ""，元数据只记真实状态。"""
        with tempfile.TemporaryDirectory() as root:
            out = self._run_update(root, self.BASE_MD)
        self.assertNotIn("github_ref", out)

    def test_main_channel_suffixes_upstream_version(self):
        with tempfile.TemporaryDirectory() as root:
            out = self._run_update(root, self.BASE_MD, "main",
                                   upstream_version="3.32.0")
        self.assertIn('github_ref: "main"', out)
        self.assertIn('version: "3.32.0+main"', out)

    def test_main_channel_without_upstream_version_invents_nothing(self):
        """上游没 VERSION 文件时不得编出 version: main —— 那不是版本号。"""
        with tempfile.TemporaryDirectory() as root:
            out = self._run_update(root, self.BASE_MD, "main")
        self.assertIn('github_ref: "main"', out)
        self.assertNotIn("version:", out)

    def test_ref_release_clears_existing_main_marker(self):
        marked = self.BASE_MD.replace(
            '  github_url: "https://github.com/a/b"\n',
            '  github_url: "https://github.com/a/b"\n  github_ref: "main"\n')
        with tempfile.TemporaryDirectory() as root:
            out = self._run_update(root, marked, "release")
        self.assertIn('github_ref: ""', out)

    def test_disabled_skill_stays_disabled_after_merge(self):
        """禁用的 skill 更新后不得多出一个 SKILL.md，否则等于被静默启用。"""
        with tempfile.TemporaryDirectory() as td:
            src, dst = Path(td, "src"), Path(td, "dst")
            src.mkdir()
            dst.mkdir()
            Path(src, "SKILL.md").write_text(
                "---\nname: demo\ndescription: up\n---\n", encoding="utf-8")
            Path(dst, "SKILL.md.disabled").write_text(
                "---\nname: demo\ndescription: old\n---\n", encoding="utf-8")

            update_skill.merge_skill_dir(str(src), str(dst), {},
                                         "SKILL.md.disabled")

            self.assertFalse(Path(dst, "SKILL.md").exists())
            self.assertIn("description: up",
                          Path(dst, "SKILL.md.disabled").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
