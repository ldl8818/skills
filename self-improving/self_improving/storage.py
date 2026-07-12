"""Private memory layout and candidate/error persistence."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re

from self_improving.paths import atomic_write
from self_improving.security import advisory_lock, contains_secret, digest, sanitize


ROOT_MARKER = ".self-improving-root"
ROOT_MARKER_CONTENT = "self-improving-private-memory-v1\n"
CORRECTIONS_LOCK = "locks/corrections.lock"
VERIFIED_RELATIVE = ".self-improving/verified-corrections.jsonl"
FINGERPRINT = re.compile(r"^\[fp:[0-9a-f]{12}\]$")

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
    (root / ".self-improving").mkdir(exist_ok=True)
    for path, content in (
        (root / "memory.md", MEMORY_TEMPLATE),
        (root / "corrections.md", CORRECTIONS_TEMPLATE),
        (root / ".learnings/CORRECTIONS_INBOX.md", INBOX_TEMPLATE),
        (root / ".learnings/ERRORS.md", ERRORS_TEMPLATE),
        (root / VERIFIED_RELATIVE, ""),
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


def pending_correction_count(root: Path) -> int:
    path = root / ".learnings/CORRECTIONS_INBOX.md"
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.rstrip().endswith("| candidate |"))


def load_verified_records(root: Path) -> tuple[list[dict], int]:
    """Fold the append-only approval event ledger into current active records."""
    path = root / VERIFIED_RELATIVE
    if not path.exists():
        return [], 0
    active: dict[str, dict] = {}
    active_sources: dict[str, str] = {}
    malformed = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            malformed += 1
            continue
        if not isinstance(record, dict):
            malformed += 1
            continue
        event = record.get("event", "approve")
        event_at_text = record.get("event_at", record.get("approved_at", ""))
        try:
            event_at = datetime.fromisoformat(event_at_text)
        except (TypeError, ValueError):
            event_at = None
        fingerprint = record.get("fingerprint", "")
        common_valid = (record.get("version") == 1 and isinstance(event, str) and event in {"approve", "revoke"}
                        and isinstance(event_at_text, str) and event_at is not None and event_at.tzinfo is not None
                        and isinstance(fingerprint, str) and FINGERPRINT.fullmatch(fingerprint))
        if not common_valid:
            malformed += 1
            continue
        if event == "revoke":
            current = active.pop(fingerprint, None)
            if current is None:
                malformed += 1
                continue
            source_id = current.get("source_id")
            if source_id:
                active_sources.pop(source_id, None)
            continue

        required = isinstance(record.get("answer"), str) and isinstance(record.get("scope"), str)
        scope = record.get("scope", "")
        scope_valid = scope == "global"
        if isinstance(scope, str) and scope.startswith("project:/"):
            project = Path(scope.removeprefix("project:"))
            scope_valid = (project.is_absolute() and project != Path(project.anchor)
                           and scope == f"project:{project.expanduser().resolve()}")
        source_id = record.get("source_id", f"candidate:{fingerprint}")
        if (not required or not isinstance(source_id, str) or not source_id.strip()
                or fingerprint in active or source_id in active_sources or not scope_valid or not record.get("answer", "").strip()
                or "verified-corrections" in record.get("answer", "").lower() or contains_secret(record.get("answer", ""))):
            malformed += 1
            continue
        normalized = dict(record)
        normalized["event"] = "approve"
        normalized["event_at"] = event_at_text
        normalized["source_id"] = source_id
        normalized["_approved_utc"] = event_at.astimezone(timezone.utc)
        active[fingerprint] = normalized
        active_sources[source_id] = fingerprint
    records = list(active.values())
    records.sort(key=lambda item: item["_approved_utc"], reverse=True)
    return records, malformed


def append_verified_correction(root: Path, fingerprint: str, answer: str, scope: str, source_id: str | None = None) -> bool:
    if not FINGERPRINT.fullmatch(fingerprint):
        raise ValueError("invalid correction fingerprint")
    scope = normalize_scope(scope)
    path = root / VERIFIED_RELATIVE
    current = path.read_text(encoding="utf-8") if path.exists() else ""
    records, malformed = load_verified_records(root)
    if malformed:
        raise ValueError("verified correction ledger is malformed")
    source_id = source_id or f"candidate:{fingerprint}"
    for existing in records:
        if existing["fingerprint"] == fingerprint or existing.get("source_id") == source_id:
            same = existing["fingerprint"] == fingerprint and existing["answer"] == answer and existing["scope"] == scope and existing.get("source_id") == source_id
            if same:
                return False
            raise ValueError("an active rule already exists for this source; revoke it before changing answer or scope")
    record = {
        "version": 1,
        "event": "approve",
        "event_at": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
        "fingerprint": fingerprint,
        "answer": answer,
        "scope": scope,
        "source_id": source_id,
    }
    atomic_write(path, current + json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    return True


def normalize_scope(scope: str, *, require_project: bool = True) -> str:
    if scope == "global":
        return scope
    if not scope.startswith("project:"):
        raise ValueError("scope must be global or project:/absolute/path")
    raw = Path(scope.removeprefix("project:")).expanduser()
    if not raw.is_absolute():
        raise ValueError("project scope must use an absolute path")
    project = raw.resolve()
    if project == Path(project.anchor):
        raise ValueError("project scope cannot be filesystem root")
    if require_project and not project.is_dir():
        raise ValueError(f"project scope directory does not exist: {project}")
    return f"project:{project}"


def revoke_verified_correction(root: Path, fingerprint: str) -> bool:
    if not FINGERPRINT.fullmatch(fingerprint):
        raise ValueError("invalid correction fingerprint")
    path = root / VERIFIED_RELATIVE
    if not path.exists():
        return False
    current = path.read_text(encoding="utf-8")
    records, malformed = load_verified_records(root)
    if malformed:
        raise ValueError("verified correction ledger is malformed")
    if not any(record["fingerprint"] == fingerprint for record in records):
        return False
    event = {
        "version": 1,
        "event": "revoke",
        "event_at": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
        "fingerprint": fingerprint,
    }
    atomic_write(path, current + json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
    return True


def _scope_applies(scope: str, cwd: str | None) -> bool:
    if scope == "global":
        return True
    if not cwd or not scope.startswith("project:"):
        return False
    try:
        current = Path(cwd).expanduser().resolve()
        project = Path(scope.removeprefix("project:")).expanduser().resolve()
        return current == project or project in current.parents
    except OSError:
        return False


def active_corrections(root: Path, cwd: str | None = None) -> list[str]:
    records, malformed = load_verified_records(root)
    if malformed:
        return []
    return [record["answer"] for record in records if _scope_applies(record["scope"], cwd)]


def verified_corrections(root: Path, max_count: int, max_chars: int, cwd: str | None = None) -> list[str]:
    """Select approved answers within deterministic count and character budgets."""
    if max_count <= 0 or max_chars <= 0:
        return []
    selected: list[str] = []
    seen: set[str] = set()
    used = 0
    for answer in active_corrections(root, cwd):
        if answer in seen or len(answer) > max_chars - used:
            continue
        selected.append(answer)
        seen.add(answer)
        used += len(answer)
        if len(selected) >= max_count:
            break
    return selected


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
