"""Legacy layout discovery, manifest creation and rollback metadata."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from self_improving.paths import atomic_write_json


LEGACY_SCRIPTS = (
    "capture-correction.sh",
    "cluster-corrections.sh",
    "generate-memory-index.py",
    "memory-doctor.sh",
    "review-correction-inbox.py",
    "scan-memory-secrets.py",
    "stop-reflexion.sh",
    "sync-memory.sh",
    "validate-memory-source.py",
)


def discover_legacy(home: Path | None = None) -> dict[str, Any]:
    home = home or Path.home()
    roots = [
        home / "Documents/obsidian/self-improving-memory",
        home / "Documents/self-improving-memory",
    ]
    memory_root = next((path for path in roots if path.joinpath("memory.md").exists()), None)
    scripts = [home / ".claude/scripts" / name for name in LEGACY_SCRIPTS]
    return {
        "memory_root": str(memory_root) if memory_root else None,
        "legacy_scripts": [str(path) for path in scripts if path.exists()],
        "claude_settings": str(home / ".claude/settings.json"),
        "codex_hooks": str(home / ".codex/hooks.json"),
    }


def write_manifest(state_root: Path, discovery: dict[str, Any], config_path: Path) -> Path:
    path = state_root / "migrations" / f"legacy-{datetime.now():%Y%m%d-%H%M%S}.json"
    payload = {
        "schema_version": 1,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "discovery": discovery,
        "config_path": str(config_path),
        "rollback": "self-improving uninstall --keep-data",
    }
    atomic_write_json(path, payload)
    return path
