from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'incident_ledger.py'


class IncidentLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        self.tests = self.root / 'tests'
        self.tests.mkdir()
        self.catcher = self.tests / 'test_checkout.py'
        self.catcher.write_text('def test_total():\n    assert 1 + 1 == 2\n')
        subprocess.run(['git', '-C', str(self.root), 'add', 'tests/test_checkout.py'], check=True)
        self.ledger = self.root / 'docs' / 'incidents.md'
        self.ledger.parent.mkdir()
        self.sha = subprocess.check_output(['git', 'hash-object', '-t', 'commit', '--stdin'], input=b'tree 4b825dc642cb6eb9a060e54bf8d69288fbee4904\nauthor Test <test@example.invalid> 0 +0000\ncommitter Test <test@example.invalid> 0 +0000\n\nfixture\n', cwd=self.root).decode().strip()
        # A shallow repository exercises the documented shape-only commit mode.
        (self.root / '.git' / 'shallow').write_text(self.sha + '\n')

    def run_ledger(self, catcher='test_total', reported='2026-10-29'):
        self.ledger.write_text(
            '## Incidents\n\n<!-- layers: unit, integration -->\n\n'
            '| ID | Reported | Fixed | Layer | Caught by |\n'
            '|---|---|---|---|---|\n'
            f'| I-01 | {reported} | {self.sha} | unit | `{catcher}` |\n')
        return subprocess.run([sys.executable, str(SCRIPT), '--root', str(self.root)], text=True, capture_output=True, timeout=10)

    def test_defined_catcher_and_tracked_gate_are_valid(self):
        self.assertEqual(self.run_ledger().returncode, 0)
        self.assertEqual(self.run_ledger('tests/test_checkout.py').returncode, 0)

    def test_call_to_missing_test_does_not_count_as_definition(self):
        self.catcher.write_text('def test_other():\n    test_total()\n')
        result = self.run_ledger()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('catcher', result.stdout)

    def test_deleted_tracked_gate_is_not_live_coverage(self):
        self.catcher.unlink()
        result = self.run_ledger('tests/test_checkout.py')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)

    def test_quoted_catcher_must_be_a_test_declaration(self):
        self.catcher = self.tests / 'checkout.test.js'
        self.catcher.write_text('test("totals stay exact", () => { expect(2).toBe(2); });\n')
        subprocess.run(['git', '-C', str(self.root), 'add', 'tests/checkout.test.js'], check=True)
        self.assertEqual(self.run_ledger('totals stay exact').returncode, 0)
        self.catcher.write_text('const description = "totals stay exact";\n')
        self.assertEqual(self.run_ledger('totals stay exact').returncode, 1)

    def test_impossible_calendar_date_is_rejected(self):
        self.assertEqual(self.run_ledger(reported='2026-02-30').returncode, 1)
        self.assertEqual(self.run_ledger(reported='2024-02-29').returncode, 0)


if __name__ == '__main__':
    unittest.main()
