from pathlib import Path
import subprocess
import tempfile
import unittest
import shlex
import os

SCRIPT = Path(__file__).resolve().parents[1] / "bootstrap/setup.command"


class BootstrapTests(unittest.TestCase):
    def test_documented_one_line_download_and_failure_paths(self):
        doc = SCRIPT.parents[1] / '使用说明.md'
        command = doc.read_text().split('```sh\n', 1)[1].split('\n```', 1)[0]
        self.assertNotIn('\n', command)
        with tempfile.TemporaryDirectory(prefix='one line ') as tmp:
            root = Path(tmp)
            fake = root / 'curl'
            fake.write_text('#!/bin/sh\nwhile [ "$1" != -o ]; do shift; done\ncp "$FIXTURE_SCRIPT" "$2"\nexit "$CURL_RESULT"\n')
            fake.chmod(0o755)
            fixture = root / 'fixture'
            marker = root / 'executed'
            environment = {**os.environ, 'PATH': str(root) + os.pathsep + os.environ['PATH'],
                           'FIXTURE_SCRIPT': str(fixture), 'MARKER': str(marker)}
            fixture.write_text('#!/bin/sh\ntouch "$MARKER"\n')
            failed = subprocess.run(['/bin/sh', '-c', command], env={**environment, 'CURL_RESULT': '22'}, capture_output=True)
            self.assertEqual(failed.returncode, 22)
            self.assertFalse(marker.exists())
            fixture.write_text('if broken\n')
            invalid = subprocess.run(['/bin/sh', '-c', command], env={**environment, 'CURL_RESULT': '0'}, capture_output=True)
            self.assertNotEqual(invalid.returncode, 0)
            self.assertFalse(marker.exists())
            fixture.write_text('#!/bin/sh\ntouch "$MARKER"\n')
            result = subprocess.run(['/bin/sh', '-c', command], env={**environment, 'CURL_RESULT': '0'}, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(marker.exists())

    def tools_shell(self, body):
        with tempfile.TemporaryDirectory() as tmp:
            command = Path(tmp) / 'xcode-select'
            command.write_text('#!/bin/sh\n[ "$1" = --install ] || [ "${MOCK_TOOLS_READY:-no}" = yes ]\n')
            command.chmod(0o755)
            return self.shell('PATH=' + shlex.quote(tmp) + ':"$PATH"; ' + body)

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

    def test_terminal_repo_and_ghostty_do_not_require_switch(self):
        result = self.shell('parse_args --repo example/dotfiles; ask() { exit 99; }; confirm_ghostty')
        self.assertEqual(result.returncode, 0)

    def test_terminal_waits_for_tools_and_continues(self):
        result = self.tools_shell('agent_mode=false; ask() { export MOCK_TOOLS_READY=yes; answer=""; }; wait_for_tools')
        self.assertEqual(result.returncode, 0)

    def test_terminal_tools_can_pause(self):
        result = self.tools_shell('agent_mode=false; ask() { answer=q; }; wait_for_tools')
        self.assertEqual(result.returncode, 20)

    def test_agent_tools_still_return_structured_action(self):
        result = self.tools_shell('agent_mode=true; ask() { exit 99; }; wait_for_tools')
        self.assertEqual(result.returncode, 20)
        self.assertIn('command_line_tools', result.stdout)

    def test_agent_selection_and_no_ghostty_prompt(self):
        result = self.shell('parse_args --agent --repo example/dotfiles; ask() { exit 99; }; confirm_ghostty')
        self.assertEqual(result.returncode, 0)

    def test_agent_requires_nonsecret_repository(self):
        for args in ['--agent', '--agent --repo https://user:secret@example.invalid/repo', '--agent --repo example/repo --prerequisites']:
            self.assertEqual(self.shell('parse_args ' + args).returncode, 64)

    def test_manual_action_is_structured_without_stdin(self):
        import json
        result = self.shell('action github_login')
        self.assertEqual(result.returncode, 20)
        self.assertEqual(json.loads(result.stdout), {"schema": 1, "status": "manual_required", "action": "github_login"})

    def test_missing_brew_hands_off_without_running_installer(self):
        import json
        # Replace commands through PATH, keeping the actual entrypoint and no TTY.
        with tempfile.TemporaryDirectory(prefix="bootstrap-agent-") as tmp:
            fake = Path(tmp)
            commands = {"uname": 'if [ "$1" = -s ]; then echo Darwin; else echo arm64; fi',
                        "id": 'echo 501', "sw_vers": 'echo 15.0', "xcode-select": 'exit 0'}
            for name, body in commands.items():
                path = fake / name
                path.write_text('#!/bin/sh\n' + body + '\n')
                path.chmod(0o755)
            import os
            result = subprocess.run(["/bin/sh", "-c", '. "$1"; brew_find() { return 1; }; installer() { exit 99; }; main --agent --repo example/dotfiles', "test", str(SCRIPT)],
                                    env={**os.environ, "PATH": str(fake) + os.pathsep + os.environ.get("PATH", "")},
                                    stdin=subprocess.DEVNULL, capture_output=True, text=True)
            self.assertEqual(result.returncode, 20)
            self.assertEqual(json.loads(result.stdout)["action"], "homebrew_install")

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
