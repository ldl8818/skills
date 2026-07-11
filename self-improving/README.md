# Self-improving cross-agent memory
A configurable, review-gated memory system for Claude Code and Codex. Program code can be public; user memory remains in a separate private directory.

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
`memory.md` directly; it does not copy private memory into Claude or Codex
instruction files.

The health report separates Hook configuration from current-version event
contract coverage. A new
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
python3 -m self_improving review approve --fingerprint '[fp:...]' --correct 'verified rule'
python3 -m self_improving review reject --fingerprint '[fp:...]'
```

## Supported behavior
Claude Code and Codex use separate adapters because their Hook payloads and lifecycle coverage differ. Codex currently limits Pre/Post Tool Hooks to shell commands. The PreToolUse guard blocks direct file-tool writes and common shell writes to `memory.md`, but shell text inspection is not an operating-system security boundary and cannot prove that every possible command is blocked. Human review, current-file verification and version control remain the authoritative safeguards.

Only Claude Code and Codex are supported in version 2.0. Obsidian, Git, Gemini,
OpenClaw and other editors or Agents are not required and are not silently
treated as installed.
