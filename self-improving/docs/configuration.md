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
- Free-form `memory.md` injection: disabled.
- Resumed-session injection without a knowledge catalog: unchanged context is skipped; newly changed context is supplied once. With a catalog, resume reloads the base and resets knowledge deduplication.
- Total dynamic-context budget: 1,200 estimated tokens.
- Automatic remote creation or data upload: never enabled.

## Approved-correction injection

```json
{
  "injection": {
    "include_core_memory": false,
    "include_verified_corrections": true,
    "resume_mode": "skip",
    "max_total_tokens": 1200,
    "min_verified_version": 2,
    "review_reminder_interval_hours": 24,
    "max_core_chars": 8000,
    "max_verified_corrections": 20,
    "max_verified_chars": 4000
  }
}
```

- `include_core_memory`: inject `memory.md`; disabled by default because stable policy belongs in Agent/project rules and detailed knowledge is read on demand.
- `include_verified_corrections`: inject eligible approvals at a new-session `SessionStart`.
- `resume_mode` (without a knowledge catalog): `skip` records a per-session digest and avoids reinjecting unchanged context on resume; a changed set is supplied once as a full replacement, and an empty set emits a one-time clear signal. `always` emits eligible context on every resume.
- `max_total_tokens`: shared estimated-token ceiling for all dynamic sections; range 0–20,000.
- `min_verified_version`: minimum approval format accepted for injection; range 1–2, default 2.
- `review_reminder_interval_hours`: minimum interval between Stop reminders; range 0–720.
- `max_core_chars`: maximum characters allowed in `memory.md`; range 0–50,000. The default is 8,000.
- `max_verified_corrections`: maximum number of newest approved answers; range 0–200.
- `max_verified_chars`: maximum total characters from approved answers; range 0–20,000.

Only approval events written to the append-only
`.self-improving/verified-corrections.jsonl` ledger by the review command
qualify. Approval, promotion and revocation are folded into current state from that single
audit source. Each v2 approval has an approval time, priority, promotion target,
review date, expiry date and a `global`, repository or project scope. Repository
scope uses stable Git identity, so linked worktrees match the same rule. Raw candidates, legacy v1 or Markdown rows,
rejected rows, error logs, malformed records and answers matching credential
patterns are excluded. Budget omissions, ignored legacy records and lifecycle
problems produce a receipt and appear in `doctor`. Existing configurations receive the new limits,
but their historical `corrections.md` rows do not become instructions merely
because the program was upgraded.

`review lifecycle-list` displays active, due and expired v2 rules with their
scope, dates and promotion target. After the target has actually been updated,
`review promote` stops injection by appending a promotion event; `review revoke`
withdraws a wrong or obsolete rule. Neither operation deletes audit history.

`doctor` uses the same receipt reserve, resume-update reserve, wrapper cost and core-memory deduction as
runtime, then evaluates that remaining budget against a conservative all-scope
upper bound, because the command itself runs from the Skill directory rather than the
project that will consume a repository- or project-scoped rule. Runtime
injection still selects only scopes that match the session's actual working
directory.

Error capture uses structured failure fields only; successful output is not a
failure merely because it contains words such as `error` or `failed`.
When a client exposes only an opaque output string, that client is skipped
rather than classified by keywords; `doctor` reports the missing structured
contract when error capture is enabled.
`persistence.max_error_entries` caps the local error ledger at 200 rows by default.

With a private knowledge catalog, resume conservatively reloads the base and resets knowledge deduplication regardless of `resume_mode`. Catalog routing is documented in [knowledge.md](knowledge.md); it adds no capture or approval switch.
