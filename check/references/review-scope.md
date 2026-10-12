# Dynamic review scope

Local adaptation for Alibaba OpenCodeReview v1.12.13. Scope follows the task and its affected behavior, with no fixed file-category whitelist. This reference handles inventory and selection; the official OCR engine remains the reviewer.

## 1. Establish the intended surface

For a changes review, inventory staged, unstaged and nonignored untracked files. For a PR/range or commit, use that exact Git snapshot. For an explicit whole-file/project audit, include unchanged tracked and nonignored untracked files under the requested roots. Expand to related callers, documentation, tests and contracts when evidence connects them to the task.

Do not exclude Markdown, tests, Skill instructions or new files by category. Inspect content only after deciding relevance and protection boundaries. Record concrete reasons for unrelated artifacts, generated/vendor material, binary, sensitive or inaccessible items. Never read a secret to satisfy a coverage count. Explicitly requested ignored files remain task items even though normal Git untracked enumeration omits them.

Use literal argv and NUL-delimited Git output. Add `--no-ext-diff --no-textconv` to Git diff commands and separate paths with `--`. Never interpolate paths, refs or business context into shell command text.

The optional deterministic helper keeps the original inventory separate from OCR:

```text
python3 <skill-root>/scripts/review_scope.py --repo <repo> --output <private-inventory.json>
python3 <skill-root>/scripts/review_scope.py --repo <repo> --mode range --from <base> --to <head> --output <private-inventory.json>
python3 <skill-root>/scripts/review_scope.py --repo <repo> --mode commit --commit <sha> --output <private-inventory.json>
python3 <skill-root>/scripts/review_scope.py --repo <repo> --mode scan --paths-file <json-array-of-exact-paths> --output <private-inventory.json>
```

`--path` can repeat; both path options select exact repository-relative file paths, not directory recursion. Enumerate files under an audit root first or inventory the whole tree and select task-relevant items. Run `--help` for the current interface. `--output` keeps large manifests out of the main context.

The helper fixes range/commit identities and preserves staged/unstaged/untracked layers, rename sides and same-path deletion/recreation. It does not choose relevance, hash file contents, enforce safe reads or prove execution coverage. Workspace/scan content can change without a different path/status inventory; record relevant diff/content identities and recheck them before accepting reusable evidence.

## 2. Prepare a per-run filter

OCR defaults omit many tests and Markdown. A temporary `--rule <json>` can admit this task's relevant text:

```json
{
  "include": ["README.md", "tests/test_orders.py", "docs/behavior.md"],
  "exclude": [],
  "rules": []
}
```

These names are an example, not a permanent scope. Build each run's include list from its actual task inventory.

Inspect the existing explicit rule, project `.opencodereview/rule.json` and global rule when present. Filtering uses the **first layer with any include/exclude entries**, in that order; a new temporary include replaces the lower layer's entire filter. Preserve the effective include/exclude intent when forming the temporary filter. Resolve an old exclusion conflicting with the current explicit task in favor of the task where safe, and record the decision. Keep other relevant exclusions; do not alter persistent configuration.

Leave temporary `rules: []` unless the task already has an explicit custom rule. This allows project/global/system rule text to resolve natively. Preserve an existing explicit rule's entries and resolve relative Markdown/text rule references against their original rule-file directory before relocating it. Project-rule references resolve against the repository root. Do not copy credentials or provider configuration into a rule file.

Rule text is first-match-wins by file. `merge_system_rule: true` adds the built-in system rule only; it does not merge lower project/global custom rules. Put concise task-wide local expectations in `--background` or the review engine's `--background-file` instead of adding a catch-all rule that shadows project rules.

**Include is not a whitelist.** Unmatched files can still pass the default filter. For a narrow diff review, exclude out-of-scope candidates as well, then verify the actual preview set. Staging selected files does not narrow workspace review. User exclusions run before include; a conflicting exclude still wins.

OCR patterns are case-insensitive globs and have special brace behavior. Do not claim exact selection from naïve escaping of glob characters, case collisions or unusual names. Check the actual preview set; record unrepresentable selections and use a focused alternative rather than silently broadening the audit.

## 3. Preview and reconcile

Use the same explicit repo, engine, immutable scope arguments, temporary rule and `--max-tokens` value for preview and execution. Preview does not resolve the model's configured token limit, so relying on defaults can change coverage at runtime. Reuse preview only when scope, content and filter identities still match.

```text
ocr review --repo <repo> --rule <temporary-rule.json> --preview --format json --audience agent --max-tokens <group-limit> --output <private-preview.json>
ocr scan --repo <repo> --path <requested-roots> --rule <temporary-rule.json> --preview --format json --audience agent --max-tokens <file-limit> --output <private-preview.json>
```

For range/commit, add the helper's fixed `ocr_args` to both review calls. To compare preview selection with the independent inventory, repeat the matching helper invocation with `--preview <private-preview.json>`. Selection is only planned dispatch, not completed review.

Account for every intended item:

- Selected: confirm it belongs to the task and the right snapshot.
- Excluded: inspect the reason, resolve an accidental exclusion or document its concrete effect.
- Missing from preview: investigate provider filtering, inaccessible content or scope mismatch.
- Deleted: inspect the actual deletion diff and affected references; OCR never dispatches the deleted file itself.
- Multiple workspace layers: inspect material index/worktree differences that OCR's combined HEAD-to-worktree view does not preserve.

Provider filtering can remove root `vendor`, `node_modules` and similar directories before selection. Root `.gitignore` matches can even remove tracked changes without an entry in preview. Include does not bypass those filters, binary/secret guards or file-size limits. OCR's counts are therefore not the original task inventory.

For a rename, retain old and new paths and verify changed references. Range semantics are `merge-base(from,to)..to`; commit review compares the first parent (or empty tree for a root commit). Supplementary reads must use the same target snapshot, not whatever happens to be checked out.

`scan --path` covers current full files, not a historical PR/commit. It uses comma-separated paths and trims whitespace; paths containing commas or leading/trailing spaces need an explicit alternative and coverage accounting. Do not automatically turn that limitation into a whole-repository scan.

## 4. Close coverage gaps

Let OCR perform the full review on its validated subset. Use targeted host reads only for unsupported task surfaces, affected dependencies, disputed findings and verification. This is a coverage supplement, not a second complete review pipeline.

Resolve missing or skipped task items before claiming complete coverage. A user-approved exclusion can be justified; an unresolved item remains a limit. If scope is large, organize coherent batches or adjust resources according to risk and budget. Preserve the complete inventory across batches and include every finding; do not silently drop docs, tests or untracked files to save tokens.
