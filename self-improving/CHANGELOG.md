# Changelog
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
