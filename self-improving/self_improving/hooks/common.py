"""Shared Hook behavior after platform payload normalization."""

from __future__ import annotations

import json
from pathlib import Path
import re
import shlex
import sys
from datetime import datetime, timezone, timedelta

from self_improving import __version__
from self_improving.config import load_config, resolved
from self_improving.events import normalize
from self_improving.paths import atomic_write_json
from self_improving.security import advisory_lock, contains_secret, digest
from self_improving.storage import (
    RECEIPT_RESERVE_TOKENS,
    SESSION_UPDATE_RESERVE_TOKENS,
    VERIFIED_RELATIVE,
    VERIFIED_WRAPPER_TOKENS,
    append_candidate,
    append_error,
    correction_selection,
    estimate_tokens,
    pending_correction_count,
    persistence_enabled,
    render_verified_corrections,
)


# 英文关键词用「前后不是英文字母」而不是 \b：要排除的是 remembering 这类派生词，
# 不是相邻的中文。\b 把中文也当词字符，会让「请remember先读文件」漏捕。
CORRECTION = re.compile(r"你又错了|我说过|你怎么又|不对|不是这样|应该是|应该用|记住|别忘了|(?<![A-Za-z])(?:remember|stop doing)(?![A-Za-z])", re.I)
REVIEW_REMINDER_THRESHOLD = 3
# 纠错是人对上一轮输出的即时否定，天然简短。长文本（粘贴的文档、客户端生成的
# 长提示词）几乎必然偶然包含某个关键词，长度越大误判概率越趋近 1，因此先于
# 关键词判定按长度截断。此判据与"消息长什么样"无关，未见过的机器消息同样挡得住。
MAX_CORRECTION_CHARS = 1500

# 客户端会把系统消息（后台任务通知、注入提醒、斜杠命令回显）作为一条"用户消息"
# 送进 UserPromptSubmit。以这些标签开头的不是人在说话，其中的纠错字眼不构成纠错；
# 照单捕获会把噪音和私人路径带进候选箱（全角变体防上游转义差异）。
MACHINE_PREFIXES = (
    "<task-notification", "＜task-notification",
    "<system-reminder", "＜system-reminder",
    "<memory-review-reminder", "＜memory-review-reminder",
    "<local-command-stdout", "＜local-command-stdout",
    "<command-message", "＜command-message",
    "<command-name", "＜command-name",
    "<command-args", "＜command-args",
    "<self-improving-", "＜self-improving-",
)


def _correction_text(prompt: str) -> str:
    """Return the part of the prompt that can count as a human correction.

    Messages that begin with a machine tag are dropped entirely; over-long
    prompts are dropped because they are documents or generated prompts rather
    than corrections; fenced code blocks are removed so keywords inside pasted
    logs/diffs do not trigger capture. Human text before an appended reminder
    block still counts.
    """
    if prompt.lstrip().startswith(MACHINE_PREFIXES):
        return ""
    if len(prompt) > MAX_CORRECTION_CHARS:
        return ""
    return re.sub(r"```.*?```", "", prompt, flags=re.S)


def _match_context(text: str, hit: re.Match, window: int = 24) -> str:
    """Render the matched keyword with a short window, for the inbox Match column."""
    start = max(0, hit.start() - window)
    end = min(len(text), hit.end() + window)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return f"{hit.group(0)} ⟨{prefix}{text[start:end]}{suffix}⟩"


