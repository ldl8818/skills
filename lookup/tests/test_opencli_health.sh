#!/usr/bin/env bash
set -uo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HEALTH_SCRIPT="$ROOT_DIR/scripts/opencli-health.sh"
RUN_SCRIPT="$ROOT_DIR/scripts/opencli-run.mjs"
TEST_ROOT="$HOME/tmp/lookup-opencli-health-test.$$"
PASS=0
FAIL=0

fake_daemon_is_current() {
  local pid="$1"
  local daemon_path="$2"
  local command_line
  [[ "$pid" =~ ^[0-9]+$ ]] || return 1
  command_line=$(ps -o command= -p "$pid" 2>/dev/null || true)
  [[ -n "$command_line" ]] && [[ "$command_line" == *"$daemon_path"* ]]
}

stop_fake_daemon() {
  local pid_file="$1"
  local state_dir="${pid_file%/spawned-pid}"
  local daemon_path="$state_dir/bin/daemon.js"
  local pid=""
  [[ -r "$pid_file" ]] || return 0
  pid=$(<"$pid_file")
  fake_daemon_is_current "$pid" "$daemon_path" || return 0
  kill -TERM "$pid" 2>/dev/null || true
  for _ in $(seq 1 25); do
    fake_daemon_is_current "$pid" "$daemon_path" || return 0
    sleep 0.01
  done
  kill -KILL "$pid" 2>/dev/null || true
  for _ in $(seq 1 25); do
    fake_daemon_is_current "$pid" "$daemon_path" || return 0
    sleep 0.01
  done
  return 1
}

cleanup() {
  local pid_file
  if [[ -d "$TEST_ROOT" ]]; then
    while IFS= read -r pid_file; do
      stop_fake_daemon "$pid_file" || true
    done < <(find "$TEST_ROOT" -type f -name spawned-pid -print)
  fi
  case "$TEST_ROOT" in
    "$HOME"/tmp/lookup-opencli-health-test.*) rm -rf -- "$TEST_ROOT" ;;
  esac
}
trap cleanup EXIT
mkdir -p "$TEST_ROOT"

ok() { printf '  ✓ %s\n' "$1"; PASS=$((PASS + 1)); }
bad() { printf '  ✗ %s\n' "$1"; FAIL=$((FAIL + 1)); }

assert_json() {
  local label="$1"
  local output="$2"
  local filter="$3"
  if jq -e "$filter" >/dev/null 2>&1 <<<"$output"; then
    ok "$label"
  else
    bad "${label}：${output}"
  fi
}

