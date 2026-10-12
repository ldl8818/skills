---
name: check
description: "用 Alibaba OpenCodeReview 审查代码、PR、文档、测试及项目质量；按任务动态包含未跟踪文件。具体故障排查用 hunt。"
license: Apache-2.0
compatibility: >
  Requires the separately installed native ocr CLI and a configured supported
  LLM provider for full review (Anthropic, OpenAI Chat Completions,
  OpenAI Responses, or AWS Bedrock). Scope inventory uses Python 3.9+ and Git.
metadata:
  version: "5.0.0"
  author: alibaba
  homepage: https://github.com/alibaba/open-code-review
  github_path: "skills/open-code-review"
  github_date: "10-08"
  github_hash: "fabbdb296b0d97e2140ada8d54ca7d6d6d1d7ad4"
  github_url: "https://github.com/alibaba/open-code-review"
  update_policy: "frozen"
---

# Open Code Review

A skill for invoking [open-code-review](https://github.com/alibaba/open-code-review) (`ocr`) — an open-source AI code review CLI that reads Git diffs and generates structured, line-level review comments.

Locally modified from Alibaba's official Skill at v1.12.13, retaining its English workflow and the local `check` entry. This Skill was previously adapted from Waza; retained material and local changes are credited in [NOTICE.md](NOTICE.md).

## Workflow

### Step 1: Gather Business Context

Analyze the review target (commits, branch, or changes) to extract concise business context. Pass this context via `--background` to improve review quality.

Determine scope from the requested outcome, actual changes and affected dependencies. Code, Markdown/Skill instructions, companion documentation, tests, configuration and untracked text are normal candidates; use no fixed extension whitelist. Add unchanged callers, contracts or tests when their relationship to a change warrants it. Use `hunt` for a concrete runtime failure; a generic “看看”“优化”“继续” alone does not establish a review task.

Inspect staged, unstaged and untracked state before reviewing or writing. Preserve other work; do not stash or reset it to simplify verification. Record exact revisions and relevant content identities. Follow [review-scope.md](references/review-scope.md) to prepare the independent inventory and temporary OCR filter. The inventory helper reads Git metadata, not file bodies; task relevance and safe content selection remain the agent's responsibility.

### Step 2: Run Code Review

Use the full OCR engine as the primary reviewer. Reuse a resolved, compatible native executable; avoid repeating installation probes for unchanged setup. Do not run a second complete host review or a delegate pipeline by default.

Always supply concise business context when available, including intended behavior and the few relevant local constraints. Read the Commands, Resource and context controls, and Validate the actual result sections of [open-code-review.md](references/open-code-review.md) as needed for the pinned v1.12.13 CLI. Load provider/setup sections only for dependency failures or an authorized setup task; reuse unchanged reference context.

| Review target | Engine and scope |
|---|---|
| Current changes | `ocr review` in workspace mode |
| PR or branch comparison | `ocr review --from <fixed-base> --to <fixed-head>` |
| A commit | `ocr review --commit <fixed-sha>` |
| Explicit whole-file or repository audit | `ocr scan --path <requested-files-or-directories>` on the current tree |

For each new scope/content/filter combination, run `--preview --format json` without an LLM. Reconcile every task item against the preview before the full run. Include relevant documents and tests through the temporary rule; review deleted content and other unsupported surfaces with focused host inspection. A preview or empty OCR subset is not a clean review.

Run the same engine, scope, rule and per-group/file token limit with `--audience agent --format json --output <private-result.json>`, removing `--preview`. Workspace OCR combines tracked changes relative to HEAD and adds untracked files; inspect staged/worktree differences separately where that combined view loses relevant behavior.

Choose concurrency, effort and token allowances from the actual scope, model context, available resources, risk and user budget. Keep native planning, review rounds and post-filtering available; adjust when evidence warrants it. `--max-tokens-budget` is a soft run threshold, not a hard billing cap. Never shrink coverage silently to meet it.

If the CLI/provider is unavailable, record **full OCR not run** and continue useful authorized host checks under that explicit label. Keep OCR acceptance pending; do not silently relabel delegate or host review as full OCR. Setup requires an available authorized provider, not merely a signed-in host client. Do not install, upgrade or change credentials during ordinary review without applicable setup authorization.

### Step 3: Report

OCR comments contain `path`, `start_line`, `end_line`, `content`, `severity`, `category` and optional `suggestion_code`/`existing_code`. Validate findings against the exact source and reachable behavior; present confirmed issues grouped by severity with location, impact and a practical repair direction. Discard unsupported findings and stylistic nitpicks. Both line numbers being zero means positioning failed: locate the issue before reporting or fixing it.

Read result status, warnings, budget state, group/file outcomes and all findings in bounded batches. Omit optional `thinking`, session transcripts and duplicate raw reports from the main context. Exit zero or `files_reviewed` alone does not establish complete execution. Explain partial, failed, skipped or unresolved coverage against the original inventory.

A supported clean review is valid. Before calling a deliberate change a regression, read its commit intent. Before declaring code dead, check callers, dynamic registration, packaging and installed entrypoints. Recommend simplification only when the simpler path preserves required behavior.

Report the target, OCR execution state, reviewed coverage, justified exclusions, unresolved items and confirmed findings. State “no confirmed issues in the reviewed scope” only with its actual coverage limits; never convert missing evidence into a clean verdict.

### Step 4: Fix

Apply the user's request and applicable standing repair authorization from project instructions. An explicit read-only request takes precedence. A standalone review is report-only when repairs are not authorized; do not ask again for necessary fixes already authorized.

When review is part of implementation or delivery, including “review, then commit/push if clean,” fix confirmed in-scope defects, verify them and continue the authorized delivery. “If clean” is a quality gate to satisfy. Ask only when a repair expands scope or requires a new authorization.

Choose verification by affected risk: documentation needs relevant readback and static checks; module logic needs targeted tests; public APIs, permissions, migrations or release paths may need affected integration or artifact checks. Read actual CI and declared runtime before relying on a documented gate. `scripts/run-tests.sh` only prints candidates; confirm them before execution. Stop once required checks pass unless a new change, failure or unresolved risk warrants more.

Verify the repairs, then complete already authorized commit/push or delivery. Do not use fallback checks to satisfy an explicitly required full-OCR or complete-review gate; keep that dependent delivery pending while continuing independent authorized work. For external mutations, prepare the concrete change, use the authorized target and read back actual state; reconcile an uncertain result before retrying. Separate source checks, runtime tests, installed behavior, CI and release acceptance. Reused evidence must identify its commit and inputs and what was rechecked.

## Conditional References

Load only what the affected surface needs:

- Security, CI, verification logic, asynchronous state, deletion or architecture: [review-patterns.md](references/review-patterns.md).
- Packaging, installed CLI or release changes: [release-surfaces.md](references/release-surfaces.md).
- Explicit public maintainer actions: [public-reply.md](references/public-reply.md).