def _schema_shape(value):
    if isinstance(value, dict):
        return {key: _schema_shape(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        return [_schema_shape(value[0])] if value else []
    return type(value).__name__


def _record_schema(state_root: Path, platform: str, event: str, payload: dict) -> None:
    path = state_root / "hook-schemas" / f"{platform}-{event}.json"
    shape = {
        "platform": platform,
        "event": event,
        "package_version": __version__,
        "observed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "shape": _schema_shape(payload),
    }
    try:
        previous = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        previous = {}
    if (
        previous.get("package_version") == __version__
        and previous.get("shape") == shape["shape"]
        and str(previous.get("observed_at", ""))[:10] == shape["observed_at"][:10]
    ):
        return
    atomic_write_json(path, shape)


def _review_reminder_due(state_root: Path, platform: str, interval_hours: int) -> bool:
    path = state_root / "review-reminders" / f"{platform}.json"
    with advisory_lock(state_root / "locks" / f"review-reminder-{platform}.lock"):
        now = datetime.now(timezone.utc)
        try:
            previous = json.loads(path.read_text(encoding="utf-8"))
            sent_at = datetime.fromisoformat(previous["sent_at"])
            if sent_at.tzinfo is not None and now - sent_at < timedelta(hours=interval_hours):
                return False
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            pass
        atomic_write_json(path, {"sent_at": now.isoformat(timespec="seconds")})
        return True


def _receipt_value(value: int | str) -> int | str:
    return "999+" if isinstance(value, int) and value > 999 else value


def _valid_core_memory(path: Path, max_chars: int) -> tuple[str, str]:
    if not path.exists():
        return "", "missing"
    memory = path.read_text(encoding="utf-8")
    lines = memory.splitlines()
    valid_title = lines and lines[0].startswith(("# Memory ·", "# Memory "))
    if not 5 <= len(lines) <= 50 or len(memory) > max_chars or not valid_title or contains_secret(memory):
        return "", "invalid"
    return memory.rstrip(), "ok"


MUTATING_REVIEW_ACTIONS = {
    "approve",
    "approve-interactive",
    "reject",
    "revoke",
    "promote",
    "import-legacy",
    "import-legacy-interactive",
}


def _shell_tokens(command: str) -> list[str]:
    """Tokenize like a POSIX shell so adjacent quoted fragments cannot hide words."""
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        lexer.commenters = ""
        return list(lexer)
    except ValueError:
        return []


def _review_invocations(tokens: list[str]) -> list[tuple[int, str]]:
    invocations: list[tuple[int, str]] = []
    for index, token in enumerate(tokens):
        normalized = Path(token).name.replace("_", "-")
        if normalized != "self-improving" or index + 2 >= len(tokens):
            continue
        if tokens[index + 1] == "review" and tokens[index + 2] in MUTATING_REVIEW_ACTIONS:
            invocations.append((index, tokens[index + 2]))
    return invocations


def _interpreter_authority_reference(command: str, tokens: list[str]) -> bool:
    """Do not associate a search argument with an unrelated interpreter call."""
    groups = [tokens]
    # Keep complex shell syntax on the conservative whole-command path.
    if not any(marker in command for marker in ("$", "`", "<<")):
        try:
            lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()\n")
            lexer.whitespace = " \t\r"
            lexer.whitespace_split = True
            lexer.commenters = ""
            groups = [[]]
            for token in lexer:
                if token and all(char in ";&|()\n" for char in token) and any(char in "()" for char in token):
                    groups = [tokens]
                    break
                # A pipeline passes source to its interpreter; keep it together.
                if token == "||" or (token and all(char in ";&()\n" for char in token)):
                    groups.append([])
                else:
                    groups[-1].append(token)
        except ValueError:
            groups = [tokens]
    references = ("verified-corrections.jsonl",
                  "self_improving.review", "self_improving.storage", "append_verified_correction")
    return any(
        any(Path(token).name.startswith("python") or token in {"node", "ruby", "perl"} for token in group)
        and any(name in token for token in group for name in references)
        for group in groups
    )


def _is_review_help(tokens: list[str]) -> bool:
    """Allow only one standalone, exact, read-only help invocation."""
    invocations = _review_invocations(tokens)
    if len(invocations) != 1:
        return False
    index, _ = invocations[0]
    prefix_ok = index == 0 or (
        index == 2
        and Path(tokens[0]).name.startswith("python")
        and tokens[1] == "-m"
    )
    return prefix_ok and tokens[index + 3 :] in (["-h"], ["--help"])


def _session_context_output(
    state_root: Path,
    platform: str,
    session_id: str,
    source: str,
    resume_mode: str,
    rendered: str,
) -> str:
    """Return a full replacement on changed resumes, or nothing when unchanged."""
    if not session_id:
        return rendered if source != "resume" else ""
    session_key = digest(session_id)[:24]
    path = state_root / "session-context" / platform / f"{session_key}.json"
    current_digest = digest(rendered)
    with advisory_lock(state_root / "locks" / f"session-context-{platform}-{session_key}.lock"):
        try:
            previous = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            previous = {}
        previous_digest = previous.get("digest")
        if source == "resume" and resume_mode != "always" and previous_digest == current_digest:
            return ""
        atomic_write_json(path, {
            "digest": current_digest,
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })
    if source == "resume" and previous_digest and previous_digest != current_digest:
        if rendered:
            return "<self-improving-prior-injection-invalidated/>\n" + rendered
        return "<self-improving-prior-injection-cleared/>"
    return rendered


def _dangerous_authority_write(event, memory_root: Path) -> bool:
    if event.event != "PreToolUse":
        return False
    command = str(event.tool_input.get("command") or "")
    file_path = str(event.tool_input.get("file_path") or "")
    authorities = ((memory_root / VERIFIED_RELATIVE).resolve(),)
    if file_path:
        try:
            candidate = Path(file_path).expanduser()
            if not candidate.is_absolute() and event.cwd:
                candidate = Path(event.cwd) / candidate
            if candidate.resolve() in authorities:
                return True
        except OSError:
            pass
    if not command:
        return False
    if event.tool_name == "apply_patch":
        patch_paths = re.findall(
            r"^\*\*\* (?:Add|Update|Delete) File: (.+?)\s*$|^\*\*\* Move to: (.+?)\s*$",
            command,
            flags=re.MULTILINE,
        )
        for source_path, move_path in patch_paths:
            candidate = Path(source_path or move_path).expanduser()
            if not candidate.is_absolute():
                if not event.cwd:
                    continue
                candidate = Path(event.cwd) / candidate
            try:
                if candidate.resolve() in authorities:
                    return True
            except OSError:
                continue
        return False
    expanded = command.replace("$HOME", str(Path.home())).replace("${HOME}", str(Path.home()))
    from self_improving.hooks.readonly import readonly_python
    if readonly_python(command):
        return False
    tokens = _shell_tokens(expanded)
    if _review_invocations(tokens) and not _is_review_help(tokens):
        return True
    if _interpreter_authority_reference(expanded, tokens):
        return True
    write_signal = (
        any(token in {"tee", "rm", "mv", "cp", "truncate"} for token in tokens)
        or any(
            token in {">", ">>"}
            and (index + 1 >= len(tokens) or tokens[index + 1] != "/dev/null")
            for index, token in enumerate(tokens)
        )
        or any(token in {"sed", "perl"} and index + 1 < len(tokens) and tokens[index + 1] == "-i" for index, token in enumerate(tokens))
    )
    if not write_signal:
        return False
    if any(str(authority) in expanded for authority in authorities):
        return True
    cwd = Path(event.cwd).expanduser().resolve() if event.cwd else None
    if cwd == memory_root.resolve() and "verified-corrections.jsonl" in expanded:
        return True
    return bool(str(memory_root.resolve()) in expanded and "verified-corrections.jsonl" in expanded)


def dispatch(platform: str, declared_event: str, payload: dict) -> int:
    config = resolved(load_config())
    event = normalize(platform, declared_event, payload)
    root = Path(config["memory_root"])
    state_root = Path(config["state_root"])
    _record_schema(state_root, platform, event.event, payload)
    if _dangerous_authority_write(event, root):
        permission_decision = "deny" if platform == "codex" else "ask"
        reason = (
            "[authority-guard] 本次调用命中受保护记忆操作检测，已拒绝；不代表一定发生了写入。"
            "若为只读检查，请核对原始命令；若为已授权的写入、移动或审核，请在普通终端执行对应操作。"
            if platform == "codex"
            else "本次调用命中已验证纠错账本或审核操作保护，需要你亲自批准。"
        )
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": permission_decision,
                "permissionDecisionReason": reason,
            }
        }, ensure_ascii=False))
        return 0
    if event.event == "SessionStart":
        injection = config.get("injection", {})
        total_budget = int(injection.get("max_total_tokens", 1200))
        if total_budget <= 0:
            return 0
        remaining = max(
            0,
            total_budget - RECEIPT_RESERVE_TOKENS - SESSION_UPDATE_RESERVE_TOKENS,
        )
        sections: list[str] = []
        receipt: dict[str, int | str] = {}
        if injection.get("include_core_memory", False):
            memory, core_status = _valid_core_memory(
                root / "memory.md", int(injection.get("max_core_chars", 8000))
            )
            if core_status != "ok":
                receipt["core"] = core_status
            else:
                rendered = f"<self-improving-memory>\n{memory}\n</self-improving-memory>"
                cost = estimate_tokens(rendered)
                if cost <= remaining:
                    sections.append(rendered)
                    remaining -= cost
                else:
                    receipt["core"] = "budget_omitted"
        if injection.get("include_verified_corrections", True):
            selection = correction_selection(
                root,
                int(injection.get("max_verified_corrections", 20)),
                int(injection.get("max_verified_chars", 4000)),
                max(0, remaining - VERIFIED_WRAPPER_TOKENS),
                event.cwd,
                min_version=int(injection.get("min_verified_version", 2)),
            )
            if selection.answers:
                sections.append(render_verified_corrections(selection.answers))
            for key in ("omitted", "expired", "due", "legacy_ignored", "malformed"):
                value = getattr(selection, key)
                if value:
                    receipt[key] = _receipt_value(value)
        if receipt:
            attrs = " ".join(f'{key}="{value}"' for key, value in receipt.items())
            sections.append(f"<self-improving-receipt {attrs}/>")
        rendered = "\n".join(sections)
        output = _session_context_output(
            state_root,
            platform,
            event.session_id,
            event.source,
            str(injection.get("resume_mode", "skip")),
            rendered,
        )
        if output and estimate_tokens(output) <= total_budget:
            print(output)
        return 0
    if event.event == "Stop":
        if not persistence_enabled(config):
            return 0
        pending = pending_correction_count(root)
        interval = int(config.get("injection", {}).get("review_reminder_interval_hours", 24))
        if pending >= REVIEW_REMINDER_THRESHOLD and _review_reminder_due(state_root, platform, interval):
            message = f"纠错候选箱已有 {pending} 条待审，请审核纠错候选。"
            print(json.dumps({"systemMessage": message}, ensure_ascii=False))
        return 0
    if not persistence_enabled(config):
        return 0
    persistence = config["persistence"]
    if event.event == "UserPromptSubmit" and persistence.get("capture_corrections"):
        text = _correction_text(event.prompt)
        hit = CORRECTION.search(text) if text else None
        if hit:
            result = append_candidate(
                root,
                state_root,
                f"{platform}-user-prompt",
                event.prompt,
                int(persistence.get("max_candidate_chars", 500)),
                _match_context(text, hit),
            )
            print(f'<correction-captured result="{result}"/>')
    if event.event == "PostToolUse" and persistence.get("capture_command_errors"):
        if event.failed:
            detail = event.tool_output or f"command exited with status {event.exit_status}"
            result = append_error(
                root,
                state_root,
                event.tool_name or "shell",
                detail,
                max_entries=int(persistence.get("max_error_entries", 200)),
            )
            print(f'<error-captured result="{result}"/>')
    return 0


def run(platform: str, event: str) -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        payload = {}
    return dispatch(platform, event, payload)
