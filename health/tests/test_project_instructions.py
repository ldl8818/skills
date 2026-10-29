import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'check_agent_context.py'


class ProjectInstructionTests(unittest.TestCase):
    def audit(self, settings):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / 'project'
            project.mkdir()
            (project / 'AGENTS.md').write_text('# Project\nUse the project test command.\n')
            home = root / 'home'
            (home / '.claude').mkdir(parents=True)
            (home / '.claude' / 'settings.json').write_text(json.dumps(settings))
            result = subprocess.run(
                [sys.executable, '-I', str(SCRIPT), str(project), 'summary', '--include-global'],
                capture_output=True, text=True, env={**os.environ, 'HOME': str(home)}, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            return result.stdout

    def test_agents_fallback_is_recognized_without_explicit_plugin_config(self):
        output = self.audit({})
        self.assertIn('project_instructions_mode: claude-md-or-agents-md', output)
        self.assertNotIn('Claude instruction surface not found', output)

    def test_current_plugin_options_control_instruction_loading(self):
        output = self.audit({'pluginConfigs': {'cc-plugin-agents-md@builtin': {'options': {'instructionFiles': 'claude-md-and-agents-md'}}}})
        self.assertIn('project_instructions_mode: claude-md-and-agents-md', output)
        self.assertNotIn('Claude instruction surface not found', output)

    def test_legacy_plugin_options_remain_supported(self):
        output = self.audit({'pluginConfigs': {'agents-md@builtin': {'options': {'instructionFiles': 'claude-md-and-agents-md'}}}})
        self.assertIn('project_instructions_mode: claude-md-and-agents-md', output)
        self.assertNotIn('Claude instruction surface not found', output)

    def test_disabled_plugin_excludes_agents_only_instruction_surface(self):
        for name in ['cc-plugin-agents-md@builtin', 'agents-md@builtin']:
            with self.subTest(plugin=name):
                output = self.audit({'enabledPlugins': {name: False}})
                self.assertIn('project_instructions_mode: claude-md', output)
                self.assertIn('Claude instruction surface not found', output)


if __name__ == '__main__':
    unittest.main()
