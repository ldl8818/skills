#!/usr/bin/env bash
# 零平台业务请求：检查指定 Profile 的 daemon/extension 状态，必要时启动 daemon。
# 一个 Python 进程维护 monotonic 预算与子进程归属，避免反复启动解释器计时。
# daemon 启动预算 3.2s；监听后另给扩展 17s 重连；恢复预算 0.75s。
# 已运行状态仍快速返回；未监听失败 <5s，冷启动重连含收尾 <22s（正常调度）。
set -uo pipefail
if ! command -v python3 >/dev/null 2>&1; then
  printf '%s\n' '{"ok":false,"state":"dependency_missing","next":"install_python3","elapsed_ms":0}'
  exit 78
fi
exec python3 - <<'PY'
import errno
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import sys
import time
from urllib.parse import urlencode

START = time.monotonic()
START_DEADLINE = START + 3.2
RECONNECT_BUDGET = 17.0
TOTAL_DEADLINE = START + 4.2
PROFILE = os.environ.get('LOOKUP_OPENCLI_PROFILE', 'ego-lite')
PORT = os.environ.get('OPENCLI_DAEMON_PORT', '19825')
daemon_child = None
restored = False
lock_fd = None
interrupted = False
status_url = ''
context_id = ''


class HealthFailure(Exception):
    def __init__(self, state, next_step, code, daemon='unknown', extension='unknown', status=None):
        self.state, self.next_step, self.code = state, next_step, code
        self.daemon, self.extension, self.status = daemon, extension, status or {}


class Interrupted(Exception):
    pass


def on_signal(_signum, _frame):
    # Defer cleanup until Popen has returned its exact child handle. A second
    # signal only sets this flag again; it cannot interrupt recovery.
    global interrupted
    interrupted = True


for sig in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
    signal.signal(sig, on_signal)


def check_signal():
    if interrupted:
        raise Interrupted()


def emit(ok, state, daemon, extension, next_step, status=None):
    status = status or {}
    result = dict(ok=ok, state=state, daemon=daemon, extension=extension,
                  started_daemon=daemon_child is not None, restored_daemon=restored,
                  elapsed_ms=round((time.monotonic() - START) * 1000), next=next_step,
                  transport='extension', profile=PROFILE, daemon_port=PORT,
                  fault_scope='bridge_profile')
    for source, target in [('daemonVersion', 'daemon_version'), ('extensionVersion', 'extension_version')]:
        if isinstance(status.get(source), str):
            result[target] = status[source]
    print(json.dumps(result, ensure_ascii=False, separators=(',', ':')), flush=True)


def probe(seconds=0.25):
    seconds = max(0.001, min(seconds, max(0.001, TOTAL_DEADLINE - time.monotonic())))
    try:
        result = subprocess.run(
            ['curl', '--silent', '--show-error', '--connect-timeout', str(seconds),
             '--max-time', str(seconds), '--max-filesize', '65536', '-H', 'X-OpenCLI: 1', status_url],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            timeout=seconds + 0.05, close_fds=True)
    except subprocess.TimeoutExpired:
        return 28, {}
    except OSError:
        return 69, {}
    try:
        status = json.loads(result.stdout)
        if not isinstance(status, dict) or status.get('ok') is not True:
            status = {}
    except (ValueError, TypeError):
        status = {}
    return result.returncode, status


def ready(status):
    return status.get('extensionConnected') is True and status.get('contextId') == context_id


def classify(status, cold=False):
    if status.get('profileRequired') is True:
        raise HealthFailure('profile_required', 'select_lookup_profile', 78, 'running', 'connected', status)
    if ready(status):
        return True
    if status.get('profileDisconnected') is True:
        if cold:
            return False  # New daemon may still be waiting for extension reconnect.
        raise HealthFailure('profile_disconnected', 'connect_lookup_profile', 78, 'running', 'disconnected', status)
    if status.get('extensionConnected') is True:
        raise HealthFailure('profile_mismatch', 'rebind_lookup_profile', 78, 'running', 'connected', status)
    if not cold:
        raise HealthFailure('extension_disconnected', 'enable_extension_in_lookup_profile', 69, 'running', 'disconnected', status)
    return False


