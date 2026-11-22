"""Merge and remove Claude Code and Codex Hook configuration safely."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import shlex
import shutil
import sys
import tempfile
from typing import Any
import re
import tomllib

from self_improving.paths import PACKAGE_ROOT, SOURCE_ROOT, atomic_write_json, default_config_path, expand_path


MARKER = "self-improving-hook"
HOOK_TIMEOUT_SECONDS = 10
LEGACY_HOOK_NAMES = (
    "activator.sh",
    "error-detector-with-gc.sh",
    "session-init.sh",
    "guard_memory_scope.py",
    "stop-reflexion.sh",
)


def _hook_command_parts(platform: str, event: str) -> tuple[str, str]:
    package = shlex.quote(str(SOURCE_ROOT))
    config = shlex.quote(str(default_config_path()))
    prefix = f"cd {package} && SELF_IMPROVING_CONFIG={config} "
    suffix = f" -m self_improving hook --platform {platform} --event {event} # {MARKER}"
    return prefix, suffix


def hook_command(platform: str, event: str) -> str:
    prefix, suffix = _hook_command_parts(platform, event)
    return f"{prefix}{shlex.quote(sys.executable)}{suffix}"


def hook_command_matches(command: str, platform: str, event: str) -> bool:
    """判定已登记的 Hook 命令是否等效于本包的期望命令。

    只放开解释器一段：安装与体检可能由不同 Python 运行（如项目 venv vs Homebrew），
    逐字比对会把接线正常的 Hook 误判为未安装（2.6.1 修复的 doctor 假 ❌）。
    包路径、配置路径、平台、事件仍须精确一致，包搬家或命令陈旧照常报警。
    """
    prefix, suffix = _hook_command_parts(platform, event)
    return (
        command.startswith(prefix)
        and command.endswith(suffix)
        and len(command) > len(prefix) + len(suffix)
    )


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _backup_directory(state_root: Path) -> Path:
    parent = state_root / "backups"
    parent.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=datetime.now().strftime("%Y%m%d-%H%M%S-"), dir=parent))


def _backup(path: Path, state_root: Path) -> Path | None:
    if not path.exists():
        return None
    backup_dir = _backup_directory(state_root)
    backup = backup_dir / path.name
    shutil.copy2(path, backup)
    return backup


ANTIGRAVITY_GROUP_KEY = "self-improving"
ANTIGRAVITY_PRETOOL_MATCHER = "run_command|write_file|edit_file"
KIMI_PRETOOL_MATCHER = "^(Bash|Write|Edit)$"
WORKBUDDY_PRETOOL_MATCHER = "Write|Edit|MultiEdit|Bash|write_to_file|replace_in_file|execute_command"


def _config_file_key(platform: str) -> str:
    if platform in {"claude", "workbuddy"}:
        return "settings_file"
    if platform == "kimi":
        return "config_file"
    return "hooks_file"


def expected_events(platform: str, config: dict[str, Any]) -> tuple[str, ...]:
    if platform == "antigravity":
        events = ["SessionStart", "PreInvocation", "PreToolUse"]
        if config["persistence"].get("enabled", True) and config["persistence"].get("capture_command_errors", False):
            events.append("PostToolUse")
        if config["persistence"].get("enabled", True) and config["persistence"].get("capture_corrections", False):
            events.append("Stop")
        return tuple(events)
    if platform == "claude":
        return ("PreToolUse", "PostToolUse", "SessionStart", "UserPromptSubmit", "Stop")
    events = ["PreToolUse", "SessionStart", "UserPromptSubmit"]
    if config["persistence"].get("enabled", True) and config["persistence"].get("capture_command_errors", False):
        events.append("PostToolUse")
    if config["persistence"].get("enabled", True) and config["persistence"].get("capture_corrections", False):
        events.append("Stop")
    return tuple(events)


def _groups(platform: str, config: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    matchers = {
        "PreToolUse": (
            "Write|Edit|Bash"
            if platform == "claude"
            else WORKBUDDY_PRETOOL_MATCHER
            if platform == "workbuddy"
            else "Bash|apply_patch"
        ),
        "PostToolUse": "Bash",
        "SessionStart": None if platform in {"claude", "workbuddy"} else "startup|resume|clear|compact",
        "UserPromptSubmit": None,
        "Stop": None,
    }
    result: dict[str, list[dict[str, Any]]] = {}
    for event, matcher in matchers.items():
        if platform in {"codex", "workbuddy"} and event in {"PostToolUse", "Stop"}:
            capture = "capture_command_errors" if event == "PostToolUse" else "capture_corrections"
            if not config["persistence"].get("enabled", True) or not config["persistence"].get(capture, False):
                continue
        group: dict[str, Any] = {
            "hooks": [
                {
                    "type": "command",
                    "command": hook_command(platform, event),
                    "timeout": HOOK_TIMEOUT_SECONDS,
                }
            ]
        }
        if platform == "codex":
            group["hooks"][0]["statusMessage"] = {
                "PreToolUse": "self-improving｜工具调用前检查",
                "PostToolUse": "self-improving｜工具结果与错误检查",
                "SessionStart": "self-improving｜加载知识与会话上下文",
                "UserPromptSubmit": "self-improving｜按需检索领域知识",
                "Stop": "self-improving｜会话结束维护",
            }[event]
        if matcher:
            group["matcher"] = matcher
        result[event] = [group]
    return result


def _antigravity_group(config: dict[str, Any], existing: object = None) -> dict[str, Any]:
    existing_commands: dict[str, str] = {}
    if isinstance(existing, dict):
        for event, entries in existing.items():
            if not isinstance(entries, list):
                continue
            for item in entries:
                if not isinstance(item, dict):
                    continue
                if isinstance(item.get("hooks"), list):
                    for hook in item["hooks"]:
                        if isinstance(hook, dict) and hook_command_matches(str(hook.get("command", "")), "antigravity", event):
                            existing_commands[event] = str(hook["command"])
                elif hook_command_matches(str(item.get("command", "")), "antigravity", event):
                    existing_commands[event] = str(item["command"])
    group: dict[str, Any] = {}
    for event in expected_events("antigravity", config):
        cmd = existing_commands.get(event) or hook_command("antigravity", event)
        handler = {"type": "command", "command": cmd, "timeout": HOOK_TIMEOUT_SECONDS}
        if event in {"PreToolUse", "PostToolUse"}:
            matcher = ANTIGRAVITY_PRETOOL_MATCHER if event == "PreToolUse" else "run_command"
            group[event] = [{"matcher": matcher, "hooks": [handler]}]
        else:
            group[event] = [handler]
    return group


def _kimi_expected_entries(config: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for event in expected_events("kimi", config):
        item: dict[str, Any] = {
            "event": event,
            "command": hook_command("kimi", event),
            "timeout": HOOK_TIMEOUT_SECONDS,
        }
        if event == "PreToolUse":
            item["matcher"] = KIMI_PRETOOL_MATCHER
        elif event == "PostToolUse":
            item["matcher"] = "^Bash$"
        entries.append(item)
    return entries


def _strip_kimi_managed_blocks(text: str) -> str:
    """Remove only [[hooks]] TOML table blocks owned by self-improving, preserving everything else."""
    header_re = re.compile(r"^[ \t]*\[\[?[^\]\n]+\]\]?[ \t]*(?:#[^\n]*)?$", re.MULTILINE)
    matches = list(header_re.finditer(text))
    if not matches:
        return text
    parts: list[str] = [text[: matches[0].start()]]
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        block = text[start:end]
        header = match.group(0).split("#", 1)[0].strip()
        if header == "[[hooks]]" and MARKER in block:
            continue
        parts.append(block)
    return "".join(parts)


def _render_kimi_hook_block(entry: dict[str, Any]) -> str:
    lines = ["[[hooks]]", f"event = {json.dumps(entry['event'])}"]
    if "matcher" in entry:
        lines.append(f"matcher = {json.dumps(entry['matcher'])}")
    lines.append(f"command = {json.dumps(entry['command'])}")
    lines.append(f"timeout = {int(entry['timeout'])}")
    return "\n".join(lines) + "\n"


def _legacy_hook(command: str) -> bool:
    expanded = command.replace("${HOME}", str(Path.home())).replace("$HOME", str(Path.home()))
    if "$(" in expanded or "`" in expanded:
        return False
    try:
        lexer = shlex.shlex(expanded, posix=True, punctuation_chars=";&|()<>\n")
        lexer.whitespace = " \t\r"
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        return False
    if not tokens or any(token and all(char in ";&|()<>\n" for char in token) for token in tokens):
        # A compound command can also run third-party code; do not remove it.
        return False
    program = Path(tokens[0]).name
    if program in {"sh", "bash", "zsh", "dash"} or re.fullmatch(r"python(?:\d+(?:\.\d+)*)?", program):
        index = 1
        while index < len(tokens) and tokens[index].startswith("-"):
            if tokens[index] in {"-c", "-m"}:
                return False
            index += 1
        if index == len(tokens):
            return False
        script = tokens[index]
    else:
        script = tokens[0]
    candidate = Path(script).expanduser()
    directories = {PACKAGE_ROOT / "scripts", Path.home() / ".claude/scripts"}
    for agent in (".claude", ".codex"):
        directories.add(Path.home() / agent / "skills/self-improving/scripts")
    return (candidate.is_absolute() and candidate.name in LEGACY_HOOK_NAMES
            and candidate.parent in directories)


def _without_managed(groups: object) -> list[dict[str, Any]]:
    if not isinstance(groups, list):
        return []
    cleaned: list[dict[str, Any]] = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        hooks = group.get("hooks", [])
        if not isinstance(hooks, list):
            cleaned.append(group)
            continue
        remaining = [
            hook
            for hook in hooks
            if not (
                isinstance(hook, dict)
                and (
                    MARKER in str(hook.get("command", ""))
                    or _legacy_hook(str(hook.get("command", "")))
                )
            )
        ]
        if remaining:
            kept = dict(group)
            kept["hooks"] = remaining
            cleaned.append(kept)
    return cleaned


def _merge_codex_groups(groups, desired, event):
    """Keep group positions, including empty slots, so other hooks retain their keys."""
    result, installed = [], False
    for group in groups:
        remaining = []
        for hook in group.get("hooks", []):
            command = str(hook.get("command", ""))
            if MARKER not in command and not _legacy_hook(command):
                remaining.append(hook)
            elif desired and not installed and group.get("matcher") == desired.get("matcher"):
                replacement = {**hook, **desired["hooks"][0]}
                if hook_command_matches(command, "codex", event):
                    replacement["command"] = command
                remaining.append(replacement)
                installed = True
        result.append({**group, "hooks": remaining})
    if desired and not installed:
        result.append(desired)
    return result


def install_hooks(config: dict[str, Any], platform: str) -> tuple[Path, Path | None]:
    agent = config["agents"][platform]
    path = expand_path(agent[_config_file_key(platform)])
    state_root = expand_path(config["state_root"])
    if platform == "antigravity":
        payload = _load_json(path)
        backup = _backup(path, state_root)
        payload[ANTIGRAVITY_GROUP_KEY] = _antigravity_group(config, payload.get(ANTIGRAVITY_GROUP_KEY))
        atomic_write_json(path, payload)
        return path, backup
    if platform == "kimi":
        path.parent.mkdir(parents=True, exist_ok=True)
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        try:
            if text.strip():
                tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            raise ValueError(f"invalid Kimi TOML, not modified: {path}: {exc}") from exc
        cleaned = _strip_kimi_managed_blocks(text).rstrip()
        blocks = "\n".join(_render_kimi_hook_block(entry) for entry in _kimi_expected_entries(config))
        updated = (cleaned + "\n\n" + blocks) if cleaned else blocks
        try:
            tomllib.loads(updated)
        except tomllib.TOMLDecodeError as exc:
            raise ValueError(f"generated invalid Kimi TOML, not modified: {path}: {exc}") from exc
        from self_improving.paths import atomic_write

        backup = _backup(path, state_root)
        atomic_write(path, updated)
        return path, backup
    if platform == "codex":
        ensure_codex_hooks_feature(config)
    payload = _load_json(path)
    backup = _backup(path, state_root)
    hooks = payload.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError(f"hooks must be an object: {path}")
    expected = _groups(platform, config)
    if platform == "codex":
        for event in dict.fromkeys([*hooks, *expected]):
            hooks[event] = _merge_codex_groups(hooks.get(event, []), expected[event][0] if event in expected else None, event)
    else:
        for event in tuple(hooks):
            if event not in expected:
                cleaned = _without_managed(hooks.get(event))
                if cleaned:
                    hooks[event] = cleaned
                else:
                    del hooks[event]
        for event, groups in expected.items():
            hooks[event] = _without_managed(hooks.get(event)) + groups
    atomic_write_json(path, payload)
    return path, backup


def uninstall_hooks(config: dict[str, Any], platform: str) -> Path:
    agent = config["agents"][platform]
    path = expand_path(agent[_config_file_key(platform)])
    if platform == "antigravity":
        payload = _load_json(path)
        payload.pop(ANTIGRAVITY_GROUP_KEY, None)
        atomic_write_json(path, payload)
        return path
    if platform == "kimi":
        if not path.exists():
            return path
        text = path.read_text(encoding="utf-8")
        try:
            if text.strip():
                tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            raise ValueError(f"invalid Kimi TOML, not modified: {path}: {exc}") from exc
        cleaned = _strip_kimi_managed_blocks(text).rstrip()
        updated = (cleaned + "\n") if cleaned else ""
        if updated.strip():
            tomllib.loads(updated)
        from self_improving.paths import atomic_write

        atomic_write(path, updated)
        return path
    payload = _load_json(path)
    hooks = payload.get("hooks", {})
    if isinstance(hooks, dict):
        for event in tuple(hooks):
            hooks[event] = _without_managed(hooks[event])
            if not hooks[event]:
                del hooks[event]
    atomic_write_json(path, payload)
    return path


def managed_hooks_present(config: dict[str, Any], platform: str) -> bool:
    """Find even partial managed wiring on an adapter marked disabled."""
    agent = config["agents"][platform]
    path = expand_path(agent[_config_file_key(platform)])
    if platform == "antigravity":
        payload = _load_json(path)
        if ANTIGRAVITY_GROUP_KEY in payload:
            return True
        return MARKER in json.dumps(payload, ensure_ascii=False)
    if platform == "kimi":
        if not path.exists():
            return False
        parsed = tomllib.loads(path.read_text(encoding="utf-8"))
        hooks = parsed.get("hooks", [])
        if not isinstance(hooks, list):
            raise ValueError("Kimi hooks must be an array")
        return any(isinstance(item, dict) and MARKER in str(item.get("command", "")) for item in hooks)
    payload = _load_json(path)
    hooks = payload.get("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("hooks must be an object")
    for groups in hooks.values():
        if not isinstance(groups, list):
            continue
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                continue
            for hook in group["hooks"]:
                if isinstance(hook, dict):
                    command = str(hook.get("command", ""))
                    if MARKER in command or _legacy_hook(command):
                        return True
    return False


def hook_is_installed(config: dict[str, Any], platform: str) -> bool:
    agent = config["agents"][platform]
    path = expand_path(agent[_config_file_key(platform)])
    if platform == "antigravity":
        try:
            payload = _load_json(path)
        except (OSError, ValueError, json.JSONDecodeError):
            return False
        group = payload.get(ANTIGRAVITY_GROUP_KEY)
        if not isinstance(group, dict) or group.get("enabled") is False:
            return False
        expected = set(expected_events("antigravity", config))
        present_events = {key for key in group if key != "enabled"}
        if present_events != expected:
            return False
        for event in expected:
            entries = group.get(event)
            if not isinstance(entries, list):
                return False
            if event in {"PreToolUse", "PostToolUse"}:
                want_matcher = ANTIGRAVITY_PRETOOL_MATCHER if event == "PreToolUse" else "run_command"
                ok = any(
                    isinstance(item, dict)
                    and item.get("matcher") == want_matcher
                    and isinstance(item.get("hooks"), list)
                    and any(
                        isinstance(h, dict)
                        and h.get("type", "command") == "command"
                        and h.get("timeout") == HOOK_TIMEOUT_SECONDS
                        and hook_command_matches(str(h.get("command", "")), "antigravity", event)
                        for h in item["hooks"]
                    )
                    for item in entries
                )
            else:
                ok = any(
                    isinstance(h, dict)
                    and h.get("type", "command") == "command"
                    and h.get("timeout") == HOOK_TIMEOUT_SECONDS
                    and hook_command_matches(str(h.get("command", "")), "antigravity", event)
                    for h in entries
                )
            if not ok:
                return False
        return True
    if platform == "kimi":
        try:
            parsed = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            return False
        hooks = parsed.get("hooks", [])
        if not isinstance(hooks, list):
            return False
        expected_entries = _kimi_expected_entries(config)
        expected_event_set = {entry["event"] for entry in expected_entries}
        managed = [item for item in hooks if isinstance(item, dict) and MARKER in str(item.get("command", ""))]
        if any(item.get("event") not in expected_event_set for item in managed):
            return False
        for entry in expected_entries:
            ok = any(
                item.get("event") == entry["event"]
                and item.get("matcher") == entry.get("matcher")
                and item.get("timeout") == HOOK_TIMEOUT_SECONDS
                and hook_command_matches(str(item.get("command", "")), "kimi", entry["event"])
                for item in managed
            )
            if not ok:
                return False
        return True
    try:
        payload = _load_json(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    hooks = payload.get("hooks", {})
    if not isinstance(hooks, dict):
        return False
    expected = _groups(platform, config)
    if platform in {"codex", "workbuddy"} and any(
        MARKER in str(hook.get("command", "")) and event not in expected
        for event, groups in hooks.items() for group in groups for hook in group.get("hooks", [])
    ):
        return False
    return all(
        any(
            isinstance(group, dict)
            and group.get("matcher") == expected[event][0].get("matcher")
            and isinstance(hook, dict)
            and hook.get("type") == "command"
            and hook.get("timeout") == HOOK_TIMEOUT_SECONDS
            and hook_command_matches(str(hook.get("command", "")), platform, event)
            for group in hooks.get(event, []) if isinstance(group, dict)
            for hook in group.get("hooks", []) if isinstance(group.get("hooks", []), list)
        )
        for event in expected
    ) and (platform != "codex" or codex_hooks_enabled(config))


def codex_hooks_enabled(config: dict[str, Any]) -> bool:
    path = expand_path(config["agents"]["codex"]["config_file"])
    try:
        payload = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return False
    return payload.get("features", {}).get("hooks") is True


def ensure_codex_hooks_feature(config: dict[str, Any]) -> Path:
    path = expand_path(config["agents"]["codex"]["config_file"])
    path.parent.mkdir(parents=True, exist_ok=True)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    try:
        parsed = tomllib.loads(text) if text.strip() else {}
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"invalid Codex TOML, not modified: {path}: {exc}") from exc
    if parsed.get("features", {}).get("hooks") is True:
        return path
    feature = re.search(r"""(?ms)^[ \t]*\[(?:features|"features"|'features')\][^\n]*\n?(.*?)(?=^[ \t]*\[|\Z)""", text)
    if feature:
        body = feature.group(1)
        key = r"""(?m)^([ \t]*(?:hooks|"hooks"|'hooks')[ \t]*=[ \t]*)(?:true|false)([ \t]*(?:#[^\n]*)?)$"""
        if re.search(key, body):
            body = re.sub(key, r"\g<1>true\2", body, count=1)
        elif "hooks" in parsed.get("features", {}):
            raise ValueError("features.hooks must be a boolean in the features table")
        else:
            body = ("hooks = true\n" + body)
        text = text[: feature.start(1)] + body + text[feature.end(1) :]
    else:
        text = text.rstrip() + ("\n\n" if text.strip() else "") + "[features]\nhooks = true\n"
    try:
        tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"generated invalid Codex TOML, not modified: {path}: {exc}") from exc
    from self_improving.paths import atomic_write

    _backup(path, expand_path(config["state_root"]))
    atomic_write(path, text)
    return path


def install_skill_links(config: dict[str, Any]) -> list[tuple[Path, Path | None]]:
    state_root = expand_path(config["state_root"])
    destinations = []
    if config["agents"]["claude"].get("enabled"):
        destinations.append(Path.home() / ".claude/skills/self-improving")
    if config["agents"]["codex"].get("enabled"):
        destinations.append(Path.home() / ".codex/skills/self-improving")
    results: list[tuple[Path, Path | None]] = []
    for destination in destinations:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.is_symlink() and destination.resolve() == PACKAGE_ROOT:
            results.append((destination, None))
            continue
        backup: Path | None = None
        if destination.exists() or destination.is_symlink():
            backup_dir = _backup_directory(state_root)
            backup = backup_dir / f"{destination.parent.parent.name}-{destination.parent.name}-{destination.name}"
            shutil.move(destination, backup)
        destination.symlink_to(PACKAGE_ROOT, target_is_directory=True)
        results.append((destination, backup))
    return results


def uninstall_skill_links() -> list[Path]:
    removed: list[Path] = []
    for destination in (
        Path.home() / ".claude/skills/self-improving",
        Path.home() / ".codex/skills/self-improving",
    ):
        if destination.is_symlink() and destination.resolve() == PACKAGE_ROOT:
            destination.unlink()
            removed.append(destination)
    return removed
