# Changelog
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