def recover_own_daemon(last_status=None):
    global restored
    if daemon_child is None:
        return 'unknown'
    # Popen owns an unreaped child PID. Never signal a PID read from /status,
    # inspect the global process list, or call the shared /shutdown endpoint.
    deadline = min(time.monotonic() + 0.75, TOTAL_DEADLINE)
    if daemon_child.poll() is None:
        daemon_child.terminate()
        try:
            daemon_child.wait(timeout=max(0.001, min(0.5, deadline - time.monotonic())))
        except subprocess.TimeoutExpired:
            daemon_child.kill()
            try:
                daemon_child.wait(timeout=max(0.001, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                return 'unknown'
    restored = daemon_child.poll() is not None
    remaining = deadline - time.monotonic()
    if remaining > 0.02:
        _, current = probe(min(0.1, remaining))
        return 'running' if current else 'stopped'
    # A different daemon may have taken the port; do not claim it was stopped.
    if last_status and last_status.get('pid') not in (None, daemon_child.pid):
        return 'running'
    return 'unknown'


def prepare_lock():
    global lock_fd
    home = Path(os.environ.get('HOME', ''))
    if not home.is_absolute():
        raise HealthFailure('lock_unavailable', 'check_home_tmp_permissions', 78)
    for directory in (home / 'tmp', home / 'tmp' / 'lookup-runtime'):
        if directory.is_symlink():
            raise HealthFailure('lock_unavailable', 'check_home_tmp_permissions', 78)
        directory.mkdir(exist_ok=True)
        info = directory.stat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            raise HealthFailure('lock_unavailable', 'check_home_tmp_permissions', 78)
    runtime = home / 'tmp' / 'lookup-runtime'
    runtime.chmod(0o700)
    lock_fd = os.open(runtime / 'opencli-health-daemon.v2.flock',
                      os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    info = os.fstat(lock_fd)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
        raise HealthFailure('lock_unavailable', 'check_home_tmp_permissions', 78)
    os.fchmod(lock_fd, 0o600)
    while True:
        check_signal()
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except OSError as error:
            if error.errno not in (errno.EACCES, errno.EAGAIN):
                raise
        if time.monotonic() >= START_DEADLINE:
            raise HealthFailure('daemon_start_lock_timeout', 'retry_opencli_health', 75)
        time.sleep(0.02)


def main():
    global status_url, context_id, PORT, daemon_child, TOTAL_DEADLINE
    if os.environ.get('OPENCLI_CDP_ENDPOINT'):
        raise HealthFailure('unsupported_transport', 'unset_opencli_cdp_endpoint', 78)
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}', PROFILE):
        raise HealthFailure('invalid_profile', 'set_lookup_opencli_profile_alias', 78)
    if not re.fullmatch(r'[0-9]+', PORT) or not 1 <= int(PORT) <= 65535:
        raise HealthFailure('invalid_daemon_port', 'set_opencli_daemon_port', 78)
    PORT = int(PORT)
    for dependency in ('opencli', 'curl', 'node'):
        if not shutil.which(dependency):
            raise HealthFailure('dependency_missing', 'install_' + dependency, 78)
    config = Path(os.environ.get('OPENCLI_CONFIG_DIR') or str(Path.home() / '.opencli'))
    try:
        context_id = json.loads((config / 'browser-profiles.json').read_text())['aliases'][PROFILE]
        if not isinstance(context_id, str) or not context_id or '\n' in context_id:
            raise ValueError()
    except (OSError, ValueError, KeyError, TypeError):
        raise HealthFailure('profile_unbound', 'bind_lookup_profile', 78)
    status_url = 'http://127.0.0.1:{}/status?{}'.format(PORT, urlencode({'contextId': context_id}))
    code, status = probe(1.0)
    check_signal()
    if code == 0 and status:
        classify(status)
        emit(True, 'ready', 'running', 'connected', 'use_opencli', status)
        return 0
    if code != 7:
        raise HealthFailure('daemon_unresponsive', 'check_opencli_daemon', 75, 'unknown', status=status)
    prepare_lock()
    remaining = START_DEADLINE - time.monotonic()
    if remaining <= 0:
        raise HealthFailure('daemon_start_lock_timeout', 'retry_opencli_health', 75)
    code, status = probe(min(1.0, remaining))
    check_signal()
    if code == 0 and status:
        classify(status)
        emit(True, 'ready', 'running', 'connected', 'use_opencli', status)
        return 0
    if code != 7:
        raise HealthFailure('daemon_unresponsive', 'check_opencli_daemon', 75, 'unknown', status=status)
    daemon_entry = Path(shutil.which('opencli')).resolve().parent / 'daemon.js'
    if not daemon_entry.is_file():
        raise HealthFailure('daemon_entry_missing', 'check_opencli_installation', 78, 'stopped')
    if time.monotonic() >= START_DEADLINE:
        raise HealthFailure('daemon_start_lock_timeout', 'retry_opencli_health', 75)
    env = dict(os.environ, OPENCLI_PROFILE=PROFILE, OPENCLI_DAEMON_PORT=str(PORT))
    # close_fds prevents both daemon and curl from extending our kernel lock.
    daemon_child = subprocess.Popen([shutil.which('node'), str(daemon_entry)], env=env,
                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, close_fds=True, start_new_session=True)
    last_status = {}
    phase_deadline = START_DEADLINE
    waiting_for_extension = False
    while time.monotonic() < phase_deadline:
        check_signal()
        _, status = probe(min(0.25, phase_deadline - time.monotonic()))
        check_signal()
        if status:
            last_status = status
            if classify(status, cold=True):
                emit(True, 'ready', 'running', 'connected', 'use_opencli', status)
                return 0
            if not waiting_for_extension:
                # The daemon is listening. Allow one complete extension retry
                # backoff; repeated disconnected replies never renew this budget.
                phase_deadline = time.monotonic() + RECONNECT_BUDGET
                TOTAL_DEADLINE = phase_deadline + 1.0
                waiting_for_extension = True
        if daemon_child.poll() is not None and not status:
            raise HealthFailure('daemon_start_failed', 'check_opencli_daemon', 69, 'stopped')
        time.sleep(max(0, min(0.1, phase_deadline - time.monotonic())))
    if last_status:
        if last_status.get('profileDisconnected') is True:
            raise HealthFailure('profile_disconnected', 'connect_lookup_profile', 78, 'running', 'disconnected', last_status)
        raise HealthFailure('extension_disconnected', 'enable_extension_in_lookup_profile', 69, 'running', 'disconnected', last_status)
    raise HealthFailure('daemon_timeout', 'check_opencli_daemon', 75)


try:
    exit_code = main()
except Interrupted:
    recover_own_daemon()
    exit_code = 130
except HealthFailure as error:
    daemon_state = recover_own_daemon(error.status) if daemon_child is not None else error.daemon
    emit(False, error.state, daemon_state, error.extension, error.next_step, error.status)
    exit_code = error.code
except OSError:
    daemon_state = recover_own_daemon() if daemon_child is not None else 'unknown'
    emit(False, 'local_runtime_error', daemon_state, 'unknown', 'check_local_runtime')
    exit_code = 78
finally:
    if lock_fd is not None:
        os.close(lock_fd)
sys.exit(exit_code)
PY
