"""Private memory layout and candidate/error persistence."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import re
import subprocess
from zoneinfo import ZoneInfo

from self_improving.paths import atomic_write
from self_improving.security import advisory_lock, contains_secret, digest, sanitize


ROOT_MARKER = ".self-improving-root"
ROOT_MARKER_CONTENT = "self-improving-private-memory-v1\n"
CORRECTIONS_LOCK = "locks/corrections.lock"
VERIFIED_RELATIVE = ".self-improving/verified-corrections.jsonl"
FINGERPRINT = re.compile(r"^\[fp:[0-9a-f]{12}\]$")
REPO_SCOPE = re.compile(r"^repo:[0-9a-f]{16}$")
VERIFIED_VERSION = 2
PRIORITIES = {"critical", "normal"}
BEIJING = ZoneInfo("Asia/Shanghai")

MEMORY_TEMPLATE = """# Memory · Cross-agent shared\n> Keep this file small. Load detailed knowledge on demand.\n\n## Preferences\n- Add durable preferences only after review.\n\n## Safety\n- Current files and verified outputs override memory.\n"""
CORRECTIONS_TEMPLATE = """# Corrections Log\n\n| Date | What Was Wrong | Correct Answer | Status | Promoted |\n|---|---|---|---|---|\n"""
INBOX_TEMPLATE = """# Correction Candidates Inbox\n\n> Unverified candidates. Never promote automatically.\n\n| Timestamp | Source | Candidate | Match | Fingerprint | Status |\n|---|---|---|---|---|---|\n"""
ERRORS_TEMPLATE = """# Errors Log\n\n> Tool output is untrusted and is stored only for diagnosis.\n\n| Timestamp | Tool | Summary | Status |\n|---|---|---|---|\n"""


@dataclass(frozen=True)
class CorrectionSelection:
    answers: tuple[str, ...]
    applicable: int
    omitted: int
    expired: int
    due: int
    legacy_ignored: int
    malformed: int
    estimated_tokens: int


def estimate_tokens(value: str) -> int:
    """Conservative dependency-free estimate for mixed Chinese and English context."""
    non_ascii = sum(1 for char in value if ord(char) > 127)
    return non_ascii + math.ceil((len(value) - non_ascii) / 4)


VERIFIED_NOTICE = "以下内容已经人工审核；当前文件和可验证证据与其冲突时，以当前证据为准。"
RECEIPT_RESERVE_TEXT = (
    '<self-improving-receipt core="budget_omitted" omitted="999+" expired="999+" '
    'due="999+" legacy_ignored="999+" malformed="999+"/>'
)
RECEIPT_RESERVE_TOKENS = estimate_tokens(RECEIPT_RESERVE_TEXT)
SESSION_UPDATE_RESERVE_TEXT = "<self-improving-prior-injection-invalidated/>\n"
SESSION_UPDATE_RESERVE_TOKENS = estimate_tokens(SESSION_UPDATE_RESERVE_TEXT)


def render_verified_corrections(answers: tuple[str, ...] | list[str]) -> str:
    rows = "\n".join(f"- {answer}" for answer in answers)
    middle = f"{VERIFIED_NOTICE}\n{rows}" if rows else VERIFIED_NOTICE
    return f"<verified-corrections>\n{middle}\n</verified-corrections>"


VERIFIED_WRAPPER_TOKENS = estimate_tokens(render_verified_corrections(()))


def _display_timestamp() -> str:
    return datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M")


