# Hook adapters
Claude Code and Codex payloads are normalized before core memory logic runs.

The adapters are tested against sanitized payload fixtures captured from real
Claude Code and Codex sessions. Only field names and synthetic example values
are committed under `examples/hook-payloads/`; transcripts and user content are
never copied into the public repository.

## Claude Code
The installer wires `SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse` and `Stop` while preserving existing groups.

At `SessionStart`, the common Hook validates the line and character budgets and
injects the small `memory.md` core. It then reads only approvals written by the
2.2 review command, filters them by the current project/global scope, applies
the configured count and character budgets, and emits them in a separate
`<verified-corrections>` block. Raw candidate and error files are never read as
instructions. If any approval-ledger event is malformed, verified-correction
injection fails closed for that session and `doctor` reports a hard failure.

At `PreToolUse`, writes to the authority files (`memory.md`, `corrections.md`,
the verified JSONL ledger) and shell-invoked approval commands emit an `ask`
permission decision (2.3.0) instead of a hard block: Claude Code shows its
permission dialog and the user approves or rejects that specific call. The
approval happens in the client UI, so in-session text — including injected
content — cannot forge it.

## Codex
The installer uses the same lifecycle names but a separate adapter. Codex currently applies Pre/Post Tool Hooks to shell commands, ignores matchers for UserPromptSubmit and Stop, and uses startup/resume matching for SessionStart.

`PreToolUse` hard-blocks direct writes and common relative, absolute and `$HOME`
shell writes to the configured `memory.md`, `corrections.md` and verified JSONL store. It also refuses approval/rejection commands invoked through an Agent shell. Codex has no equivalent of the Claude Code `ask` permission dialog, so the block stays unconditional there. Because arbitrary shell syntax
cannot be parsed safely with string matching, this is an accidental-write guard,
not a complete sandbox or access-control mechanism. Code running as the same OS
user can deliberately call internal Python APIs or obfuscate a write. Keep
private memory under version control when audit and rollback matter, and run
approval/revocation commands yourself in a normal terminal rather than asking
an Agent to do so.

Installation must preserve unrelated Hooks such as status or notification integrations. After Codex upgrades, run `doctor` and a real-session smoke test because Hook payload fields may evolve.

`doctor` records current-package schema coverage, not proof that every event was
produced by the latest client launch. End-to-end smoke results must be reported
separately from fixture replay.
