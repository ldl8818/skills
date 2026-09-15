# Reviewed knowledge on demand

Knowledge routing is optional. Without `knowledge-catalog.json` in the configured private `memory_root`, the existing correction-only behavior remains unchanged. Never place private sources or a real catalog in this public repository.

## Register and review sources

The catalog is the only manually maintained route table. Text stays in the original Markdown; `sync` generates titles, line counts and a registered view alongside full-document discovery. Registration and scope expansion require user authorization. An authorized maintenance task may review its own source changes without another permission round.

```json
{
  "version": 1,
  "roots": ["./domains"],
  "entries": [
    {
      "id": "design",
      "path": "domains/design.md",
      "status": "active",
      "scope": "global",
      "triggers": ["architecture", "workflow"],
      "exclude": ["do not discuss architecture"],
      "sections": ["## Rules"],
      "dependencies": [],
      "required": false
    }
  ]
}
```

Paths are relative to the private memory root unless absolute. Roots must be bounded directories, never the home or filesystem root. There are at most128 entries. `scope` uses the existing global/project/repo syntax. `active` routes by triggers; `reference` monitors a source without injecting its body. Empty sections mean full text. Set `required: true` and empty sections for sources that must be read in full. Optional `source` names a source copy whose bytes must equal the deployed file. Direct dependency IDs bind the reviewed revision, without recursive invalidation of the entire library.

Run from the source checkout's `src/` directory, or use the installed CLI:

```bash
python3 -m self_improving knowledge check --json
python3 -m self_improving knowledge list
python3 -m self_improving knowledge list --all
python3 -m self_improving knowledge read design
python3 -m self_improving knowledge read design --full
python3 -m self_improving knowledge accept --revision <digest-from-check>
python3 -m self_improving sync
```

Run `sync` when source text, titles, paths or catalog inputs change. Run `python3 -m self_improving doctor` when installation, configuration or Hook wiring changes; a wording-only update does not require a full diagnosis. Changes to authorization, routing or workflow instructions need targeted behavior scenarios as well as source and deployment checks.

`check` exits1 for invalid or unreviewed sources. It reports exact repeated clauses as review leads, not automatic deletion requests. Existing doctor link checks supplement it. Read the changed sources and their direct dependencies, resolve semantic conflicts within authorization, verify deployment, then accept the exact digest. Concurrent changes reject acceptance. `accept` confirms only a reviewed knowledge version; it neither approves policy nor changes the correction ledger. When policy changes, also inspect `review lifecycle-list --json` and use the existing guarded correction workflow for promotion or revocation.

## Runtime contract

With a catalog, SessionStart supplies a short lookup entry and eligible corrections. Startup, clear, compact and resume reset knowledge deduplication; resume conservatively supplies the base once. Compact recovers the most recently requested IDs only if still active in the current scope. This is a generated-output receipt, not proof that a model read or followed the document.

UserPromptSubmit routes original reviewed sections, at most2 bodies per event. Correction capture can be disabled independently. Fenced code, explicit catalog exclusions and unrelated prompts do not load domain bodies. Keyword matching is imperfect: use list/read when intent is ambiguous or not matched.

Corrections, knowledge and short receipts share the configured event token estimate, default1200. Required full documents over budget are never truncated: the Hook returns a `knowledge read ID --full` obligation. Explicit reading costs additional task context. This is neither an exact tokenizer count nor a session-wide cumulative ceiling. Only notifications actually emitted count as delivered for deduplication.

Changed, removed, unsafe or unreviewed sources cannot silently reuse old bodies. Source/reference changes produce a short review or invalidation notice; existing global instructions must be explicitly reread. Historical context cannot be retracted. A source version binds routing, resolved path, bytes, selected sections, direct dependencies and optional source/deployment identity.

## Failure and safety boundaries

Knowledge uses a separate subprocess with a one-second runtime deadline and bounded lock waits. Failures leave correction handling and write guards operational and emit a short diagnostic, deduplicated per session stage. Missing session identity or damaged state falls back to repeated safe output. State stores IDs, hashes and timestamps, never prompts or source bodies.

Only bounded regular UTF-8 Markdown is eligible. Safe POSIX descriptor traversal rejects symlink replacement races; native Windows knowledge loading fails closed, so use WSL. Candidate directories, core memory, correction files and approval ledgers, including their symlink aliases, are excluded. Sensitive-pattern or control-tag matches block the source. These checks are accidental-contamination defenses, not a guarantee against arbitrary malicious natural language or same-user code execution.

For deployment, prepare and test code, sources and routes; deploy exact files; verify copies; publish the accepted revision last. Keep a before/after hash record. Before rollback, verify each file still matches the task-written version; stop on later user edits. Do not install background workers or automatically approve candidate content.
