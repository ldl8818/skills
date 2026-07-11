# Configuration
Configuration is read from `SELF_IMPROVING_CONFIG` or `~/.config/self-improving/config.json`.

## Required fields
- `schema_version`: configuration schema; version 1 is currently supported.
- `memory_root`: private memory directory.
- `state_root`: locks, backups and migration manifests.
- `agents`: enabled Agent adapters and their configuration files.
- `persistence`: correction/error capture settings.

All paths accept `~` and environment-variable expansion. Unknown future schema versions fail explicitly instead of silently using legacy defaults.

`memory_root` may be an ordinary directory, an Obsidian Vault subdirectory, or
a private Git working tree. The software does not infer or publish a remote.

## Safe defaults
- Correction capture: enabled only after an interactive yes or explicit `--capture-corrections`.
- Command-error capture: disabled.
- Central error fallback: disabled.
- Automatic remote creation or data upload: never enabled.
