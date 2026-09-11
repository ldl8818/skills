"""Knowledge routing safety and lifecycle contracts, using synthetic sources."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from self_improving import knowledge as k
from self_improving.config import default_config, write_config
from self_improving.hooks.common import dispatch
from self_improving.storage import estimate_tokens


class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "notes"
        self.root.mkdir()
        self.path = self.root / "design.md"
        self.path.write_text("# Design\n\n## Rules\nKeep the human approval boundary.\n\n## Examples\nExample only.\n")
        self.entry = {"id": "design", "path": "design.md", "status": "active", "scope": "global", "triggers": ["architecture", "架构", "岗位"], "exclude": ["不讨论架构"], "sections": ["## Rules"]}
        self.catalog = {"version": 1, "roots": [str(self.root)], "entries": [self.entry]}
        self.config = default_config(str(self.root))
        self.config["state_root"] = str(self.base / "state")
        self.config["persistence"]["enabled"] = False
        self.configpath = self.base / "config.json"
        write_config(self.config, self.configpath)
        self.save()
        self.event = {"platform": "codex", "event": "UserPromptSubmit", "session_id": "one", "cwd": str(self.base), "prompt": "帮我设计架构"}

    def save(self):
        (self.root / k.CATALOG).write_text(json.dumps(self.catalog))

    def accept(self):
        k.accept(self.config, k.check(self.config)["revision"])

    def context(self, **updates):
        return k.context_worker(self.config, {**self.event, **updates}, 1200)

    def test_unreviewed_then_reviewed_then_source_changed(self):
        self.assertIn("needs review", self.context())
        self.assertNotIn("Keep the human", self.context())
        self.accept()
        self.assertIn("Keep the human", self.context())
        self.assertEqual(self.context(), "")
        self.path.write_text("# Design\n\n## Rules\nChanged content.\n")
        text = self.context()
        self.assertIn("invalidated", text)
        self.assertNotIn("Changed content", text)

    def test_metadata_change_invalidates_and_stale_accept_fails(self):
        self.accept()
        revision = k.check(self.config)["revision"]
        self.entry["triggers"].append("workflow")
        self.save()
        self.assertFalse(k.check(self.config)["reviewed"])
        with self.assertRaises(ValueError):
            k.accept(self.config, revision)

    def test_full_read_and_missing_section(self):
        self.accept()
        self.assertNotIn("Example only", k.read(self.config, "design")["body"])
        self.assertIn("Example only", k.read(self.config, "design", True)["body"])
        self.entry["sections"] = ["## Missing"]
        self.save()
        self.assertFalse(k.check(self.config)["structural_ok"])

    def test_excluded_and_code_only_prompts_do_not_load(self):
        self.accept()
        self.assertEqual(self.context(prompt="不讨论架构"), "")
        self.assertEqual(self.context(prompt="```\n架构\n```"), "")
        self.assertEqual(self.context(prompt="今天吃什么"), "")

    def test_budget_does_not_truncate_required_full_document(self):
        self.entry.update(required=True, sections=[])
        self.save()
        self.path.write_text("# Design\n" + "完整规则。" * 500)
        self.accept()
        text = self.context()
        self.assertIn("knowledge read design --full", text)
        self.assertNotIn("完整规则", text)
        self.assertLessEqual(estimate_tokens(text), 1200)

    def test_resumed_and_compacted_contexts_load_again(self):
        self.accept()
        self.assertIn("Keep the human", self.context())
        compact = self.context(event="SessionStart", source="compact")
        self.assertIn("Keep the human", compact)
        self.context(event="SessionStart", source="resume")
        self.assertIn("Keep the human", self.context())

    def test_no_id_and_bad_state_do_not_lose_content(self):
        self.accept()
        self.assertIn("Keep the human", self.context(session_id=""))
        self.context()
        state = self.base / "state/knowledge/sessions" / f"{k.fingerprint(['codex', 'one'])}.json"
        state.write_text("invalid")
        self.assertIn("Keep the human", self.context())

    def test_persistence_disabled_still_routes_real_hook(self):
        self.accept()
        out = io.StringIO()
        with patch.dict(os.environ, {"SELF_IMPROVING_CONFIG": str(self.configpath)}), redirect_stdout(out):
            dispatch("codex", "UserPromptSubmit", {"session_id": "live", "cwd": str(self.base), "prompt": "架构"})
        self.assertIn("Keep the human", out.getvalue())
        self.assertFalse((self.root / ".learnings").exists())

    def test_dependencies_and_deployment_drift(self):
        dep = self.root / "policy.md"
        dep.write_text("# Policy\nExisting boundary.\n")
        self.catalog["entries"].append({"id": "policy", "path": "policy.md", "status": "reference"})
        self.entry["dependencies"] = ["policy"]
        self.save()
        self.accept()
        dep.write_text("# Policy\nNew boundary.\n")
        self.assertFalse(k.check(self.config)["reviewed"])
        self.entry["source"] = "policy.md"
        self.save()
        self.assertFalse(k.check(self.config)["structural_ok"])

    def test_untrusted_sources_aliases_and_secrets(self):
        for target in ("../outside.md", ".learnings/log.md", "memory.md"):
            path = self.root / target
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# Notes\nUntrusted text\n")
            self.entry["path"] = target
            self.save()
            self.assertFalse(k.check(self.config)["structural_ok"], target)
        alias = self.root / "alias.md"
        alias.symlink_to(self.root / "memory.md")
        self.entry["path"] = "alias.md"
        self.save()
        self.assertFalse(k.check(self.config)["structural_ok"])
        self.entry["path"] = "design.md"
        self.save()
        self.path.write_text("# Design\n## Rules\napi_key=synthetic-sensitive-value\n")
        self.assertFalse(k.check(self.config)["structural_ok"])

    def test_worker_timeout_and_bad_catalog_are_nonfatal(self):
        with patch.object(subprocess, "run", side_effect=subprocess.TimeoutExpired("worker", 1)):
            self.assertIn("unavailable", k.context(self.config, self.event, 1200))
        (self.root / k.CATALOG).write_text("[]")
        self.assertEqual("", k.context(self.config, self.event, 1200))
        self.assertIn("unavailable", k.context(self.config, {**self.event, "event": "SessionStart"}, 1200))

    def test_required_pointer_survives_compact_but_not_task_switch(self):
        self.entry.update(required=True, sections=[], scope=f"project:{self.base}")
        self.path.write_text("# Design\n" + "Complete policy.\n" * 1000)
        self.save()
        self.accept()
        self.assertIn("--full", self.context())
        self.assertIn("--full", self.context(event="SessionStart", source="compact"))
        self.context(prompt="unrelated", cwd="/different-project")
        self.assertNotIn("design", self.context(event="SessionStart", source="compact", cwd="/different-project"))

    def test_notifications_only_deduplicate_after_actual_output(self):
        self.catalog["entries"] = [{**self.entry, "id": f"source-{i:02d}-" + "x" * 45, "required": True, "sections": []} for i in range(40)]
        self.path.write_text("# Design\n" + "Full policy.\n" * 1000)
        self.save()
        self.accept()
        first, second = self.context(), self.context()
        for entry in self.catalog["entries"]:
            self.assertIn(entry["id"], first + second)
        self.assertLessEqual(estimate_tokens(first), 1200)
        self.assertLessEqual(estimate_tokens(second), 1200)

    def test_safe_open_rejects_late_symlink_and_parent_swap(self):
        real_read = k.read_bytes
        outside = self.base / "outside.md"
        outside.write_text("# Private outside root\n")
        def swap(path):
            self.path.unlink()
            self.path.symlink_to(outside)
            return real_read(path)
        with patch.object(k, "read_bytes", side_effect=swap), self.assertRaises(OSError):
            k.source_bytes(str(self.path), self.root, [self.root.resolve()])

    def test_invalid_state_types_and_source_types_fail_closed(self):
        self.accept()
        self.context()
        state = self.base / "state/knowledge/sessions" / f"{k.fingerprint(['codex', 'one'])}.json"
        state.write_text(json.dumps({"generation": [], "emitted": [], "requested": {}, "notices": {}}))
        self.assertIn("Keep the human", self.context())
        self.entry["source"] = 123
        self.save()
        with self.assertRaises(ValueError):
            k.check(self.config)

    def test_unrelated_sources_not_read_in_runtime(self):
        self.catalog["entries"].append({"id": "unrelated", "path": "missing.md", "status": "active", "triggers": ["other"]})
        self.save()
        with patch.object(k, "source_bytes", wraps=k.source_bytes) as reader:
            self.assertIn("needs review", self.context())
            self.assertEqual(reader.call_count, 1)

    def test_accept_rejects_change_between_snapshots(self):
        revision = k.check(self.config)["revision"]
        real_snapshot = k.snapshot
        calls = 0
        def mutate(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                self.path.write_text("# Design\n## Rules\nChanged.\n")
            return real_snapshot(*args, **kwargs)
        with patch.object(k, "snapshot", side_effect=mutate), self.assertRaises(ValueError):
            k.accept(self.config, revision)
        self.assertFalse(k.accepted(self.config))

    def test_keyword_free_followup_retains_required_context(self):
        self.entry.update(required=True, sections=[])
        self.save()
        self.accept()
        self.context()
        self.context(prompt="按这个改")
        self.assertIn("Keep the human", self.context(event="SessionStart", source="compact"))
        self.path.write_text("# Design\nNew verified policy.\n")
        self.context(prompt="继续")
        self.accept()
        self.context(prompt="继续")
        self.assertIn("New verified policy", self.context(event="SessionStart", source="compact"))

    def test_resume_then_queued_compact_keeps_full_read_obligation(self):
        self.entry.update(required=True, sections=[])
        self.path.write_text("# Design\n" + "Complete policy.\n" * 1000)
        self.save()
        self.accept()
        self.assertIn("--full", self.context())
        self.context(event="SessionStart", source="resume")
        self.assertIn("--full", self.context(event="SessionStart", source="compact"))

    def test_pending_invalidations_survive_budget_overflow(self):
        self.path.write_text("# Design\nShort.\n")
        self.catalog["entries"] = [{**self.entry, "id": f"source-{i:02d}-" + "x" * 45, "sections": []} for i in range(64)]
        self.save()
        self.accept()
        for _ in range(32):
            self.context()
        self.path.write_text("# Design\nChanged.\n")
        outputs = self.context(prompt="unrelated") + self.context(prompt="unrelated") + self.context(prompt="unrelated")
        for entry in self.catalog["entries"]:
            self.assertIn(entry["id"] + ": prior version", outputs)

    def test_catalog_index_is_short_and_discovery_preserves_archives(self):
        from self_improving.indexing import render_index
        folder = self.root / "archive"
        folder.mkdir()
        for i in range(100):
            (folder / f"history-{i}.md").write_text("# History\n")
        index = render_index(self.root)
        self.assertIn("design", index)
        self.assertIn("archive", index)
        self.assertNotIn("history-99", index)
        self.assertTrue(any("history-99" in path for path in k.discover(self.config)))

    def test_cli_requires_matching_revision_and_returns_original_text(self):
        env = {**os.environ, "SELF_IMPROVING_CONFIG": str(self.configpath)}
        cmd = [sys.executable, "-m", "self_improving", "knowledge"]
        initial = subprocess.run(cmd + ["check", "--json"], capture_output=True, text=True, env=env)
        self.assertEqual(initial.returncode, 1)
        revision = json.loads(initial.stdout)["revision"]
        accepted = subprocess.run(cmd + ["accept", "--revision", revision], capture_output=True, text=True, env=env)
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        reading = subprocess.run(cmd + ["read", "design", "--json"], capture_output=True, text=True, env=env)
        self.assertEqual(reading.returncode, 0, reading.stderr)
        self.assertIn("Keep the human", json.loads(reading.stdout)["body"])
