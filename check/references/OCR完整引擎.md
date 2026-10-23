# Optional full OCR engine

<!-- SPDX-License-Identifier: Apache-2.0 -->

Alibaba OpenCodeReview v1.12.13, commit `fabbdb296b0d97e2140ada8d54ca7d6d6d1d7ad4`. This reference is only for an explicit full-engine request or authorized setup; normal Check reviews use host review with optional Delegate assistance. Source and license details: [NOTICE.md](../NOTICE.md).

## Full-engine commands (explicit opt-in)

Use this path only when the task explicitly selects full OCR and an authorized supported provider is available. An existing provider alone does not override Check's host-review routing. Missing API access leaves only an explicitly required full-engine gate pending; it does not block ordinary host or Delegate review.

Prepare inventory and full-engine preview using [review-scope.md](review-scope.md). Run the validated scope:

```text
ocr review --repo <repo> --audience agent --format json --output <private-result.json> --background <concise-context> --rule <temporary-rule.json> --max-tokens <group-limit> --max-tokens-budget <run-budget> --concurrency <workers> --max-git-procs <git-workers> --effort <low|medium|high>
ocr scan --repo <repo> --path <requested-roots> --audience agent --format json --output <private-result.json> --background <concise-context> --rule <temporary-rule.json> --max-tokens <file-limit> --max-tokens-budget <run-budget> --concurrency <workers> --max-git-procs <git-workers>
```

Use the same fixed `--from/--to` or `--commit` arguments as preview for a historical review. Omit those flags for workspace. Create unique, access-restricted task directories for manifests, background and results outside committed/public artifacts. Keep filenames and context as data.

Review supports `--background-file <markdown>`, which takes precedence over `--background`. Scan uses `--background`. Supply only concise intent, known constraints and relevant verification facts; do not paste transcripts or duplicate source files into background.

The engine provides native grouping/planning, contextual file/search tools, review rounds, finding positioning and filtering; scan adds its full-file planning, deduplication and summary phases. Preserve these capabilities unless a concrete task tradeoff justifies changing them. OCR's built-in review tools do not execute tests or apply repairs; the host completes authorized fixes and verification.

## Full-engine resource and context controls

There is no universal scope size or token quota. Select a budget from the requested coverage, preview, model capacity, risk and available resources. Separate these controls:

| Control | Actual meaning in v1.12.13 |
|---|---|
| `--max-tokens` | Per-review-group or scan-file prompt ceiling; a large input can be excluded before inference |
| `--max-tokens-budget` | Soft total input + output threshold across model phases; zero is unlimited |
| `--concurrency` | Parallel review workers; default eight can multiply in-flight context and cost |
| `--max-git-procs` | Native Git subprocess concurrency, independent of model workers |
| `--effort` | Review depth: low/medium/high uses one/two/three main rounds |
| `--timeout` | Engine timeout control, not a substitute for observing the actual job and its phase/round behavior |

For unknown local capacity, start with modest concurrency, such as two workers, then adapt to measured memory, rate limits and urgency. Keep each prompt ceiling within the configured model's input allowance with room for output and tool results. Do not lower it below relevant diffs and then treat skipped files as reviewed.

The soft aggregate threshold is checked at dispatch/round boundaries; in-flight calls, some auxiliary phases and final submission work can exceed it. A hard cost ceiling cannot be promised from this flag. If a strict budget cannot cover the task, surface that tradeoff before expanding paid execution.

Scan batching does not impose a total RAM cap: its provider may read eligible content before later filtering. Prefer requested paths and coherent batches for a large audit. Do not automatically scan the whole tree after a failed diff review. `--max-tools` cannot lower the template's tool-round ceiling in this version.

Use file output for the complete result. Read a compact execution summary first, then all relevant comments in bounded batches. Do not pipe raw output through `head`/`tail`, load optional `thinking` or entire session transcripts, or repeat the full review in the host context. Keep a coverage ledger across batches.

## Validate the full-engine result

Check the process outcome and parse the JSON, then inspect:

- `status`, `warnings` and `summary.budget_exceeded`.
- `summary` token usage, elapsed time and comment counts.
- Every `comments` item, validating source positions and material impact.
- Review group/file outcomes, `manifest`, `retry_report` and resume information when present.

An exit code of zero can still accompany partial work. `files_reviewed` may describe selected files rather than successfully completed reviews. Compare execution evidence with the independent inventory and preview; failed, skipped or budget-limited groups leave coverage unresolved.

Scan does not supply the same review RunManifest in this version. Use scan output, warnings and available per-file outcomes; do not require a nonexistent review manifest, and do not infer complete success from its selected-file count alone. If completion cannot be established, report the limit.

Resume interrupted range/commit review only with the same exact target and `--resume <id>`; workspace resume is unsupported. Scan supports its own resume. Reconcile the existing job/session before rerunning; retry only failed work whose inputs still match.

## Provider and failure handling (full engine only)

Full `review`/`scan` needs an OCR-supported LLM endpoint. Existing configured provider access can be reused under the task's authorization. OCR resolves its configuration, OCR environment, compatible Claude Code environment and supported shell exports; signing in to Codex alone is not an endpoint configuration.

Inspect only provider/model metadata and credential presence when needed. Do not print secrets, copy host login tokens, invent keys, select a new paid provider without authorization or commit machine configuration. A missing provider is an explicit setup dependency, not a reason to claim the full engine ran.

- Missing executable or incompatible flags: report the observed limitation; ordinary review does not auto-install or auto-upgrade.
- Invalid rule/output: correct the input or establish the changed schema before accepting evidence.
- Authentication, network, rate-limit or model errors: identify the actual failure, preserve partial output and resolve that cause before retrying.
- Missing endpoint: report `full OCR not run` for the explicit full-engine request and continue useful authorized host checks. Do not request or provision an API for host or Delegate review. Provider setup is a separate authorized task.

For explicitly authorized setup, use `ocr config provider` with the chosen supported provider, then `ocr llm test` and a small real review. Native provider setup is interactive; keep credentials in the approved local credential/configuration path. Neither preview nor a mock endpoint proves real model access or review quality.

## Installation and deliberate updates

The frozen Skill installer only links local Skill directories; it does not install OCR or configure a model. Reuse an existing native installation. When setup is authorized and no compatible binary exists, choose the official asset for the detected OS/architecture, pin the release and verify its published SHA-256 before execution. Preserve conflicting installations.

Reference macOS arm64 asset:
- [opencodereview-darwin-arm64](https://github.com/alibaba/open-code-review/releases/download/v1.12.13/opencodereview-darwin-arm64)
- SHA-256: `d973dd5926f1ac5e22e91e56780873a86a8d79cae504ae488ee03e6f7a1e80ee`
- [Published checksums](https://github.com/alibaba/open-code-review/releases/download/v1.12.13/sha256sum.txt)

Keep the binary outside the skills repository, for example under `~/.local/share/open-code-review/v1.12.13/ocr`, with a non-conflicting `~/.local/bin/ocr` link. No automatic npm wrapper, sudo, service or provider change is part of ordinary review.

Future updates are deliberate: compare upstream changes, preserve local scope/authorization/verification contracts, validate flags and output on a disposable Git fixture, and verify provider execution separately. Update the source baseline only when adopting that baseline, and keep `update_policy: frozen`.
