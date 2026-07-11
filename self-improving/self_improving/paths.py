"""Path expansion and atomic file helpers."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Any
import sysconfig


SOURCE_ROOT = Path(__file__).resolve().parents[1]
INSTALLED_SKILL_ROOT = Path(sysconfig.get_path("data")) / "self_improving_skill"
PACKAGE_ROOT = SOURCE_ROOT if SOURCE_ROOT.joinpath("SKILL.md").is_file() else INSTALLED_SKILL_ROOT


def expand_path(value: str | os.PathLike[str]) -> Path:
    return Path(os.path.expandvars(os.fspath(value))).expanduser().resolve()


def default_config_path() -> Path:
    override = os.environ.get("SELF_IMPROVING_CONFIG")
    if override:
        return expand_path(override)
    return Path.home() / ".config/self-improving/config.json"


def atomic_write(path: Path, content: str, *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp = Path(temp_name)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def atomic_write_json(path: Path, payload: Any) -> None:
    atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
