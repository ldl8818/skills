from pathlib import Path
import subprocess
import sys
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/check_punctuation.py'


class WikilinkPreservationTests(unittest.TestCase):
    def run_checker(self, text, *args):
        return subprocess.run([sys.executable, str(SCRIPT), '--lang', 'zh', *args],
                              input=text, capture_output=True, text=True, timeout=10)

    def test_obsidian_target_before_pipe_is_literal_and_alias_after_pipe_is_prose(self):
        # Obsidian syntax is [[target|display text]], not [[display text|target]].
        good = self.run_checker('见 [[docs/Python教程|Python 教程]]。\n')
        self.assertEqual(good.returncode, 0, good.stdout)
        bad = self.run_checker('见 [[docs/python|Python教程]]。\n')
        self.assertEqual(bad.returncode, 1, bad.stdout)
        self.assertIn('zh-missing-space', bad.stdout)

    def test_fix_preserves_link_identity_and_changes_only_visible_alias(self):
        result = self.run_checker('见 [[docs/Python教程|Python教程]]。\n', '--fix')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, '见 [[docs/Python教程|Python 教程]]。\n')

    def test_unaliased_links_and_inline_code_remain_literal(self):
        result = self.run_checker('见 [[docs/Python教程]] 与 `中文,标点`。\n')
        self.assertEqual(result.returncode, 0, result.stdout)


if __name__ == '__main__':
    unittest.main()
