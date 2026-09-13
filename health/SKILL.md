---
name: health
description: "以脱敏证据审计 AI Agent 指令、配置、Skills、Hooks、MCP、权限和验证器健康。明确要求审计或诊断 Codex／Claude／Pi 的配置异常、指令冲突或工具不生效时使用；不用于应用故障、PR 审查、通用代码质量或普通指令文件编辑。"
license: MIT
metadata:
  github_path: "skills/health"
  github_date: "09-06"
  github_hash: "2d1420da16d22794ba100183bbd4198fd9d0ba03"
  github_url: "https://github.com/tw93/waza"
  version: "4.0.0"
  update_policy: "frozen"
---

# Health

## Use when
Audit or diagnose an Agent instruction, configuration, Skill, Hook, MCP, permission or verifier problem with a concrete object and audit/failure intent.

## Not for
Application bugs, PR review, general code-quality scoring, or routine edits to AGENTS.md or config.toml. Bare filenames and “context” do not trigger an audit.

## Outcome and evidence
Produce a prioritized, evidence-backed report within the requested Agent scope.
Each finding names the affected layer, redacted evidence, impact and actionable next step. A clean report with explicit coverage limits is valid.

## Rules
1. Audits are report-only unless the user authorizes repairs. Keep existing task authorization; do not repeat approval requests.
2. Start with current-project static summary. Do not read historical sessions, unrelated global configuration or live MCP tools by default.
3. Explain scope before expanding to global configuration, deep inspection, live probes or inspector delegation. Perform them only when included in the user's request or subsequently authorized.
4. Redact credentials and private payloads at collection time. Report structural evidence rather than raw configuration, command bodies or historical transcript.
5. Distinguish configured, discoverable, invoked and verified behavior. A file, permission flag or empty verifier log does not prove a working tool or passed check.
6. Examine reachable instruction conflicts and supply-chain/permission boundaries using the specific evidence at issue. Do not turn an Agent audit into generic maintainability scoring.
7. Complete the authorized report or repair with proportional verification. State missing evidence without expanding privacy scope to look comprehensive.

## Astra compatibility
For instruction or Skill conflicts, conditionally read [references/astra-compatibility.md](references/astra-compatibility.md).
Check narrow routing, AGENTS.md conflicts, redundant approvals, excessive stopping or testing, obsolete model assumptions, output conflicts, unnecessary reference loading and arbitrary restrictions on useful parallel work.

## Collection
`scripts/collect-data.sh --root PATH` emits a bounded project-only JSON summary; it does not execute project commands.
Use `--include-global` only for an authorized global audit. History requires both `--include-history` and an explicit `--history-path`; collection reports metadata, not transcript text.
Deep analysis is a reasoning scope, not permission to read additional directories.
Live MCP probes use the host's specific supported tool only after scope is authorized; no default collector performs them.

## Conditional helpers
Read [references/checks.md](references/checks.md) to select instruction, document-reference, verifier-output or Skill security checks. Helpers must stay within the approved scope.
Do not invoke every helper for each audit.

## Completion
Findings and coverage reflect actual redacted evidence. Runtime or historical coverage that was not exercised remains explicitly unverified.
