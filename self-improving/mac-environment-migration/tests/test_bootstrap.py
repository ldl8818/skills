from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "bootstrap/setup.command"


class BootstrapTests(unittest.TestCase):
    def shell(self, body):
        # Sourcing only loads functions; no production environment overrides exist.
        return subprocess.run(["/bin/sh", "-c", '. "$1"\n' + body, "test", str(SCRIPT)],
                              text=True, capture_output=True)

    def test_no_python_first_stage(self):
        text = SCRIPT.read_text()
        self.assertNotIn("python", text[:text.index("brew_package python")]
                         if "brew_package python" in text else text[:text.index("# Python is")])

    def test_unsupported_platform_stops_before_install(self):
        result = self.shell('uname() { echo Linux; }; main')
        self.assertEqual(result.returncode, 30)

    def test_arguments_rejected(self):
        self.assertEqual(self.shell('main unexpected').returncode, 64)

    def test_existing_package_never_installs(self):
        result = self.shell('example() { return 0; }; BREW=false; brew_package example')
        self.assertEqual(result.returncode, 0)

    def test_broken_package_does_not_reinstall(self):
        result = self.shell('example() { return 1; }; BREW=true; brew_package example')
        self.assertEqual(result.returncode, 30)

    def test_missing_package_install_failure(self):
        result = self.shell('BREW=false; brew_package nonexistent_example_123')
        self.assertEqual(result.returncode, 30)

    def test_failed_download_is_not_executed(self):
        result = self.shell('curl() { return 22; }; installer https://example.invalid/install.sh')
        self.assertNotEqual(result.returncode, 0)

    def test_script_with_spaces_can_be_loaded(self):
        with tempfile.TemporaryDirectory(prefix="setup test ") as tmp:
            path = Path(tmp) / "setup.command"
            path.write_bytes(SCRIPT.read_bytes())
            result = subprocess.run(["/bin/sh", "-c", '. "$1"; say loaded', "test", str(path)], capture_output=True)
            self.assertEqual(result.returncode, 0)
            self.assertIn(b"loaded", result.stderr)


if __name__ == "__main__":
    unittest.main()
