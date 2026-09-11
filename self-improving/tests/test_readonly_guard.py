"""Read-only inspection must not request approval; writes still must."""

import unittest
from pathlib import Path
from types import SimpleNamespace
import shlex

from self_improving.hooks.common import _dangerous_authority_write


class ReadonlyGuardTests(unittest.TestCase):
    def blocked(self, command):
        event = SimpleNamespace(event="PreToolUse", tool_name="Bash",
                                tool_input={"command": command}, cwd="/example/memory")
        return _dangerous_authority_write(event, Path(event.cwd))

    def test_readonly_heredoc(self):
        command = """python3 - <<'PY'
from pathlib import Path
b = Path('/example/memory')
for name in ['memory.md', 'index.md', 'corrections.md']:
    p = b / name
    print('FILE', p)
    for i, line in enumerate(p.read_text().splitlines(), 1):
        print(f'{i}: {line}')
PY"""
        self.assertFalse(self.blocked(command))

    def test_readonly_inline_and_literals(self):
        for source in (
            "from pathlib import Path; print(Path('corrections.md').read_text())",
            "import json; print(json.loads('{\"file\": \"corrections.md\"}'))",
            "print('self_improving.review corrections.md >')",
        ):
            with self.subTest(source=source):
                self.assertFalse(self.blocked('python3 -c ' + shlex.quote(source)))

    def test_writes_and_unknown_code_stay_guarded(self):
        for source in (
            "from pathlib import Path; Path('.self-improving/verified-corrections.jsonl').write_text('bad')",
            "open('.self-improving/verified-corrections.jsonl', 'w').write('bad')",
            "from self_improving.review import decide",
            "exec(\"print('verified-corrections.jsonl')\")",
            "import os; os.remove('.self-improving/verified-corrections.jsonl')",
            "from pathlib import Path; Path('.self-improving/verified-corrections.jsonl').unlink()",
            "from pathlib import Path; Path('source').replace('.self-improving/verified-corrections.jsonl')",
            "from pathlib import Path; print = Path('.self-improving/verified-corrections.jsonl').write_text; print('bad')",
            "from pathlib import Path; Path.write_text = print; print('verified-corrections.jsonl')",
            "print('verified-corrections.jsonl', file=open('output', 'w'))",
            "print('verified-corrections.jsonl') # incomplete\n(",
        ):
            with self.subTest(source=source):
                self.assertTrue(self.blocked('python3 -c ' + shlex.quote(source)))

    def test_shell_composition_is_not_exempt(self):
        for command in (
            "python3 -c \"print('verified-corrections.jsonl')\" > .self-improving/verified-corrections.jsonl",
            "python3 -c \"print('verified-corrections.jsonl')\"; touch other",
            "python3 - <<PY\nprint('verified-corrections.jsonl')\nPY",
            "python3 - <<'PY'\nprint('verified-corrections.jsonl')\nPY\nrm .self-improving/verified-corrections.jsonl",
            "python3 -m self_improving review approve --fingerprint example",
        ):
            with self.subTest(command=command):
                self.assertTrue(self.blocked(command))

    def test_callable_callbacks_stay_guarded(self):
        for source in (
            "sorted(['verified-corrections.jsonl'], key=eval)",
            "sorted(['verified-corrections.jsonl'], key=exec)",
            "import json; json.loads('1', parse_int=eval); print('verified-corrections.jsonl')",
            "import json; json.loads('{}', object_hook=exec); print('verified-corrections.jsonl')",
            "import json; callback=eval; json.loads('1', parse_int=callback); print('verified-corrections.jsonl')",
        ):
            with self.subTest(source=source):
                self.assertTrue(self.blocked('python3 -c ' + shlex.quote(source)))

    def test_markdown_maintenance_is_allowed(self):
        for command in ("printf updated >> corrections.md", "mv corrections.md archive/"):
            self.assertFalse(self.blocked(command))

    def test_pipeline_keeps_interpreter_and_source_together(self):
        for pipe in (' | ', ' |& '):
            command = "printf '%s' \"open('.self-improving/verified-corrections.jsonl', 'w').write('bad')\"" + pipe + 'python3'
            self.assertTrue(self.blocked(command))

            source = command.rsplit(pipe, 1)[0]
            self.assertTrue(self.blocked('(' + source + ')' + pipe + 'python3'))
            self.assertTrue(self.blocked('(' + source + '; printf done)' + pipe + 'python3'))

    def test_table_inspection(self):
        self.assertFalse(self.blocked("""python3 - <<'PY'
from pathlib import Path
p = Path('/example/memory/verified-corrections.jsonl')
for n, line in enumerate(p.read_text().splitlines(), 1):
    if line.startswith('| 20'):
        parts = line.split('|')
        print(n, parts[1].strip(), parts[3].strip()[:130], parts[-3].strip())
PY"""))

    def test_search_and_review_list(self):
        for separator in ('; ', '\n', ' && '):
            command = separator.join((
                "rg -n 'append_verified_correction' self_improving/storage.py",
                'python3 -m self_improving review lifecycle-list --json',
            ))
            with self.subTest(separator=separator):
                self.assertFalse(self.blocked(command))
                self.assertTrue(self.blocked(command + separator +
                    "python3 -c 'from self_improving.review import decide'"))
                self.assertTrue(self.blocked(command + separator +
                    "mv verified-corrections.jsonl archive.md"))
                self.assertTrue(self.blocked(command + separator +
                    'python3 -m self_improving review approve --fingerprint example'))
