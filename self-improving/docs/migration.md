# Legacy migration
Preview without writing:

```bash
python3 -m self_improving migrate legacy
```

Apply after reviewing detected paths:

```bash
python3 -m self_improving migrate legacy --apply
```

Migration keeps the existing memory directory in place, writes versioned configuration, backs up Hook files, merges new Hook handlers, and records a manifest under the configured state directory. It does not delete legacy scripts until new-session verification succeeds.

Migration refuses to overwrite an existing self-improving configuration. Use
`upgrade` for an installation that is already configured. Historical
`corrections.md` rows remain audit history; they are not silently imported into
the 2.2 verified-injection ledger.

To retain a still-valid legacy lesson, review and distill it rather than copying
the whole historical incident into every prompt:

```bash
python3 -m self_improving review import-legacy \
  --legacy-id 'legacy:12ab34cd56ef' \
  --correct '工具要求原文展示时，完整原文必须进入最终回复。' \
  --scope global
```

Run `review legacy-list` first; its `legacy:...` identifier is derived from the
raw row content, so it does not drift when unrelated lines are inserted. Use a
project scope for project-only lessons. The returned verified fingerprint is
the stable audit and revocation handle. Promoted, superseded and obsolete rows
normally stay audit-only; do not import them again unless the distilled rule is
missing from current authoritative memory.

When moving the private memory directory to another computer, `global`
approvals remain portable. Project-scoped approvals contain absolute paths; if
the project lives at a different path on the new computer, revoke and approve
that rule again with the new `project:/absolute/path` scope.

Rollback removes managed Hooks with:

```bash
python3 -m self_improving uninstall --keep-data
```

Configuration backups remain available under `state_root/backups/`.
