"""Versioned user configuration without third-party dependencies."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from self_improving.paths import atomic_write_json, default_config_path, expand_path


SCHEMA_VERSION = 1


INJECTION_DEFAULTS = {
    "include_verified_corrections": True,
    "max_core_chars": 8000,
    "max_verified_corrections": 20,
    "max_verified_chars": 4000,
}


def default_config(memory_root: str | None = None) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "memory_root": memory_root or "~/Documents/self-improving-memory",
        "state_root": "~/.local/state/self-improving",
        "agents": {
            "claude": {
                "enabled": True,
                "settings_file": "~/.claude/settings.json",
                "project_memory_root": "~/.claude/projects",
            },
            "codex": {
                "enabled": True,
                "hooks_file": "~/.codex/hooks.json",
                "agents_file": "~/.codex/AGENTS.md",
                "config_file": "~/.codex/config.toml",
            },
        },
        "persistence": {
            "enabled": True,
            "capture_corrections": False,
            "capture_command_errors": False,
            "max_candidate_chars": 500,
        },
        "injection": deepcopy(INJECTION_DEFAULTS),
    }


def validate_config(config: dict[str, Any]) -> None:
    if config.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            f"unsupported schema_version={config.get('schema_version')!r}; expected {SCHEMA_VERSION}"
        )
    for key in ("memory_root", "state_root", "agents", "persistence"):
        if key not in config:
            raise ValueError(f"missing config key: {key}")
    if not isinstance(config["agents"], dict) or not isinstance(config["persistence"], dict):
        raise ValueError("agents and persistence must be objects")
    injection = config.get("injection", INJECTION_DEFAULTS)
    if not isinstance(injection, dict):
        raise ValueError("injection must be an object")
    enabled = injection.get("include_verified_corrections", True)
    if not isinstance(enabled, bool):
        raise ValueError("injection.include_verified_corrections must be a boolean")
    for key, maximum in (("max_core_chars", 50000), ("max_verified_corrections", 200), ("max_verified_chars", 20000)):
        value = injection.get(key, INJECTION_DEFAULTS[key])
        if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= maximum:
            raise ValueError(f"injection.{key} must be an integer between 0 and {maximum}")


def with_defaults(config: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(config)
    injection = result.setdefault("injection", {})
    for key, value in INJECTION_DEFAULTS.items():
        injection.setdefault(key, value)
    return result


def load_config(path: Path | None = None) -> dict[str, Any]:
    config_path = path or default_config_path()
    data = json.loads(config_path.read_text(encoding="utf-8"))
    validate_config(data)
    return with_defaults(data)


def write_config(config: dict[str, Any], path: Path | None = None) -> Path:
    validate_config(config)
    config_path = path or default_config_path()
    atomic_write_json(config_path, config)
    return config_path


def resolved(config: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(config)
    for key in ("memory_root", "state_root"):
        result[key] = str(expand_path(result[key]))
    for agent in result["agents"].values():
        for key, value in tuple(agent.items()):
            if key.endswith(("_file", "_root")) and isinstance(value, str):
                agent[key] = str(expand_path(value))
    return result
