"""Redaction, hashing and portable advisory locking."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import re
from typing import Iterator


SECRET_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"(?i)(authorization\s*[:=]\s*['\"]?bearer\s+)\S+", r"\1[REDACTED]"),
    (r"(?i)(authorization\s*[:=]\s*['\"]?basic\s+)[A-Za-z0-9+/=]+", r"\1[REDACTED]"),
    (r"(?i)\b((?:access|refresh|id|auth)?[_-]?(?:token|secret|password|passwd|api[_-]?key|apikey|cookie))\b\s*[:=]\s*([^\s,;]+)", r"\1=[REDACTED]"),
    (r"([A-Za-z][A-Za-z0-9+.-]*://)[^/@\s:]+:[^/@\s]+@", r"\1[REDACTED]@"),
    (r"\bsk-[A-Za-z0-9_-]{16,}\b", "[REDACTED_OPENAI_KEY]"),
    (r"\bgh[pousr]_[A-Za-z0-9]{20,}\b", "[REDACTED_GITHUB_TOKEN]"),
    (r"\bAKIA[0-9A-Z]{16}\b", "[REDACTED_AWS_KEY]"),
    (r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}", "[REDACTED_JWT]"),
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", "[REDACTED_PRIVATE_KEY]"),
)


def sanitize(value: str, limit: int = 500) -> str:
    text = value
    for pattern, replacement in SECRET_PATTERNS:
        text = re.sub(pattern, replacement, text, flags=re.S)
    text = "".join(character if ord(character) >= 32 else " " for character in text)
    text = re.sub(r"\s+", " ", text).strip()
    text = text.translate(str.maketrans({"|": "¦", "<": "＜", ">": "＞", "`": "'", "!": "！"}))
    return text[:limit]


def contains_secret(value: str) -> bool:
    return any(re.search(pattern, value, flags=re.S) for pattern, _ in SECRET_PATTERNS)


def digest(value: bytes | str) -> str:
    data = value.encode() if isinstance(value, str) else value
    return hashlib.sha256(data).hexdigest()


@contextmanager
def advisory_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()
