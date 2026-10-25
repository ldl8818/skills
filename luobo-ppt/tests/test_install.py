"""Exercise the real shell installer only against disposable synthetic kits."""
import hashlib
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

INSTALLER = Path(__file__).resolve().parents[1] / "install.sh"


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="luobo-install-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.kit = self.root / "kit"
        self.kit.mkdir()
        shutil.copyfile(INSTALLER, self.kit / "install.sh")
        (self.kit / "SKILL.md").write_text("synthetic skill\n")
        (self.kit / "scripts").mkdir()
        (self.kit / "scripts/setup_check.py").write_text("raise SystemExit(0)\n")
        self.target = self.root / "skills"
        self.target.mkdir()
        self.dst = self.target / "luobo-ppt"
        self.dst.mkdir()
        (self.dst / "old.txt").write_text("KEEP")
        (self.dst / "config.json").write_text('{"synthetic": true}\n')
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.env = {"PATH": f"{self.bin}:/usr/bin:/bin", "HOME": str(self.root / "home"),
                    "TMPDIR": str(self.root), "LANG": "en_US.UTF-8"}

    def shim(self, name, code):
        path = self.bin / name
        path.write_text("#!/bin/bash\nset -eu\n" + code)
        path.chmod(0o755)

    def run_install(self, source=None, target=None):
        return subprocess.run(
            ["/bin/bash", str((source or self.kit) / "install.sh"),
             "--dest", str(target or self.target), "--skip-deps"],
            env=self.env, capture_output=True, text=True, timeout=15)

    def assert_old_and_clean(self):
        self.assertEqual((self.dst / "old.txt").read_text(), "KEEP")
        self.assertEqual((self.dst / "config.json").read_text(), '{"synthetic": true}\n')
        self.assertEqual(sorted(p.name for p in self.target.iterdir()), ["luobo-ppt"])

    def test_success_keeps_config_and_cleans_staging(self):
        result = self.run_install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.dst / "SKILL.md").read_text(), "synthetic skill\n")
        self.assertEqual((self.dst / "config.json").read_text(), '{"synthetic": true}\n')
        self.assertEqual(sorted(p.name for p in self.target.iterdir()), ["luobo-ppt"])
        self.assertTrue((self.kit / "install.sh").exists())

    def test_copy_failure_preserves_existing_install(self):
        self.shim("tar", "exit 42\n")
        self.assertNotEqual(self.run_install().returncode, 0)
        self.assert_old_and_clean()

    def test_staged_config_symlink_does_not_overwrite_other_file(self):
        outside = self.root / "outside.json"
        outside.write_text("KEEP OUTSIDE")
        (self.kit / "config.json").symlink_to(outside)
        self.assertEqual(self.run_install().returncode, 0)
        self.assertEqual(outside.read_text(), "KEEP OUTSIDE")
        self.assertFalse((self.dst / "config.json").is_symlink())
        self.assertEqual((self.dst / "config.json").read_text(), '{"synthetic": true}\n')

    def test_config_copy_failure_preserves_existing_install(self):
        self.shim("cp", "exit 45\n")
        self.assertNotEqual(self.run_install().returncode, 0)
        self.assert_old_and_clean()

    def test_failed_rollback_preserves_backup_and_reports_location(self):
        self.shim("mv", 'if [[ "$1" == */new || "$1" == */old ]]; then exit 43; fi\nexec /bin/mv "$@"\n')
        result = self.run_install()
        self.assertNotEqual(result.returncode, 0)
        backups = list(self.target.glob(".luobo-ppt.install.*/old/old.txt"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), "KEEP")
        self.assertIn(str(backups[0].parent), result.stderr)

    def test_empty_successful_copy_is_rejected(self):
        self.shim("tar", "cat >/dev/null || true\nexit 0\n")
        self.assertNotEqual(self.run_install().returncode, 0)
        self.assert_old_and_clean()

    def test_publish_failure_rolls_back(self):
        self.shim("mv", 'if [[ "$1" == */new && "$2" == */luobo-ppt ]]; then exit 43; fi\nexec /bin/mv "$@"\n')
        self.assertNotEqual(self.run_install().returncode, 0)
        self.assert_old_and_clean()

    def test_signal_during_copy_cleans_staging(self):
        self.shim("tar", 'kill -TERM "$PPID"\nexit 44\n')
        self.assertNotEqual(self.run_install().returncode, 0)
        self.assert_old_and_clean()

    def test_signal_after_publish_rolls_back(self):
        self.shim("mv", 'if [[ "$1" == */new && "$2" == */luobo-ppt ]]; then\n'
                  '  /bin/mv "$@"\n  kill -TERM "$PPID"\n  exit 0\nfi\nexec /bin/mv "$@"\n')
        self.assertNotEqual(self.run_install().returncode, 0)
        self.assert_old_and_clean()

    def test_interrupted_first_install_restores_absent_destination(self):
        shutil.rmtree(self.dst)
        self.shim("mv", 'if [[ "$1" == */new && "$2" == */luobo-ppt ]]; then\n'
                  '  /bin/mv "$@"\n  kill -TERM "$PPID"\n  exit 0\nfi\nexec /bin/mv "$@"\n')
        self.assertNotEqual(self.run_install().returncode, 0)
        self.assertFalse(self.dst.exists())
        self.assertEqual(list(self.target.iterdir()), [])

    def test_alias_install_to_self_preserves_source(self):
        alias = self.root / "alias"
        alias.symlink_to(self.kit, target_is_directory=True)
        target = self.root / "same"
        target.mkdir()
        (target / "luobo-ppt").symlink_to(self.kit, target_is_directory=True)
        self.assertEqual(self.run_install(alias, target).returncode, 0)
        self.assertTrue((self.kit / "SKILL.md").exists())
        self.assertTrue((target / "luobo-ppt").is_symlink())

    def test_source_directory_alias_to_real_destination(self):
        shutil.copytree(self.kit, self.dst, dirs_exist_ok=True)
        alias = self.root / "alias"
        alias.symlink_to(self.dst, target_is_directory=True)
        self.assertEqual(self.run_install(alias).returncode, 0)
        self.assertTrue((self.dst / "SKILL.md").exists())
        self.assertTrue((self.dst / "install.sh").exists())

    def test_containment_rejected_both_directions(self):
        nested_target = self.kit / "nested"
        nested_target.mkdir()
        self.assertNotEqual(self.run_install(target=nested_target).returncode, 0)
        self.assertTrue((self.kit / "SKILL.md").exists())
        child = self.dst / "source"
        shutil.copytree(self.kit, child)
        self.assertNotEqual(self.run_install(source=child).returncode, 0)
        self.assertTrue((child / "SKILL.md").exists())
        self.assert_old_and_clean()

    def test_different_destination_symlink_does_not_delete_referent(self):
        target = self.root / "linked"
        target.mkdir()
        (target / "luobo-ppt").symlink_to(self.dst, target_is_directory=True)
        self.assertEqual(self.run_install(target=target).returncode, 0)
        self.assertEqual((self.dst / "old.txt").read_text(), "KEEP")
        self.assertTrue((target / "luobo-ppt/SKILL.md").exists())

    def test_full_skill_cli_install_and_repeat_in_clean_home(self):
        home = Path(self.env["HOME"])
        self.assertFalse(home.exists())
        command = ["/bin/bash", str(INSTALLER), "--agent", "codex", "--skip-deps"]
        destination = home / ".agents/skills/luobo-ppt"
        snapshots = []
        for _ in range(2):
            result = subprocess.run(command, env=self.env, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            snapshots.append({str(p.relative_to(destination)): hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in destination.rglob("*") if p.is_file()})
        self.assertEqual(snapshots[0], snapshots[1])
        self.assertIn("scripts/setup_check.py", snapshots[0])
        self.assertIn("scripts/build_deck.py", snapshots[0])
        self.assertIn("tests/test_regressions.py", snapshots[0])
        self.assertEqual(list(destination.parent.glob(".luobo-ppt.install.*")), [])


if __name__ == "__main__":
    unittest.main()
