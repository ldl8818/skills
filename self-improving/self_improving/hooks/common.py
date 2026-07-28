"""Shared Hook behavior after platform payload normalization."""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys
from datetime import datetime, timezone

from self_improving import __version__
from self_improving.config import load_config, resolved
from self_improving.events import normalize
from self_improving.paths import atomic_write_json
from self_improving.security import contains_secret
from self_improving.storage import VERIFIED_RELATIVE, append_candidate, append_error, pending_correction_count, persistence_enabled, verified_corrections


# 英文关键词用「前后不是英文字母」而不是 \b：要排除的是 remembering 这类派生词，
# 不是相邻的中文。\b 把中文也当词字符，会让「请remember先读文件」漏捕。
CORRECTION = re.compile(r"你又错了|我说过|你怎么又|不对|不是这样|应该是|应该用|记住|别忘了|(?<![A-Za-z])(?:remember|stop doing)(?![A-Za-z])", re.I)
ERROR = re.compile(r"error:|failed|command not found|no such file|permission denied|fatal:|exception|traceback|non-zero|interrupted", re.I)
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
    atomic_write_json(path, shape)


def _dangerous_authority_write(event, memory_root: Path) -> bool:
    if event.event != "PreToolUse":
        return False
    command = str(event.tool_input.get("command") or "")
    file_path = str(event.tool_input.get("file_path") or "")
    authorities = tuple((memory_root / name).resolve() for name in ("memory.md", "corrections.md", VERIFIED_RELATIVE))
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
    expanded = command.replace("$HOME", str(Path.home())).replace("${HOME}", str(Path.home()))
    if re.search(r"(?:self_improving|self-improving)\s+review\s+(?:approve|reject|revoke|import-legacy)\b", expanded):
        return True
    internal_authority_api = any(name in expanded for name in ("self_improving.review", "self_improving.storage", "append_verified_correction"))
    if ("corrections.md" in expanded or "verified-corrections.jsonl" in expanded or internal_authority_api) and re.search(r"\b(?:python\d*|node|ruby|perl)\b", expanded):
        return True
    write_signal = bool(re.search(r">{1,2}(?!\s*(?:/dev/null\b|&\d))|\b(?:tee|rm|mv|cp|truncate)\b|\b(?:sed|perl)\s+-i", expanded))
    if not write_signal:
        return False
    if any(str(authority) in expanded for authority in authorities):
        return True
    cwd = Path(event.cwd).expanduser().resolve() if event.cwd else None
    if cwd == memory_root.resolve() and re.search(r"(?:^|[/\s'\"])(?:memory|corrections)\.md(?:$|[\s'\"])", expanded):
        return True
    return bool(str(memory_root.resolve()) in expanded and any(name in expanded for name in ("memory.md", "corrections.md", "verified-corrections.jsonl")))


def dispatch(platform: str, declared_event: str, payload: dict) -> int:
    config = resolved(load_config())
    event = normalize(platform, declared_event, payload)
    root = Path(config["memory_root"])
    state_root = Path(config["state_root"])
    _record_schema(state_root, platform, event.event, payload)
    if _dangerous_authority_write(event, root):
        # Claude Code 与 Codex（0.144 实证）解析同一套 PreToolUse ask 决策：弹出权限框由用户当场批准，
        # 批准动作发生在客户端 UI，会话内文本（含注入内容）无法伪造。
        # 不解析决策输出的更旧 Codex 版本守门不生效，需升级 Codex。
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "ask",
                "permissionDecisionReason": "本次调用将写入核心记忆或已验证纠错（权威文件），需要你亲自批准。",
            }
        }, ensure_ascii=False))
        return 0
    if event.event == "SessionStart":
        memory_path = root / "memory.md"
        if not memory_path.exists():
            print(f"<memory-source-warning>共享记忆不存在：{memory_path}</memory-source-warning>")
            return 0
        memory = memory_path.read_text(encoding="utf-8")
        lines = memory.splitlines()
        valid_title = lines and lines[0].startswith(("# Memory ·", "# Memory "))
        injection = config.get("injection", {})
        core_limit = int(injection.get("max_core_chars", 8000))
        if not 5 <= len(lines) <= 50 or len(memory) > core_limit or not valid_title or contains_secret(memory):
            print(f"<memory-source-warning>共享记忆结构异常或疑似含敏感信息：{memory_path}</memory-source-warning>")
            return 0
        print("<self-improving-memory>")
        print(memory.rstrip())
        print("</self-improving-memory>")
        if injection.get("include_verified_corrections", True):
            corrections = verified_corrections(
                root,
                int(injection.get("max_verified_corrections", 20)),
                int(injection.get("max_verified_chars", 4000)),
                event.cwd,
            )
            if corrections:
                print("<verified-corrections>")
                print("以下内容已经人工审核；当前文件和可验证证据与其冲突时，以当前证据为准。")
                for answer in corrections:
                    print(f"- {answer}")
                print("</verified-corrections>")
        pending = pending_correction_count(root)
        if pending >= REVIEW_REMINDER_THRESHOLD:
            print(
                f'<memory-review-reminder pending="{pending}">'
                f"纠错候选箱已有 {pending} 条待审。请在合适时机向用户提议预审："
                "运行 python3 -m self_improving review list --json 读取候选，"
                "逐条提炼规则草稿并给出批准/拒绝建议与作用范围，经用户明确同意后再执行 review approve/reject"
                "（多条可用 && 串联成一条命令）。未经用户同意禁止批准。"
                "</memory-review-reminder>"
            )
        return 0
    if event.event == "Stop":
        pending = pending_correction_count(root)
        if pending >= REVIEW_REMINDER_THRESHOLD:
            print(f'<memory-review-reminder pending="{pending}">请审核纠错候选。</memory-review-reminder>')
        return 0
    if not persistence_enabled(config):
        print('<self-improving-persistence enabled="false"/>')
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
        failed = event.exit_status not in (None, 0) or bool(ERROR.search(event.tool_output))
        if failed:
            detail = event.tool_output or f"command exited with status {event.exit_status}"
            result = append_error(root, state_root, event.tool_name or "shell", detail)
            print(f'<error-captured result="{result}"/>')
    return 0


def run(platform: str, event: str) -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        payload = {}
    return dispatch(platform, event, payload)
