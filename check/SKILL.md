---
name: check
description: "审查代码、PR、文档、测试及项目质量，按风险检查并验证修复；复杂审查按需使用 Alibaba OCR。具体故障排查用 hunt。"
license: MIT AND Apache-2.0
metadata:
  version: "6.0.0"
  author: Tw93
  homepage: https://github.com/tw93/Waza
  github_path: "skills/check"
  github_date: "09-06"
  github_hash: "2d1420da16d22794ba100183bbd4198fd9d0ba03"
  github_url: "https://github.com/tw93/Waza"
  update_policy: "frozen"
---

# Check

Locally maintained from Waza's Check, with risk-based routing and optional Alibaba OpenCodeReview (OCR) assistance. Check owns scope, business judgment and repair verification; OCR supplies review tools. Source history and file-level licenses: [NOTICE.md](NOTICE.md).

## Establish the review

Review the requested changes, PR or project behavior against intended outcomes. Use `hunt` for an observed runtime failure; a generic “看看”“优化”“继续” alone does not establish a review task.

Read applicable project requirements and inspect staged, unstaged and untracked state. Preserve other work. Fix historical targets to exact revisions; inspect that snapshot rather than unrelated checkout contents. Scope follows the task and affected behavior, including relevant documents, tests, configuration, untracked text, deletion impact and unchanged callers. Exclude unrelated, generated or sensitive material with a concrete reason.

## Choose the depth

- **Lightweight:** impact is local, expected behavior is clear, and a focused check can establish correctness. Read the relevant diff and direct context, repair authorized defects and verify the affected behavior. No OCR call, generated inventory, separate review ledger or broad rule loading is required.
- **Deep:** money, permissions, destructive operations, shared contracts, state transitions, concurrency, cross-module effects, broad audits or material uncertainty require connected reasoning. Follow [深入审查.md](references/深入审查.md); use OCR Delegate for applicable rule assistance and retain host review of the complete task scope.
- Escalate when inspection reveals those risks; reuse work already done. File count, diff length and extension do not determine risk. A one-line permission change or a Markdown authorization rule can require deep review.

## Judgment and repair

Ground findings in intended behavior, reachable code and concrete impact. Read change intent before calling a deliberate change a regression. Check static callers, dynamic registration, packaging and installed entrypoints before declaring code dead. Report simplification only when required behavior is preserved; a supported clean review is valid.

Follow the user's request and standing repair authorization. Explicit read-only takes precedence. Fix confirmed in-scope defects when authorized, establish the expected result independently of the implementation, and verify the original failure plus affected normal paths. Do not invent requirements or modify tests merely to accept broken behavior. Clarify material ambiguity while continuing independent checks.

When review is part of authorized delivery, “if clean” is a quality gate to satisfy: repair, verify and continue. Ask again only for a genuine scope or authorization gap. Review alone does not authorize external writes.

## Verification and completion

Use relevant readback/static checks for prose and narrow edits, targeted tests for logic, and affected integration or installed-artifact checks for higher-risk changes. Read actual CI and runtime before trusting a documented gate. Required project checks still apply; `scripts/run-tests.sh` only discovers candidates.

After repair, recheck affected behavior and invalidated evidence. Do not repeat unchanged reviews or full suites without a new failure, change or concrete uncertainty. Keep task requirements and unresolved coverage visible across batches; do not silently omit work to meet a budget.

Report confirmed findings with location, impact and repair/verification status, or a supported clean result. Name the actual scope, exclusions and remaining limits; use “not verified” where evidence is absent. Separate source, runtime, installed behavior, CI and publication. For authorized external actions, read back actual state and reconcile uncertain outcomes before retrying.

## Conditional tools and references

Load only the reference relevant to the chosen depth or affected surface:
- Deep business review and context budget: [深入审查.md](references/深入审查.md).
- OCR Delegate commands, when used: [open-code-review.md](references/open-code-review.md). Uses the current host session; no separate model API. Unavailable OCR does not block useful host review.
- Explicit full-engine OCR request: [OCR完整引擎.md](references/OCR完整引擎.md). Requires an authorized provider; do not substitute Delegate for an explicitly required full-engine gate.
- Security, CI, tests, deletion, async or architecture: [review-patterns.md](references/review-patterns.md).
- Packaging, installation or release readiness: [release-surfaces.md](references/release-surfaces.md).
- Explicit public maintainer actions: [public-reply.md](references/public-reply.md).
