# Changelog
## 2.5.0 - 2026-07-12
- Codex authority-write guard now emits the same PreToolUse `ask` permission decision as Claude Code, verified against codex-cli 0.144.1 which parses the identical `hookSpecificOutput` protocol. One-click batch approval now works the same way on both platforms; no more hand-pasting commands into a terminal. Codex versions too old to parse hook decisions do not enforce the guard — upgrade Codex.

## 2.4.0 - 2026-07-12
- Add an agent pre-review path toward low-friction learning: `review list --json` emits machine-readable pending candidates, and `SessionStart` injects a review reminder with pre-review guidance once pending candidates reach the reminder threshold. Agents draft distilled rules and recommendations; approval still requires explicit user consent in conversation plus the client permission dialog, and raw candidates are still never injected.
- Recognize Chinese memory directory names (`领域知识`, `项目`, `创作风格`, `归档`, `草稿`) as index categories alongside the legacy English names, whose labels now match (`archive` → `归档`, `styles` → `创作风格`).

## 2.3.0 - 2026-07-12
- Claude Code authority-write guard now returns a PreToolUse `ask` decision instead of a hard block: the user approves or rejects the specific write in the client permission dialog, which in-session text (including injected content) cannot forge. Codex keeps the hard block because it has no equivalent ask mechanism.
- Add `方案` as a recognized memory index category alongside the legacy `设计` directory name.
- Stop link-checking auto-captured candidate logs under `.learnings/`: untrusted captured text is not a document and produced false broken-link warnings in `doctor`.

## 2.2.1 - 2026-07-12
- Add `review legacy-list` with content-derived stable IDs and an explicit `review import-legacy` path that requires a newly distilled answer and global/project scope.
- Make the private approval ledger append-only: approval, revocation and re-approval are auditable events in one authoritative file instead of cross-file state changes.
- Enforce one active rule per legacy source; changing its answer or scope requires revocation first.

## 2.2.0 - 2026-07-12
- Inject human-approved corrections into new Claude Code and Codex sessions within configurable count and character budgets.
- Keep raw correction candidates out of Agent instructions and preserve the human review gate.
- Store new approvals in a machine-readable private JSONL ledger with explicit global/project scope; legacy Markdown rows remain audit-only.
- Add an 8,000-character default budget for the core memory and protect both authority stores from common Agent writes and shell-invoked approval bypasses.
- Add learning-loop health reporting for pending, approved, and currently injectable corrections.
- Add a Chinese zero-to-one guide and troubleshooting guide for first-time users.
- Keep 2.1.x configuration compatible and fill the new injection defaults during upgrade.

## 2.1.1 - 2026-07-11
- Fixed the authority-write guard falsely blocking read-only commands: redirects to `/dev/null` and file descriptors (e.g. `2>/dev/null`, `2>&1`) no longer count as write signals.

## 2.1.0 - 2026-07-11
- Removed the mandatory `YYYY-MM-DD-` date-prefix naming convention and its doctor check; memory documents may use plain descriptive names.

## 2.0.0 - 2026-07-11
- Separated public code, user configuration, runtime state, and private memory.
- Added configurable Claude Code and Codex Hook adapters.
- Added initialization, health checks, persistence controls, legacy migration, upgrades, review, and uninstall commands.
- Replaced fixed author paths with versioned configuration.
- Added safe defaults that keep centralized command-error persistence disabled for new users.
- Added stable index generation, document naming/link checks, and real-event coverage reporting.
- Verified all five Hook event types in fresh Claude Code and Codex sessions.
- Added sanitized real-schema fixtures to catch platform payload drift.
