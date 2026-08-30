# Self-improving cross-agent memory

A configurable, review-gated memory system for Claude Code and Codex. It captures explicit corrections, waits for human approval, and automatically supplies approved answers to both Agents in later sessions. Program code can be public; user memory remains in a separate private directory.

中文用户请从 [五分钟从零开始](docs/quickstart-zh.md) 阅读。遇到问题看 [中文排错手册](docs/troubleshooting-zh.md)。想了解系统怎么设计、为什么这样设计，看 [Doraemon 跨 Agent 自我进化记忆系统架构与设计](docs/architecture-zh.md)。

## 它怎样变聪明

```text
你明确纠正 Agent
  → Hook 自动放入“不可信候选箱”
  → 你批准一次正确答案
  → Claude Code 与 Codex 下次会话自动采用
```

正常工作流中，未经批准的候选不会成为 Agent 指令。系统不会自己判断真理，也不会把网页、邮件或命令错误自动晋升为权威记忆。Claude Code 命中权威写入时会弹出权限确认框；Codex 的 `PreToolUse` 不支持请求单次批准，因此命中后直接拒绝，Agent 只给出含指纹的交互审核命令，由你复制到普通终端执行。需要注意：Hook 是防误操作和流程守门，不是把同一 macOS/Linux 用户下的任意 Shell 变成低权限沙箱。

## Requirements
- Python 3.11+
- macOS, Linux, or Windows WSL
- Claude Code and/or Codex

Obsidian and Git are optional. Obsidian can edit the memory directory; Git can version it privately.

## Install
```bash
git clone https://github.com/ldl8818/skills.git
cd skills/self-improving
python3 -m self_improving init
```

Non-interactive example:

```bash
python3 -m self_improving init \
  --agents claude,codex \
  --memory-root "$HOME/Documents/self-improving-memory" \
  --capture-corrections \
  --no-capture-errors
```

The installer merges Hook configuration and backs up existing files. It does not replace unrelated Hooks.
In an interactive terminal it asks before enabling correction capture. In
non-interactive use, correction capture stays off unless
`--capture-corrections` is supplied.

## Verify
```bash
python3 -m self_improving --version
python3 -m self_improving sync
python3 -m self_improving doctor
```

`sync` refreshes the stable knowledge index. Hook injection reads the configured
`memory.md` and approved correction answers directly; it does not copy private
memory into Claude or Codex instruction files.

The health report validates each managed Hook's command path, type, matcher and
timeout, then reports current-version event contract coverage separately. A new
installation can therefore be configured correctly while still warning that a
fresh Claude Code or Codex session, or a sanitized real-schema replay, has not
yet exercised all five event types. Release notes should still state separately
whether an end-to-end new client session was run.

## Sensitive sessions
```bash
SELF_IMPROVING_PERSIST=0 codex
SELF_IMPROVING_PERSIST=0 claude
```

Or disable persistence until explicitly re-enabled:

```bash
python3 -m self_improving persistence disable
python3 -m self_improving persistence enable
```

## Upgrade
```bash
git pull --ff-only
python3 -m self_improving upgrade
python3 -m self_improving doctor
```

## Uninstall
```bash
python3 -m self_improving uninstall --keep-data
```

Private memory is retained by default. Deleting it requires `--delete-data` and
`--confirm` with the full resolved memory path printed by the CLI. The target
must also contain the identity marker written by this software; filesystem root,
HOME, unrelated non-empty directories, and the public Skill directory are
refused.

## Review captured corrections

```bash
python3 -m self_improving review list
# Manual terminal approval: rule text and scope are entered at prompts.
python3 -m self_improving review approve-interactive --fingerprint '[fp:...]'
# Claude Code or trusted programmatic callers only; quote every argument for the target shell.
python3 -m self_improving review approve --fingerprint '[fp:...]' --correct '先读取当前文件，再根据实际内容判断。' --scope global
python3 -m self_improving review reject --fingerprint '[fp:...]'
python3 -m self_improving review revoke --fingerprint '[fp:...]'
python3 -m self_improving review legacy-list
python3 -m self_improving review import-legacy-interactive --legacy-id 'legacy:12ab34cd56ef'
# Claude Code or trusted programmatic callers only.
python3 -m self_improving review import-legacy --legacy-id 'legacy:12ab34cd56ef' --correct '重新提炼后的现行规则' --scope global
```

Approved answers are injected at the next `SessionStart`. The default budget is
the newest 20 answers and 4,000 answer characters. Raw candidates are never
injected. Use `--scope global` only for rules that apply everywhere; use
`--scope 'project:/absolute/project/path'` for project-only rules. Legacy rows
already present in `corrections.md` remain audit history and are not silently
activated by an upgrade. See [configuration](docs/configuration.md) for the switches.

Claude Code can run a user-confirmed review command and let the user approve it
in the client permission dialog. Codex deliberately cannot run review commands
inside the Agent tool loop: copy the fingerprint-only `approve-interactive`
command it drafts into a regular terminal, then enter the rule text and scope
at the CLI prompts. Run one interactive approval at a time; the CLI validates
and displays the current fingerprint before reading those fields. User-derived
text never becomes Shell syntax. The explicit
`--correct` / `--scope` form remains available for trusted programmatic callers.
This platform difference prevents Codex from continuing a protected write
after an unsupported `ask` Hook response.

To reuse a legacy row, distill it into a concise current rule and import it
explicitly with `review import-legacy`. The command requires a scope and returns
a verified fingerprint that can later be revoked. There is intentionally no
bulk “activate every active row” command.

## Supported behavior
Claude Code and Codex use separate adapters because their Hook payloads and lifecycle coverage differ. The PreToolUse guard covers Claude file tools and Shell calls, plus Codex `Bash` and `apply_patch` calls. It protects common writes to `memory.md`, `corrections.md` and the machine-authoritative approval store, and blocks an Agent from invoking approval commands through a hooked shell. Claude returns `ask`; Codex returns `deny`. Hook handlers have a 10-second timeout so a stuck local process cannot pause a client for Codex's 600-second default. Codex terminal approvals use an interactive CLI so distilled rules and project paths do not enter copied Shell commands. Shell and patch text inspection is not an operating-system security boundary and cannot prove that every obfuscated write is blocked. Human review outside the Agent tool loop, current-file verification and version control remain the authoritative safeguards.

Only Claude Code and Codex are supported. Obsidian, Git, Gemini,
OpenClaw and other editors or Agents are not required and are not silently
treated as installed.
