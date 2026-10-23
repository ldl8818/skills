import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SKILL = Path(__file__).resolve().parents[1]


class FullStaticCollectionTests(unittest.TestCase):
    def test_full_static_collection_restores_maintainability_without_reading_history(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            skill = root / 'installed-health'
            shutil.copytree(SKILL, skill, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            project = root / 'project'
            project.mkdir()
            (project / 'AGENTS.md').write_text('## Project\nSynthetic fixture\n## Verification\nRun `make test`.\n')
            home = root / 'home'
            key = str(project).replace('/', '-').replace('_', '-')
            history = home / '.claude/projects' / key
            history.mkdir(parents=True)
            (history / 'previous.jsonl').write_text(json.dumps({'message': 'Access denied - path outside allowed directories HISTORY_SENTINEL'}) + '\n')
            (skill / 'scripts/conversation_audit.py').write_text('raise SystemExit("HISTORY_HELPER_WAS_RUN")\n')
            result = subprocess.run(['/bin/bash', str(skill / 'scripts/collect-data.sh'), '--include-global', 'instructions', 'deep'],
                                    cwd=project, env={**os.environ, 'HOME': str(home)},
                                    capture_output=True, text=True, timeout=45)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('=== AI MAINTAINABILITY DETAIL ===', result.stdout)
            self.assertIn('=== AGENT CONFIG DETAIL ===', result.stdout)
            self.assertIn('session history not read', result.stdout)
            self.assertNotIn('HISTORY_SENTINEL', result.stdout + result.stderr)
            self.assertNotIn('HISTORY_HELPER_WAS_RUN', result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
