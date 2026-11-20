---
name: check
description: "Risk-tiered code and diff review with high-signal blind-spot checks and optional Alibaba OpenCodeReview (OCR) Delegate assistance. Use when asked to review diffs, PRs, or audit code quality. Not for commit/push workflows or prose editing."
when_to_use: "review, 看看代码, 合并前看看这段代码, 检查这个 PR 有没有漏测, 审查这次改动的风险, 检查一下, 合并前, 看看PR, code review, code-review, audit, 项目体检, 项目评分, scorecard"
dispatch_intent: "Risk-tiered code review, high-risk blind spots (sibling bugs, hollow green, artifact sync, safety sinks), optional Alibaba OCR Delegate deep review, codebase audit"
license: MIT AND Apache-2.0
metadata:
  version: "7.0.0"
  source: local
  zh_description: "风险分级代码与 diff 审查，聚焦高风险盲区与按需 Alibaba OCR 深度审查；不含发布推送流。"
---

# Check: High-Signal Code Review

Read the diff, inspect upstream callers and downstream consumers, and surface real defects. Follow the active user and project authorization rules: explicit read-only remains read-only; authorized necessary fixes apply cleanly and invalidate any prior verdict until re-verified. Commit, push, and release execution stay with the dedicated delivery workflow, not this skill.

## 1. Freeze Scope & Classify Depth

Read `git status --short --branch -uall` before reviewing. Treat modified, staged, and untracked files as user work -- never run `git switch`, `git checkout`, `git reset --hard`, `git clean`, or `git stash` to set up a review. For PRs, use read-only views (`gh pr view`, `gh pr diff`, `git fetch origin pull/<n>/head:refs/tmp/pr-<n>`).

Classify review depth by behavioral risk, not file count:

| Depth | When to use | Execution |
|---|---|---|
| **Quick** | Local impact, clear expected behavior, static/copy/config diff | Direct diff read + targeted check; no OCR or ledger needed |
| **Standard** | Multi-file behavior change, shared logic, or material uncertainty | Diff + caller/consumer trace + blind-spot checks |
| **Deep** | Money, permissions, destructive state, concurrency, shared contracts, or explicit full audit | Load [references/深入审查.md](references/深入审查.md) and optional Alibaba OCR via [references/open-code-review.md](references/open-code-review.md) |

For repository-wide audits ("audit", "项目体检", "scorecard"), load [references/mode-audit.md](references/mode-audit.md). For multi-layer inventories, use [references/review-scope.md](references/review-scope.md).

## 2. High-Signal Blind-Spot Checks

Focus on defect classes that even strong reviewers routinely miss:

- **Scope drift & over-design**: Flag unrelated edits, unnecessary config knobs, or removable abstractions/fallbacks that are not justified by a real failure mode.
- **Sibling sweep (pattern-fix completeness)**: When the diff fixes one instance of a bug shape, grep the repository for the same pattern and confirm whether sibling sites were fixed or safe.
- **Hollow green verifiers**: A passing check is invalid if assertions were skipped, an optional dependency bypassed the real path, or an early return left output empty so a true-on-empty check passed.
- **Source vs. distribution / dependency sync**: Verify generated artifacts, lockfiles, manifests, version fields, and bundled scripts/references stay synchronized with source changes. Flag unexpected dependency additions or unimported SDKs.
- **Safety sinks & injection**: Explicitly check command/SQL/path injection, symlink/cwd traversal, credential exposure, non-atomic overwrites of user files, and mutating CLI commands (`cleanup`, `update`, `uninstall`, `migrate`).
- **Route verdict on recurring root causes**: When findings cluster on one architectural defect or repeated patch chain, state the route verdict (`keep` / `adjust` / `replace`) before listing site-by-site patches.

When the diff touches recurring bug catalogs or packaged/CLI install surfaces, load [references/review-patterns.md](references/review-patterns.md) or [references/release-surfaces.md](references/release-surfaces.md) on demand.

## 3. Finding Quality Gate

- Every finding must cite exact `file:line`, the triggering input or state, and real caller/consumer impact.
- **HIGH / CRITICAL** findings must explain why existing guards (types, validation, upstream catch, framework defaults) do not already block them; otherwise downgrade or drop.
- **A clean review is a valid outcome**: report `no issues found` with the covered scope rather than manufacturing low-confidence noise.
- Label pre-existing issues explicitly as `pre-existing`.

## 4. Verification & Alibaba OCR

- Prefer the project's documented verification command. To discover candidate test commands without executing package tools, run `bash <skill-base-dir>/scripts/run-tests.sh` (pass `--execute` only when explicitly authorized and suitable).
- Never claim a test passed or a fix is verified without current-session command output (or explicitly marked reused equivalent evidence). In a dirty checkout with unrelated WIP, verify in a detached worktree if WIP could mask or break the result.
- **Alibaba OCR integration**: Use [references/open-code-review.md](references/open-code-review.md) for optional Delegate assistance (`ocr delegate preview` / `rule`) -- it uses the active host session without an external API key. The host owns the entire requested scope (including Markdown, tests, untracked files, and deletion impact); OCR exclusions never shrink scope. Explicit full-engine requests follow [references/OCR完整引擎.md](references/OCR完整引擎.md). Licensing and dual-source history stay in [NOTICE.md](NOTICE.md).

## 5. Output

Lead with the verdict and highest-severity findings grouped by bug class (each with `file:line`, impact, and minimal fix), followed by sibling sweep, verification commands/results, and any unreviewed scope or doc debt. Keep it concise; omit inapplicable boilerplate.
