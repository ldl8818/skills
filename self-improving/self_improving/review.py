"""Human review of correction candidates."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
import re

from self_improving.paths import atomic_write
from self_improving.security import advisory_lock, digest, sanitize
from self_improving.storage import (
    CORRECTIONS_LOCK,
    append_verified_correction,
    load_verified_records,
    normalize_scope,
    promote_verified_correction,
    revoke_verified_correction,
)


# The Match column (why capture fired) was added in 2.6.4; rows written before
# that have no such column, so the group stays optional and old inboxes keep parsing.
ROW = re.compile(r"^\| (?P<timestamp>[^|]+) \| (?P<source>[^|]+) \| (?P<candidate>.+?) \| (?:(?P<matched>[^|]*) \| )?(?P<fingerprint>\[fp:[0-9a-f]{12}\]) \| (?P<status>[^|]+) \|$")
STABLE_LEGACY_ID = re.compile(r"^legacy:[0-9a-f]{12}$")


def candidate_entries(root: Path) -> list[dict]:
    path = root / ".learnings/CORRECTIONS_INBOX.md"
    if not path.exists():
        return []
    rows = [match for line in path.read_text(encoding="utf-8").splitlines() if (match := ROW.match(line))]
    return [
        {
            "fingerprint": row["fingerprint"],
            "timestamp": row["timestamp"].strip(),
            "source": row["source"].strip(),
            "candidate": row["candidate"].strip(),
            "matched": (row["matched"] or "").strip(),
        }
        for row in rows
        if row["status"].strip() == "candidate"
    ]


def list_candidates(root: Path) -> list[str]:
    return [
        f"{entry['fingerprint']} | {entry['source']} | {entry['candidate']}"
        + (f" | 命中：{entry['matched']}" if entry["matched"] not in ("", "-") else "")
        for entry in candidate_entries(root)
    ]


def _markdown_legacy_entries(root: Path) -> list[dict]:
    path = root / "corrections.md"
    if not path.exists():
        return []
    entries: list[dict] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.startswith("| 20"):
            continue
        parts = [part.strip() for part in raw.rstrip().strip("|").rsplit("|", 2)]
        date_text = raw.split("|", 2)[1].strip()
        try:
            date.fromisoformat(date_text)
            valid_date = True
        except ValueError:
            valid_date = False
        system_audit = any(marker in parts[2] for marker in ("imported:[fp:", "legacy-import:[fp:", "revoked:[fp:")) if len(parts) == 3 else False
        if len(parts) != 3 or parts[1] not in {"active", "promoted"} or system_audit or not valid_date or not date_text.startswith("20"):
            continue
        entries.append({
            "legacy_id": f"legacy:{digest(raw)[:12]}",
            "origin": "markdown",
            "line_number": line_number,
            "date": date_text,
            "status": parts[1],
            "preview": sanitize(raw.split("|", 2)[2], 180),
        })
    return entries


def _verified_v1_legacy_entries(root: Path) -> list[dict]:
    records, malformed = load_verified_records(root)
    if malformed:
        raise ValueError("verified correction ledger is malformed")
    entries: list[dict] = []
    for record in records:
        if record["version"] != 1:
            continue
        fingerprint = record["fingerprint"]
        entries.append({
            "legacy_id": f"legacy:{digest(f'verified-v1|{fingerprint}')[:12]}",
            "origin": "verified-v1",
            "fingerprint": fingerprint,
            "line_number": None,
            "date": record["_approved_utc"].date().isoformat(),
            "status": "approved-v1",
            "preview": sanitize(record["answer"], 180),
        })
    return entries


def legacy_entries(root: Path) -> list[dict]:
    return _markdown_legacy_entries(root) + _verified_v1_legacy_entries(root)


def list_legacy(root: Path) -> list[str]:
    rows = []
    for entry in legacy_entries(root):
        location = f"L{entry['line_number']}" if entry["origin"] == "markdown" else "verified-v1.jsonl"
        rows.append(
            f"{entry['legacy_id']} | {location} | {entry['status']} | {entry['date']} | {entry['preview']}"
        )
    return rows


def lifecycle_entries(root: Path, *, now: datetime | None = None) -> list[dict]:
    records, malformed = load_verified_records(root)
    if malformed:
        raise ValueError("verified correction ledger is malformed")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    rows: list[dict] = []
    for record in records:
        if record["version"] != 2:
            continue
        review_at = record["_review_utc"]
        expires_at = record["_expires_utc"]
        status = "expired" if expires_at <= current else "due" if review_at <= current else "active"
        rows.append({
            "fingerprint": record["fingerprint"],
            "status": status,
            "priority": record["priority"],
            "scope": record["scope"],
            "review_at": review_at.isoformat(timespec="seconds"),
            "expires_at": expires_at.isoformat(timespec="seconds"),
            "promotion_target": record["promotion_target"],
            "answer": record["answer"],
        })
    return rows


def list_lifecycle(root: Path) -> list[str]:
    return [
        f"{entry['fingerprint']} | {entry['status']} | {entry['priority']} | {entry['scope']} | "
        f"复核 {entry['review_at']} | 失效 {entry['expires_at']} | 归位 {entry['promotion_target']} | "
        f"{sanitize(entry['answer'], 180)}"
        for entry in lifecycle_entries(root)
    ]


def _validated_answer(correct: str) -> str:
    answer = sanitize(correct, 1200)
    if not answer:
        raise ValueError("correct answer is required")
    if "verified-corrections" in answer.lower():
        raise ValueError("correct answer cannot contain the injection wrapper name")
    return answer


def decide(
    root: Path,
    state_root: Path,
    fingerprint: str,
    action: str,
    correct: str = "",
    scope: str = "",
    *,
    priority: str = "normal",
    promotion_target: str = "temporary",
    review_after_days: int = 30,
    expires_after_days: int = 90,
) -> str:
    inbox = root / ".learnings/CORRECTIONS_INBOX.md"
    with advisory_lock(state_root / CORRECTIONS_LOCK):
        text = inbox.read_text(encoding="utf-8")
        selected = next((match for line in text.splitlines() if (match := ROW.match(line)) and match["fingerprint"] == fingerprint), None)
        if selected is None or selected["status"].strip() != "candidate":
            raise ValueError("candidate not found or already handled")
        status = "imported" if action == "approve" else "rejected"
        old = selected.group(0)
        new = old.rsplit("| candidate |", 1)[0] + f"| {status} |"
        if action == "approve":
            answer = _validated_answer(correct)
            scope = normalize_scope(scope, allow_resolved_repo=False)
            append_verified_correction(
                root,
                fingerprint,
                answer,
                scope,
                f"candidate:{fingerprint}",
                priority=priority,
                promotion_target=promotion_target,
                review_after_days=review_after_days,
                expires_after_days=expires_after_days,
            )
        try:
            atomic_write(inbox, text.replace(old, new, 1))
        except OSError as exc:
            if action == "approve":
                raise OSError("approval is active, but inbox status update failed; retry the same approval to repair it") from exc
            raise
        return status


def revoke(root: Path, state_root: Path, fingerprint: str) -> str:
    with advisory_lock(state_root / CORRECTIONS_LOCK):
        if not revoke_verified_correction(root, fingerprint):
            raise ValueError("verified correction not found")
    return "revoked"


def promote(root: Path, state_root: Path, fingerprint: str) -> str:
    with advisory_lock(state_root / CORRECTIONS_LOCK):
        target = promote_verified_correction(root, fingerprint)
    return f"promoted:{target}"


def import_legacy(
    root: Path,
    state_root: Path,
    legacy_id: str,
    correct: str,
    scope: str,
    *,
    priority: str = "normal",
    promotion_target: str = "temporary",
    review_after_days: int = 30,
    expires_after_days: int = 90,
) -> str:
    source = sanitize(legacy_id, 80)
    answer = _validated_answer(correct)
    if not source:
        raise ValueError("legacy id is required")
    if not STABLE_LEGACY_ID.fullmatch(source):
        raise ValueError("legacy id must come from review legacy-list")
    scope = normalize_scope(scope, allow_resolved_repo=False)
    fingerprint = f"[fp:{digest(f'verified|{source}')[:12]}]"
    with advisory_lock(state_root / CORRECTIONS_LOCK):
        selected = next((entry for entry in legacy_entries(root) if entry["legacy_id"] == source), None)
        if selected is None:
            raise ValueError("legacy row not found; refresh review legacy-list")
        append_verified_correction(
            root,
            fingerprint,
            answer,
            scope,
            source,
            priority=priority,
            promotion_target=promotion_target,
            review_after_days=review_after_days,
            expires_after_days=expires_after_days,
        )
        if selected["origin"] == "verified-v1":
            revoke_verified_correction(root, selected["fingerprint"])
    return fingerprint
