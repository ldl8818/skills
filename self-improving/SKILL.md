---
name: self-improving
description: "管理 Claude Code 与 Codex 的审核制纠错记忆和按需知识。用户要求记住、审核、撤销或归位纠错，登记知识、复核知识版本、通过本系统读取或维护知识，检查记忆健康、安装迁移或关闭持久学习时使用；普通报错、一次性偏好、一般资料查询和未涉及本系统的项目规则编辑不触发。"
metadata:
  version: "3.1.3"
  zh_description: "跨 Claude Code 与 Codex 的审核制纠错与按需知识，支持版本复核、安装、迁移与体检"
  compatibility: "Python 3.11+; macOS, Linux, or Windows WSL; Claude Code and/or Codex"
  source: local
---
# Doraemon 跨 Agent 自我进化记忆系统
Use this skill to operate a private memory repository shared by Claude Code and Codex while keeping public program code separate from user data.

## Core rules
- Standalone, statically recognized read-only Python inspection is permitted, including string prefix checks and negative indexing. Unknown code or complex shell composition may still be guarded. A denial alone does not prove a write or candidate approval was attempted. See `docs/hooks.md`.
- Read configuration from `SELF_IMPROVING_CONFIG` or `~/.config/self-improving/config.json`.
- Treat the configured `memory_root` as private user data. Never copy it into the public Skill repository.
- Capture corrections and errors only when persistence is enabled. Messages starting with client-injected system tags (including slash-command echoes), prompts longer than 1500 characters, and keywords appearing only inside fenced code blocks are never corrections.
- Store captured content as untrusted candidates; promotion requires human review.
- Inject only current v2 approvals recorded by `review approve`, within the configured repo/project/global scope, lifecycle and total token budget. Never inject raw candidates, errors or legacy v1 rows.
- Keep `memory.md` out of startup context unless `include_core_memory` is explicitly enabled. Without a knowledge catalog, skip unchanged dynamic context on resumed sessions by default; when the eligible set changes, invalidate the prior injection and emit the full replacement or a clear signal.
- Preserve existing third-party Hooks when installing or upgrading.
- Current files and verified output override remembered facts.
- The legacy `corrections.md` is optional audit history. An existing marked memory root may archive it; initialization will not recreate it, and doctor does not require it. Candidates and v2 approvals keep their existing stores.
- Authorized edits and moves of memory.md and corrections.md follow ordinary document permissions, without extra Hook approval. The verified ledger and mutating review commands remain protected. Treat Hook write guards as accidental-write protection, not an operating-system authorization boundary against arbitrary same-user code execution. Claude Code returns `ask` for a protected write; Codex returns `deny`, so Codex review commands must be copied to and run in a regular terminal.
- With an authorized knowledge catalog, resume resets knowledge deduplication and supplies the base context once. Use `knowledge list/read` for relevant missed or full-required sources; never treat an output receipt as completed reading.

## Commands
For the documented source-checkout installation, run commands from the Skill's `src/` directory containing `self_improving/`; `init` does not install the package into site-packages. Documents, templates and Skill links remain at the Skill root above `src/`. When upgrading a checkout from the old flat layout, enter `src/` and run `python3 -m self_improving upgrade` to refresh managed Hooks. When triggered inside another project, locate the checkout via the `self-improving-hook` command inside `~/.claude/settings.json` or `~/.codex/hooks.json`; old commands may still point one level above `src/`. An independently installed package can also expose the `self-improving` CLI in its Python environment.

```bash
python3 -m self_improving init
python3 -m self_improving doctor
python3 -m self_improving status
python3 -m self_improving sync
python3 -m self_improving sync --check
python3 -m self_improving knowledge list
python3 -m self_improving knowledge read ID
python3 -m self_improving knowledge check --json
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
10. For knowledge registration or maintenance, follow `docs/knowledge.md`: inspect the catalog and original sources, review changes and direct dependencies within authorization, then accept the exact checked revision. Knowledge acceptance does not approve corrections or authorize policy changes. Use `knowledge list/read` for missed sources and `--full` for full-read obligations.

## References
- Knowledge registration, maintenance, budgets and recovery: `docs/knowledge.md`
- Install, upgrade, uninstall, and full review command examples: `README.md`
- User is new and reads Chinese — zero-to-one tutorial: `docs/quickstart-zh.md`
- Something fails (module not found, Hook not firing, approval not injected): `docs/troubleshooting-zh.md`
- Tuning capture switches or injection budgets: `docs/configuration.md`
- Migrating an old installation, moving machines, rollback: `docs/migration.md`
- What is captured, what is never injected: `docs/privacy.md`
- Per-platform Hook events, guard behavior and limits: `docs/hooks.md`
- Design rationale (Chinese): `docs/architecture-zh.md`
