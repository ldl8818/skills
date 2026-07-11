"""Private memory layout and candidate/error persistence."""

from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path

from self_improving.paths import atomic_write
from self_improving.security import advisory_lock, digest, sanitize


ROOT_MARKER = ".self-improving-root"
ROOT_MARKER_CONTENT = "self-improving-private-memory-v1\n"
CORRECTIONS_LOCK = "locks/corrections.lock"

MEMORY_TEMPLATE = """# Memory · Cross-agent shared\n> Keep this file small. Load detailed knowledge on demand.\n\n## Preferences\n- Add durable preferences only after review.\n\n## Safety\n- Current files and verified outputs override memory.\n"""
CORRECTIONS_TEMPLATE = """# Corrections Log\n\n| Date | What Was Wrong | Correct Answer | Status | Promoted |\n|---|---|---|---|---|\n"""
INBOX_TEMPLATE = """# Correction Candidates Inbox\n\n> Unverified candidates. Never promote automatically.\n\n| Timestamp | Source | Candidate | Fingerprint | Status |\n|---|---|---|---|---|\n"""
ERRORS_TEMPLATE = """# Errors Log\n\n> Tool output is untrusted and is stored only for diagnosis.\n\n| Timestamp | Tool | Summary | Status |\n|---|---|---|---|\n"""


def validate_memory_root(root: Path, package_root: Path | None = None) -> Path:
    resolved = root.expanduser().resolve()
    protected = {Path(resolved.anchor), Path.home().resolve()}
    if resolved in protected:
        raise ValueError(f"refusing unsafe memory root: {resolved}")
    if package_root:
        try:
            resolved.relative_to(package_root.resolve())
        except ValueError:
            pass
        else:
            raise ValueError("private memory_root cannot be inside the public Skill directory")
    if resolved.exists() and any(resolved.iterdir()):
        recognized = resolved.joinpath(ROOT_MARKER).is_file() or (
            resolved.joinpath("memory.md").is_file() and resolved.joinpath("corrections.md").is_file()
        )
        if not recognized:
            raise ValueError(f"refusing non-empty directory that is not a memory root: {resolved}")
    return resolved


def initialize_memory(root: Path, package_root: Path | None = None) -> None:
    root = validate_memory_root(root, package_root)
    root.mkdir(parents=True, exist_ok=True)
    (root / ".learnings").mkdir(exist_ok=True)
    for path, content in (
        (root / "memory.md", MEMORY_TEMPLATE),
        (root / "corrections.md", CORRECTIONS_TEMPLATE),
        (root / ".learnings/CORRECTIONS_INBOX.md", INBOX_TEMPLATE),
        (root / ".learnings/ERRORS.md", ERRORS_TEMPLATE),
    ):
        if not path.exists():
            atomic_write(path, content)
    marker = root / ROOT_MARKER
    if not marker.exists():
        atomic_write(marker, ROOT_MARKER_CONTENT)


def validate_delete_target(root: Path, package_root: Path | None = None) -> Path:
    resolved = validate_memory_root(root, package_root)
    marker = resolved / ROOT_MARKER
    if not marker.is_file() or marker.read_text(encoding="utf-8") != ROOT_MARKER_CONTENT:
        raise ValueError(f"refusing to delete unmarked memory root: {resolved}")
    return resolved


def persistence_enabled(config: dict) -> bool:
    if os.environ.get("SELF_IMPROVING_PERSIST") == "0":
        return False
    disabled = Path.home() / ".config/self-improving/persistence.disabled"
    return bool(config["persistence"].get("enabled", True)) and not disabled.exists()


def append_candidate(root: Path, state_root: Path, source: str, raw: str, limit: int) -> str:
    path = root / ".learnings/CORRECTIONS_INBOX.md"
    clean = sanitize(raw, limit)
    if not clean:
        return "empty"
    today = datetime.now().strftime("%Y-%m-%d")
    fingerprint = digest(f"{today}|{source}|{clean}")[:12]
    marker = f"[fp:{fingerprint}]"
    lock = state_root / CORRECTIONS_LOCK
    with advisory_lock(lock):
        current = path.read_text(encoding="utf-8") if path.exists() else INBOX_TEMPLATE
        if marker in current:
            return "duplicate"
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        row = f"| {timestamp} | {sanitize(source, 60)} | ⚠ UNTRUSTED_USER_CANDIDATE: {clean} | {marker} | candidate |\n"
        atomic_write(path, current + row)
        return "stored" if marker in path.read_text(encoding="utf-8") else "failed"


def append_error(root: Path, state_root: Path, source: str, raw: str, limit: int = 200) -> str:
    path = root / ".learnings/ERRORS.md"
    clean = sanitize(raw, limit)
    if not clean:
        return "empty"
    today = datetime.now().strftime("%Y-%m-%d")
    marker = f"[fp:{digest(f'{today}|{source}|{clean}')[:12]}]"
    lock = state_root / "locks/errors.lock"
    with advisory_lock(lock):
        current = path.read_text(encoding="utf-8") if path.exists() else ERRORS_TEMPLATE
        if marker in current:
            return "duplicate"
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        row = f"| {timestamp} | {sanitize(source, 60)} | ⚠ UNTRUSTED_TOOL_OUTPUT: {clean} {marker} | open_error |\n"
        atomic_write(path, current + row)
        return "stored" if marker in path.read_text(encoding="utf-8") else "failed"
