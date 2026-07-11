# Changelog
## 2.0.0 - 2026-07-11
- Separated public code, user configuration, runtime state, and private memory.
- Added configurable Claude Code and Codex Hook adapters.
- Added initialization, health checks, persistence controls, legacy migration, upgrades, review, and uninstall commands.
- Replaced fixed author paths with versioned configuration.
- Added safe defaults that keep centralized command-error persistence disabled for new users.
- Added stable index generation, document naming/link checks, and real-event coverage reporting.
- Verified all five Hook event types in fresh Claude Code and Codex sessions.
- Added sanitized real-schema fixtures to catch platform payload drift.
