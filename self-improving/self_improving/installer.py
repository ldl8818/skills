"""Merge and remove Claude Code and Codex Hook configuration safely."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import shlex
import shutil
import sys
from typing import Any
import re
import tomllib

from self_improving.paths import PACKAGE_ROOT, atomic_write_json, default_config_path, expand_path


MARKER = "self-improving-hook"
LEGACY_HOOK_NAMES = (
    "activator.sh",
    "error-detector-with-gc.sh",
    "session-init.sh",
    "guard_memory_scope.py",
    "stop-reflexion.sh",
)


def hook_command(platform: str, event: str) -> str:
    package = shlex.quote(str(PACKAGE_ROOT))
    python = shlex.quote(sys.executable)
    config = shlex.quote(str(default_config_path()))
    return f"cd {package} && SELF_IMPROVING_CONFIG={config} {python} -m self_improving hook --platform {platform} --event {event} # {MARKER}"


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _backup(path: Path, state_root: Path) -> Path | None:
    if not path.exists():
        return None
    backup_dir = state_root / "backups" / datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / path.name
    shutil.copy2(path, backup)
    return backup


def _groups(platform: str) -> dict[str, list[dict[str, Any]]]:
    matchers = {
        "PreToolUse": "Write|Edit|Bash" if platform == "claude" else "Bash",
        "PostToolUse": "Bash",
        "SessionStart": None if platform == "claude" else "startup|resume",
        "UserPromptSubmit": None,
        "Stop": None,
    }
    result: dict[str, list[dict[str, Any]]] = {}
    for event, matcher in matchers.items():
        group: dict[str, Any] = {
            "hooks": [{"type": "command", "command": hook_command(platform, event)}]
        }
        if matcher:
            group["matcher"] = matcher
        result[event] = [group]
    return result


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
                    or any(name in str(hook.get("command", "")) for name in LEGACY_HOOK_NAMES)
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
    for event, groups in _groups(platform).items():
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
    return all(
        any(
            isinstance(hook, dict) and str(hook.get("command", "")) == hook_command(platform, event)
            for group in hooks.get(event, []) if isinstance(group, dict)
            for hook in group.get("hooks", []) if isinstance(group.get("hooks", []), list)
        )
        for event in _groups(platform)
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
    feature = re.search(r"(?ms)^\[features\][^\n]*\n?(.*?)(?=^\[|\Z)", text)
    if feature:
        body = feature.group(1)
        if re.search(r"(?m)^hooks\s*=", body):
            body = re.sub(r"(?m)^hooks\s*=.*$", "hooks = true", body, count=1)
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
            backup_dir = state_root / "backups" / datetime.now().strftime("%Y%m%d-%H%M%S")
            backup_dir.mkdir(parents=True, exist_ok=True)
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
