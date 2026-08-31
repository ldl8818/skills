#!/usr/bin/env python3
"""Hold an advisory file lock only while the direct parent process is alive."""

from __future__ import annotations

import errno
import fcntl
import os
from pathlib import Path
import signal
import sys
import time


def main() -> int:
    if len(sys.argv) != 5:
        return 78

    lock_path = Path(sys.argv[1])
    status_path = Path(sys.argv[2])
    wait_ms = int(sys.argv[3])
    expected_parent = int(sys.argv[4])
    stop_requested = False

    def stop(_signum: int, _frame: object) -> None:
        nonlocal stop_requested
        stop_requested = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    def report(code: int) -> None:
        status_path.write_text(f"{code}\n", encoding="ascii")

    deadline = time.monotonic() + max(0, wait_ms) / 1000
    try:
        with lock_path.open("a", encoding="ascii") as lock_file:
            os.chmod(lock_path, 0o600)
            while True:
                if stop_requested or os.getppid() != expected_parent:
                    return 130
                try:
                    fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError as exc:
                    if exc.errno not in (errno.EACCES, errno.EAGAIN):
                        report(78)
                        return 78
                if time.monotonic() >= deadline:
                    report(75)
                    return 75
                time.sleep(0.02)

            report(0)
            while not stop_requested and os.getppid() == expected_parent:
                time.sleep(0.02)
            try:
                status_path.unlink()
            except FileNotFoundError:
                pass
        return 0
    except (OSError, ValueError):
        try:
            report(78)
        except OSError:
            pass
        return 78


if __name__ == "__main__":
    raise SystemExit(main())
