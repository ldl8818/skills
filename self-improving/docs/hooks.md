# Hook adapters
Claude Code and Codex payloads are normalized before core memory logic runs.

The adapters are tested against sanitized payload fixtures captured from real
Claude Code and Codex sessions. Only field names and synthetic example values
are committed under `examples/hook-payloads/`; transcripts and user content are
never copied into the public repository.

## Claude Code
The installer wires `SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse` and `Stop` while preserving existing groups.

## Codex
The installer uses the same lifecycle names but a separate adapter. Codex currently applies Pre/Post Tool Hooks to shell commands, ignores matchers for UserPromptSubmit and Stop, and uses startup/resume matching for SessionStart.

`PreToolUse` prevents direct writes and common relative, absolute and `$HOME`
shell writes to the configured `memory.md`. Because arbitrary shell syntax
cannot be parsed safely with string matching, this is an accidental-write guard,
not a complete sandbox or access-control mechanism. Keep private memory under
version control when audit and rollback matter.

Installation must preserve unrelated Hooks such as status or notification integrations. After Codex upgrades, run `doctor` and a real-session smoke test because Hook payload fields may evolve.

`doctor` records current-package schema coverage, not proof that every event was
produced by the latest client launch. End-to-end smoke results must be reported
separately from fixture replay.
