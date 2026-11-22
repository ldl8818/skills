"""Regression tests for Antigravity, Kimi Code, and WorkBuddy Hook adapters."""
from __future__ import annotations

from copy import deepcopy
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from self_improving import knowledge
from self_improving.config import OPTIONAL_AGENT_DEFAULTS, default_config, write_config
from self_improving.doctor import run_checks
from self_improving.hooks.common import dispatch
from self_improving.installer import (
    ANTIGRAVITY_GROUP_KEY,
    hook_is_installed,
    install_hooks,
    managed_hooks_present,
    uninstall_hooks,
)
from self_improving.storage import VERIFIED_RELATIVE, initialize_memory


class MultiAgentAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.root = self.base / "memory"
        self.state = self.base / "state"
        self.config_path = self.base / "config.json"
        self.config = default_config(str(self.root))
        self.config["state_root"] = str(self.state)
        self.config["agents"]["claude"]["enabled"] = False
        self.config["agents"]["claude"]["settings_file"] = str(self.base / "claude.json")
        self.config["agents"]["codex"]["hooks_file"] = str(self.base / "codex.json")
        self.config["agents"]["codex"]["config_file"] = str(self.base / "codex.toml")
        for platform, defaults in OPTIONAL_AGENT_DEFAULTS.items():
            self.config["agents"][platform] = deepcopy(defaults)
            self.config["agents"][platform]["enabled"] = True
        self.config["agents"]["antigravity"]["hooks_file"] = str(self.base / "agy-hooks.json")
        self.config["agents"]["kimi"]["config_file"] = str(self.base / "kimi-config.toml")
        self.config["agents"]["workbuddy"]["settings_file"] = str(self.base / "workbuddy-settings.json")
        initialize_memory(self.root)
        (self.root / "guide.md").write_text("# Guide\nSynthetic verified domain body.\n", encoding="utf-8")
        (self.root / "knowledge-catalog.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "roots": [str(self.root)],
                    "entries": [
                        {
                            "id": "guide",
                            "path": "guide.md",
                            "status": "active",
                            "scope": "global",
                            "triggers": ["排查", "排障"],
                            "sections": [],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        env = patch.dict(os.environ, {"SELF_IMPROVING_CONFIG": str(self.config_path)})
        env.start()
        self.addCleanup(env.stop)
        write_config(self.config, self.config_path)
        knowledge.accept(self.config, knowledge.check(self.config)["revision"])

    def call_hook(self, platform: str, event: str, payload: dict) -> str:
        out = io.StringIO()
        with redirect_stdout(out):
            dispatch(platform, event, payload)
        return out.getvalue()

    def test_antigravity_session_preinvocation_dedup_and_guard(self) -> None:
        start_raw = self.call_hook(
            "antigravity",
            "SessionStart",
            {
                "conversationId": "conv-agy-1",
                "workspacePaths": [str(self.base)],
                "hookEventName": "SessionStart",
            },
        )
        start = json.loads(start_raw)
        self.assertIn("injectSteps", start)
        self.assertIn("knowledge", start["injectSteps"][0]["systemMessage"]["systemMessage"])

        first_raw = self.call_hook(
            "antigravity",
            "PreInvocation",
            {
                "conversationId": "conv-agy-1",
                "cwd": str(self.base),
                "lastUserInput": "帮我排查一下这个问题",
                "invocationNum": 1,
            },
        )
        first = json.loads(first_raw)
        self.assertIn("Synthetic verified domain body.", first["injectSteps"][0]["systemMessage"]["systemMessage"])

        # Same user turn, second model invocation after a tool call -> deduplicated to {}.
        second_raw = self.call_hook(
            "antigravity",
            "PreInvocation",
            {
                "conversationId": "conv-agy-1",
                "cwd": str(self.base),
                "lastUserInput": "帮我排查一下这个问题",
                "invocationNum": 2,
            },
        )
        self.assertEqual(json.loads(second_raw), {})

        # Next user turn with unrelated prompt -> valid empty JSON object {}.
        third_raw = self.call_hook(
            "antigravity",
            "PreInvocation",
            {
                "conversationId": "conv-agy-1",
                "cwd": str(self.base),
                "lastUserInput": "谢谢",
                "invocationNum": 3,
            },
        )
        self.assertEqual(json.loads(third_raw), {})

        # PreToolUse guard on write_file targeting verified ledger -> ask.
        guard_file = json.loads(
            self.call_hook(
                "antigravity",
                "PreToolUse",
                {
                    "conversationId": "conv-agy-1",
                    "cwd": str(self.base),
                    "toolCall": {
                        "name": "write_file",
                        "args": {"Path": str(self.root / VERIFIED_RELATIVE)},
                    },
                },
            )
        )
        self.assertEqual(guard_file["decision"], "ask")

        # PreToolUse guard on run_command invoking review approve -> ask.
        guard_cmd = json.loads(
            self.call_hook(
                "antigravity",
                "PreToolUse",
                {
                    "conversationId": "conv-agy-1",
                    "cwd": str(self.base),
                    "toolCall": {
                        "name": "run_command",
                        "args": {
                            "CommandLine": "python3 -m self_improving review approve --fingerprint '[fp:123456789abc]'"
                        },
                    },
                },
            )
        )
        self.assertEqual(guard_cmd["decision"], "ask")

    def test_antigravity_pretool_passes_safe_calls_to_default_policy(self) -> None:
        calls = (
            ("run_command", {"CommandLine": "ls -la"}),
            ("write_file", {"Path": str(self.base / "ordinary.txt")}),
            ("edit_file", {"Path": str(self.base / "ordinary.txt")}),
        )
        for enabled in (True, False):
            self.config["agents"]["antigravity"]["enabled"] = enabled
            write_config(self.config, self.config_path)
            for name, args in calls:
                with self.subTest(enabled=enabled, name=name):
                    result = self.call_hook(
                        "antigravity",
                        "PreToolUse",
                        {"workspacePaths": [str(self.base)], "toolCall": {"name": name, "args": args}},
                    )
                    self.assertEqual(json.loads(result), {"decision": "allow"})

    def test_antigravity_installer_preserves_other_named_hooks(self) -> None:
        hooks_path = Path(self.config["agents"]["antigravity"]["hooks_file"])
        hooks_path.write_text(
            json.dumps(
                {
                    "easyinput-status": {"Stop": [{"type": "command", "command": "echo ok", "timeout": 5}]},
                    "one-sidebar-naming": {"PreInvocation": [{"type": "command", "command": "echo title", "timeout": 5}]},
                }
            ),
            encoding="utf-8",
        )
        install_hooks(self.config, "antigravity")
        self.assertTrue(hook_is_installed(self.config, "antigravity"))
        self.assertTrue(managed_hooks_present(self.config, "antigravity"))
        saved = json.loads(hooks_path.read_text(encoding="utf-8"))
        self.assertIn("easyinput-status", saved)
        self.assertIn("one-sidebar-naming", saved)
        self.assertEqual(set(saved[ANTIGRAVITY_GROUP_KEY]), {"SessionStart", "PreInvocation", "PreToolUse"})

        # Idempotent reinstall.
        install_hooks(self.config, "antigravity")
        self.assertTrue(hook_is_installed(self.config, "antigravity"))

        uninstall_hooks(self.config, "antigravity")
        self.assertFalse(hook_is_installed(self.config, "antigravity"))
        self.assertFalse(managed_hooks_present(self.config, "antigravity"))
        after = json.loads(hooks_path.read_text(encoding="utf-8"))
        self.assertIn("easyinput-status", after)
        self.assertNotIn(ANTIGRAVITY_GROUP_KEY, after)

    def test_kimi_array_prompt_guard_and_toml_installer(self) -> None:
        out = self.call_hook(
            "kimi",
            "UserPromptSubmit",
            {
                "session_id": "kimi-sess-1",
                "cwd": str(self.base),
                "prompt": [{"type": "text", "text": "请帮我排障一下"}],
            },
        )
        self.assertIn("Synthetic verified domain body.", out)

        # Kimi only blocks on permissionDecision == "deny".
        guard = json.loads(
            self.call_hook(
                "kimi",
                "PreToolUse",
                {
                    "session_id": "kimi-sess-1",
                    "cwd": str(self.base),
                    "tool_name": "Write",
                    "tool_input": {"path": str(self.root / VERIFIED_RELATIVE)},
                },
            )
        )
        self.assertEqual(guard["hookSpecificOutput"]["permissionDecision"], "deny")

        # TOML installer preserves existing Kimi settings and third-party [[hooks]].
        toml_path = Path(self.config["agents"]["kimi"]["config_file"])
        toml_path.write_text(
            'default_model = "kimi-code/k3.1-pro"\n\n'
            '[[hooks]]\n'
            'event = "SessionStart"\n'
            'command = "echo third-party"\n'
            'timeout = 10\n',
            encoding="utf-8",
        )
        install_hooks(self.config, "kimi")
        self.assertTrue(hook_is_installed(self.config, "kimi"))
        self.assertTrue(managed_hooks_present(self.config, "kimi"))
        parsed = tomllib.loads(toml_path.read_text(encoding="utf-8"))
        self.assertEqual(parsed["default_model"], "kimi-code/k3.1-pro")
        self.assertEqual(len(parsed["hooks"]), 4)
        self.assertEqual(parsed["hooks"][0]["command"], "echo third-party")

        # Idempotent reinstall does not duplicate [[hooks]].
        install_hooks(self.config, "kimi")
        parsed_again = tomllib.loads(toml_path.read_text(encoding="utf-8"))
        self.assertEqual(len(parsed_again["hooks"]), 4)

        uninstall_hooks(self.config, "kimi")
        self.assertFalse(hook_is_installed(self.config, "kimi"))
        self.assertFalse(managed_hooks_present(self.config, "kimi"))
        parsed_after = tomllib.loads(toml_path.read_text(encoding="utf-8"))
        self.assertEqual(len(parsed_after["hooks"]), 1)
        self.assertEqual(parsed_after["hooks"][0]["command"], "echo third-party")

    def test_workbuddy_structured_context_guard_and_settings_installer(self) -> None:
        start = json.loads(
            self.call_hook(
                "workbuddy",
                "SessionStart",
                {"session_id": "wb-sess-1", "cwd": str(self.base), "source": "startup"},
            )
        )
        self.assertEqual(start["hookSpecificOutput"]["hookEventName"], "SessionStart")
        self.assertIn("knowledge", start["hookSpecificOutput"]["additionalContext"])

        prompt = json.loads(
            self.call_hook(
                "workbuddy",
                "UserPromptSubmit",
                {"session_id": "wb-sess-1", "cwd": str(self.base), "prompt": "帮我排查这个问题"},
            )
        )
        self.assertEqual(prompt["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit")
        self.assertIn("Synthetic verified domain body.", prompt["hookSpecificOutput"]["additionalContext"])

        guard = json.loads(
            self.call_hook(
                "workbuddy",
                "PreToolUse",
                {
                    "session_id": "wb-sess-1",
                    "cwd": str(self.base),
                    "tool_name": "Write",
                    "tool_input": {"file_path": str(self.root / VERIFIED_RELATIVE)},
                },
            )
        )
        self.assertEqual(guard["hookSpecificOutput"]["permissionDecision"], "ask")

        settings_path = Path(self.config["agents"]["workbuddy"]["settings_file"])
        settings_path.write_text(
            json.dumps({"enabledPlugins": {"demo": True}, "sandbox": {"enabled": False}}),
            encoding="utf-8",
        )
        install_hooks(self.config, "workbuddy")
        self.assertTrue(hook_is_installed(self.config, "workbuddy"))
        saved = json.loads(settings_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["enabledPlugins"], {"demo": True})
        self.assertEqual(set(saved["hooks"]), {"SessionStart", "UserPromptSubmit", "PreToolUse"})

        uninstall_hooks(self.config, "workbuddy")
        self.assertFalse(hook_is_installed(self.config, "workbuddy"))
        self.assertFalse(managed_hooks_present(self.config, "workbuddy"))

    def test_doctor_validates_all_enabled_multi_agent_adapters(self) -> None:
        for platform in ("codex", "antigravity", "kimi", "workbuddy"):
            install_hooks(self.config, platform)
        checks = {check.name: check for check in run_checks()}
        for platform in ("codex", "antigravity", "kimi", "workbuddy"):
            self.assertTrue(checks[f"{platform} Hook"].passed, f"{platform} Hook check failed")


if __name__ == "__main__":
    unittest.main()
