"""Versioned user configuration without third-party dependencies."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from self_improving.paths import atomic_write_json, default_config_path, expand_path


SCHEMA_VERSION = 1


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


def load_config(path: Path | None = None) -> dict[str, Any]:
    config_path = path or default_config_path()
    data = json.loads(config_path.read_text(encoding="utf-8"))
    validate_config(data)
    return data


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
