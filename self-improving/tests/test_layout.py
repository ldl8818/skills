"""Optional core and private catalog layout, using synthetic knowledge only."""
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
from self_improving.indexing import sync_index
from self_improving.storage import initialize_memory


class LayoutTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.root = self.base / "notes"
        initialize_memory(self.root)
        self.config = default_config(str(self.root))
        self.config["state_root"] = str(self.base / "state")
        self.config["persistence"]["enabled"] = False
        self.configpath = self.base / "config.json"
        write_config(self.config, self.configpath)
        self.catalog = {"version": 1, "roots": [str(self.root)], "entries": [{
            "id": "guide", "path": "guide.md", "status": "active", "scope": "global",
            "triggers": ["workflow"], "sections": [],
        }]}
        (self.root / "guide.md").write_text("# Guide\nPreserve the complete input.\n")

    def hook(self, event, **payload):
        out = io.StringIO()
        with patch.dict(os.environ, {"SELF_IMPROVING_CONFIG": str(self.configpath)}), redirect_stdout(out):
            dispatch("codex", event, {"session_id": "layout", "cwd": str(self.base), **payload})
        return out.getvalue()

    def test_core_is_optional_and_not_recreated(self):
        self.assertFalse((self.root / "memory.md").exists())
        initialize_memory(self.root)
        self.assertFalse((self.root / "memory.md").exists())
        with patch.dict(os.environ, {"SELF_IMPROVING_CONFIG": str(self.configpath)}):
            core = next(c for c in run_checks() if c.name.startswith("核心记忆"))
        self.assertTrue(core.passed)
        self.config["injection"]["include_core_memory"] = True
        write_config(self.config, self.configpath)
        with patch.dict(os.environ, {"SELF_IMPROVING_CONFIG": str(self.configpath)}):
            core = next(c for c in run_checks() if c.name.startswith("核心记忆"))
        self.assertFalse(core.passed)

    def test_existing_opt_in_core_is_preserved_and_respected(self):
        p = self.root / "memory.md"
        body = "# Memory · Example\n\n## Rules\n- Synthetic core rule.\n- Keep this file.\n"
        p.write_text(body)
        initialize_memory(self.root)
        self.assertEqual(p.read_text(), body)
        self.assertNotIn("Synthetic core rule", self.hook("SessionStart"))
        self.config["injection"]["include_core_memory"] = True
        write_config(self.config, self.configpath)
        self.assertIn("Synthetic core rule", self.hook("SessionStart", source="startup"))

    def test_hidden_catalog_routes_after_source_move_and_on_resume(self):
        catalog = self.root / ".self-improving/knowledge-catalog.json"
        catalog.write_text(json.dumps(self.catalog))
        knowledge.accept(self.config, knowledge.check(self.config)["revision"])
        self.assertIn("knowledge list", self.hook("SessionStart"))
        self.assertIn("complete input", self.hook("UserPromptSubmit", prompt="workflow"))
        folder = self.root / "practice"
        folder.mkdir()
        (self.root / "guide.md").rename(folder / "guide.md")
        self.catalog["entries"][0]["path"] = "practice/guide.md"
        catalog.write_text(json.dumps(self.catalog))
        self.assertFalse(knowledge.check(self.config)["reviewed"])
        knowledge.accept(self.config, knowledge.check(self.config)["revision"])
        self.assertIn("knowledge list", self.hook("SessionStart", source="resume"))
        self.assertIn("complete input", self.hook("UserPromptSubmit", prompt="workflow"))
        self.assertIn("complete input", knowledge.read(self.config, "guide", True)["body"])
        _, index = sync_index(self.root)
        self.assertIn("practice/guide.md", index.read_text())
        self.assertNotIn("verified-corrections.jsonl", index.read_text())

    def test_legacy_catalog_remains_usable_and_hidden_catalog_does_not_fall_back(self):
        legacy = self.root / "knowledge-catalog.json"
        legacy.write_text(json.dumps(self.catalog))
        knowledge.accept(self.config, knowledge.check(self.config)["revision"])
        self.assertIn("complete input", self.hook("UserPromptSubmit", prompt="workflow"))
        hidden = self.root / ".self-improving/knowledge-catalog.json"
        hidden.write_text("[]")
        with self.assertRaises(ValueError):
            knowledge.check(self.config)
        self.assertNotIn("complete input", self.hook("UserPromptSubmit", prompt="workflow"))

    def test_doctor_checks_legacy_catalog_versions(self):
        (self.root / "knowledge-catalog.json").write_text(json.dumps(self.catalog))
        knowledge.accept(self.config, knowledge.check(self.config)["revision"])
        with patch.dict(os.environ, {"SELF_IMPROVING_CONFIG": str(self.configpath)}):
            checks = [c for c in run_checks() if c.name == "知识目录与版本"]
            self.assertEqual(len(checks), 1)
            self.assertTrue(checks[0].passed)
            (self.root / "guide.md").write_text("# Guide\nChanged after review.\n")
            check = next(c for c in run_checks() if c.name == "知识目录与版本")
            self.assertFalse(check.passed)
            self.assertIn("guide", check.detail)


if __name__ == "__main__":
    unittest.main()
