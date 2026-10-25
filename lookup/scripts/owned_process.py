"""Let a maintenance child finish its own cancellation before forced termination."""
import os
import signal
import subprocess
import threading
import time


def call(argv):
    """Own one foreground process group until every cancellable member is stopped."""
    process = None
    cancelled = None
    handlers = {}

    def interrupted(signum, frame):
        nonlocal cancelled
        if cancelled is None:
            cancelled = signum

    def signal_group(signum):
        try:
            os.killpg(process.pid, signum)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            if signum == 0:
                # A zombie-only group is not signalable on macOS. Keep the
                # bounded wait alive so poll() can reap the leader next turn.
                return True
            # A leader may become a zombie between poll() and killpg() on
            # macOS. Reap only our child, then retry the same owned group.
            if process.poll() is None:
                raise
            try:
                os.killpg(process.pid, signum)
                return True
            except ProcessLookupError:
                return False

    for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        handlers[signum] = signal.signal(signum, interrupted)
    try:
        if cancelled is not None:
            return 128 + cancelled
        process = subprocess.Popen(argv, start_new_session=True)
        try:
            while cancelled is None:
                try:
                    process.wait(timeout=0.05)
                    break
                except subprocess.TimeoutExpired:
                    pass
        finally:
            # The leader may have exited while descendants still hold stdout.
            # Only this newly created session is ours; never inspect/kill by name.
            if signal_group(cancelled or signal.SIGTERM):
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    # macOS can report EPERM for a group containing only the
                    # unreaped leader. Reap our child before probing the group.
                    process.poll()
                    if not signal_group(0):
                        break
                    time.sleep(0.02)
                if signal_group(0):
                    signal_group(signal.SIGKILL)
            process.wait()
        if cancelled is not None:
            return 128 + cancelled
        return process.returncode if process.returncode >= 0 else 128 - process.returncode
    finally:
        for signum, handler in handlers.items():
            signal.signal(signum, handler)


def run(argv, timeout):
    process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, start_new_session=True)
    handlers = {}
    forwarded = False

    def interrupted(signum, frame):
        nonlocal forwarded
        if process.poll() is None and not forwarded:
            process.send_signal(signum)
            forwarded = True
        raise KeyboardInterrupt

    if threading.current_thread() is threading.main_thread():
        for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            handlers[signum] = signal.signal(signum, interrupted)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
        return subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)
    except BaseException:
        if process.poll() is None:
            if not forwarded:
                process.send_signal(signal.SIGTERM)
            try:
                process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.communicate()
        raise
    finally:
        for signum, handler in handlers.items():
            signal.signal(signum, handler)
