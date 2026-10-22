"""Let a maintenance child finish its own cancellation before forced termination."""
import os
import signal
import subprocess
import threading


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
