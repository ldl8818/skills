"""Disabled adapters and optional capture must not create background work."""
import io
import json
import os
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from self_improving import knowledge
from self_improving.config import default_config, write_config
from self_improving.doctor import run_checks
from self_improving.hooks.common import dispatch
from self_improving.installer import install_hooks, uninstall_hooks
from self_improving.storage import append_candidate, initialize_memory


class RuntimeControls(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.root = self.base / "notes"
        self.state = self.base / "state"
        self.path = self.base / "config.json"
        self.config = default_config(str(self.root))
        self.config["state_root"] = str(self.state)
        self.config["agents"]["claude"]["settings_file"] = str(self.base / "claude.json")
        self.config["agents"]["codex"]["hooks_file"] = str(self.base / "codex.json")
        self.config["agents"]["codex"]["config_file"] = str(self.base / "codex.toml")
        self.config["persistence"].update(capture_corrections=True, capture_command_errors=True)
        initialize_memory(self.root)
        env = patch.dict(os.environ, {"SELF_IMPROVING_CONFIG": str(self.path)})
        env.start()
        self.addCleanup(env.stop)
        self.save()

    def save(self):
        write_config(self.config, self.path)

    def hook(self, platform, event, **payload):
        out = io.StringIO()
        with redirect_stdout(out):
            dispatch(platform, event, {"cwd": str(self.base), "session_id": "synthetic", **payload})
        return out.getvalue()

    def pending(self):
        for index in range(3):
            append_candidate(self.root, self.state, "synthetic", f"不对，样例{index}", 500)

    def test_disabled_adapter_is_silent_and_does_not_change_state(self):
        self.pending()
        self.config["agents"]["claude"]["enabled"] = False
        self.save()
        before = {p: p.read_bytes() for base in (self.root, self.state) for p in base.rglob('*') if p.is_file()}
        for event, payload in (
            ("SessionStart", {}), ("UserPromptSubmit", {"prompt": "不对，新增纠错"}),
            ("PostToolUse", {"tool_name": "Bash", "tool_response": {"exit_code": 1, "stderr": "synthetic failure"}}),
            ("Stop", {}), ("PreToolUse", {"tool_name": "Bash", "tool_input": {"command": "pwd"}}),
        ):
            with self.subTest(event=event):
                self.assertEqual(self.hook("claude", event, **payload), "")
        after = {p: p.read_bytes() for base in (self.root, self.state) for p in base.rglob('*') if p.is_file()}
        self.assertEqual(before, after)
        self.assertIn('stored', self.hook("codex", "UserPromptSubmit", prompt="不对，启用端正常记录"))

    def test_capture_off_preserves_knowledge_and_silences_old_backlog(self):
        self.pending()
        self.config["persistence"]["capture_corrections"] = False
        self.save()
        (self.root / "guide.md").write_text("# Guide\nUse the original failed sample.\n")
        (self.root / "knowledge-catalog.json").write_text(json.dumps({
            "version": 1, "roots": [str(self.root)], "entries": [{
                "id": "guide", "path": "guide.md", "status": "active", "scope": "global",
                "triggers": ["纠错"], "sections": [],
            }],
        }))
        knowledge.accept(self.config, knowledge.check(self.config)["revision"])
        before = (self.root / ".learnings/CORRECTIONS_INBOX.md").read_bytes()
        self.assertIn("original failed sample", self.hook("codex", "UserPromptSubmit", prompt="不对，请纠错"))
        self.assertEqual((self.root / ".learnings/CORRECTIONS_INBOX.md").read_bytes(), before)
        self.assertEqual(self.hook("codex", "Stop"), "")
        self.assertFalse((self.state / "review-reminders/codex.json").exists())
        self.config["persistence"]["capture_corrections"] = True
        self.save()
        self.assertIn("systemMessage", self.hook("codex", "Stop"))

    def test_disabled_adapter_retains_authority_guard_if_still_called(self):
        self.config["agents"]["codex"]["enabled"] = False
        self.save()
        result = self.hook("codex", "PreToolUse", tool_name="Bash", tool_input={
            "command": "python3 -m self_improving review approve --fingerprint '[fp:123456789abc]'",
        })
        self.assertIn('"permissionDecision": "deny"', result)

    def test_doctor_finds_disabled_residue_without_flagging_other_hooks(self):
        settings = Path(self.config["agents"]["claude"]["settings_file"])
        settings.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "other-hook"}]}]}}))
        install_hooks(self.config, "claude")
        self.config["agents"]["claude"]["enabled"] = False
        self.save()
        check = next(c for c in run_checks() if c.name == "claude 停用接线")
        self.assertFalse(check.passed)
        uninstall_hooks(self.config, "claude")
        check = next(c for c in run_checks() if c.name == "claude 停用接线")
        self.assertTrue(check.passed)
        self.assertIn("other-hook", settings.read_text())

    def test_doctor_does_not_call_empty_injection_learning(self):
        checks = run_checks()
        self.assertFalse(any(c.name == "学习闭环" for c in checks))
        self.assertTrue(any(c.name == "纠错注入条件" for c in checks))
        self.assertIn("不证明", next(c.detail for c in checks if c.name == "修复验证边界"))


if __name__ == "__main__":
    unittest.main()
