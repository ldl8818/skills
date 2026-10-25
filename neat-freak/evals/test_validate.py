import importlib.util
from pathlib import Path
import unittest


SPEC = importlib.util.spec_from_file_location("validate", Path(__file__).with_name("validate.py"))
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


class DescriptionTests(unittest.TestCase):
    def test_folded_description_measures_content_instead_of_scalar_marker(self):
        text = '\nname: sample\ndescription: >-\n  first line\n  second line\nmetadata:\n  version: "1"\n'
        self.assertEqual(VALIDATOR.folded_description(text), "first line second line")
        oversized = "description: >-\n  " + "x" * 1025 + "\n"
        self.assertGreater(len(VALIDATOR.folded_description(oversized)), 1024)

    def test_inline_description_stays_supported(self):
        self.assertEqual(VALIDATOR.folded_description('description: "short text"\n'), "short text")
        self.assertEqual(VALIDATOR.folded_description("name: sample\n"), "")
