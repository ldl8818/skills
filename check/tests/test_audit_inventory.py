import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/audit_signals.py"
SPEC = importlib.util.spec_from_file_location("audit_signals", SCRIPT)
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


class InventoryTests(unittest.TestCase):
    def test_non_object_manifest_does_not_abort_audit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            for data in ("[]", "null", "42", '"invalid"'):
                with self.subTest(data=data):
                    (root / "package.json").write_text(data)
                    self.assertEqual(AUDIT._package_bin_entrypoints(root), [])
            (root / "package.json").write_text('{"name":"sample","bin":"cli.js"}')
            self.assertEqual(
                AUDIT._package_bin_entrypoints(root),
                ["package.json bin:sample -> cli.js"],
            )

    def test_empty_git_inventory_does_not_scan_ignored_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            (root / ".git/info/exclude").write_text("*\n")
            (root / "private.py").write_text("SYNTHETIC_PRIVATE = True\n")
            self.assertEqual(AUDIT.iter_files(root), [])

    def test_git_inventory_keeps_visible_untracked_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            (root / ".git/info/exclude").write_text("private.py\n")
            (root / "private.py").touch()
            (root / "visible.py").touch()
            self.assertEqual(AUDIT.iter_files(root), [root / "visible.py"])

    def test_non_git_directory_still_uses_filesystem_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "visible.py").touch()
            self.assertEqual(AUDIT.iter_files(root), [root / "visible.py"])
