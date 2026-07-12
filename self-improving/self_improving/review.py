"""Human review of correction candidates."""

from __future__ import annotations

from datetime import date
from pathlib import Path
import re

from self_improving.paths import atomic_write
from self_improving.security import advisory_lock, digest, sanitize
from self_improving.storage import CORRECTIONS_LOCK, append_verified_correction, normalize_scope, revoke_verified_correction


ROW = re.compile(r"^\| (?P<timestamp>[^|]+) \| (?P<source>[^|]+) \| (?P<candidate>.+) \| (?P<fingerprint>\[fp:[0-9a-f]{12}\]) \| (?P<status>[^|]+) \|$")
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
        }
        for row in rows
        if row["status"].strip() == "candidate"
    ]


def list_candidates(root: Path) -> list[str]:
    return [f"{entry['fingerprint']} | {entry['source']} | {entry['candidate']}" for entry in candidate_entries(root)]


def legacy_entries(root: Path) -> list[dict]:
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
            "line_number": line_number,
            "date": date_text,
            "status": parts[1],
            "preview": sanitize(raw.split("|", 2)[2], 180),
        })
    return entries


def list_legacy(root: Path) -> list[str]:
    return [
        f"{entry['legacy_id']} | L{entry['line_number']} | {entry['status']} | {entry['date']} | {entry['preview']}"
        for entry in legacy_entries(root)
    ]


def _validated_answer(correct: str) -> str:
    answer = sanitize(correct, 1200)
    if not answer:
        raise ValueError("correct answer is required")
    if "verified-corrections" in answer.lower():
        raise ValueError("correct answer cannot contain the injection wrapper name")
    return answer


def decide(root: Path, state_root: Path, fingerprint: str, action: str, correct: str = "", scope: str = "") -> str:
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
            scope = normalize_scope(scope)
            append_verified_correction(root, fingerprint, answer, scope, f"candidate:{fingerprint}")
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


def import_legacy(root: Path, state_root: Path, legacy_id: str, correct: str, scope: str) -> str:
    source = sanitize(legacy_id, 80)
    answer = _validated_answer(correct)
    if not source:
        raise ValueError("legacy id is required")
    if not STABLE_LEGACY_ID.fullmatch(source):
        raise ValueError("legacy id must come from review legacy-list")
    scope = normalize_scope(scope)
    fingerprint = f"[fp:{digest(f'verified|{source}')[:12]}]"
    with advisory_lock(state_root / CORRECTIONS_LOCK):
        if not any(entry["legacy_id"] == source for entry in legacy_entries(root)):
            raise ValueError("legacy row not found; refresh review legacy-list")
        append_verified_correction(root, fingerprint, answer, scope, source)
    return fingerprint