make_health_fakes() {
  local fake_bin="$1"
  local fake_config_dir="${fake_bin%/bin}/opencli-config"
  mkdir -p "$fake_bin"
  mkdir -p "$fake_config_dir"
  printf '%s\n' '{"version":1,"aliases":{"ego-lite":"ego"},"defaultContextId":"ego"}' \
    > "$fake_config_dir/browser-profiles.json"

  printf '%s\n' \
    '#!/usr/bin/env bash' \
    'case "${1:-} ${2:-}" in' \
    '  "daemon restart")' \
    '    : > "$FAKE_STATE_DIR/lifecycle-active"' \
    '    trap '\''rm -f "$FAKE_STATE_DIR/lifecycle-active"'\'' EXIT' \
    '    [[ "${FAKE_IGNORE_TERM:-0}" -eq 0 ]] || trap "" TERM' \
    '    printf "restart\n" >> "$FAKE_STATE_DIR/opencli.log"' \
    '    [[ "${FAKE_START_BEFORE_SLEEP:-0}" -eq 0 ]] || : > "$FAKE_STATE_DIR/restarted"' \
    '    [[ "${FAKE_RESTART_SLEEP:-0}" == 0 ]] || sleep "$FAKE_RESTART_SLEEP"' \
    '    [[ "${FAKE_START_FAIL:-0}" -eq 0 ]] || exit 1' \
    '    [[ "${FAKE_START_BEFORE_SLEEP:-0}" -ne 0 ]] || : > "$FAKE_STATE_DIR/restarted"' \
    '    ;;' \
    '  "daemon stop")' \
    '    : > "$FAKE_STATE_DIR/lifecycle-active"' \
    '    trap '\''rm -f "$FAKE_STATE_DIR/lifecycle-active"'\'' EXIT' \
    '    [[ "${FAKE_IGNORE_TERM:-0}" -eq 0 ]] || trap "" TERM' \
    '    printf "stop\n" >> "$FAKE_STATE_DIR/opencli.log"' \
    '    [[ "${FAKE_STOP_SLEEP:-0}" == 0 ]] || sleep "$FAKE_STOP_SLEEP"' \
    '    [[ "${FAKE_STOP_FAIL:-0}" -eq 0 ]] || exit 1' \
    '    : > "$FAKE_STATE_DIR/stopped"' \
    '    ;;' \
    '  *) exit 2 ;;' \
    'esac' > "$fake_bin/opencli"

  printf '%s\n' \
    '#!/usr/bin/env node' \
    'import fs from "node:fs"' \
    'const dir = process.env.FAKE_STATE_DIR' \
    'const delay = Math.max(0, Number(process.env.FAKE_RESTART_SLEEP || 0) * 1000)' \
    'fs.appendFileSync(`${dir}/opencli.log`, "restart\n")' \
    'fs.writeFileSync(`${dir}/spawned-pid`, String(process.pid))' \
    'const markReady = () => fs.writeFileSync(`${dir}/restarted`, "")' \
    'if (process.env.FAKE_START_BEFORE_SLEEP === "1") markReady()' \
    'const finishStart = () => {' \
    '  if (process.env.FAKE_START_FAIL === "1") process.exit(1)' \
    '  if (process.env.FAKE_START_BEFORE_SLEEP !== "1") markReady()' \
    '}' \
    'if (delay > 0) setTimeout(finishStart, delay); else finishStart()' \
    'const stop = () => {' \
    '  fs.appendFileSync(`${dir}/opencli.log`, `stop:${process.pid}\n`)' \
    '  if (process.env.FAKE_IGNORE_TERM === "1" || process.env.FAKE_STOP_FAIL === "1") return' \
    '  fs.writeFileSync(`${dir}/stopped`, String(process.pid))' \
    '  process.exit(0)' \
    '}' \
    'process.on("SIGTERM", stop)' \
    'process.on("SIGINT", stop)' \
    'setInterval(() => {}, 1000)' \
    > "$fake_bin/daemon.js"

  printf '%s\n' \
    '#!/usr/bin/env bash' \
    'status_pid="${FAKE_DAEMON_PID:-}"' \
    '[[ -n "$status_pid" ]] || [[ ! -r "$FAKE_STATE_DIR/spawned-pid" ]] || status_pid=$(<"$FAKE_STATE_DIR/spawned-pid")' \
    '[[ -n "$status_pid" ]] || status_pid=$$' \
    'if [[ "$FAKE_STATUS_MODE" == "start-profile-replaced" ]] && [[ -f "$FAKE_STATE_DIR/restarted" ]]; then' \
    '  count_file="$FAKE_STATE_DIR/status-count"' \
    '  count=0; [[ ! -f "$count_file" ]] || count=$(<"$count_file"); count=$((count + 1)); printf "%s" "$count" > "$count_file"' \
    '  if [[ "${FAKE_FIRST_REPLACEMENT:-0}" -eq 1 ]] || [[ "$count" -ge 2 ]]; then status_pid="$FAKE_REPLACEMENT_PID"; fi' \
    'fi' \
    'if [[ -r "$FAKE_STATE_DIR/stopped" ]] && [[ "$(<"$FAKE_STATE_DIR/stopped")" == "$status_pid" ]]; then exit 7; fi' \
    'kill -0 "$status_pid" 2>/dev/null || exit 7' \
    'case "$FAKE_STATUS_MODE" in' \
    '  ready)' \
    '    printf '\''{"ok":true,"pid":%s,"daemonVersion":"1.8.6","extensionConnected":true,"extensionVersion":"1.0.23","contextId":"ego","profileRequired":false,"profileDisconnected":false,"profiles":[{"contextId":"ego"}]}\n'\'' "$status_pid"' \
    '    ;;' \
    '  start-ready)' \
    '    [[ -f "$FAKE_STATE_DIR/restarted" ]] || exit 7' \
    '    printf '\''{"ok":true,"pid":%s,"daemonVersion":"1.8.6","extensionConnected":true,"extensionVersion":"1.0.23","contextId":"ego","profileRequired":false,"profileDisconnected":false,"profiles":[{"contextId":"ego"}]}\n'\'' "$status_pid"' \
    '    ;;' \
    '  start-delayed-ready)' \
    '    [[ -f "$FAKE_STATE_DIR/status-ready" ]] || exit 7' \
    '    printf '\''{"ok":true,"pid":%s,"daemonVersion":"1.8.6","extensionConnected":true,"extensionVersion":"1.0.23","contextId":"ego","profileRequired":false,"profileDisconnected":false,"profiles":[{"contextId":"ego"}]}\n'\'' "$status_pid"' \
    '    ;;' \
    '  start-profile-reconnect)' \
    '    [[ -f "$FAKE_STATE_DIR/restarted" ]] || exit 7' \
    '    count_file="$FAKE_STATE_DIR/reconnect-count"' \
    '    count=0; [[ ! -f "$count_file" ]] || count=$(<"$count_file"); count=$((count + 1)); printf "%s" "$count" > "$count_file"' \
    '    if [[ "$count" -eq 1 ]]; then' \
    '      printf '\''{"ok":true,"pid":%s,"daemonVersion":"1.8.6","extensionConnected":false,"contextId":"ego","profileRequired":false,"profileDisconnected":true,"profiles":[]}\n'\'' "$status_pid"' \
    '    else' \
    '      printf '\''{"ok":true,"pid":%s,"daemonVersion":"1.8.6","extensionConnected":true,"extensionVersion":"1.0.23","contextId":"ego","profileRequired":false,"profileDisconnected":false,"profiles":[{"contextId":"ego"}]}\n'\'' "$status_pid"' \
    '    fi' \
    '    ;;' \
    '  running-disconnected)' \
    '    printf '\''{"ok":true,"pid":%s,"daemonVersion":"1.8.6","extensionConnected":false,"profileRequired":false,"profileDisconnected":false,"profiles":[]}\n'\'' "$status_pid"' \
    '    ;;' \
    '  start-disconnected)' \
    '    [[ -f "$FAKE_STATE_DIR/restarted" ]] || exit 7' \
    '    printf '\''{"ok":true,"pid":%s,"daemonVersion":"1.8.6","extensionConnected":false,"profileRequired":false,"profileDisconnected":false,"profiles":[]}\n'\'' "$status_pid"' \
    '    ;;' \
    '  start-profile-required)' \
    '    [[ -f "$FAKE_STATE_DIR/restarted" ]] || exit 7' \
    '    printf '\''{"ok":true,"pid":%s,"daemonVersion":"1.8.6","extensionConnected":true,"profileRequired":true,"profileDisconnected":false,"profiles":[{"contextId":"one"},{"contextId":"two"}]}\n'\'' "$status_pid"' \
    '    ;;' \
    '  start-profile-replaced)' \
    '    [[ -f "$FAKE_STATE_DIR/restarted" ]] || exit 7' \
    '    printf '\''{"ok":true,"pid":%s,"daemonVersion":"1.8.6","extensionConnected":true,"profileRequired":true,"profileDisconnected":false,"profiles":[{"contextId":"one"},{"contextId":"two"}]}\n'\'' "$status_pid"' \
    '    ;;' \
    '  profile-required)' \
    '    printf '\''{"ok":true,"pid":%s,"daemonVersion":"1.8.6","extensionConnected":true,"profileRequired":true,"profileDisconnected":false,"profiles":[{"contextId":"one"},{"contextId":"two"}]}\n'\'' "$status_pid"' \
    '    ;;' \
    '  profile-disconnected)' \
    '    printf '\''{"ok":true,"pid":%s,"daemonVersion":"1.8.6","extensionConnected":false,"profileRequired":false,"profileDisconnected":true,"profiles":[]}\n'\'' "$status_pid"' \
    '    ;;' \
    '  wrong-profile-online)' \
    '    if [[ "$*" == *"contextId=ego"* ]]; then' \
    '      printf '\''{"ok":true,"pid":%s,"daemonVersion":"1.8.6","extensionConnected":false,"contextId":"ego","profileRequired":false,"profileDisconnected":true,"profiles":[{"contextId":"chrome","extensionConnected":true}]}\n'\'' "$status_pid"' \
    '    else' \
    '      printf '\''{"ok":true,"pid":%s,"daemonVersion":"1.8.6","extensionConnected":true,"contextId":"chrome","profileRequired":false,"profileDisconnected":false,"profiles":[{"contextId":"chrome","extensionConnected":true}]}\n'\'' "$status_pid"' \
    '    fi' \
    '    ;;' \
    '  blocked-second-probe)' \
    '    count_file="$FAKE_STATE_DIR/status-count"' \
    '    count=0; [[ ! -f "$count_file" ]] || count=$(<"$count_file"); count=$((count + 1)); printf "%s" "$count" > "$count_file"' \
    '    if [[ "$count" -ge 2 ]]; then printf "%s" "$$" > "$FAKE_STATE_DIR/blocked-curl-pid"; : > "$FAKE_STATE_DIR/probe-blocked"; exec sleep 5; fi' \
    '    exit 7' \
    '    ;;' \
    '  invalid-status)' \
    '    printf "not-json\n"' \
    '    ;;' \
    '  *) exit 7 ;;' \
    'esac' > "$fake_bin/curl"

  printf '%s\n' \
    '#!/usr/bin/env bash' \
    'if [[ "${1:-}" == "-" ]] || [[ "${1:-}" == */flock-holder.py ]] || [[ "${2:-}" == *"os.setpgid(0, 0)"* ]] || [[ "${2:-}" == *"os.setsid()"* ]]; then exec "$FAKE_REAL_PYTHON" "$@"; fi' \
    'count_file="${FAKE_TIME_STATE_DIR:-$FAKE_STATE_DIR}/time-count"' \
    'count=0' \
    '[[ ! -f "$count_file" ]] || count=$(<"$count_file")' \
    'step=${FAKE_TIME_STEP_MS:-100}' \
    '[[ ! -f "$FAKE_STATE_DIR/lifecycle-active" ]] || step=${FAKE_LIFECYCLE_STEP_MS:-10}' \
    'count=$((count + step))' \
    'printf "%s" "$count" > "$count_file"' \
    'printf "%s\n" "$count"' > "$fake_bin/python3"

  chmod +x "$fake_bin/opencli" "$fake_bin/curl" "$fake_bin/python3" "$fake_bin/daemon.js"
}

