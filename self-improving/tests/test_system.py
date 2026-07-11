from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import subprocess
import sys

from self_improving.config import default_config, load_config, resolved, write_config
from self_improving.events import normalize
from self_improving.hooks.common import dispatch
from self_improving.installer import MARKER, hook_is_installed, install_hooks, uninstall_hooks
from self_improving.indexing import broken_local_links, sync_index
from self_improving.security import contains_secret, sanitize
from self_improving.storage import initialize_memory


class SystemTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.config_path = self.home / "config/config.json"
        self.memory = self.home / "private-memory"
        self.claude = self.home / ".claude/settings.json"
        self.codex = self.home / ".codex/hooks.json"
        self.codex_config = self.home / ".codex/config.toml"
        self.claude.parent.mkdir(parents=True)
        self.codex.parent.mkdir(parents=True)
        self.claude.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "third-party"}]}]}}))
        self.codex.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "notchbar"}]}]}}))
        self.codex_config.write_text("[features]\nother = true\n")
        config = default_config(str(self.memory))
        config["state_root"] = str(self.home / "state")
        config["agents"]["claude"]["settings_file"] = str(self.claude)
        config["agents"]["claude"]["project_memory_root"] = str(self.home / ".claude/projects")
        config["agents"]["codex"]["hooks_file"] = str(self.codex)
        config["agents"]["codex"]["agents_file"] = str(self.home / ".codex/AGENTS.md")
        config["agents"]["codex"]["config_file"] = str(self.codex_config)
        config["persistence"]["capture_corrections"] = True
        self.config = config
        with patch.dict(os.environ, {"SELF_IMPROVING_CONFIG": str(self.config_path)}):
            write_config(config)
        initialize_memory(self.memory)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def env(self):
        return patch.dict(os.environ, {"SELF_IMPROVING_CONFIG": str(self.config_path)}, clear=False)

    def test_cli_help_version_and_invalid_exit_codes(self) -> None:
        root = Path(__file__).resolve().parents[1]
        env = {**os.environ, "PYTHONPATH": str(root)}
        for arguments, expected in ((["--help"], 0), (["--version"], 0), (["unknown"], 2)):
            result = subprocess.run(
                [sys.executable, "-m", "self_improving", *arguments],
                text=True,
                capture_output=True,
                env=env,
                check=False,
            )
            self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        version = subprocess.run(
            [sys.executable, "-m", "self_improving", "--version"],
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )
        self.assertEqual(version.stdout.strip(), "self-improving 2.0.0")

    def test_custom_paths_resolve(self) -> None:
        with self.env():
            self.assertEqual(Path(resolved(load_config())["memory_root"]), self.memory.resolve())

    def test_config_template_matches_runtime_defaults(self) -> None:
        template = json.loads((Path(__file__).resolve().parents[1] / "templates/config.json").read_text())
        self.assertEqual(template, default_config())

    def test_claude_and_codex_payloads_normalize(self) -> None:
        fixtures = Path(__file__).resolve().parents[1] / "examples/hook-payloads"
        claude_payload = json.loads((fixtures / "claude-user-prompt.json").read_text())
        codex_payload = json.loads((fixtures / "codex-user-prompt.json").read_text())
        claude = normalize("claude", "UserPromptSubmit", claude_payload)
        codex = normalize("codex", "UserPromptSubmit", codex_payload)
        self.assertEqual((claude.prompt, codex.prompt), ("不对，应该先核验事实", "不对，应该先核验事实"))

        claude_post = normalize("claude", "PostToolUse", json.loads((fixtures / "claude-post-tool.json").read_text()))
        codex_post = normalize("codex", "PostToolUse", json.loads((fixtures / "codex-post-tool.json").read_text()))
        self.assertIn("command failed", claude_post.tool_output)
        self.assertEqual(codex_post.tool_output, "command failed")

    def test_install_preserves_third_party_hooks(self) -> None:
        with self.env():
            install_hooks(self.config, "claude")
            install_hooks(self.config, "codex")
        self.assertIn("third-party", self.claude.read_text())
        self.assertIn("notchbar", self.codex.read_text())
        self.assertIn(MARKER, self.claude.read_text())
        self.assertIn(MARKER, self.codex.read_text())
        self.assertIn("hooks = true", self.codex_config.read_text())

    def test_mixed_group_preserves_third_party_hook(self) -> None:
        self.claude.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [
            {"type": "command", "command": "third-party"},
            {"type": "command", "command": "~/.claude/scripts/activator.sh"},
        ]}]}}))
        with self.env():
            install_hooks(self.config, "claude")
        content = self.claude.read_text()
        self.assertIn("third-party", content)
        self.assertNotIn("activator.sh", content)

    def test_codex_hooks_false_is_replaced_with_valid_toml(self) -> None:
        import tomllib

        self.codex_config.write_text("[features]\nhooks = false\nother = true\n")
        with self.env():
            install_hooks(self.config, "codex")
        parsed = tomllib.loads(self.codex_config.read_text())
        self.assertIs(parsed["features"]["hooks"], True)
        self.assertIs(parsed["features"]["other"], True)

    def test_invalid_codex_toml_does_not_change_hook_file(self) -> None:
        original = self.codex.read_text()
        self.codex_config.write_text("[features]\nhooks = false\nhooks = true\n")
        with self.env():
            with self.assertRaises(ValueError):
                install_hooks(self.config, "codex")
        self.assertEqual(self.codex.read_text(), original)

    def test_install_replaces_legacy_memory_hook(self) -> None:
        payload = json.loads(self.claude.read_text())
        payload.setdefault("hooks", {}).setdefault("UserPromptSubmit", []).append(
            {"hooks": [{"type": "command", "command": "~/.claude/skills/self-improving/scripts/activator.sh"}]}
        )
        self.claude.write_text(json.dumps(payload))
        with self.env():
            install_hooks(self.config, "claude")
        content = self.claude.read_text()
        self.assertNotIn("activator.sh", content)
        self.assertIn(MARKER, content)

    def test_uninstall_removes_only_managed_hooks(self) -> None:
        with self.env():
            install_hooks(self.config, "codex")
            uninstall_hooks(self.config, "codex")
        content = self.codex.read_text()
        self.assertIn("notchbar", content)
        self.assertNotIn(MARKER, content)

    def test_correction_capture_and_disable_switch(self) -> None:
        with self.env():
            result = dispatch("codex", "UserPromptSubmit", {"prompt": "不对，应该先核验事实"})
            self.assertEqual(result, 0)
            inbox = self.memory / ".learnings/CORRECTIONS_INBOX.md"
            first = inbox.read_text()
            self.assertIn("UNTRUSTED_USER_CANDIDATE", first)
            with patch.dict(os.environ, {"SELF_IMPROVING_PERSIST": "0"}, clear=False):
                dispatch("codex", "UserPromptSubmit", {"prompt": "你又错了，第二条"})
            self.assertEqual(inbox.read_text(), first)

    def test_authority_write_is_blocked(self) -> None:
        with self.env():
            result = dispatch(
                "claude",
                "PreToolUse",
                {"tool_name": "Write", "tool_input": {"file_path": str(self.memory / "memory.md")}},
            )
        self.assertEqual(result, 2)

        with self.env():
            relative = dispatch(
                "codex",
                "PreToolUse",
                {"cwd": str(self.memory), "tool_name": "Bash", "tool_input": {"command": "printf hacked >> memory.md"}},
            )
            read_only = dispatch(
                "codex",
                "PreToolUse",
                {"cwd": str(self.memory), "tool_name": "Bash", "tool_input": {"command": f"cat {self.memory / 'memory.md'}"}},
            )
        self.assertEqual(relative, 2)
        self.assertEqual(read_only, 0)

    def test_payload_cannot_override_declared_event(self) -> None:
        with self.env():
            with self.assertRaises(ValueError):
                dispatch("codex", "../../escape", {"hook_event_name": "SessionStart"})
        self.assertFalse((self.home / "escape.json").exists())

    def test_stale_hook_marker_is_not_reported_as_installed(self) -> None:
        groups = {}
        for event in ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"):
            groups[event] = [{"hooks": [{"type": "command", "command": f"/missing # {MARKER}"}]}]
        self.claude.write_text(json.dumps({"hooks": groups}))
        with self.env():
            self.assertFalse(hook_is_installed(self.config, "claude"))

    def test_session_start_injects_validated_memory_and_records_schema(self) -> None:
        with self.env():
            result = dispatch("codex", "SessionStart", {"hook_event_name": "SessionStart", "cwd": "/example"})
        self.assertEqual(result, 0)
        schema = self.home / "state/hook-schemas/codex-SessionStart.json"
        self.assertTrue(schema.exists())
        self.assertIn('"cwd": "str"', schema.read_text())

    def test_index_is_stable_when_candidate_log_changes(self) -> None:
        ok, path = sync_index(self.memory)
        self.assertTrue(ok)
        first = path.read_text()
        inbox = self.memory / ".learnings/CORRECTIONS_INBOX.md"
        inbox.write_text(inbox.read_text() + "| now | test | changed | fp | candidate |\n")
        sync_index(self.memory)
        self.assertEqual(path.read_text(), first)

    def test_local_link_check_and_secret_redaction(self) -> None:
        note = self.memory / "2026-07-11-note.md"
        note.write_text("# Note\n\n[missing](missing.md)\n")
        self.assertEqual(broken_local_links(self.memory), ["2026-07-11-note.md -> missing.md"])
        secret = "api_key=abcdefghijklmnopqrstuvwxyz"
        self.assertTrue(contains_secret(secret))
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz", sanitize(secret))

    def test_only_enabled_agent_gets_skill_link(self) -> None:
        from self_improving.installer import install_skill_links

        self.config["agents"]["codex"]["enabled"] = False
        with patch("pathlib.Path.home", return_value=self.home):
            destinations = [path for path, _ in install_skill_links(self.config)]
        self.assertEqual(destinations, [self.home / ".claude/skills/self-improving"])

    def test_existing_agent_skill_backups_do_not_collide(self) -> None:
        from self_improving.installer import install_skill_links

        claude_skill = self.home / ".claude/skills/self-improving"
        codex_skill = self.home / ".codex/skills/self-improving"
        claude_skill.mkdir(parents=True)
        codex_skill.mkdir(parents=True)
        (claude_skill / "old.txt").write_text("claude")
        (codex_skill / "old.txt").write_text("codex")
        with patch("pathlib.Path.home", return_value=self.home):
            results = install_skill_links(self.config)
        backups = [backup for _, backup in results if backup]
        self.assertEqual(len(set(backups)), 2)
        self.assertEqual({backup.joinpath("old.txt").read_text() for backup in backups}, {"claude", "codex"})

    def test_fresh_install_in_empty_home(self) -> None:
        fresh = self.home / "fresh-home"
        (fresh / ".claude").mkdir(parents=True)
        (fresh / ".codex").mkdir(parents=True)
        (fresh / ".claude/settings.json").write_text("{}")
        (fresh / ".codex/hooks.json").write_text("{}")
        env = {
            **os.environ,
            "HOME": str(fresh),
            "SELF_IMPROVING_CONFIG": str(fresh / ".config/self-improving/config.json"),
            "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
        }
        installed = subprocess.run(
            [
                sys.executable,
                "-m",
                "self_improving",
                "init",
                "--agents",
                "claude,codex",
                "--memory-root",
                str(fresh / "memory"),
            ],
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )
        self.assertEqual(installed.returncode, 0, installed.stdout + installed.stderr)
        self.assertTrue((fresh / "memory/memory.md").exists())
        self.assertTrue((fresh / "memory/index.md").exists())
        installed_config = json.loads((fresh / ".config/self-improving/config.json").read_text())
        self.assertFalse(installed_config["persistence"]["capture_corrections"])
        self.assertTrue((fresh / ".claude/skills/self-improving").is_symlink())
        self.assertTrue((fresh / ".codex/skills/self-improving").is_symlink())
        self.assertIn(MARKER, (fresh / ".claude/settings.json").read_text())
        self.assertIn(MARKER, (fresh / ".codex/hooks.json").read_text())

        settings = json.loads((fresh / ".claude/settings.json").read_text())
        hook_command = settings["hooks"]["SessionStart"][-1]["hooks"][0]["command"]
        hook_env = {key: value for key, value in env.items() if key != "SELF_IMPROVING_CONFIG"}
        hook_run = subprocess.run(
            hook_command,
            input=json.dumps({"hook_event_name": "SessionStart", "cwd": str(fresh)}),
            text=True,
            capture_output=True,
            env=hook_env,
            shell=True,
            check=False,
        )
        self.assertEqual(hook_run.returncode, 0, hook_run.stdout + hook_run.stderr)
        self.assertIn("self-improving-memory", hook_run.stdout)

        for command in (("upgrade",), ("sync",), ("doctor",)):
            result = subprocess.run(
                [sys.executable, "-m", "self_improving", *command],
                text=True,
                capture_output=True,
                env=env,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        removed = subprocess.run(
            [sys.executable, "-m", "self_improving", "uninstall", "--keep-data"],
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )
        self.assertEqual(removed.returncode, 0, removed.stdout + removed.stderr)
        self.assertTrue((fresh / "memory/memory.md").exists())
        self.assertNotIn(MARKER, (fresh / ".claude/settings.json").read_text())
        self.assertNotIn(MARKER, (fresh / ".codex/hooks.json").read_text())

    def test_uninstall_rejects_unsafe_or_unconfirmed_delete_before_changes(self) -> None:
        fresh = self.home / "delete-home"
        (fresh / ".claude").mkdir(parents=True)
        settings = fresh / ".claude/settings.json"
        settings.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": f"managed # {MARKER}"}]}]}}))
        config = default_config(str(fresh))
        config["agents"]["codex"]["enabled"] = False
        config["agents"]["claude"]["settings_file"] = str(settings)
        config_path = fresh / ".config/self-improving/config.json"
        with patch.dict(os.environ, {"SELF_IMPROVING_CONFIG": str(config_path)}):
            write_config(config)
        env = {**os.environ, "HOME": str(fresh), "SELF_IMPROVING_CONFIG": str(config_path), "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
        rejected = subprocess.run(
            [sys.executable, "-m", "self_improving", "uninstall", "--delete-data", "--confirm", str(fresh)],
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )
        self.assertEqual(rejected.returncode, 1)
        self.assertIn(MARKER, settings.read_text())
        self.assertTrue(fresh.exists())

        safe_memory = fresh / "memory"
        initialize_memory(safe_memory)
        config["memory_root"] = str(safe_memory)
        with patch.dict(os.environ, {"SELF_IMPROVING_CONFIG": str(config_path)}):
            write_config(config)
        unconfirmed = subprocess.run(
            [sys.executable, "-m", "self_improving", "uninstall", "--delete-data", "--confirm", "wrong"],
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )
        self.assertEqual(unconfirmed.returncode, 2)
        self.assertIn(MARKER, settings.read_text())
        self.assertTrue(safe_memory.exists())

    def test_legacy_migration_keeps_memory_and_writes_manifest(self) -> None:
        fresh = self.home / "legacy-home"
        memory = fresh / "Documents/obsidian/self-improving-memory"
        initialize_memory(memory)
        (fresh / ".claude").mkdir(parents=True)
        (fresh / ".claude/settings.json").write_text("{}")
        env = {
            **os.environ,
            "HOME": str(fresh),
            "SELF_IMPROVING_CONFIG": str(fresh / ".config/self-improving/config.json"),
            "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
        }
        migrated = subprocess.run(
            [sys.executable, "-m", "self_improving", "migrate", "legacy", "--apply"],
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )
        self.assertEqual(migrated.returncode, 0, migrated.stdout + migrated.stderr)
        self.assertTrue((memory / "memory.md").exists())
        manifests = list((fresh / ".local/state/self-improving/migrations").glob("legacy-*.json"))
        self.assertEqual(len(manifests), 1)
        self.assertIn(MARKER, (fresh / ".claude/settings.json").read_text())
        migrated_config = json.loads((fresh / ".config/self-improving/config.json").read_text())
        self.assertFalse(migrated_config["agents"]["codex"]["enabled"])
        self.assertFalse((fresh / ".codex/skills/self-improving").exists())


if __name__ == "__main__":
    unittest.main()
