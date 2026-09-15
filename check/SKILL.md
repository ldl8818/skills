---
name: check
description: "审查代码、PR、项目质量或发布就绪状态；不用于具体故障修复。"
license: MIT
metadata:
  version: "4.0.1"
  github_path: "skills/check"
  github_date: "09-06"
  github_hash: "2d1420da16d22794ba100183bbd4198fd9d0ba03"
  github_url: "https://github.com/tw93/waza"
  update_policy: "frozen"
---

# Check

## Use when
Review a diff or PR, audit repository code quality, triage an issue, or verify an explicitly requested merge or release outcome.

## Not for
Concrete runtime failures, prose editing, or implementing a plan. A generic “看看”“优化”“继续” is not a review request by itself.

## Outcome and evidence
Cover the requested surface with current findings or a supported clean review.
Findings name the location, observed defect, impact, and a practical repair direction.
Separate source, generated files, installed packages, CI, registry and release state.

## Rules
1. A review request is report-only. Apply repairs or external actions only within authorization already valid for the task; do not ask again for an authorized action.
2. Inspect staged, unstaged and untracked state before reviewing or writing. Preserve other work; do not stash or reset it to simplify verification.
3. Ground defects in current code and reachable behavior. Trace dynamic registration, packaging and callers before claiming something is dead. A clean review is valid.
4. Choose verification by affected risk. Stop once required checks pass unless a new change, failure or unresolved risk justifies expansion.
5. Complete the requested authorized outcome. For external mutations, prepare the concrete change, use the authorized target, and read back actual state; a tool return alone is insufficient.
6. Report missing evidence as a limit, without substituting source checks for runtime or release acceptance.

## Verification budget
- Documentation, comments and narrow low-risk changes: relevant readback, links and static checks.
- Module logic: targeted tests and required build checks.
- Public APIs, permissions, money, migrations or release pipelines: affected integration, regression and artifact checks.
- Project-required checks still apply. Do not choose reviewer count from diff size or repeat equivalent checks.

## Conditional references
Load only the mode needed by the request:
- Repository audit: [references/mode-audit.md](references/mode-audit.md).
- Issue or PR triage: [references/mode-triage.md](references/mode-triage.md).
- Shipping or release readiness: [references/mode-ship.md](references/mode-ship.md).
- Public maintainer actions: [references/public-reply.md](references/public-reply.md).
- Packaging or installed CLI changes: [references/release-surfaces.md](references/release-surfaces.md).
- Security, asynchronous state, destructive operations or architectural changes: [references/review-patterns.md](references/review-patterns.md).

## Helpers
`scripts/run-tests.sh` only prints candidate verification commands. Confirm them against project instructions, manifests, lockfiles and CI before execution.
`scripts/release_gate.py --help` and `scripts/audit_signals.py --help` describe optional deterministic evidence helpers; their output is evidence, not a review verdict.
