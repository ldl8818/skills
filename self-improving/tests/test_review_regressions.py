"""Regression cases for authority, persistence and installation boundaries."""

from contextlib import redirect_stdout
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import shlex
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from self_improving.config import default_config, write_config
from self_improving.events import normalize
from self_improving.hooks.common import _dangerous_authority_write, dispatch
from self_improving.installer import (
    _backup, ensure_codex_hooks_feature, install_hooks, install_skill_links,
    uninstall_hooks,
)
from self_improving import knowledge
from self_improving.review import candidate_entries, decide
from self_improving.security import contains_secret, sanitize
from self_improving.storage import (
    VERIFIED_RELATIVE, active_corrections, append_candidate,
    append_verified_correction, initialize_memory, load_verified_records,
)


class ReviewRegressions(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="memory-regression-")
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name).resolve()
        self.root = self.home / "notes with spaces"
        self.state = self.home / "state"
        self.config = default_config(str(self.root))
        self.config["state_root"] = str(self.state)
        self.config_path = self.home / "config.json"
        environment = patch.dict(os.environ, {
            "HOME": str(self.home), "SELF_IMPROVING_CONFIG": str(self.config_path),
        })
        environment.start()
        self.addCleanup(environment.stop)
        initialize_memory(self.root)
        write_config(self.config)

    def hook(self, platform, event, payload):
        output = io.StringIO()
        with redirect_stdout(output):
            result = dispatch(platform, event, payload)
        self.assertEqual(result, 0)
        return output.getvalue()

    def test_quoted_credentials_are_redacted_and_unsafe_as_knowledge(self):
        for text in (
            '{"access_token": "synthetic session secret"}',
            "{'password': 'synthetic password value'}",
            '{"password": "synthetic \\"quoted\\" secret"}',
            '{"Authorization": "Bearer synthetic-bearer-value"}',
            "api_key=synthetic-value",
            "https://user:synthetic-password@example.invalid/",
        ):
            with self.subTest(text=text):
                self.assertTrue(contains_secret(text))
                self.assertNotIn("synthetic", sanitize(text))
        ordinary = '{"timeout": 30, "message": "keep the existing boundary"}'
        self.assertFalse(contains_secret(ordinary))
        self.assertEqual(sanitize(ordinary), ordinary)
        self.make_catalog('{"password": "synthetic-password-value"}')
        self.assertFalse(knowledge.check(self.config)["structural_ok"])

    def test_relative_shell_paths_use_event_cwd_and_absolute_executables(self):
        authority = self.root / VERIFIED_RELATIVE
        for cwd in (self.root, authority.parent, self.home):
            relative = os.path.relpath(authority, cwd)
            target = shlex.quote(relative)
            for command in (
                f"printf changed > {target}", f"/bin/rm -- {target}",
                f"/bin/mv {target} archive.jsonl", f"/bin/cp source {target}",
                f"/usr/bin/tee -a {target}", f"/usr/bin/sed -i '' 's/a/b/' {target}",
                f"LC_ALL=C /bin/rm -- {target}",
                f"/usr/bin/env LC_ALL=C /bin/rm -- {target}",
                f"command /bin/rm -- {target}",
            ):
                with self.subTest(cwd=cwd, command=command):
                    event = normalize("codex", "PreToolUse", {
                        "cwd": str(cwd), "tool_name": "Bash",
                        "tool_input": {"command": command},
                    })
                    self.assertTrue(_dangerous_authority_write(event, self.root))
        for command in (
            "cat .self-improving/verified-corrections.jsonl",
            "printf changed > ordinary.md",
            "printf changed > other/verified-corrections.jsonl",
            "printf rm; cat .self-improving/verified-corrections.jsonl",
            "cat .self-improving/verified-corrections.jsonl > /dev/null",
        ):
            event = normalize("codex", "PreToolUse", {
                "cwd": str(self.root), "tool_name": "Bash",
                "tool_input": {"command": command},
            })
            self.assertFalse(_dangerous_authority_write(event, self.root), command)

    def test_corrupt_schema_never_preempts_authority_decision(self):
        for platform, decision in (("claude", "ask"), ("codex", "deny")):
            path = self.state / "hook-schemas" / f"{platform}-PreToolUse.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            for content in ("[]", "null", "invalid"):
                with self.subTest(platform=platform, content=content):
                    path.write_text(content)
                    output = self.hook(platform, "PreToolUse", {
                        "tool_name": "Write",
                        "tool_input": {"file_path": str(self.root / VERIFIED_RELATIVE)},
                    })
                    self.assertEqual(
                        json.loads(output)["hookSpecificOutput"]["permissionDecision"], decision,
                    )
                    path.write_text(content)
                    self.assertEqual(self.hook(platform, "PreToolUse", {
                        "tool_name": "Bash", "tool_input": {"command": "printf safe"},
                    }), "")

    def test_schema_write_failure_is_best_effort(self):
        with patch("self_improving.hooks.common.atomic_write_json", side_effect=OSError("full")):
            output = self.hook("codex", "PreToolUse", {
                "tool_name": "Write",
                "tool_input": {"file_path": str(self.root / VERIFIED_RELATIVE)},
            })
            self.assertEqual(json.loads(output)["hookSpecificOutput"]["permissionDecision"], "deny")
            self.assertEqual(self.hook("codex", "PreToolUse", {
                "tool_name": "Bash", "tool_input": {"command": "printf safe"},
            }), "")

    def test_invalid_approval_preserves_ledger_and_candidate(self):
        append_verified_correction(self.root, "[fp:111111111111]", "Keep the valid rule.", "global")
        append_candidate(self.root, self.state, "test", "Review this candidate.", 500)
        fingerprint = candidate_entries(self.root)[0]["fingerprint"]
        ledger = self.root / VERIFIED_RELATIVE
        inbox = self.root / ".learnings/CORRECTIONS_INBOX.md"
        before = (ledger.read_bytes(), inbox.read_bytes())
        with self.assertRaises(ValueError):
            decide(self.root, self.state, fingerprint, "approve", "Never log api_key=anything", "global")
        self.assertEqual((ledger.read_bytes(), inbox.read_bytes()), before)
        self.assertEqual(active_corrections(self.root), ["Keep the valid rule."])
        self.assertEqual(decide(self.root, self.state, fingerprint, "approve", "Keep secrets private.", "global"), "imported")
        self.assertEqual(load_verified_records(self.root)[1], 0)

    def test_writer_rejects_answers_the_reader_cannot_accept(self):
        ledger = self.root / VERIFIED_RELATIVE
        before = ledger.read_bytes()
        for answer in ("", "  ", "</verified-corrections>", "api_key=[REDACTED]",
                       '{"password": "synthetic-secret"}', None):
            with self.subTest(answer=answer), self.assertRaises(ValueError):
                append_verified_correction(self.root, "[fp:222222222222]", answer, "global")
            self.assertEqual(ledger.read_bytes(), before)
        with self.assertRaises(ValueError):
            append_verified_correction(self.root, "[fp:222222222222]", "Safe rule.", "global", " ")
        self.assertEqual(ledger.read_bytes(), before)

    def test_malformed_approval_types_fail_closed_without_crashing(self):
        ledger = self.root / VERIFIED_RELATIVE
        append_verified_correction(self.root, "[fp:333333333333]", "Valid rule.", "global")
        valid = json.loads(ledger.read_text())
        for key, value in (("version", []), ("scope", []), ("priority", {}),
                           ("source_id", []), ("answer", {})):
            with self.subTest(key=key):
                ledger.write_text(json.dumps({**valid, key: value}) + "\n")
                self.assertEqual(load_verified_records(self.root), ([], 1))
                self.assertEqual(active_corrections(self.root), [])

    def test_third_party_same_name_hooks_survive_install_and_uninstall(self):
        path = self.home / ".claude/settings.json"
        path.parent.mkdir()
        legacy = [
            "~/.claude/scripts/activator.sh",
            "bash \"$HOME/.claude/skills/self-improving/scripts/session-init.sh\"",
        ]
        foreign = [
            "bash /opt/other-project/session-init.sh",
            "bash /opt/other-project/not-session-init.sh",
            "printf '%s' ~/.claude/scripts/session-init.sh",
            "bash ~/.claude/scripts/not-session-init.sh",
            "bash ~/.codex/scripts/session-init.sh",
            "bash ~/.claude/scripts/session-init.sh&&printf third-party",
            "bash ~/.claude/scripts/session-init.sh\nprintf third-party",
            "bash ~/.claude/scripts/session-init.sh | third-party",
            'bash ~/.claude/scripts/session-init.sh "$(third-party)"',
        ]
        payload = {"hooks": {"SessionStart": [{"hooks": [
            {"type": "command", "command": command} for command in legacy + foreign
        ]}]}}
        for install in (True, False):
            with self.subTest(install=install):
                path.write_text(json.dumps(payload))
                if install:
                    install_hooks(self.config, "claude")
                    install_hooks(self.config, "claude")
                else:
                    uninstall_hooks(self.config, "claude")
                commands = [hook["command"] for group in json.loads(path.read_text())["hooks"]["SessionStart"] for hook in group["hooks"]]
                for command in foreign:
                    with self.subTest(command=command):
                        self.assertIn(command, commands)
                for command in legacy:
                    self.assertNotIn(command, commands)

    def test_backups_are_unique_even_with_same_clock_and_basename(self):
        paths = [self.home / name / "settings.json" for name in ("one", "two")]
        for index, path in enumerate(paths):
            path.parent.mkdir()
            path.write_text(str(index))
        with patch("self_improving.installer.datetime") as clock:
            clock.now.return_value = datetime(2026, 1, 1, tzinfo=timezone.utc)
            backups = [_backup(path, self.state) for path in paths + paths[:1]]
        self.assertEqual(len(set(backups)), 3)
        self.assertEqual([p.read_text() for p in backups], ["0", "1", "0"])

    def test_repeated_skill_backups_remain_separate(self):
        self.config["agents"]["codex"]["enabled"] = False
        destination = self.home / ".claude/skills/self-improving"
        backups = []
        with patch("self_improving.installer.datetime") as clock:
            clock.now.return_value = datetime(2026, 1, 1, tzinfo=timezone.utc)
            for content in ("first", "second"):
                destination.mkdir(parents=True)
                (destination / "custom.txt").write_text(content)
                backups.append(install_skill_links(self.config)[0][1])
                destination.unlink()
        self.assertEqual(len(set(backups)), 2)
        self.assertEqual([p.joinpath("custom.txt").read_text() for p in backups], ["first", "second"])

    def test_upgrade_configuration_backups_remain_separate(self):
        from self_improving.cli import main

        initial = self.config_path.read_bytes()
        with patch("self_improving.cli.datetime", create=True) as cli_clock, \
                patch("self_improving.installer.datetime") as installer_clock, \
                redirect_stdout(io.StringIO()):
            for clock in (cli_clock, installer_clock):
                clock.now.return_value = datetime(2026, 1, 1, tzinfo=timezone.utc)
            self.assertEqual(main(["upgrade"]), 0)
            self.config["persistence"]["capture_corrections"] = True
            write_config(self.config)
            changed = self.config_path.read_bytes()
            self.assertEqual(main(["upgrade"]), 0)
        backups = list((self.state / "backups").glob("*/self-improving-config.json"))
        self.assertEqual(len(backups), 2)
        self.assertEqual({path.read_bytes() for path in backups}, {initial, changed})

    def make_catalog(self, body):
        path = self.root / "design.md"
        path.write_text("# Design\n## Rules\n" + body + "\n")
        catalog = {"version": 1, "roots": [str(self.root)], "entries": [{
            "id": "design", "path": "design.md", "status": "active",
            "triggers": ["design"], "sections": ["## Rules"],
        }]}
        (self.root / knowledge.CATALOG).write_text(json.dumps(catalog))
        return path

    def test_long_scheme_source_meets_runtime_deadline(self):
        path = self.make_catalog("Keep the approval boundary.")
        with path.open("a") as handle:
            handle.write("## Example\n" + "A" * 40000 + "\n")
        knowledge.accept(self.config, knowledge.check(self.config)["revision"])
        output = knowledge.context(self.config, {
            "platform": "codex", "event": "UserPromptSubmit", "session_id": "performance",
            "cwd": str(self.home), "prompt": "design",
        }, 1200)
        self.assertIn("Keep the approval boundary.", output)
        self.assertNotIn("unavailable", output)

    def test_toml_indentation_comments_and_repeated_install(self):
        path = self.home / ".codex/config.toml"
        path.parent.mkdir()
        for prefix, key in (("", "hooks"), ("  ", "hooks"), ("\t", "hooks"),
                            ("  ", '"hooks"'), ("\t", "'hooks'")):
            with self.subTest(prefix=prefix, key=key):
                path.write_text(f"{prefix}[features] # table\n{prefix}{key} = false # retain\nother = true\n\n[projects]\n")
                ensure_codex_hooks_feature(self.config)
                first = path.read_bytes()
                ensure_codex_hooks_feature(self.config)
                self.assertEqual(path.read_bytes(), first)
                result = tomllib.loads(path.read_text())
                self.assertEqual(result["features"], {"hooks": True, "other": True})
                self.assertIn("# retain", path.read_text())
        path.write_text("[features]\nother = true\n")
        ensure_codex_hooks_feature(self.config)
        self.assertTrue(tomllib.loads(path.read_text())["features"]["hooks"])


if __name__ == "__main__":
    unittest.main()