prepare_health_fixture() {
  local mode="$1"
  local state_dir="$TEST_ROOT/state-$mode"
  local fake_bin="$state_dir/bin"
  mkdir -p "$state_dir"
  rm -f "$state_dir/restarted" "$state_dir/stopped" "$state_dir/spawned-pid" "$state_dir/lifecycle-active" "$state_dir/time-count" "$state_dir/status-count" "$state_dir/reconnect-count"
  : > "$state_dir/opencli.log"
  make_health_fakes "$fake_bin"
  if [[ "${FAKE_REAL_TIME:-0}" -eq 1 ]]; then
    rm -f -- "$fake_bin/python3"
    ln -s "$(command -v python3)" "$fake_bin/python3"
  fi
}

run_health() {
  local mode="$1"
  local step_ms="${2:-100}"
  local state_dir="$TEST_ROOT/state-$mode"
  local fake_bin="$state_dir/bin"
  local health_status
  local spawned_pid=""
  if [[ "${FAKE_HEALTH_PREPARED:-0}" -ne 1 ]]; then
    prepare_health_fixture "$mode"
  fi
  FAKE_STATE_DIR="$state_dir" \
  FAKE_REAL_PYTHON="$(command -v python3)" \
  FAKE_STATUS_MODE="$mode" \
  FAKE_TIME_STEP_MS="$step_ms" \
  FAKE_LIFECYCLE_STEP_MS="${FAKE_LIFECYCLE_STEP_MS:-10}" \
  FAKE_IGNORE_TERM="${FAKE_IGNORE_TERM:-0}" \
  FAKE_RESTART_SLEEP="${FAKE_RESTART_SLEEP:-0}" \
  FAKE_START_BEFORE_SLEEP="${FAKE_START_BEFORE_SLEEP:-0}" \
  FAKE_STOP_SLEEP="${FAKE_STOP_SLEEP:-0}" \
  FAKE_STOP_FAIL="${FAKE_STOP_FAIL:-0}" \
  FAKE_DAEMON_PID="${FAKE_DAEMON_PID:-}" \
  FAKE_REPLACEMENT_PID="${FAKE_REPLACEMENT_PID:-}" \
  FAKE_FIRST_REPLACEMENT="${FAKE_FIRST_REPLACEMENT:-0}" \
  OPENCLI_CONFIG_DIR="$state_dir/opencli-config" \
  HOME="${FAKE_HOME:-$state_dir/home}" \
  PATH="$fake_bin:$PATH" \
  bash "$HEALTH_SCRIPT"
  health_status=$?
  [[ ! -r "$state_dir/spawned-pid" ]] || spawned_pid=$(<"$state_dir/spawned-pid")
  stop_fake_daemon "$state_dir/spawned-pid" || true
  return "$health_status"
}

test_ready_without_restart() {
  local output status
  set +e
  output=$(run_health ready)
  status=$?
  set -e
  [[ "$status" -eq 0 ]] || { bad "已在线时退出 0"; return; }
  assert_json "已在线时不重启 daemon" "$output" '.ok == true and .state == "ready" and .started_daemon == false and .extension == "connected"'
}

test_start_then_ready() {
  local output status
  set +e
  output=$(run_health start-ready)
  status=$?
  set -e
  [[ "$status" -eq 0 ]] || { bad "冷启动成功时退出 0"; return; }
  assert_json "冷启动 daemon 后桥接成功" "$output" '.ok == true and .state == "ready" and .started_daemon == true and .restored_daemon == false'
}

test_cold_start_waits_for_profile_reconnect() {
  local output status
  set +e
  output=$(run_health start-profile-reconnect)
  status=$?
  set -e
  [[ "$status" -eq 0 ]] || { bad "冷启动暂态断连后未继续等待：status=${status} output=${output}"; return; }
  assert_json "冷启动预算内等待 ego lite Profile 重连" "$output" '.ok == true and .state == "ready" and .started_daemon == true'
}

test_daemon_does_not_inherit_start_lock() {
  local state_dir="$TEST_ROOT/state-lock-inheritance"
  local fake_bin="$state_dir/bin"
  local fake_home="$state_dir/home"
  local lock_file="$fake_home/tmp/lookup-runtime/opencli-health-daemon.v2.flock"
  local output status spawned_pid lock_status
  mkdir -p "$state_dir" "$fake_home/tmp"
  : > "$state_dir/opencli.log"
  make_health_fakes "$fake_bin"

  set +e
  output=$(FAKE_STATE_DIR="$state_dir" FAKE_REAL_PYTHON="$(command -v python3)" \
    FAKE_STATUS_MODE=start-ready OPENCLI_CONFIG_DIR="$state_dir/opencli-config" HOME="$fake_home" PATH="$fake_bin:$PATH" bash "$HEALTH_SCRIPT")
  status=$?
  set -e
  [[ "$status" -eq 0 ]] || { bad "冷启动后无法检查锁继承：status=${status} output=${output}"; return; }
  spawned_pid=$(<"$state_dir/spawned-pid")
  python3 - "$lock_file" <<'PY'
import fcntl
import sys

with open(sys.argv[1], 'a') as lock_file:
    fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
PY
  lock_status=$?
  kill -TERM "$spawned_pid" 2>/dev/null || true
  wait "$spawned_pid" 2>/dev/null || true
  if [[ "$lock_status" -eq 0 ]]; then
    ok "daemon 不继承健康门禁的内核锁"
  else
    bad "daemon 继承了健康门禁内核锁"
  fi
}

test_running_disconnected_fails_fast() {
  local output status
  set +e
  output=$(run_health running-disconnected)
  status=$?
  set -e
  [[ "$status" -eq 69 ]] || { bad "既有 daemon 扩展断连时退出 69"; return; }
  assert_json "既有 daemon 扩展断连不冒充 ready" "$output" '.ok == false and .state == "extension_disconnected" and .started_daemon == false and .restored_daemon == false'
}

test_started_daemon_is_restored_on_failure() {
  local output status
  set +e
  output=$(run_health start-profile-required 100)
  status=$?
  set -e
  [[ "$status" -eq 78 ]] || { bad "冷启动后需要选择 Profile 时退出 78"; return; }
  assert_json "失败时停止本次启动的 daemon" "$output" '.ok == false and .state == "profile_required" and .daemon == "stopped" and .started_daemon == true and .restored_daemon == true'
}

test_daemon_start_failure() {
  local state_dir="$TEST_ROOT/state-start-failed"
  local fake_bin="$state_dir/bin"
  local output status
  mkdir -p "$state_dir"
  : > "$state_dir/opencli.log"
  make_health_fakes "$fake_bin"
  set +e
  output=$(FAKE_STATE_DIR="$state_dir" FAKE_REAL_PYTHON="$(command -v python3)" \
    FAKE_STATUS_MODE=unreachable FAKE_START_FAIL=1 HOME="$state_dir/home" \
    OPENCLI_CONFIG_DIR="$state_dir/opencli-config" PATH="$fake_bin:$PATH" bash "$HEALTH_SCRIPT")
  status=$?
  set -e
  [[ "$status" -eq 69 ]] || { bad "daemon 启动失败时退出 69"; return; }
  assert_json "daemon 启动失败给结构化状态" "$output" '.ok == false and .state == "daemon_start_failed" and .started_daemon == true and .restored_daemon == true'
}

