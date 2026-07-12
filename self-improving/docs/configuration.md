# Configuration
Configuration is read from `SELF_IMPROVING_CONFIG` or `~/.config/self-improving/config.json`.

## Required fields
- `schema_version`: configuration schema; version 1 is currently supported.
- `memory_root`: private memory directory.
- `state_root`: locks, backups and migration manifests.
- `agents`: enabled Agent adapters and their configuration files.
- `persistence`: correction/error capture settings.
- `injection`: later-session injection of human-approved corrections.

All paths accept `~` and environment-variable expansion. Unknown future schema versions fail explicitly instead of silently using legacy defaults.

`memory_root` may be an ordinary directory, an Obsidian Vault subdirectory, or
a private Git working tree. The software does not infer or publish a remote.

## Safe defaults
- Correction capture: enabled only after an interactive yes or explicit `--capture-corrections`.
- Command-error capture: disabled.
- Automatic remote creation or data upload: never enabled.

## Approved-correction injection

```json
{
  "injection": {
    "include_verified_corrections": true,
    "max_core_chars": 8000,
    "max_verified_corrections": 20,
    "max_verified_chars": 4000
  }
}
```

- `include_verified_corrections`: inject approved answers at `SessionStart`.
- `max_core_chars`: maximum characters allowed in `memory.md`; range 0–50,000. The default is 8,000.
- `max_verified_corrections`: maximum number of newest approved answers; range 0–200.
- `max_verified_chars`: maximum total characters from approved answers; range 0–20,000.

Only approval events written to the append-only
`.self-improving/verified-corrections.jsonl` ledger by the review command
qualify. Approval and revocation are folded into current state from that single
audit source. Each approval has an approval time and either a
`global` or `project:/absolute/path` scope. Raw candidates, legacy Markdown rows,
rejected rows, error logs, malformed records and answers matching credential
patterns are excluded. Existing 2.1.x configurations receive the new limits,
but their historical `corrections.md` rows do not become instructions merely
because the program was upgraded.