def _repo_identity(path: Path) -> str | None:
    """Return one stable id for a repository and all of its linked worktrees."""
    try:
        top = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
            text=True,
            capture_output=True,
            check=True,
            timeout=2,
        ).stdout.strip()
        remote = subprocess.run(
            ["git", "-C", top, "config", "--get", "remote.origin.url"],
            text=True,
            capture_output=True,
            check=False,
            timeout=2,
        ).stdout.strip()
        if remote:
            identity = "remote:" + remote.removesuffix(".git")
        else:
            raw_common = subprocess.run(
                ["git", "-C", top, "rev-parse", "--git-common-dir"],
                text=True,
                capture_output=True,
                check=True,
                timeout=2,
            ).stdout.strip()
            common = Path(raw_common)
            if not common.is_absolute():
                common = Path(top) / common
            identity = "common:" + str(common.resolve())
        return digest(identity)[:16]
    except (OSError, subprocess.SubprocessError):
        return None


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
        version = record.get("version")
        common_valid = (version in {1, VERIFIED_VERSION} and isinstance(event, str) and event in {"approve", "revoke", "promote"}
                        and isinstance(event_at_text, str) and event_at is not None and event_at.tzinfo is not None
                        and isinstance(fingerprint, str) and FINGERPRINT.fullmatch(fingerprint))
        if not common_valid:
            malformed += 1
            continue
        if event in {"revoke", "promote"}:
            current = active.pop(fingerprint, None)
            if current is None:
                malformed += 1
                continue
            if event == "promote" and record.get("promotion_target") != current.get("promotion_target"):
                malformed += 1
                active[fingerprint] = current
                continue
            source_id = current.get("source_id")
            if source_id:
                active_sources.pop(source_id, None)
            continue

        required = isinstance(record.get("answer"), str) and isinstance(record.get("scope"), str)
        scope = record.get("scope", "")
        try:
            scope_valid = normalize_scope(scope, require_project=False) == scope
        except (OSError, ValueError):
            scope_valid = False
        priority = record.get("priority", "normal")
        promotion_target = record.get("promotion_target", "legacy" if version == 1 else "")
        review_at = None
        expires_at = None
        lifecycle_valid = True
        if version == VERIFIED_VERSION:
            try:
                review_at = datetime.fromisoformat(record.get("review_at", ""))
                expires_at = datetime.fromisoformat(record.get("expires_at", ""))
                lifecycle_valid = (
                    review_at.tzinfo is not None
                    and expires_at.tzinfo is not None
                    and event_at < review_at < expires_at
                    and priority in PRIORITIES
                    and isinstance(promotion_target, str)
                    and bool(promotion_target.strip())
                )
            except (TypeError, ValueError):
                lifecycle_valid = False
        source_id = record.get("source_id", f"candidate:{fingerprint}")
        if (not required or not isinstance(source_id, str) or not source_id.strip()
                or fingerprint in active or source_id in active_sources or not scope_valid or not lifecycle_valid
                or not record.get("answer", "").strip()
                or "verified-corrections" in record.get("answer", "").lower() or contains_secret(record.get("answer", ""))):
            malformed += 1
            continue
        normalized = dict(record)
        normalized["event"] = "approve"
        normalized["event_at"] = event_at_text
        normalized["source_id"] = source_id
        normalized["priority"] = priority
        normalized["promotion_target"] = promotion_target
        normalized["_approved_utc"] = event_at.astimezone(timezone.utc)
        normalized["_review_utc"] = review_at.astimezone(timezone.utc) if review_at else None
        normalized["_expires_utc"] = expires_at.astimezone(timezone.utc) if expires_at else None
        active[fingerprint] = normalized
        active_sources[source_id] = fingerprint
    records = list(active.values())
    records.sort(key=lambda item: item["_approved_utc"], reverse=True)
    return records, malformed


