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


def _groups(platform: str, config: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    matchers = {
        "PreToolUse": "Write|Edit|Bash" if platform == "claude" else "Bash|apply_patch",
        "PostToolUse": "Bash",
        "SessionStart": None if platform == "claude" else "startup|resume|clear|compact",
        "UserPromptSubmit": None,
        "Stop": None,
    }
    result: dict[str, list[dict[str, Any]]] = {}
    for event, matcher in matchers.items():
        group: dict[str, Any] = {
            "hooks": [
                {
                    "type": "command",
                    "command": hook_command(platform, event),
                    "timeout": HOOK_TIMEOUT_SECONDS,
                }
            ]
        }
        if matcher:
            group["matcher"] = matcher
        result[event] = [group]
    return result


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


def install_hooks(config: dict[str, Any], platform: str) -> tuple[Path, Path | None]:
    agent = config["agents"][platform]
    key = "settings_file" if platform == "claude" else "hooks_file"
    path = expand_path(agent[key])
    state_root = expand_path(config["state_root"])
    if platform == "codex":
        ensure_codex_hooks_feature(config)
    payload = _load_json(path)
    backup = _backup(path, state_root)
    hooks = payload.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError(f"hooks must be an object: {path}")
    for event, groups in _groups(platform, config).items():
        hooks[event] = _without_managed(hooks.get(event)) + groups
    atomic_write_json(path, payload)
    return path, backup


def uninstall_hooks(config: dict[str, Any], platform: str) -> Path:
    agent = config["agents"][platform]
    key = "settings_file" if platform == "claude" else "hooks_file"
    path = expand_path(agent[key])
    payload = _load_json(path)
    hooks = payload.get("hooks", {})
    if isinstance(hooks, dict):
        for event in tuple(hooks):
            hooks[event] = _without_managed(hooks[event])
            if not hooks[event]:
                del hooks[event]
    atomic_write_json(path, payload)
    return path


def hook_is_installed(config: dict[str, Any], platform: str) -> bool:
    agent = config["agents"][platform]
    key = "settings_file" if platform == "claude" else "hooks_file"
    path = expand_path(agent[key])
    try:
        payload = _load_json(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    hooks = payload.get("hooks", {})
    if not isinstance(hooks, dict):
        return False
    expected = _groups(platform, config)
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
