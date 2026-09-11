"""Versioned user configuration without third-party dependencies."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from self_improving.paths import atomic_write_json, default_config_path, expand_path


SCHEMA_VERSION = 1


INJECTION_DEFAULTS = {
    "include_core_memory": False,
    "include_verified_corrections": True,
    "resume_mode": "skip",
    "max_total_tokens": 1200,
    "min_verified_version": 2,
    "review_reminder_interval_hours": 24,
    "max_core_chars": 8000,
    "max_verified_corrections": 20,
    "max_verified_chars": 4000,
}

PERSISTENCE_DEFAULTS = {
    "enabled": True,
    "capture_corrections": False,
    "capture_command_errors": False,
    "max_candidate_chars": 500,
    "max_error_entries": 200,
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
        "persistence": deepcopy(PERSISTENCE_DEFAULTS),
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
    for key in ("include_core_memory", "include_verified_corrections"):
        if not isinstance(injection.get(key, INJECTION_DEFAULTS[key]), bool):
            raise ValueError(f"injection.{key} must be a boolean")
    if injection.get("resume_mode", INJECTION_DEFAULTS["resume_mode"]) not in {"skip", "always"}:
        raise ValueError("injection.resume_mode must be skip or always")
    for key, minimum, maximum in (
        ("max_total_tokens", 0, 20000),
        ("min_verified_version", 1, 2),
        ("review_reminder_interval_hours", 0, 24 * 30),
        ("max_core_chars", 0, 50000),
        ("max_verified_corrections", 0, 200),
        ("max_verified_chars", 0, 20000),
    ):
        value = injection.get(key, INJECTION_DEFAULTS[key])
        if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
            raise ValueError(f"injection.{key} must be an integer between {minimum} and {maximum}")
    persistence = config["persistence"]
    for key in ("enabled", "capture_corrections", "capture_command_errors"):
        if not isinstance(persistence.get(key, PERSISTENCE_DEFAULTS[key]), bool):
            raise ValueError(f"persistence.{key} must be a boolean")
    for key, maximum in (("max_candidate_chars", 5000), ("max_error_entries", 5000)):
        value = persistence.get(key, PERSISTENCE_DEFAULTS[key])
        if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= maximum:
            raise ValueError(f"persistence.{key} must be an integer between 0 and {maximum}")


def with_defaults(config: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(config)
    persistence = result.setdefault("persistence", {})
    for key, value in PERSISTENCE_DEFAULTS.items():
        persistence.setdefault(key, value)
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
