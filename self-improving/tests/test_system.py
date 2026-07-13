from __future__ import annotations

import json
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout
import subprocess
import sys

from self_improving import __version__
from self_improving.config import default_config, load_config, resolved, write_config
from self_improving.events import normalize
from self_improving.hooks.common import dispatch
from self_improving.installer import MARKER, hook_is_installed, install_hooks, uninstall_hooks
from self_improving.indexing import broken_local_links, sync_index
from self_improving.security import contains_secret, sanitize
from self_improving.review import decide, list_candidates
from self_improving.storage import active_corrections, append_verified_correction, initialize_memory, verified_corrections


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
        self.assertEqual(version.stdout.strip(), f"self-improving {__version__}")

    def test_custom_paths_resolve(self) -> None:
        with self.env():
            self.assertEqual(Path(resolved(load_config())["memory_root"]), self.memory.resolve())

    def test_old_config_gets_injection_defaults_without_schema_bump(self) -> None:
        old = dict(self.config)
        old.pop("injection", None)
        self.config_path.write_text(json.dumps(old))
        with self.env():
            loaded = load_config()
        self.assertTrue(loaded["injection"]["include_verified_corrections"])
        self.assertEqual(loaded["injection"]["max_verified_corrections"], 20)

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

    def test_machine_messages_are_not_captured_as_corrections(self) -> None:
        inbox = self.memory / ".learnings/CORRECTIONS_INBOX.md"
        with self.env():
            dispatch("claude", "UserPromptSubmit", {"prompt": "<task-notification>任务完成，记住检查输出</task-notification>"})
            dispatch("claude", "UserPromptSubmit", {"prompt": "＜task-notification＞全角变体，别忘了＜/task-notification＞"})
            dispatch("claude", "UserPromptSubmit", {"prompt": "<system-reminder>候选箱已有记录，记住审核</system-reminder>"})
            self.assertNotIn("UNTRUSTED_USER_CANDIDATE", inbox.read_text())

    def test_keywords_inside_fenced_blocks_are_not_captured(self) -> None:
        inbox = self.memory / ".learnings/CORRECTIONS_INBOX.md"
        with self.env():
            dispatch("claude", "UserPromptSubmit", {"prompt": "帮我看下这段日志\n```\nerror: 不对，应该是 utf-8\n```\n谢谢"})
            self.assertNotIn("UNTRUSTED_USER_CANDIDATE", inbox.read_text())
            dispatch("claude", "UserPromptSubmit", {"prompt": "不对，应该用 utf-8。报错如下\n```\nUnicodeDecodeError\n```"})
            self.assertIn("应该用 utf-8", inbox.read_text())

    def test_only_human_approved_correction_is_injected_next_session(self) -> None:
        with self.env():
            dispatch("codex", "UserPromptSubmit", {"prompt": "不对，应该先读取当前文件再判断"})
            before = io.StringIO()
            with redirect_stdout(before):
                dispatch("codex", "SessionStart", {"hook_event_name": "SessionStart"})
            self.assertNotIn("verified-corrections", before.getvalue())
            self.assertNotIn("UNTRUSTED_USER_CANDIDATE", before.getvalue())

            fingerprint = list_candidates(self.memory)[0].split(" | ", 1)[0]
            decide(self.memory, self.home / "state", fingerprint, "approve", "先读取当前文件，再根据实际内容判断。", "global")
            after = io.StringIO()
            with redirect_stdout(after):
                dispatch("claude", "SessionStart", {"hook_event_name": "SessionStart"})

        output = after.getvalue()
        self.assertIn("<verified-corrections>", output)
        self.assertIn("先读取当前文件，再根据实际内容判断。", output)
        self.assertNotIn("UNTRUSTED_USER_CANDIDATE", output)

    def test_approval_recovers_idempotently_when_inbox_update_fails(self) -> None:
        with self.env():
            dispatch("codex", "UserPromptSubmit", {"prompt": "不对，应该保留已批准真身"})
            fingerprint = list_candidates(self.memory)[0].split(" | ", 1)[0]
            with patch("self_improving.review.atomic_write", side_effect=OSError("disk full")):
                with self.assertRaisesRegex(OSError, "approval is active"):
                    decide(self.memory, self.home / "state", fingerprint, "approve", "保留已批准真身。", "global")
            self.assertEqual(active_corrections(self.memory), ["保留已批准真身。"])
            self.assertEqual(len(list_candidates(self.memory)), 1)
            repaired = decide(self.memory, self.home / "state", fingerprint, "approve", "保留已批准真身。", "global")
        self.assertEqual(repaired, "imported")
        self.assertEqual(active_corrections(self.memory), ["保留已批准真身。"])
        self.assertEqual(list_candidates(self.memory), [])

    def test_reject_command_does_not_require_correct_answer(self) -> None:
        from self_improving.cli import main

        with self.env():
            dispatch("codex", "UserPromptSubmit", {"prompt": "不对，这条候选应当拒绝"})
            fingerprint = list_candidates(self.memory)[0].split(" | ", 1)[0]
            output = io.StringIO()
            with redirect_stdout(output):
                result = main(["review", "reject", "--fingerprint", fingerprint])
        self.assertEqual(result, 0)
        self.assertEqual(output.getvalue().strip(), "rejected")
        self.assertEqual(active_corrections(self.memory), [])

    def test_verified_correction_can_be_revoked(self) -> None:
        from self_improving.cli import main
        from self_improving.storage import VERIFIED_RELATIVE

        fingerprint = "[fp:555555555555]"
        append_verified_correction(self.memory, fingerprint, "可撤销规则", "global")
        with self.env():
            output = io.StringIO()
            with redirect_stdout(output):
                result = main(["review", "revoke", "--fingerprint", fingerprint])
        self.assertEqual(result, 0)
        self.assertEqual(output.getvalue().strip(), "revoked")
        self.assertEqual(active_corrections(self.memory), [])
        events = (self.memory / VERIFIED_RELATIVE).read_text().splitlines()
        self.assertEqual(len(events), 2)
        self.assertIn('"event":"revoke"', events[-1])

    def test_legacy_rule_requires_explicit_answer_and_scope_then_can_be_revoked(self) -> None:
        from self_improving.cli import main

        corrections = self.memory / "corrections.md"
        lines = corrections.read_text().splitlines()
        lines.append("| 2026-01-01 | old incident | old answer | active | |")
        corrections.write_text("\n".join(lines) + "\n")
        legacy_audit = corrections.read_text()
        with self.env():
            listed = io.StringIO()
            with redirect_stdout(listed):
                listed_result = main(["review", "legacy-list"])
            self.assertEqual(listed_result, 0)
            legacy_id = listed.getvalue().split(" | ", 1)[0]
            self.assertRegex(legacy_id, r"^legacy:[0-9a-f]{12}$")
            output = io.StringIO()
            with redirect_stdout(output):
                result = main([
                    "review", "import-legacy", "--legacy-id", legacy_id,
                    "--correct", "工具要求原文展示时，完整原文必须进入最终回复。", "--scope", "global",
                ])
            fingerprint = output.getvalue().strip()
            self.assertEqual(result, 0)
            self.assertRegex(fingerprint, r"^\[fp:[0-9a-f]{12}\]$")
            self.assertEqual(active_corrections(self.memory), ["工具要求原文展示时，完整原文必须进入最终回复。"])
            conflicting = main([
                "review", "import-legacy", "--legacy-id", legacy_id,
                "--correct", "另一条规则", "--scope", "global",
            ])
            self.assertEqual(conflicting, 1)
            project = self.home / "legacy-project"
            project.mkdir()
            scope_conflict = main([
                "review", "import-legacy", "--legacy-id", legacy_id,
                "--correct", "工具要求原文展示时，完整原文必须进入最终回复。",
                "--scope", f"project:{project}",
            ])
            self.assertEqual(scope_conflict, 1)
            revoke_output = io.StringIO()
            with redirect_stdout(revoke_output):
                revoked = main(["review", "revoke", "--fingerprint", fingerprint])
        self.assertEqual(revoked, 0)
        self.assertEqual(revoke_output.getvalue().strip(), "revoked")
        self.assertEqual(active_corrections(self.memory), [])
        self.assertEqual(corrections.read_text(), legacy_audit)

        with self.env():
            reimported = io.StringIO()
            with redirect_stdout(reimported):
                reimport_result = main([
                    "review", "import-legacy", "--legacy-id", legacy_id,
                    "--correct", "调整后的规则", "--scope", "global",
                ])
        self.assertEqual(reimport_result, 0)
        self.assertEqual(reimported.getvalue().strip(), fingerprint)
        self.assertEqual(active_corrections(self.memory), ["调整后的规则"])

    def test_legacy_id_is_content_stable_and_non_table_text_is_ignored(self) -> None:
        from self_improving.review import list_legacy

        corrections = self.memory / "corrections.md"
        valid = "| 2026-01-01 | incident | answer | active | |"
        corrections.write_text(corrections.read_text() + valid + "\n")
        before = list_legacy(self.memory)
        self.assertEqual(len(before), 1)
        stable_id = before[0].split(" | ", 1)[0]
        text = corrections.read_text()
        corrections.write_text(
            "# inserted heading\n" + text
            + "this is not a table | active | anything\n"
            + "| 2026-01-02 | system audit | answer | active | imported:[fp:123456789abc] |\n"
            + "| 2026-02-30 | impossible date | answer | active | |\n"
        )
        after = list_legacy(self.memory)
        self.assertEqual(len(after), 1)
        self.assertEqual(after[0].split(" | ", 1)[0], stable_id)

    def test_append_only_ledger_failure_does_not_change_effective_state(self) -> None:
        from self_improving.storage import revoke_verified_correction

        fingerprint = "[fp:bbbbbbbbbbbb]"
        with patch("self_improving.storage.atomic_write", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                append_verified_correction(self.memory, fingerprint, "不会半写入", "global")
        self.assertEqual(active_corrections(self.memory), [])

        append_verified_correction(self.memory, fingerprint, "保持生效", "global")
        with patch("self_improving.storage.atomic_write", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                revoke_verified_correction(self.memory, fingerprint)
        self.assertEqual(active_corrections(self.memory), ["保持生效"])

    def test_verified_correction_budgets_and_disable_switch(self) -> None:
        append_verified_correction(self.memory, "[fp:111111111111]", "第一条规则", "global")
        append_verified_correction(self.memory, "[fp:222222222222]", "第二条规则", "global")
        self.assertEqual(active_corrections(self.memory), ["第二条规则", "第一条规则"])
        self.assertEqual(verified_corrections(self.memory, 1, 100), ["第二条规则"])
        self.assertEqual(verified_corrections(self.memory, 10, len("第二条规则")), ["第二条规则"])

        self.config["injection"]["include_verified_corrections"] = False
        with self.env():
            write_config(self.config)
            output = io.StringIO()
            with redirect_stdout(output):
                dispatch("codex", "SessionStart", {"hook_event_name": "SessionStart"})
        self.assertNotIn("verified-corrections", output.getvalue())

    def test_project_scope_only_applies_inside_that_project(self) -> None:
        project = self.home / "project-a"
        project.mkdir()
        append_verified_correction(self.memory, "[fp:333333333333]", "仅项目甲适用", f"project:{project}")
        append_verified_correction(self.memory, "[fp:444444444444]", "全局适用", "global")
        self.assertEqual(active_corrections(self.memory, str(project / "child")), ["全局适用", "仅项目甲适用"])
        self.assertEqual(active_corrections(self.memory, str(self.home / "project-b")), ["全局适用"])

    def test_project_scope_rejects_root_and_missing_directory(self) -> None:
        from self_improving.storage import normalize_scope

        with self.assertRaises(ValueError):
            normalize_scope("project:/")
        with self.assertRaises(ValueError):
            normalize_scope(f"project:{self.home / 'missing'}")

    def test_legacy_markdown_active_rows_are_not_silently_injected(self) -> None:
        corrections = self.memory / "corrections.md"
        corrections.write_text(corrections.read_text() + "| 2026-07-12 | old | 历史规则 | active | manual |\n")
        self.assertEqual(active_corrections(self.memory), [])

    def test_core_memory_character_budget_is_enforced(self) -> None:
        self.memory.joinpath("memory.md").write_text("# Memory · Test\n" + "\n".join(["## A", "- " + "字" * 9000, "## B", "- end"]))
        with self.env():
            output = io.StringIO()
            with redirect_stdout(output):
                dispatch("codex", "SessionStart", {"hook_event_name": "SessionStart"})
        self.assertIn("memory-source-warning", output.getvalue())
        self.assertNotIn("<self-improving-memory>", output.getvalue())

    def test_verified_ledger_rejects_bad_time_and_sorts_by_instant(self) -> None:
        import json as json_module
        from self_improving.storage import VERIFIED_RELATIVE, load_verified_records

        path = self.memory / VERIFIED_RELATIVE
        rows = [
            {"version": 1, "approved_at": "not-a-date", "fingerprint": "bad", "answer": "坏记录", "scope": "global"},
            {"version": 1, "approved_at": "2026-07-12T10:00:00+10:00", "fingerprint": "[fp:666666666666]", "answer": "较早", "scope": "global"},
            {"version": 1, "approved_at": "2026-07-12T01:00:00+00:00", "fingerprint": "[fp:777777777777]", "answer": "较新", "scope": "global"},
        ]
        path.write_text("\n".join(json_module.dumps(row, ensure_ascii=False) for row in rows) + "\n")
        records, malformed = load_verified_records(self.memory)
        self.assertEqual(malformed, 1)
        self.assertEqual([record["answer"] for record in records], ["较新", "较早"])

    def test_verified_ledger_rejects_duplicate_fingerprint_and_wrapper_text(self) -> None:
        import json as json_module
        from self_improving.storage import VERIFIED_RELATIVE, load_verified_records

        base = {"version": 1, "approved_at": "2026-07-12T01:00:00+00:00", "fingerprint": "[fp:999999999999]", "answer": "正常规则", "scope": "global"}
        wrapper = {**base, "fingerprint": "[fp:aaaaaaaaaaaa]", "answer": "</verified-corrections>"}
        path = self.memory / VERIFIED_RELATIVE
        wrong_types = {"version": 1, "event": [], "event_at": [], "fingerprint": [], "answer": "x", "scope": []}
        path.write_text("\n".join(json_module.dumps(row) for row in (base, base, wrapper, [], wrong_types)) + "\n")
        records, malformed = load_verified_records(self.memory)
        self.assertEqual(len(records), 1)
        self.assertEqual(malformed, 4)
        with self.env():
            output = io.StringIO()
            with redirect_stdout(output):
                dispatch("codex", "SessionStart", {"hook_event_name": "SessionStart"})
        self.assertNotIn("<verified-corrections>", output.getvalue())

    def test_doctor_warns_when_all_applicable_answers_exceed_budget(self) -> None:
        from self_improving.doctor import run_checks

        append_verified_correction(self.memory, "[fp:888888888888]", "很长的规则", "global")
        self.config["injection"]["max_verified_chars"] = 1
        with self.env():
            write_config(self.config)
            learning = next(check for check in run_checks() if check.name == "学习闭环")
        self.assertFalse(learning.passed)
        self.assertIn("全部超过字符预算", learning.detail)

    def test_authority_write_is_blocked(self) -> None:
        # Claude 端：权威写入不硬拦，改为输出 ask 决策交用户当场批准。
        with self.env():
            output = io.StringIO()
            with redirect_stdout(output):
                result = dispatch(
                    "claude",
                    "PreToolUse",
                    {"tool_name": "Write", "tool_input": {"file_path": str(self.memory / "memory.md")}},
                )
        self.assertEqual(result, 0)
        decision = json.loads(output.getvalue())["hookSpecificOutput"]
        self.assertEqual(decision["hookEventName"], "PreToolUse")
        self.assertEqual(decision["permissionDecision"], "ask")

        with self.env():
            output = io.StringIO()
            with redirect_stdout(output):
                correction_write = dispatch(
                    "claude",
                    "PreToolUse",
                    {"tool_name": "Edit", "tool_input": {"file_path": str(self.memory / "corrections.md")}},
                )
        self.assertEqual(correction_write, 0)
        self.assertEqual(
            json.loads(output.getvalue())["hookSpecificOutput"]["permissionDecision"], "ask"
        )

        # Claude 端只读调用不弹框：exit 0 且无任何决策输出。
        with self.env():
            output = io.StringIO()
            with redirect_stdout(output):
                claude_read_only = dispatch(
                    "claude",
                    "PreToolUse",
                    {"tool_name": "Bash", "tool_input": {"command": f"cat {self.memory / 'memory.md'}"}},
                )
        self.assertEqual(claude_read_only, 0)
        self.assertEqual(output.getvalue(), "")

        # Codex（0.144+）解析同一套 ask 协议：守门命中同样弹框请用户批准。
        def codex_decision(payload: dict) -> tuple[int, str]:
            with self.env():
                output = io.StringIO()
                with redirect_stdout(output):
                    code = dispatch("codex", "PreToolUse", payload)
            return code, output.getvalue()

        for command in (
            "python3 -m self_improving review approve --fingerprint x --correct y --scope global",
            "python3 -c 'from self_improving.review import decide'",
        ):
            code, text = codex_decision({"tool_name": "Bash", "tool_input": {"command": command}})
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(text)["hookSpecificOutput"]["permissionDecision"], "ask")

        for command, expects_ask in (
            ("printf hacked >> memory.md", True),
            (f"cat {self.memory / 'memory.md'}", False),
            ("grep -n 边界 memory.md 2>/dev/null", False),
            ("wc -l memory.md 2>&1", False),
            ("sed -i '' 's/rejected/active/' corrections.md", True),
        ):
            code, text = codex_decision({"cwd": str(self.memory), "tool_name": "Bash", "tool_input": {"command": command}})
            self.assertEqual(code, 0)
            if expects_ask:
                self.assertEqual(json.loads(text)["hookSpecificOutput"]["permissionDecision"], "ask")
            else:
                self.assertEqual(text, "")

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

    def test_candidate_entries_json_and_session_start_review_reminder(self) -> None:
        from self_improving.review import candidate_entries
        from self_improving.storage import append_candidate

        state = self.home / "state"
        for text in ("规则甲", "规则乙", "规则丙"):
            append_candidate(self.memory, state, "claude-user-prompt", text, 500)
        entries = candidate_entries(self.memory)
        self.assertEqual(len(entries), 3)
        self.assertTrue(all(entry["fingerprint"].startswith("[fp:") for entry in entries))
        self.assertIn("规则甲", entries[0]["candidate"])
        with self.env():
            output = io.StringIO()
            with redirect_stdout(output):
                dispatch("claude", "SessionStart", {"hook_event_name": "SessionStart"})
        self.assertIn('<memory-review-reminder pending="3">', output.getvalue())
        self.assertIn("review list --json", output.getvalue())

    def test_local_link_check_and_secret_redaction(self) -> None:
        note = self.memory / "2026-07-11-note.md"
        note.write_text("# Note\n\n[missing](missing.md)\n")
        captured = self.memory / ".learnings/ERRORS.md"
        captured.write_text(captured.read_text() + "| now | Bash | 捕获文本 [gone](gone.md) | fp | open_error |\n")
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

    def test_init_refuses_to_overwrite_existing_configuration(self) -> None:
        from self_improving.cli import main

        with self.env():
            before = self.config_path.read_text()
            result = main(["init", "--agents", "codex", "--memory-root", str(self.home / "other")])
        self.assertEqual(result, 1)
        self.assertEqual(self.config_path.read_text(), before)
        self.assertFalse((self.home / "other").exists())

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

    def test_legacy_migration_refuses_existing_configuration(self) -> None:
        from self_improving.cli import main

        with self.env():
            before = self.config_path.read_text()
            result = main(["migrate", "legacy", "--apply"])
        self.assertEqual(result, 1)
        self.assertEqual(self.config_path.read_text(), before)

    def test_legacy_migration_preview_warns_when_already_configured(self) -> None:
        from self_improving.cli import main

        with self.env():
            output = io.StringIO()
            with redirect_stdout(output):
                result = main(["migrate", "legacy"])
        self.assertEqual(result, 0)
        self.assertIn("upgrade", output.getvalue())
        self.assertNotIn("加 --apply 才会写配置和 Hook", output.getvalue())


if __name__ == "__main__":
    unittest.main()
