---
name: self-improving
description: "管理 Claude Code 与 Codex 的审核制跨 Agent 纠错记忆。仅在用户明确要求记住、审核或撤销纠错，检查记忆健康，安装迁移该系统，或为敏感任务关闭持久学习时使用；普通报错、一次性偏好和项目规则编辑不触发。"
metadata:
  version: "3.0.0"
  zh_description: "跨 Claude Code 与 Codex 的审核制纠错记忆，支持安装、迁移与体检"
  compatibility: "Python 3.11+; macOS, Linux, or Windows WSL; Claude Code and/or Codex"
  source: local
---
# Self-improving cross-agent memory
Use this skill to operate a private memory repository shared by Claude Code and Codex while keeping public program code separate from user data.

## Core rules
- Standalone, statically recognized read-only Python inspection is permitted; unknown Python or shell composition may still be guarded. A denial alone does not mean a candidate approval was attempted. See `docs/hooks.md`.
- Read configuration from `SELF_IMPROVING_CONFIG` or `~/.config/self-improving/config.json`.
- Treat the configured `memory_root` as private user data. Never copy it into the public Skill repository.
- Capture corrections and errors only when persistence is enabled. Messages starting with client-injected system tags (including slash-command echoes), prompts longer than 1500 characters, and keywords appearing only inside fenced code blocks are never corrections.
- Store captured content as untrusted candidates; promotion requires human review.
- Inject only current v2 approvals recorded by `review approve`, within the configured repo/project/global scope, lifecycle and total token budget. Never inject raw candidates, errors or legacy v1 rows.
- Keep `memory.md` out of startup context unless `include_core_memory` is explicitly enabled. Skip unchanged dynamic context on resumed sessions by default; when the eligible set changes, invalidate the prior injection and emit the full replacement or a clear signal.
- Preserve existing third-party Hooks when installing or upgrading.
- Current files and verified output override remembered facts.
- Treat Hook write guards as accidental-write protection, not an operating-system authorization boundary against arbitrary same-user code execution. Claude Code returns `ask` for a protected write; Codex returns `deny`, so Codex review commands must be copied to and run in a regular terminal.

## Commands
The package is not installed into site-packages: run every command from the skill install directory (the directory containing `self_improving/`), otherwise `python3 -m self_improving` fails with `ModuleNotFoundError`. When triggered inside another project, find that directory in the `self-improving-hook` command inside `~/.claude/settings.json` or `~/.codex/hooks.json`, then `cd` there first.

```bash
python3 -m self_improving init
python3 -m self_improving doctor
python3 -m self_improving status
python3 -m self_improving sync
python3 -m self_improving sync --check
python3 -m self_improving review list
python3 -m self_improving review list --json
# Manual terminal approval: rule text and scope are entered at prompts.
python3 -m self_improving review approve-interactive --fingerprint '[fp:...]'
# Claude Code or trusted programmatic callers only.
python3 -m self_improving review approve --fingerprint '[fp:...]' --correct '...' --scope global --promotion-target global-rules
python3 -m self_improving review reject --fingerprint '[fp:...]'
python3 -m self_improving review revoke --fingerprint '[fp:...]'
python3 -m self_improving review lifecycle-list
python3 -m self_improving review promote --fingerprint '[fp:...]'
python3 -m self_improving review legacy-list
python3 -m self_improving review import-legacy-interactive --legacy-id 'legacy:...'
# Claude Code or trusted programmatic callers only.
python3 -m self_improving review import-legacy --legacy-id 'legacy:...' --correct '...' --scope global --promotion-target global-rules
python3 -m self_improving persistence disable
python3 -m self_improving migrate legacy
```

## Workflow
1. For a new installation, run `init`, choose Claude/Codex and a private memory directory, then run `doctor`.
2. For an older local installation, run `migrate legacy` first without `--apply`; review the preview, then apply it.
3. When a user explicitly corrects an Agent, let the Hook store the prompt as an untrusted candidate. Fix the current task before reviewing memory.
4. Review candidates with `review list`, then approve or reject by fingerprint. Approval must name a `global`, `repo:/absolute/repository`, or `project:/absolute/path` scope plus the formal promotion target. Each v2 approval receives review and expiry dates; it is a temporary bridge until promoted into that target.
5. Pre-review when the user asks or the throttled `Stop` reminder fires. Read `review list --json`, use `matched` to detect incidental triggers, and draft one rule, decision, scope and promotion target per candidate. Only after explicit user consent may Claude run the approved commands. Codex must present one fingerprint-only interactive command at a time for a regular terminal; never put candidate-derived text in Shell syntax.
6. Use `review lifecycle-list` to inspect active, due and expired v2 rules. After the named formal target is actually updated and verified, run `review promote --fingerprint ...`; promotion is an append-only event that stops future injection without deleting audit history. Use `review revoke` when the rule is wrong or should be withdrawn without formal promotion.
7. For a legacy Markdown row or v1 JSONL approval, do not activate it directly. Run `review legacy-list`, distill the selected stable `legacy:...` record into a current rule, then use `review import-legacy --legacy-id ... --correct ... --scope ... --promotion-target ...` in Claude Code or trusted programmatic calls. In Codex, give the user `review import-legacy-interactive --legacy-id ...` and show the rule, scope, promotion target and lifecycle separately for the terminal prompts. A migrated v1 approval is revoked after its v2 replacement is appended, so it disappears from later legacy lists.
8. Before processing untrusted PDFs, scraped content, email, or other sensitive material, disable persistence for that session.
9. After upgrades or Hook changes, run `doctor` and a real new-session plus resume smoke test for each enabled Agent.

## References
- Install, upgrade, uninstall, and full review command examples: `README.md`
- User is new and reads Chinese — zero-to-one tutorial: `docs/quickstart-zh.md`
- Something fails (module not found, Hook not firing, approval not injected): `docs/troubleshooting-zh.md`
- Tuning capture switches or injection budgets: `docs/configuration.md`
- Migrating an old installation, moving machines, rollback: `docs/migration.md`
- What is captured, what is never injected: `docs/privacy.md`
- Per-platform Hook events, guard behavior and limits: `docs/hooks.md`
- Design rationale (Chinese): `docs/architecture-zh.md`