def append_verified_correction(
    root: Path,
    fingerprint: str,
    answer: str,
    scope: str,
    source_id: str | None = None,
    *,
    priority: str = "normal",
    promotion_target: str = "temporary",
    review_after_days: int = 30,
    expires_after_days: int = 90,
) -> bool:
    if not FINGERPRINT.fullmatch(fingerprint):
        raise ValueError("invalid correction fingerprint")
    scope = normalize_scope(scope)
    if priority not in PRIORITIES:
        raise ValueError("priority must be critical or normal")
    promotion_target = sanitize(promotion_target, 160)
    if not promotion_target:
        raise ValueError("promotion target is required")
    if not 1 <= review_after_days < expires_after_days <= 3650:
        raise ValueError("lifecycle days must satisfy 1 <= review < expiry <= 3650")
    path = root / VERIFIED_RELATIVE
    current = path.read_text(encoding="utf-8") if path.exists() else ""
    records, malformed = load_verified_records(root)
    if malformed:
        raise ValueError("verified correction ledger is malformed")
    source_id = source_id or f"candidate:{fingerprint}"
    for existing in records:
        if existing["fingerprint"] == fingerprint or existing.get("source_id") == source_id:
            same = (
                existing["fingerprint"] == fingerprint
                and existing["answer"] == answer
                and existing["scope"] == scope
                and existing.get("source_id") == source_id
                and existing.get("priority") == priority
                and existing.get("promotion_target") == promotion_target
                and round((existing["_review_utc"] - existing["_approved_utc"]).total_seconds() / 86400) == review_after_days
                and round((existing["_expires_utc"] - existing["_approved_utc"]).total_seconds() / 86400) == expires_after_days
            )
            if same:
                return False
            raise ValueError("an active rule already exists for this source; revoke it before changing answer or scope")
    approved_at = datetime.now(timezone.utc)
    record = {
        "version": VERIFIED_VERSION,
        "event": "approve",
        "event_at": approved_at.isoformat(timespec="microseconds"),
        "fingerprint": fingerprint,
        "answer": answer,
        "scope": scope,
        "source_id": source_id,
        "priority": priority,
        "promotion_target": promotion_target,
        "review_at": (approved_at + timedelta(days=review_after_days)).isoformat(timespec="seconds"),
        "expires_at": (approved_at + timedelta(days=expires_after_days)).isoformat(timespec="seconds"),
    }
    atomic_write(path, current + json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    return True


def normalize_scope(
    scope: str,
    *,
    require_project: bool = True,
    allow_resolved_repo: bool = True,
) -> str:
    if scope == "global":
        return scope
    if REPO_SCOPE.fullmatch(scope):
        if allow_resolved_repo:
            return scope
        raise ValueError("repo scope must use an existing absolute repository path")
    if scope.startswith("repo:"):
        raw = Path(scope.removeprefix("repo:")).expanduser()
        if not raw.is_absolute() or not raw.is_dir():
            raise ValueError("repo scope must use an existing absolute repository path")
        identity = _repo_identity(raw.resolve())
        if not identity:
            raise ValueError(f"repo scope path is not a git repository: {raw}")
        return f"repo:{identity}"
    if not scope.startswith("project:"):
        raise ValueError("scope must be global, project:/absolute/path, or repo:/absolute/repository")
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
        "version": VERIFIED_VERSION,
        "event": "revoke",
        "event_at": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
        "fingerprint": fingerprint,
    }
    atomic_write(path, current + json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
    return True


def promote_verified_correction(root: Path, fingerprint: str) -> str:
    """Stop injecting one rule after its formal target has been updated."""
    if not FINGERPRINT.fullmatch(fingerprint):
        raise ValueError("invalid correction fingerprint")
    path = root / VERIFIED_RELATIVE
    if not path.exists():
        raise ValueError("verified correction not found")
    current = path.read_text(encoding="utf-8")
    records, malformed = load_verified_records(root)
    if malformed:
        raise ValueError("verified correction ledger is malformed")
    record = next((item for item in records if item["fingerprint"] == fingerprint), None)
    if record is None:
        raise ValueError("verified correction not found")
    event = {
        "version": VERIFIED_VERSION,
        "event": "promote",
        "event_at": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
        "fingerprint": fingerprint,
        "promotion_target": record["promotion_target"],
    }
    atomic_write(path, current + json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
    return record["promotion_target"]


def _scope_applies(scope: str, cwd: str | None, repo_identity: str | None = None) -> bool:
    if scope == "global":
        return True
    if not cwd:
        return False
    try:
        current = Path(cwd).expanduser().resolve()
        if scope.startswith("repo:"):
            return repo_identity == scope.removeprefix("repo:")
        if not scope.startswith("project:"):
            return False
        project = Path(scope.removeprefix("project:")).expanduser().resolve()
        return current == project or project in current.parents
    except OSError:
        return False


def _active_records(
    root: Path,
    cwd: str | None = None,
    *,
    min_version: int = 1,
    now: datetime | None = None,
    all_scopes: bool = False,
) -> tuple[list[dict], int, int, int]:
    records, malformed = load_verified_records(root)
    if malformed:
        return [], malformed, 0, 0
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    repo_identity = None
    if not all_scopes and cwd and any(record["scope"].startswith("repo:") for record in records):
        try:
            repo_identity = _repo_identity(Path(cwd).expanduser().resolve())
        except OSError:
            repo_identity = None
    scoped = (
        records
        if all_scopes
        else [
            record
            for record in records
            if _scope_applies(record["scope"], cwd, repo_identity)
        ]
    )
    legacy_ignored = sum(1 for record in scoped if int(record["version"]) < min_version)
    eligible = [record for record in scoped if int(record["version"]) >= min_version]
    expired = sum(
        1 for record in eligible
        if record.get("_expires_utc") is not None and record["_expires_utc"] <= current
    )
    active = [
        record for record in eligible
        if record.get("_expires_utc") is None or record["_expires_utc"] > current
    ]
    active.sort(
        key=lambda record: (
            0 if record.get("priority") == "critical" else 1,
            -record["_approved_utc"].timestamp(),
        )
    )
    return active, malformed, legacy_ignored, expired


def active_corrections(root: Path, cwd: str | None = None, *, min_version: int = 1) -> list[str]:
    records, malformed, _, _ = _active_records(root, cwd, min_version=min_version)
    if malformed:
        return []
    return [record["answer"] for record in records]


def correction_selection(
    root: Path,
    max_count: int,
    max_chars: int,
    max_tokens: int,
    cwd: str | None = None,
    *,
    min_version: int = 1,
    now: datetime | None = None,
    all_scopes: bool = False,
) -> CorrectionSelection:
    records, malformed, legacy_ignored, expired = _active_records(
        root, cwd, min_version=min_version, now=now, all_scopes=all_scopes
    )
    if malformed or max_count <= 0 or max_chars <= 0 or max_tokens <= 0:
        return CorrectionSelection((), len(records), len(records), expired, 0, legacy_ignored, malformed, 0)
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    due = sum(
        1 for record in records
        if record.get("_review_utc") is not None and record["_review_utc"] <= current
    )
    answers: list[str] = []
    seen: set[str] = set()
    used_chars = 0
    used_tokens = 0
    for record in records:
        answer = record["answer"]
        cost = estimate_tokens(f"- {answer}\n")
        if (
            answer in seen
            or len(answers) >= max_count
            or len(answer) > max_chars - used_chars
            or cost > max_tokens - used_tokens
        ):
            continue
        answers.append(answer)
        seen.add(answer)
        used_chars += len(answer)
        used_tokens += cost
    return CorrectionSelection(
        tuple(answers), len(records), len(records) - len(answers), expired, due,
        legacy_ignored, malformed, used_tokens,
    )


def verified_corrections(root: Path, max_count: int, max_chars: int, cwd: str | None = None) -> list[str]:
    """Select approved answers within deterministic count and character budgets."""
    return list(correction_selection(
        root, max_count, max_chars, 1000000, cwd, min_version=1
    ).answers)


def append_candidate(root: Path, state_root: Path, source: str, raw: str, limit: int, matched: str = "") -> str:
    """Store one untrusted candidate.

    `matched` records why capture fired (the keyword plus a short window around
    it). Keyword matching runs on the full prompt while `raw` is truncated, so
    without it a reviewer can face a candidate whose trigger is not visible in
    the stored text. It stays out of the fingerprint: the same sentence must
    deduplicate regardless of which keyword happened to match.
    """
    path = root / ".learnings/CORRECTIONS_INBOX.md"
    clean = sanitize(raw, limit)
    if not clean:
        return "empty"
    today = datetime.now(BEIJING).strftime("%Y-%m-%d")
    fingerprint = digest(f"{today}|{source}|{clean}")[:12]
    marker = f"[fp:{fingerprint}]"
    lock = state_root / CORRECTIONS_LOCK
    with advisory_lock(lock):
        current = path.read_text(encoding="utf-8") if path.exists() else INBOX_TEMPLATE
        if marker in current:
            return "duplicate"
        timestamp = _display_timestamp()
        row = f"| {timestamp} | {sanitize(source, 60)} | ⚠ UNTRUSTED_USER_CANDIDATE: {clean} | {sanitize(matched, 80) or '-'} | {marker} | candidate |\n"
        atomic_write(path, current + row)
        return "stored" if marker in path.read_text(encoding="utf-8") else "failed"


def append_error(
    root: Path,
    state_root: Path,
    source: str,
    raw: str,
    limit: int = 200,
    max_entries: int = 200,
) -> str:
    path = root / ".learnings/ERRORS.md"
    clean = sanitize(raw, limit)
    if not clean:
        return "empty"
    today = datetime.now(BEIJING).strftime("%Y-%m-%d")
    marker = f"[fp:{digest(f'{today}|{source}|{clean}')[:12]}]"
    lock = state_root / "locks/errors.lock"
    with advisory_lock(lock):
        current = path.read_text(encoding="utf-8") if path.exists() else ERRORS_TEMPLATE
        if marker in current:
            return "duplicate"
        timestamp = _display_timestamp()
        row = f"| {timestamp} | {sanitize(source, 60)} | ⚠ UNTRUSTED_TOOL_OUTPUT: {clean} {marker} | open_error |\n"
        rows = [line + "\n" for line in current.splitlines() if line.startswith("| 20")]
        kept = (rows + [row])[-max_entries:] if max_entries > 0 else []
        atomic_write(path, ERRORS_TEMPLATE + "".join(kept))
        return "stored" if marker in path.read_text(encoding="utf-8") else "failed"
