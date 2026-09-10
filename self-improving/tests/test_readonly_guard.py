"""Read-only inspection must not request approval; writes still must."""

import unittest
from pathlib import Path
from types import SimpleNamespace

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
            import shlex
            with self.subTest(source=source):
                self.assertFalse(self.blocked('python3 -c ' + shlex.quote(source)))

    def test_writes_and_unknown_code_stay_guarded(self):
        import shlex
        for source in (
            "from pathlib import Path; Path('corrections.md').write_text('bad')",
            "open('corrections.md', 'w').write('bad')",
            "from self_improving.review import decide",
            "exec(\"print('corrections.md')\")",
            "import os; os.remove('corrections.md')",
            "from pathlib import Path; Path('corrections.md').unlink()",
            "from pathlib import Path; Path('source').replace('corrections.md')",
            "from pathlib import Path; print = Path('corrections.md').write_text; print('bad')",
            "from pathlib import Path; Path.write_text = print; print('corrections.md')",
            "print('corrections.md', file=open('output', 'w'))",
            "print('corrections.md') # incomplete\n(",
        ):
            with self.subTest(source=source):
                self.assertTrue(self.blocked('python3 -c ' + shlex.quote(source)))

    def test_shell_composition_is_not_exempt(self):
        for command in (
            "python3 -c \"print('corrections.md')\" > corrections.md",
            "python3 -c \"print('corrections.md')\"; touch other",
            "python3 - <<PY\nprint('corrections.md')\nPY",
            "python3 - <<'PY'\nprint('corrections.md')\nPY\nrm corrections.md",
            "python3 -m self_improving review approve --fingerprint example",
        ):
            with self.subTest(command=command):
                self.assertTrue(self.blocked(command))

    def test_callable_callbacks_stay_guarded(self):
        import shlex
        for source in (
            "sorted(['corrections.md'], key=eval)",
            "sorted(['corrections.md'], key=exec)",
            "import json; json.loads('1', parse_int=eval); print('corrections.md')",
            "import json; json.loads('{}', object_hook=exec); print('corrections.md')",
            "import json; callback=eval; json.loads('1', parse_int=callback); print('corrections.md')",
        ):
            with self.subTest(source=source):
                self.assertTrue(self.blocked('python3 -c ' + shlex.quote(source)))
