# Legacy migration
Preview without writing:

```bash
python3 -m self_improving migrate legacy
```

Apply after reviewing detected paths:

```bash
python3 -m self_improving migrate legacy --apply
```

Migration keeps the existing memory directory in place, writes versioned configuration, backs up Hook files, merges new Hook handlers, and records a manifest under the configured state directory. It preserves the v3 safe default with command-error capture disabled and does not delete legacy scripts until new-session verification succeeds.

Migration refuses to overwrite an existing self-improving configuration. Use
`upgrade` for an installation that is already configured. Historical
`corrections.md` rows and v1 JSONL approvals remain audit history; they are not silently imported into
the verified-injection ledger.

To retain a still-valid legacy lesson, review and distill it rather than copying
the whole historical incident into every prompt:

```bash
python3 -m self_improving review import-legacy \
  --legacy-id 'legacy:12ab34cd56ef' \
  --correct '工具要求原文展示时，完整原文必须进入最终回复。' \
  --scope global \
  --promotion-target global-rules
```

Run `review legacy-list` first. It lists eligible legacy Markdown rows and active
v1 JSONL approvals under stable `legacy:...` identifiers. A Markdown identifier
is derived from raw row content, so it does not drift when unrelated lines are inserted. Use a
repository scope for one Git repository including linked worktrees, or project
scope for one directory tree. The returned v2 fingerprint is the stable audit
and lifecycle handle; the approval also receives review and expiry dates. After
a v1 JSONL approval is replaced successfully, the importer appends a revoke event
for the old record so it is not offered again.
Promoted, superseded and obsolete rows
normally stay audit-only; do not import them again unless the distilled rule is
missing from current authoritative memory.

When moving the private memory directory to another computer, `global`
approvals remain portable. Repository identity uses the remote URL when one is
configured. Project-scoped approvals contain absolute paths; if
the project lives at a different path on the new computer, revoke and approve
that rule again with the new `project:/absolute/path` scope.

Copy the complete verified ledger, including revocation and promotion events,
and the memory root marker; do not export only currently active rows.
The knowledge catalog lives in `memory_root`, but its review receipts live in
`state_root/knowledge/accepted.json`. Register that file separately from disposable
session state. Knowledge revisions include resolved paths and dependencies;
moving identical documents can still require review. Run `knowledge check`,
read affected sources and dependencies, then accept the checked revision.
Do not copy old client-event evidence as proof of a new machine's readiness.
For the planned whole-machine workflow, see [新机转移](新机转移.md).

Rollback removes managed Hooks with:

```bash
python3 -m self_improving uninstall --keep-data
```

Configuration backups remain available under `state_root/backups/`.