test_invalid_status_does_not_claim_existing_daemon() {
  local state_dir="$TEST_ROOT/state-invalid-status"
  local fake_bin="$state_dir/bin"
  local output status
  mkdir -p "$state_dir"
  : > "$state_dir/opencli.log"
  make_health_fakes "$fake_bin"
  set +e
  output=$(FAKE_STATE_DIR="$state_dir" FAKE_STATUS_MODE=invalid-status OPENCLI_CONFIG_DIR="$state_dir/opencli-config" PATH="$fake_bin:$PATH" bash "$HEALTH_SCRIPT")
  status=$?
  set -e
  [[ "$status" -eq 75 ]] || { bad "既有端口返回坏状态时退出 75"; return; }
  if [[ -s "$state_dir/opencli.log" ]]; then
    bad "既有端口返回坏状态时没有认领 daemon"
    return
  fi
  assert_json "既有端口返回坏状态时没有认领 daemon" "$output" '.state == "daemon_unresponsive" and .started_daemon == false and .daemon == "running"'
}

test_lifecycle_commands_have_hard_timeout() {
  local output status wall_start_ms wall_end_ms wall_elapsed_ms
  FAKE_REAL_TIME=1 prepare_health_fixture unreachable
  set +e
  wall_start_ms=$(python3 -c 'import time; print(int(time.monotonic() * 1000))')
  output=$(FAKE_RESTART_SLEEP=6 FAKE_IGNORE_TERM=1 FAKE_REAL_TIME=1 FAKE_HEALTH_PREPARED=1 run_health unreachable 100)
  status=$?
  wall_end_ms=$(python3 -c 'import time; print(int(time.monotonic() * 1000))')
  wall_elapsed_ms=$((wall_end_ms - wall_start_ms))
  set -e
  [[ "$status" -eq 75 ]] || { bad "daemon 启动后端口未出现时退出 75"; return; }
  if [[ "$wall_elapsed_ms" -lt 5000 ]]; then
    assert_json "忽略 TERM 的 daemon 仍受总硬超时约束" "$output" '.state == "daemon_timeout" and .elapsed_ms < 5000 and .restored_daemon == true'
  else
    bad "忽略 TERM 的 daemon 突破硬超时：${wall_elapsed_ms}ms output=${output}"
  fi
}

test_concurrent_cold_start_has_single_owner() {
  local state_dir="$TEST_ROOT/state-concurrent-cold-start"
  local fake_bin="$state_dir/bin"
  local pid_one pid_two status_one status_two restart_count output_one output_two spawned_pid
  mkdir -p "$state_dir/home/tmp" "$state_dir/time-one" "$state_dir/time-two"
  : > "$state_dir/opencli.log"
  make_health_fakes "$fake_bin"
  rm -f -- "$fake_bin/python3"
  ln -s "$(command -v python3)" "$fake_bin/python3"

  set +e
  FAKE_STATE_DIR="$state_dir" FAKE_REAL_PYTHON="$(command -v python3)" FAKE_TIME_STATE_DIR="$state_dir/time-one" \
    FAKE_STATUS_MODE=start-ready FAKE_RESTART_SLEEP=0.2 FAKE_DAEMON_PID="$$" HOME="$state_dir/home" \
    OPENCLI_CONFIG_DIR="$state_dir/opencli-config" PATH="$fake_bin:$PATH" bash "$HEALTH_SCRIPT" > "$state_dir/output-one.json" &
  pid_one=$!
  FAKE_STATE_DIR="$state_dir" FAKE_REAL_PYTHON="$(command -v python3)" FAKE_TIME_STATE_DIR="$state_dir/time-two" \
    FAKE_STATUS_MODE=start-ready FAKE_RESTART_SLEEP=0.2 FAKE_DAEMON_PID="$$" HOME="$state_dir/home" \
    OPENCLI_CONFIG_DIR="$state_dir/opencli-config" PATH="$fake_bin:$PATH" bash "$HEALTH_SCRIPT" > "$state_dir/output-two.json" &
  pid_two=$!
  wait "$pid_one"
  status_one=$?
  wait "$pid_two"
  status_two=$?
  set -e

  output_one=$(<"$state_dir/output-one.json")
  output_two=$(<"$state_dir/output-two.json")
  if [[ -f "$state_dir/opencli.log" ]]; then restart_count=$(grep -c '^restart$' "$state_dir/opencli.log" || true); else restart_count=0; fi
  if [[ "$status_one" -eq 0 ]] && [[ "$status_two" -eq 0 ]] \
    && [[ "$restart_count" -eq 1 ]] \
    && jq -e --argjson one "$output_one" --argjson two "$output_two" '
      ($one.ok == true and $two.ok == true)
      and ([($one.started_daemon), ($two.started_daemon)] | sort == [false, true])
    ' >/dev/null 2>&1 <<< '{}'; then
    ok "并发冷启动只有一个 daemon owner"
  else
    bad "并发冷启动发生重复认领：restart=${restart_count} status=${status_one}/${status_two} output=${output_one} | ${output_two}"
  fi
  if [[ -r "$state_dir/spawned-pid" ]]; then
    spawned_pid=$(<"$state_dir/spawned-pid")
    stop_fake_daemon "$state_dir/spawned-pid" || true
  fi
}

test_legacy_malformed_lock_does_not_block_kernel_lock() {
  local state_dir="$TEST_ROOT/state-start-ready"
  local fake_home="$state_dir/home"
  local lock_dir="$fake_home/tmp/lookup-runtime/opencli-health-daemon.lock"
  local output status
  mkdir -p "$lock_dir"
  printf 'not-a-pid\n' > "$lock_dir/owner"
  python3 -c 'import os,sys,time; os.utime(sys.argv[1], (time.time() - 10, time.time() - 10))' "$lock_dir"

  set +e
  output=$(FAKE_HOME="$fake_home" run_health start-ready)
  status=$?
  set -e
  [[ "$status" -eq 0 ]] || { bad "旧版损坏锁目录干扰内核锁：status=${status} output=${output}"; return; }
  assert_json "旧版损坏锁目录不阻塞内核锁" "$output" '.ok == true and .state == "ready" and .started_daemon == true'
}

test_legacy_ownerless_lock_does_not_block_kernel_lock() {
  local state_dir="$TEST_ROOT/state-recent-ownerless"
  local fake_home="$state_dir/home"
  local lock_dir="$fake_home/tmp/lookup-runtime/opencli-health-daemon.lock"
  local output status
  mkdir -p "$lock_dir"
  python3 -c 'import os,sys,time; os.utime(sys.argv[1], (time.time() - 2, time.time() - 2))' "$lock_dir"

  set +e
  output=$(FAKE_HOME="$fake_home" run_health start-ready)
  status=$?
  set -e
  if [[ "$status" -eq 0 ]] && [[ -d "$lock_dir" ]]; then
    assert_json "旧版 ownerless 目录不阻塞内核锁" "$output" '.ok == true and .state == "ready" and .started_daemon == true'
  else
    bad "旧版 ownerless 目录干扰内核锁：status=${status} output=${output}"
  fi
}

