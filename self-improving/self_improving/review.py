"""Human review of correction candidates."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re

from self_improving.paths import atomic_write
from self_improving.security import advisory_lock, sanitize
from self_improving.storage import CORRECTIONS_LOCK, append_verified_correction, normalize_scope, revoke_verified_correction


ROW = re.compile(r"^\| (?P<timestamp>[^|]+) \| (?P<source>[^|]+) \| (?P<candidate>.+) \| (?P<fingerprint>\[fp:[0-9a-f]{12}\]) \| (?P<status>[^|]+) \|$")


def list_candidates(root: Path) -> list[str]:
    path = root / ".learnings/CORRECTIONS_INBOX.md"
    if not path.exists():
        return []
    rows = [match for line in path.read_text(encoding="utf-8").splitlines() if (match := ROW.match(line))]
    return [f"{row['fingerprint']} | {row['source'].strip()} | {row['candidate'].strip()}" for row in rows if row["status"].strip() == "candidate"]


def decide(root: Path, state_root: Path, fingerprint: str, action: str, correct: str = "", scope: str = "") -> str:
    inbox = root / ".learnings/CORRECTIONS_INBOX.md"
    corrections = root / "corrections.md"
    with advisory_lock(state_root / CORRECTIONS_LOCK):
        text = inbox.read_text(encoding="utf-8")
        selected = next((match for line in text.splitlines() if (match := ROW.match(line)) and match["fingerprint"] == fingerprint), None)
        if selected is None or selected["status"].strip() != "candidate":
            raise ValueError("candidate not found or already handled")
        status = "imported" if action == "approve" else "rejected"
        old = selected.group(0)
        new = old.rsplit("| candidate |", 1)[0] + f"| {status} |"
        if action == "approve":
            answer = sanitize(correct, 1200)
            if not answer:
                raise ValueError("correct answer is required")
            if "verified-corrections" in answer.lower():
                raise ValueError("correct answer cannot contain the injection wrapper name")
            scope = normalize_scope(scope)
            current = corrections.read_text(encoding="utf-8")
            marker = f"imported:{fingerprint}"
            if marker not in current:
                row = f"| {datetime.now():%Y-%m-%d} | {selected['candidate'].strip()} | {answer} | active | {marker} |\n"
                atomic_write(corrections, current + row)
            append_verified_correction(root, fingerprint, answer, scope)
        atomic_write(inbox, text.replace(old, new, 1))
        return status


def revoke(root: Path, state_root: Path, fingerprint: str) -> str:
    with advisory_lock(state_root / CORRECTIONS_LOCK):
        if not revoke_verified_correction(root, fingerprint):
            raise ValueError("verified correction not found")
        corrections = root / "corrections.md"
        current = corrections.read_text(encoding="utf-8")
        row = f"| {datetime.now():%Y-%m-%d} | Revoke {fingerprint} | No longer auto-injected | revoked | revoked:{fingerprint} |\n"
        atomic_write(corrections, current + row)
    return "revoked"
