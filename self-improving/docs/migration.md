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

Rollback removes managed Hooks with:

```bash
python3 -m self_improving uninstall --keep-data
```

Configuration backups remain available under `state_root/backups/`.