test_start_lock_releases_after_sigkill() {
  local state_dir="$TEST_ROOT/state-start-ready"
  local fake_bin="$state_dir/bin"
  local fake_home="$state_dir/home"
  local health_pid spawned_pid output status
  mkdir -p "$state_dir" "$fake_home/tmp"
  : > "$state_dir/opencli.log"
  make_health_fakes "$fake_bin"

  FAKE_STATE_DIR="$state_dir" FAKE_REAL_PYTHON="$(command -v python3)" \
    FAKE_STATUS_MODE=start-ready FAKE_RESTART_SLEEP=6 FAKE_IGNORE_TERM=1 \
    OPENCLI_CONFIG_DIR="$state_dir/opencli-config" HOME="$fake_home" PATH="$fake_bin:$PATH" bash "$HEALTH_SCRIPT" > "$state_dir/killed-output.json" &
  health_pid=$!
  for _ in $(seq 1 200); do
    [[ -r "$state_dir/spawned-pid" ]] && break
    sleep 0.01
  done
  if [[ ! -r "$state_dir/spawned-pid" ]]; then
    kill -KILL "$health_pid" 2>/dev/null || true
    wait "$health_pid" 2>/dev/null || true
    bad "SIGKILL 前未进入 daemon 启动临界区"
    return
  fi
  spawned_pid=$(<"$state_dir/spawned-pid")
  kill -KILL "$health_pid" 2>/dev/null || true
  wait "$health_pid" 2>/dev/null || true
  kill -KILL "$spawned_pid" 2>/dev/null || true
  wait "$spawned_pid" 2>/dev/null || true

  set +e
  output=$(FAKE_HOME="$fake_home" run_health start-ready)
  status=$?
  set -e
  if [[ "$status" -eq 0 ]]; then
    assert_json "持锁进程被 SIGKILL 后内核立即释放启动锁" "$output" '.ok == true and .state == "ready" and .started_daemon == true'
  else
    bad "SIGKILL 后启动锁没有立即恢复：status=${status} output=${output}"
  fi
}

test_child_process_cannot_extend_start_lock() {
  local state_dir="$TEST_ROOT/state-blocked-second-probe"
  local fake_bin="$state_dir/bin"
  local fake_home="$state_dir/home"
  local lock_file="$fake_home/tmp/lookup-runtime/opencli-health-daemon.v2.flock"
  local health_pid blocked_pid lock_status
  mkdir -p "$state_dir" "$fake_home/tmp"
  : > "$state_dir/opencli.log"
  make_health_fakes "$fake_bin"

  FAKE_STATE_DIR="$state_dir" FAKE_REAL_PYTHON="$(command -v python3)" \
    FAKE_STATUS_MODE=blocked-second-probe HOME="$fake_home" PATH="$fake_bin:$PATH" \
    OPENCLI_CONFIG_DIR="$state_dir/opencli-config" bash "$HEALTH_SCRIPT" > "$state_dir/killed-during-probe.json" &
  health_pid=$!
  for _ in $(seq 1 200); do
    [[ -e "$state_dir/probe-blocked" ]] && break
    sleep 0.01
  done
  if [[ ! -r "$state_dir/blocked-curl-pid" ]]; then
    kill -KILL "$health_pid" 2>/dev/null || true
    wait "$health_pid" 2>/dev/null || true
    bad "未进入持锁后的长子进程夹具"
    return
  fi
  blocked_pid=$(<"$state_dir/blocked-curl-pid")
  kill -KILL "$health_pid" 2>/dev/null || true
  wait "$health_pid" 2>/dev/null || true
  set +e
  python3 - "$lock_file" <<'PY'
import errno
import fcntl
import sys
import time

deadline = time.monotonic() + 0.3
with open(sys.argv[1], 'a') as lock_file:
    while True:
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            raise SystemExit(0)
        except OSError as exc:
            if exc.errno not in (errno.EACCES, errno.EAGAIN):
                raise
        if time.monotonic() >= deadline:
            raise SystemExit(75)
        time.sleep(0.01)
PY
  lock_status=$?
  set -e
  kill -KILL "$blocked_pid" 2>/dev/null || true
  wait "$blocked_pid" 2>/dev/null || true
  if [[ "$lock_status" -eq 0 ]]; then
    ok "普通子进程不能延长健康门禁内核锁"
  else
    bad "顶层进程退出后普通子进程仍持有健康门禁锁"
  fi
}

test_restart_timeout_recognizes_daemon_that_started() {
  local output status wall_start_ms wall_end_ms wall_elapsed_ms spawned_pid
  set +e
  wall_start_ms=$(python3 -c 'import time; print(int(time.monotonic() * 1000))')
  output=$(FAKE_RESTART_SLEEP=6 FAKE_IGNORE_TERM=1 FAKE_START_BEFORE_SLEEP=1 FAKE_REAL_TIME=1 run_health start-ready 100)
  status=$?
  wall_end_ms=$(python3 -c 'import time; print(int(time.monotonic() * 1000))')
  wall_elapsed_ms=$((wall_end_ms - wall_start_ms))
  spawned_pid=$(<"$TEST_ROOT/state-start-ready/spawned-pid")
  set -e
  [[ "$status" -eq 0 ]] || { bad "restart 超时但 daemon 已启动时继续探活：status=${status} output=${output}"; return; }
  if kill -0 "$spawned_pid" 2>/dev/null; then
    bad "测试夹具没有回收忽略 TERM 的假 daemon：pid=${spawned_pid}"
  elif [[ "$wall_elapsed_ms" -lt 5000 ]]; then
    assert_json "restart 超时但 daemon 已启动时正确认领" "$output" '.ok == true and .state == "ready" and .started_daemon == true and .elapsed_ms < 5000'
  else
    bad "restart 超时后的状态确认突破总预算：${wall_elapsed_ms}ms"
  fi
}

test_term_ignored_escalates_to_exact_pid_kill() {
  local output status
  set +e
  output=$(FAKE_STOP_FAIL=1 run_health start-profile-required 100)
  status=$?
  set -e
  [[ "$status" -eq 78 ]] || { bad "恢复时仍保留原失败码：status=${status} output=${output}"; return; }
  assert_json "TERM 被忽略时只对本次 PID 升级 KILL" "$output" '.state == "profile_required" and .daemon == "stopped" and .started_daemon == true and .restored_daemon == true'
}

test_signal_waits_for_detached_daemon_and_restores() {
  local state_dir="$TEST_ROOT/state-signal-delayed"
  local fake_bin="$state_dir/bin"
  local health_pid marker_pid status stop_count spawned_pid wall_start wall_end wall_elapsed lock_status
  mkdir -p "$state_dir/home/tmp"
  : > "$state_dir/opencli.log"
  make_health_fakes "$fake_bin"
  rm -f -- "$fake_bin/python3"
  ln -s "$(command -v python3)" "$fake_bin/python3"

  FAKE_STATE_DIR="$state_dir" FAKE_REAL_PYTHON="$(command -v python3)" \
    FAKE_STATUS_MODE=start-delayed-ready FAKE_DAEMON_PID="$$" \
    FAKE_START_BEFORE_SLEEP=1 FAKE_RESTART_SLEEP=6 FAKE_IGNORE_TERM=1 \
    HOME="$state_dir/home" PATH="$fake_bin:$PATH" \
    OPENCLI_CONFIG_DIR="$state_dir/opencli-config" bash "$HEALTH_SCRIPT" > "$state_dir/output.json" &
  health_pid=$!

  for _ in $(seq 1 300); do
    [[ -f "$state_dir/restarted" ]] && break
    sleep 0.01
  done
  if [[ ! -f "$state_dir/restarted" ]]; then
    kill -KILL "$health_pid" 2>/dev/null || true
    wait "$health_pid" 2>/dev/null || true
    bad "信号恢复测试等待假 daemon 启动超时"
    return
  fi
  # OpenCLI 的 detached 子进程可能在父命令被中断后才开始监听；1.5 秒覆盖
  # 旧实现只等 750ms、随后漏回收 daemon 的竞态。
  (sleep 1.5; : > "$state_dir/status-ready") &
  marker_pid=$!
  sleep 0.05
  wall_start=$(python3 -c 'import time; print(int(time.monotonic() * 1000))')
  kill -TERM "$health_pid"
  sleep 0.05
  kill -TERM "$health_pid" 2>/dev/null || true
  set +e
  wait "$health_pid"
  status=$?
  set -e
  wait "$marker_pid" 2>/dev/null || true
  wall_end=$(python3 -c 'import time; print(int(time.monotonic() * 1000))')
  wall_elapsed=$((wall_end - wall_start))
  stop_count=$(grep -c '^stop:' "$state_dir/opencli.log" || true)
  spawned_pid=$(<"$state_dir/spawned-pid")
  python3 - "$state_dir/home/tmp/lookup-runtime/opencli-health-daemon.v2.flock" <<'PY'
import fcntl
import sys

with open(sys.argv[1], 'a') as lock_file:
    fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
PY
  lock_status=$?

  if [[ "$status" -eq 130 ]] && [[ "$stop_count" -eq 1 ]] \
    && ! kill -0 "$spawned_pid" 2>/dev/null && [[ "$wall_elapsed" -lt 3500 ]] \
    && [[ "$lock_status" -eq 0 ]]; then
    ok "连续信号后仍等待 detached daemon 可见并只恢复本次实例"
  else
    bad "信号恢复竞态未关闭：status=${status} stop=${stop_count} wall=${wall_elapsed}"
  fi
}

