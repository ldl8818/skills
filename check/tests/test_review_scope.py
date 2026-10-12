# SPDX-License-Identifier: Apache-2.0
"""Behavior tests for the local scope adapter using isolated synthetic Git repos."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "review_scope.py"
spec = importlib.util.spec_from_file_location("review_scope", SCRIPT)
scope = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scope)


class ReviewScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="check-scope-")
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name) / "repo"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Scope Test")
        self.git("config", "user.email", "scope@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        self.git("config", "core.hooksPath", str(Path(self.temp.name) / "no-hooks"))
        for path, content in {
            "README.md": "# Synthetic project\nOriginal instructions.\n",
            "tests/test_total.py": "def test_total():\n    assert 2 + 2 == 4\n",
            "src/old.py": "def total(a, b):\n    return a + b\n",
            "replace.py": "VALUE = 1\n",
            ".gitignore": ".ignored/\n",
        }.items():
            self.write(path, content)
        self.commit("Initial fixture")
        self.initial = self.git("rev-parse", "HEAD").strip()

    def git(self, *args):
        result = subprocess.run(["git", "-C", str(self.repo), *args],
                                capture_output=True, text=True, check=True)
        return result.stdout

    def write(self, path, content):
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def commit(self, message):
        self.git("add", "--all", "--", ".")
        self.git("commit", "-q", "-m", message)
        return self.git("rev-parse", "HEAD").strip()

    def test_workspace_includes_docs_tests_untracked_rename_and_recreated_path(self):
        self.write("README.md", "# Synthetic project\nChanged instructions.\n")
        self.write("tests/test_total.py", "def test_total():\n    assert 3 + 3 == 6\n")
        self.git("add", "--", "tests/test_total.py")
        self.git("mv", "--", "src/old.py", "src/new.py")
        self.git("rm", "-q", "--", "replace.py")
        self.write("replace.py", "VALUE = 2\n")
        self.write("docs/new.md", "New untracked documentation.\n")
        report = scope.inventory(self.repo)
        rows = report["entries"]
        self.assertIn(("unstaged", "README.md"), {(r["layer"], r["path"]) for r in rows})
        self.assertIn(("staged", "tests/test_total.py"), {(r["layer"], r["path"]) for r in rows})
        self.assertIn(("untracked", "docs/new.md"), {(r["layer"], r["path"]) for r in rows})
        renamed = next(r for r in rows if r["status"].startswith("R"))
        self.assertEqual((renamed["old_path"], renamed["new_path"]),
                         ("src/old.py", "src/new.py"))
        replacement = [r for r in rows if r["path"] == "replace.py"]
        self.assertEqual({(r["layer"], r["new_path"]) for r in replacement},
                         {("staged", None), ("untracked", "replace.py")})
        self.assertFalse(report["scope"]["immutable"])
        self.assertEqual(report["identity_kind"], "paths-status-refs-only")

    def test_exact_paths_are_literal_and_preserve_newlines(self):
        names = ["docs/[x]*.md", "-flag.md", " leading\nname.md", "docs/other.md"]
        for name in names:
            self.write(name, "Synthetic text.\n")
        report = scope.inventory(self.repo, paths=names[:3])
        self.assertEqual({r["path"] for r in report["entries"]}, set(names[:3]))
        self.assertEqual(report["unmatched_paths"], [])
        self.git("mv", "--", "src/old.py", "src/new.py")
        renamed = scope.inventory(self.repo, paths=["src/old.py"])["entries"]
        self.assertEqual(len(renamed), 1)
        self.assertEqual(renamed[0]["new_path"], "src/new.py")

    def test_range_pins_merge_base_and_ignores_dirty_workspace(self):
        self.git("switch", "-q", "-c", "feature")
        self.write("docs/feature.md", "Feature document.\n")
        feature = self.commit("Feature change")
        self.git("switch", "-q", "main")
        self.write("main_only.py", "MAIN = True\n")
        self.commit("Independent main change")
        self.write("dirty.md", "Unrelated untracked file.\n")
        report = scope.inventory(self.repo, "range", "main", "feature")
        self.assertEqual(report["scope"]["base"], self.initial)
        self.assertEqual(report["scope"]["head"], feature)
        self.assertEqual(report["scope"]["ocr_args"],
                         ["--from", self.initial, "--to", feature])
        self.assertEqual([r["path"] for r in report["entries"]], ["docs/feature.md"])
        self.git("branch", "-f", "feature", "main")
        pinned = scope.inventory(self.repo, "range", self.initial, feature)
        self.assertEqual(pinned["entries"], report["entries"])

    def test_commit_handles_root_and_first_parent_of_merge(self):
        root = scope.inventory(self.repo, "commit", commit_ref=self.initial)
        self.assertIsNone(root["scope"]["base"])
        self.assertTrue(all(r["status"] == "A" for r in root["entries"]))
        self.git("switch", "-q", "-c", "feature")
        self.write("docs/merged.md", "Branch contribution.\n")
        self.commit("Feature")
        self.git("switch", "-q", "main")
        self.write("main_only.py", "MAIN = True\n")
        parent = self.commit("Main")
        self.git("merge", "-q", "--no-ff", "feature", "-m", "Merge fixture")
        merged = scope.inventory(self.repo, "commit", commit_ref="HEAD")
        self.assertEqual(merged["scope"]["base"], parent)
        self.assertEqual([r["path"] for r in merged["entries"]], ["docs/merged.md"])

    def test_scan_keeps_tracked_files_even_when_now_gitignored(self):
        self.write(".gitignore", ".ignored/\nREADME.md\n")
        self.write(".ignored/noise.md", "Ignored local output.\n")
        self.write("docs/new.md", "Untracked source documentation.\n")
        (self.repo / "replace.py").unlink()
        report = scope.inventory(self.repo, "scan")
        paths = {r["path"] for r in report["entries"]}
        self.assertIn("README.md", paths)
        self.assertIn("docs/new.md", paths)
        self.assertNotIn(".ignored/noise.md", paths)
        self.assertIsNone(next(r for r in report["entries"]
                               if r["path"] == "replace.py")["new_path"])
        requested = scope.inventory(self.repo, paths=["README.md", "missing.md"])
        self.assertEqual(requested["unmatched_paths"], ["README.md", "missing.md"])

    def test_preview_reports_all_gaps_and_never_claims_review_success(self):
        self.write("README.md", "# New instructions\n")
        self.write("tests/test_total.py", "def test_total():\n    assert True\n")
        self.git("add", "--", "tests/test_total.py")
        self.write("tests/test_total.py", "def test_total():\n    assert False\n")
        self.git("rm", "-q", "--", "replace.py")
        self.write(".vscode/settings.json", "{}\n")
        self.write("notes.md", "Documentation excluded by supplied OCR rules.\n")
        preview = {"files": [
            {"path": "README.md", "status": "modified", "will_review": True},
            {"path": "tests/test_total.py", "status": "modified", "will_review": True},
            {"path": "replace.py", "status": "deleted", "will_review": False,
             "exclude_reason": "deleted"},
            {"path": "notes.md", "status": "added", "will_review": False,
             "exclude_reason": "user_exclude"},
            {"path": "other-scope.py", "status": "modified", "will_review": True},
        ]}
        report = scope.reconcile(scope.inventory(self.repo), preview)
        dispositions = {r["path"]: r["preview"]["disposition"]
                        for r in report["entries"]}
        self.assertEqual(dispositions["README.md"], "selected")
        self.assertEqual(dispositions["tests/test_total.py"], "manual_layer_gap")
        self.assertEqual(dispositions["replace.py"], "deleted")
        self.assertEqual(dispositions[".vscode/settings.json"], "provider_missing")
        self.assertEqual(dispositions["notes.md"], "excluded")
        self.assertTrue(report["preview"]["selection_only"])
        self.assertFalse(report["preview"]["identity_verified"])
        self.assertEqual(report["preview"]["selected_outside_inventory"], 1)

    def test_delete_and_untracked_recreation_are_not_one_selected_record(self):
        self.git("rm", "-q", "--", "replace.py")
        self.write("replace.py", "VALUE = 2\n")
        preview = {"files": [
            {"path": "replace.py", "status": "added", "will_review": True}
        ]}
        report = scope.reconcile(scope.inventory(self.repo), preview)
        self.assertEqual({r["preview"]["disposition"] for r in report["entries"]},
                         {"deleted", "manual_layer_gap"})

    def test_delegate_selection_preserves_exclusions_deletions_and_missing_paths(self):
        self.write("README.md", "Changed documentation.\n")
        self.write("tests/test_total.py", "def test_total():\n    assert True\n")
        self.write("new.md", "New documentation.\n")
        self.git("rm", "-q", "--", "replace.py")
        preview = {"schema_version": "1", "reviewable_files": [
            {"path": "README.md", "status": "modified"},
            {"path": "outside.py", "status": "modified"},
        ], "excluded_files": [
            {"path": "tests/test_total.py", "status": "modified",
             "exclude_reason": "default_path"},
            {"path": "replace.py", "status": "deleted", "exclude_reason": "deleted"},
        ]}
        report = scope.reconcile(scope.inventory(self.repo), preview)
        states = {r["path"]: r["preview"]["disposition"] for r in report["entries"]}
        self.assertEqual(states, {"README.md": "selected", "tests/test_total.py": "excluded",
                                  "new.md": "provider_missing", "replace.py": "deleted"})
        self.assertEqual(report["preview"]["selected_outside_inventory"], 1)
        self.assertTrue(report["preview"]["selection_only"])
        self.assertFalse(report["preview"]["identity_verified"])
        self.assertNotIn("files", preview)

    def test_delegate_empty_and_malformed_output_cannot_hide_unreviewed_items(self):
        self.write("new.md", "Review me.\n")
        empty = {"schema_version": "1", "reviewable_files": [], "excluded_files": []}
        report = scope.reconcile(scope.inventory(self.repo), empty)
        self.assertEqual(report["preview"]["dispositions"], {"provider_missing": 1})
        malformed = [
            {"schema_version": "2", "reviewable_files": [], "excluded_files": []},
            {"schema_version": "1", "reviewable_files": []},
            {**empty, "excluded_files": ["bad"]},
            {**empty, "reviewable_files": [{"path": "new.md"}]},
            {**empty, "reviewable_files": [{"path": "new.md", "status": "added",
                                            "will_review": False}]},
        ]
        for preview in malformed:
            with self.subTest(preview=preview), self.assertRaises(scope.ScopeError):
                scope.reconcile(scope.inventory(self.repo), preview)

    def test_cli_saves_large_report_and_prints_only_summary(self):
        self.write("docs/new.md", "Untracked documentation.\n")
        wanted = Path(self.temp.name) / "paths.json"
        wanted.write_text(json.dumps(["docs/new.md"]), encoding="utf-8")
        output = Path(self.temp.name) / "inventory.json"
        command = [sys.executable, "-B", str(SCRIPT), "--repo", str(self.repo),
                   "--paths-file", str(wanted), "--output", str(output)]
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["entries"], 1)
        self.assertNotIn("docs/new.md", result.stdout)
        self.assertEqual(json.loads(output.read_text())["entries"][0]["path"], "docs/new.md")
        again = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(again.returncode, 2)
        self.assertEqual(json.loads(output.read_text())["entries"][0]["path"], "docs/new.md")

    def test_rejects_option_refs_escaping_paths_and_malformed_preview(self):
        with self.assertRaises(scope.ScopeError):
            scope.inventory(self.repo, "range", "--help", "HEAD")
        with self.assertRaises(scope.ScopeError):
            scope.inventory(self.repo, paths=["../outside"])
        with self.assertRaises(scope.ScopeError):
            scope.reconcile(scope.inventory(self.repo), {"files": [
                {"path": "README.md", "status": "modified", "will_review": 1}
            ]})


if __name__ == "__main__":
    unittest.main()
