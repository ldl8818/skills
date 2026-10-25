from pathlib import Path
import importlib.util
import subprocess
import sys
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/check_punctuation.py'
SPEC = importlib.util.spec_from_file_location("check_punctuation", SCRIPT)
PUNCTUATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PUNCTUATION)


class InlineCodeTests(unittest.TestCase):
    def test_different_delimiters_and_unmatched_runs(self):
        for text, expected in [
            ("`one` ``two ` three``", ["`one`", "``two ` three``"]),
            ("`one `` two` three``", ["`one `` two`"]),
            ("``` literal `one`", ["`one`"]),
            ("` `` ```", []),
        ]:
            with self.subTest(text=text):
                self.assertEqual(
                    [text[start:end] for start, end in PUNCTUATION._inline_code_spans(text)],
                    expected,
                )

    def test_unmatched_delimiters_do_not_repeatedly_scan_suffixes(self):
        class CountedText(str):
            reads = 0

            def __getitem__(self, key):
                self.reads += 1
                return super().__getitem__(key)

        text = CountedText(" ".join("`" * size for size in range(1, 100)))
        self.assertEqual(list(PUNCTUATION._inline_code_spans(text)), [])
        self.assertLessEqual(text.reads, 8 * len(text))


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