test_signal_handler_blocks_reentry_during_restore() {
  local handler
  handler=$(sed -n '/^handle_signal()/,/^}/p' "$HEALTH_SCRIPT")
  if grep -F "trap '' HUP INT TERM" >/dev/null <<<"$handler"; then
    ok "信号恢复期间忽略重入信号"
  else
    bad "信号恢复期间仍可能被第二个信号打断"
  fi
}

test_first_visible_daemon_is_not_misclaimed() {
  local state_dir="$TEST_ROOT/state-start-profile-replaced"
  local output status stop_count replacement_pid
  mkdir -p "$state_dir"
  : > "$state_dir/opencli.log"
  sleep 10 &
  replacement_pid=$!
  set +e
  output=$(FAKE_FIRST_REPLACEMENT=1 FAKE_REPLACEMENT_PID="$replacement_pid" run_health start-profile-replaced)
  status=$?
  set -e
  stop_count=$(grep -c '^stop:' "$state_dir/opencli.log" 2>/dev/null || true)
  if [[ "$status" -eq 78 ]] && [[ "$stop_count" -eq 1 ]] \
    && kill -0 "$replacement_pid" 2>/dev/null; then
    assert_json "首次可见的替代 daemon 不会被误认领" "$output" '.state == "profile_required" and .restored_daemon == true and .daemon == "running"'
  else
    bad "首次可见替代 daemon 被误停：status=${status} stop=${stop_count} output=${output}"
  fi
  kill "$replacement_pid" 2>/dev/null || true
  wait "$replacement_pid" 2>/dev/null || true
}

test_restore_does_not_stop_replacement_daemon() {
  local state_dir="$TEST_ROOT/state-start-profile-replaced"
  local output status stop_count replacement_pid
  mkdir -p "$state_dir"
  : > "$state_dir/opencli.log"
  sleep 10 &
  replacement_pid=$!
  set +e
  output=$(FAKE_REPLACEMENT_PID="$replacement_pid" run_health start-profile-replaced)
  status=$?
  set -e
  stop_count=$(grep -c '^stop:' "$state_dir/opencli.log" 2>/dev/null || true)
  if [[ "$status" -eq 78 ]] && [[ "$stop_count" -eq 1 ]] \
    && kill -0 "$replacement_pid" 2>/dev/null; then
    assert_json "本次 daemon 被替换时不停止其他实例" "$output" '.state == "profile_required" and .started_daemon == true and .restored_daemon == true and .daemon == "running"'
  else
    bad "错误停止替代 daemon：status=${status} stop=${stop_count} output=${output}"
  fi
  kill "$replacement_pid" 2>/dev/null || true
  wait "$replacement_pid" 2>/dev/null || true
}

test_profile_required_is_config_error() {
  local output status
  set +e
  output=$(run_health profile-required)
  status=$?
  set -e
  [[ "$status" -eq 78 ]] || { bad "多 Profile 未选择时退出 78"; return; }
  assert_json "多 Profile 未选择不是扩展断连" "$output" '.ok == false and .state == "profile_required" and .extension == "connected"'
}

test_profile_disconnected_is_config_error() {
  local output status
  set +e
  output=$(run_health profile-disconnected)
  status=$?
  set -e
  [[ "$status" -eq 78 ]] || { bad "指定 Profile 断连时退出 78"; return; }
  assert_json "指定 Profile 断连给准确状态" "$output" '.ok == false and .state == "profile_disconnected" and .extension == "disconnected"'
}

test_ego_lite_profile_must_be_bound() {
  local state_dir="$TEST_ROOT/state-ready"
  local output status
  prepare_health_fixture ready
  rm -f -- "$state_dir/opencli-config/browser-profiles.json"
  set +e
  output=$(FAKE_HEALTH_PREPARED=1 run_health ready)
  status=$?
  set -e
  if [[ "$status" -eq 78 ]]; then
    assert_json "未绑定 ego-lite Profile 时关闭失败" "$output" '.ok == false and .state == "profile_unbound"'
  else
    bad "未绑定 ego-lite Profile 仍通过门禁：status=${status} output=${output}"
  fi
}

test_other_profile_online_does_not_pass_ego_lite_gate() {
  local output status
  set +e
  output=$(run_health wrong-profile-online)
  status=$?
  set -e
  if [[ "$status" -eq 78 ]]; then
    assert_json "只有其他 Profile 在线时拒绝冒充 ego lite" "$output" '.ok == false and .state == "profile_disconnected"'
  else
    bad "其他 Profile 在线时错误放行：status=${status} output=${output}"
  fi
}

test_registry_stderr_does_not_pollute_json() {
  local fixture_dir="$TEST_ROOT/registry-fixture"
  local fake_bin="$fixture_dir/bin"
  local fake_home="$fixture_dir/home"
  local output reader_pid runtime_mode
  mkdir -p "$fixture_dir/scripts" "$fixture_dir/references" "$fake_bin" "$fake_home/.agents/skills/read/scripts"
  : > "$fake_home/.agents/skills/read/scripts/fetch.sh"
  cp "$ROOT_DIR/scripts/selftest.sh" "$fixture_dir/scripts/selftest.sh"
  cp "$ROOT_DIR/scripts/flock-holder.py" "$fixture_dir/scripts/flock-holder.py"
  cp "$ROOT_DIR/scripts/find-url.mjs" "$ROOT_DIR/scripts/match-site.mjs" "$ROOT_DIR/scripts/ego-spaces.mjs" "$fixture_dir/scripts/"
  cp "$ROOT_DIR/references/providers.json" "$fixture_dir/references/providers.json"

  jq '[.actions[] | .providers[] | select(.type == "opencli" and (.status == "active" or .status == "conditional")) |
    (.command | split("/")) as $parts |
    {
      site: $parts[0],
      name: $parts[1],
      access: .required_access,
      args: ((.required_args | map({name: ., positional: false, choices: []})) + ((.policy_args // []) | map({name: .name, positional: false, choices: [.value]}))),
      columns: .required_columns
    }
  ]' "$ROOT_DIR/references/providers.json" > "$fixture_dir/registry.json"

  printf '%s\n' \
    '#!/usr/bin/env bash' \
    'if [[ "${1:-}" == "list" ]]; then' \
    '  cat "$FAKE_REGISTRY_JSON"' \
    '  printf "Update available: test banner\n" >&2' \
    '  exit 0' \
    'fi' \
    'if [[ "${1:-}" == "--version" ]]; then printf "1.8.8\n"; exit 0; fi' \
    'if [[ "${1:-}" == "verify" ]]; then exit 0; fi' \
    'if [[ "${1:-} ${2:-}" == "auth status" ]]; then printf "[]\n"; exit 0; fi' \
    'exit 2' > "$fake_bin/opencli"
  chmod +x "$fake_bin/opencli"

  printf '%s\n' \
    '#!/usr/bin/env node' \
    'import { spawnSync } from "node:child_process"' \
    'const result = spawnSync("opencli", process.argv.slice(2), { stdio: "inherit" })' \
    'process.exit(result.status ?? 1)' > "$fixture_dir/scripts/opencli-run.mjs"

  printf '%s\n' \
    '#!/usr/bin/env bash' \
    'printf "%s\n" '\''{"ok":true,"state":"ready","daemon":"running","extension":"connected","started_daemon":false,"restored_daemon":false,"elapsed_ms":1,"next":"use_opencli"}'\''' > "$fixture_dir/scripts/opencli-health.sh"
  chmod +x "$fixture_dir/scripts/opencli-health.sh"

  bash -c 'sleep 5' 'review-selftest.sh' &
  reader_pid=$!
  set +e
  output=$(HOME="$fake_home" FAKE_REGISTRY_JSON="$fixture_dir/registry.json" PATH="$fake_bin:$PATH" bash "$fixture_dir/scripts/selftest.sh" 2>&1)
  set -e
  kill "$reader_pid" 2>/dev/null || true
  wait "$reader_pid" 2>/dev/null || true
  if runtime_mode=$(stat -f '%Lp' "$fake_home/tmp/lookup-runtime" 2>/dev/null); then :; else runtime_mode=$(stat -c '%a' "$fake_home/tmp/lookup-runtime" 2>/dev/null || true); fi
  if [[ "$output" == *"opencli list 未返回非空 JSON 数组"* ]]; then
    bad "stderr 升级提示没有污染注册表 JSON"
  elif [[ "$output" == *"opencli list 返回 12 条结构化命令"* ]] \
    && [[ "$runtime_mode" == "700" ]]; then
    ok "stderr 升级提示不污染 JSON，selftest 使用私有运行目录"
  else
    bad "注册表或私有运行目录测试未命中成功判据：mode=${runtime_mode} ${output:0:180}"
  fi
}

test_selftest_kernel_lock_blocks_parallel_run() {
  local fixture_dir="$TEST_ROOT/registry-fixture"
  local fake_home="$fixture_dir/home"
  local lock_file="$fake_home/tmp/lookup-runtime/lookup-selftest.v2.flock"
  local ready_file="$fixture_dir/selftest-lock-ready"
  local output status holder_pid
  python3 - "$lock_file" "$ready_file" <<'PY' &
import fcntl
import pathlib
import sys
import time

with open(sys.argv[1], 'a') as lock_file:
    fcntl.flock(lock_file, fcntl.LOCK_EX)
    pathlib.Path(sys.argv[2]).touch()
    time.sleep(5)
PY
  holder_pid=$!
  for _ in $(seq 1 100); do
    [[ -e "$ready_file" ]] && break
    sleep 0.01
  done
  set +e
  output=$(HOME="$fake_home" FAKE_REGISTRY_JSON="$fixture_dir/registry.json" PATH="$fixture_dir/bin:$PATH" bash "$fixture_dir/scripts/selftest.sh" 2>&1)
  status=$?
  set -e
  kill "$holder_pid" 2>/dev/null || true
  wait "$holder_pid" 2>/dev/null || true
  if [[ "$status" -eq 2 ]] && [[ "$output" == *"已有 selftest 在跑"* ]]; then
    ok "selftest 内核锁阻止并发执行"
  else
    bad "selftest 内核锁没有阻止并发执行：status=${status} output=${output:0:160}"
  fi
}

test_async_runner_waits_for_browser_action() {
  local fixture_dir="$TEST_ROOT/async-runner-fixture"
  local package_dir="$fixture_dir/opencli-package"
  local fake_bin="$fixture_dir/bin"
  local direct_output wrapped_output direct_status wrapped_status
  mkdir -p "$package_dir/build/runtime/cli" "$package_dir/node_modules/commander" "$fake_bin"

  printf '%s\n' '{"type":"module","bin":{"opencli":"build/runtime/cli/main.mjs"}}' > "$package_dir/package.json"
  printf '%s\n' '{"type":"module","exports":{".":"./esm.mjs","./esm.mjs":"./esm.mjs"}}' > "$package_dir/node_modules/commander/package.json"
  printf '%s\n' \
    'export class Command {' \
    '  parseAsync() {' \
    '    if (process.env.FAKE_NEVER === "1") return { then() {} }' \
    '    if (process.env.FAKE_DELAY_MS) return new Promise(resolve => setTimeout(() => { process.stdout.write("delayed-result\n"); resolve() }, Number(process.env.FAKE_DELAY_MS)))' \
    '    return { then(resolve) { process.stdout.write("async-result\n"); resolve() } }' \
    '  }' \
    '  parse() { this.parseAsync(); return this }' \
    '}' > "$package_dir/node_modules/commander/esm.mjs"
  printf '%s\n' \
    '#!/usr/bin/env node' \
    'import { Command } from "commander"' \
    'if (process.env.FAKE_PRINT_PROFILE === "1") process.stdout.write(`profile=${process.env.OPENCLI_PROFILE}\n`)' \
    'new Command().parse()' > "$package_dir/build/runtime/cli/main.mjs"
  chmod +x "$package_dir/build/runtime/cli/main.mjs"
  ln -s "$package_dir/build/runtime/cli/main.mjs" "$fake_bin/opencli"

  set +e
  direct_output=$(PATH="$fake_bin:$PATH" opencli)
  direct_status=$?
  wrapped_output=$(PATH="$fake_bin:$PATH" node "$RUN_SCRIPT")
  wrapped_status=$?
  set -e

  if [[ "$direct_status" -eq 0 ]] && [[ -z "$direct_output" ]] \
    && [[ "$wrapped_status" -eq 0 ]] && [[ "$wrapped_output" == "async-result" ]]; then
    ok "异步兼容入口等待 browser action，避免退出 0 但 stdout 为空"
  else
    bad "异步兼容入口行为异常：direct=${direct_status}/${direct_output} wrapped=${wrapped_status}/${wrapped_output}"
  fi
}

test_async_runner_forces_ego_lite_profile() {
  local fixture_dir="$TEST_ROOT/async-runner-fixture"
  local fake_bin="$fixture_dir/bin"
  local output status rejected rejected_status
  set +e
  output=$(FAKE_PRINT_PROFILE=1 PATH="$fake_bin:$PATH" node "$RUN_SCRIPT")
  status=$?
  rejected=$(PATH="$fake_bin:$PATH" node "$RUN_SCRIPT" --profile chrome 2>&1)
  rejected_status=$?
  set -e
  if [[ "$status" -eq 0 ]] && [[ "$output" == *"profile=ego-lite"* ]] \
    && [[ "$rejected_status" -eq 78 ]] && [[ "$rejected" == *"OPENCLI_PROFILE_REJECTED"* ]]; then
    ok "runner 强制使用 ego-lite 并拒绝其他 Profile"
  else
    bad "runner Profile 边界异常：status=${status}/${rejected_status} output=${output} rejected=${rejected}"
  fi
}

test_async_runner_does_not_cut_off_dispatched_action() {
  local fixture_dir="$TEST_ROOT/async-runner-fixture"
  local fake_bin="$fixture_dir/bin"
  local output status
  set +e
  output=$(FAKE_DELAY_MS=100 OPENCLI_RUN_HARD_TIMEOUT_MS=50 PATH="$fake_bin:$PATH" node "$RUN_SCRIPT" 2>&1)
  status=$?
  set -e
  if [[ "$status" -eq 0 ]] && [[ "$output" == "delayed-result" ]]; then
    ok "runner 不会提前截断已派发的 OpenCLI 动作"
  else
    bad "runner 提前截断或丢失异步结果：status=${status} output=${output}"
  fi
}

test_async_runner_times_out_during_entry_import() {
  local fixture_dir="$TEST_ROOT/async-runner-fixture"
  local package_dir="$fixture_dir/opencli-package"
  local fake_bin="$fixture_dir/bin"
  local output_file="$fixture_dir/import-timeout.out"
  local output status runner_pid attempt process_state
  printf '%s\n' \
    '#!/usr/bin/env node' \
    'import { Command } from "commander"' \
    'if (process.env.FAKE_IMPORT_NEVER === "1") await new Promise(() => {})' \
    'new Command().parse()' > "$package_dir/build/runtime/cli/main.mjs"

  set +e
  FAKE_IMPORT_NEVER=1 OPENCLI_RUN_HARD_TIMEOUT_MS=50 PATH="$fake_bin:$PATH" node "$RUN_SCRIPT" > "$output_file" 2>&1 &
  runner_pid=$!
  for attempt in $(seq 1 100); do
    process_state=$(ps -o stat= -p "$runner_pid" 2>/dev/null | tr -d '[:space:]')
    [[ -n "$process_state" ]] && [[ "$process_state" != Z* ]] || break
    sleep 0.01
  done
  process_state=$(ps -o stat= -p "$runner_pid" 2>/dev/null | tr -d '[:space:]')
  if [[ -n "$process_state" ]] && [[ "$process_state" != Z* ]]; then
    kill -KILL "$runner_pid" 2>/dev/null || true
    wait "$runner_pid" 2>/dev/null || true
    status=124
  else
    wait "$runner_pid"
    status=$?
  fi
  output=$(<"$output_file")
  set -e
  if [[ "$status" -eq 75 ]] && [[ "$output" == *"OPENCLI_RUN_IMPORT_TIMEOUT"* ]]; then
    ok "异步兼容入口的硬超时覆盖顶层动态加载"
  else
    bad "顶层动态加载硬超时异常：status=${status} output=${output}"
  fi
}

test_auth_batch_requires_explicit_sites() {
  local rejected rejected_status prefixed prefixed_status
  local root_sep root_sep_status auth_sep auth_sep_status refresh_sep refresh_sep_status
  set +e
  rejected=$(node "$RUN_SCRIPT" auth status --timeout 8 2>&1)
  rejected_status=$?
  prefixed=$(node "$RUN_SCRIPT" --profile ego-lite auth status --timeout 8 2>&1)
  prefixed_status=$?
  root_sep=$(node "$RUN_SCRIPT" --profile ego-lite -- auth status --timeout 8 2>&1)
  root_sep_status=$?
  auth_sep=$(node "$RUN_SCRIPT" --profile ego-lite auth -- status --timeout 8 2>&1)
  auth_sep_status=$?
  refresh_sep=$(node "$RUN_SCRIPT" auth -- refresh --timeout 8 2>&1)
  refresh_sep_status=$?
  set -e
  if [[ "$rejected_status" -eq 78 ]] && [[ "$rejected" == *"OPENCLI_AUTH_SITE_REQUIRED"* ]] \
    && [[ "$prefixed_status" -eq 78 ]] && [[ "$prefixed" == *"OPENCLI_AUTH_SITE_REQUIRED"* ]] \
    && [[ "$root_sep_status" -eq 78 ]] && [[ "$root_sep" == *"OPENCLI_AUTH_SITE_REQUIRED"* ]] \
    && [[ "$auth_sep_status" -eq 78 ]] && [[ "$auth_sep" == *"OPENCLI_AUTH_SITE_REQUIRED"* ]] \
    && [[ "$refresh_sep_status" -eq 78 ]] && [[ "$refresh_sep" == *"OPENCLI_AUTH_SITE_REQUIRED"* ]]; then
    ok "runner 要求 auth 批量检查显式限定站点，且全局参数与两层 -- 不能绕过"
  else
    bad "auth 批量范围未关闭：plain=${rejected_status}/${rejected} prefixed=${prefixed_status}/${prefixed} root_sep=${root_sep_status}/${root_sep} auth_sep=${auth_sep_status}/${auth_sep} refresh_sep=${refresh_sep_status}/${refresh_sep}"
  fi
}

printf 'OpenCLI health 回归\n'
test_ready_without_restart
test_start_then_ready
test_cold_start_waits_for_profile_reconnect
test_daemon_does_not_inherit_start_lock
test_running_disconnected_fails_fast
test_started_daemon_is_restored_on_failure
test_daemon_start_failure
test_invalid_status_does_not_claim_existing_daemon
test_lifecycle_commands_have_hard_timeout
test_concurrent_cold_start_has_single_owner
test_legacy_malformed_lock_does_not_block_kernel_lock
test_legacy_ownerless_lock_does_not_block_kernel_lock
test_start_lock_releases_after_sigkill
test_child_process_cannot_extend_start_lock
test_restart_timeout_recognizes_daemon_that_started
test_term_ignored_escalates_to_exact_pid_kill
test_signal_waits_for_detached_daemon_and_restores
test_signal_handler_blocks_reentry_during_restore
test_first_visible_daemon_is_not_misclaimed
test_restore_does_not_stop_replacement_daemon
test_profile_required_is_config_error
test_profile_disconnected_is_config_error
test_ego_lite_profile_must_be_bound
test_other_profile_online_does_not_pass_ego_lite_gate
test_registry_stderr_does_not_pollute_json
test_selftest_kernel_lock_blocks_parallel_run
test_async_runner_waits_for_browser_action
test_async_runner_forces_ego_lite_profile
test_async_runner_does_not_cut_off_dispatched_action
test_async_runner_times_out_during_entry_import
test_auth_batch_requires_explicit_sites

leaked_fake_daemons=0
while IFS= read -r pid_file; do
  state_dir="${pid_file%/spawned-pid}"
  spawned_pid=$(<"$pid_file")
  if fake_daemon_is_current "$spawned_pid" "$state_dir/bin/daemon.js"; then
    leaked_fake_daemons=$((leaked_fake_daemons + 1))
  fi
done < <(find "$TEST_ROOT" -type f -name spawned-pid -print)
if [[ "$leaked_fake_daemons" -eq 0 ]]; then
  ok "回归套件结束后没有遗留假 daemon"
else
  bad "回归套件遗留 ${leaked_fake_daemons} 个假 daemon"
fi

printf '结果：通过 %d，失败 %d\n' "$PASS" "$FAIL"
[[ "$FAIL" -eq 0 ]]
