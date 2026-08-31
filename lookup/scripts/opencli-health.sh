#!/usr/bin/env bash
# OpenCLI daemon 与 ego lite Browser Bridge 的零业务请求健康门禁。
# 用户侧墙钟不超过 5 秒：内部桥接等待最多 3.2 秒，预留 0.75 秒恢复
# 本次启动的 daemon、0.25 秒渲染，并给解释器启动与系统调度留 0.8 秒余量。

set -uo pipefail

STATUS_URL_BASE="http://127.0.0.1:19825/status"
STATUS_URL=""
PROFILE_ALIAS="ego-lite"
PROFILE_CONTEXT_ID=""
TOTAL_BUDGET_MS=4200
START_BUDGET_MS=3200
STOP_TOTAL_BUDGET_MS=750
RUNTIME_DIR="${HOME:-}/tmp/lookup-runtime"
LOCK_FILE="$RUNTIME_DIR/opencli-health-daemon.v2.flock"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCK_HOLDER="$SCRIPT_DIR/flock-holder.py"
started_daemon=false
started_daemon_pid=""
started_daemon_fingerprint=""
restored_daemon=false
restored_daemon_state=unknown
lock_owned=false
lock_holder_pid=""
lock_status_file=""
daemon_entry=""
node_bin=""
signal_pending=false
start_ms=0
start_deadline_ms=0
overall_deadline_ms=0

fixed_error() {
  local state="$1"
  local next="$2"
  local exit_code="$3"
  printf '{"ok":false,"state":"%s","daemon":"unknown","extension":"unknown","started_daemon":false,"restored_daemon":false,"elapsed_ms":0,"next":"%s"}\n' "$state" "$next"
  exit "$exit_code"
}

if ! command -v python3 >/dev/null 2>&1; then
  fixed_error "dependency_missing" "install_python3" 78
fi

now_ms() {
  python3 -c 'import time; print(int(time.monotonic() * 1000))'
}

start_ms=$(now_ms)

for dependency in opencli curl jq node; do
  if ! command -v "$dependency" >/dev/null 2>&1; then
    fixed_error "dependency_missing" "install_$dependency" 78
  fi
done

resolve_ego_lite_profile() {
  local config_dir="${OPENCLI_CONFIG_DIR:-${HOME:-}/.opencli}"
  local config_file="$config_dir/browser-profiles.json"
  local encoded_context
  [[ -r "$config_file" ]] || return 1
  PROFILE_CONTEXT_ID=$(jq -er --arg alias "$PROFILE_ALIAS" \
    '.aliases[$alias] | select(type == "string" and length > 0)' "$config_file" 2>/dev/null) || return 1
  [[ "$PROFILE_CONTEXT_ID" != *$'\n'* ]] || return 1
  encoded_context=$(jq -nr --arg value "$PROFILE_CONTEXT_ID" '$value | @uri') || return 1
  STATUS_URL="${STATUS_URL_BASE}?contextId=${encoded_context}"
}

if ! resolve_ego_lite_profile; then
  fixed_error "profile_unbound" "bind_ego_lite_profile" 78
fi

elapsed_ms() {
  local current
  current=$(now_ms)
  printf '%s\n' "$((current - start_ms))"
}

remaining_until_ms() {
  local remaining=$(( $1 - $(now_ms) ))
  [[ "$remaining" -gt 0 ]] || remaining=0
  printf '%s\n' "$remaining"
}

min_ms() {
  if [[ "$1" -le "$2" ]]; then printf '%s\n' "$1"; else printf '%s\n' "$2"; fi
}

read_status() {
  local timeout_ms="${1:-1000}"
  local timeout_seconds
  [[ "$timeout_ms" -gt 0 ]] || timeout_ms=1
  printf -v timeout_seconds '%d.%03d' "$((timeout_ms / 1000))" "$((timeout_ms % 1000))"
  curl --silent --show-error --connect-timeout "$timeout_seconds" --max-time "$timeout_seconds" \
    -H 'X-OpenCLI: 1' \
    "$STATUS_URL" 2>/dev/null
}

status_is_ready() {
  jq -e --arg context_id "$PROFILE_CONTEXT_ID" \
    '.extensionConnected == true and .contextId == $context_id' >/dev/null 2>&1 <<<"$1"
}

process_is_done() {
  local process_state
  process_state=$(ps -o stat= -p "$1" 2>/dev/null | tr -d '[:space:]')
  [[ -z "$process_state" ]] || [[ "$process_state" == Z* ]]
}

release_start_lock() {
  if [[ "$lock_holder_pid" =~ ^[0-9]+$ ]]; then
    kill -TERM "$lock_holder_pid" 2>/dev/null || true
    wait "$lock_holder_pid" 2>/dev/null || true
  fi
  lock_holder_pid=""
  if [[ -n "$lock_status_file" ]]; then
    rm -f -- "$lock_status_file"
  fi
  lock_status_file=""
  lock_owned=false
}

process_fingerprint() {
  ps -o lstart= -p "$1" 2>/dev/null | tr -d '[:space:]'
}

process_command() {
  ps -o command= -p "$1" 2>/dev/null
}

claim_spawned_daemon() {
  local daemon_pid="$1"
  local fingerprint
  started_daemon=true
  [[ "$daemon_pid" =~ ^[0-9]+$ ]] || return 1
  fingerprint=$(process_fingerprint "$daemon_pid")
  [[ -n "$fingerprint" ]] || return 1
  started_daemon_pid="$daemon_pid"
  started_daemon_fingerprint="$fingerprint"
}

started_daemon_is_current() {
  local command_line
  [[ -n "$started_daemon_pid" ]] && [[ -n "$started_daemon_fingerprint" ]] || return 1
  [[ "$(process_fingerprint "$started_daemon_pid")" == "$started_daemon_fingerprint" ]] || return 1
  command_line=$(process_command "$started_daemon_pid")
  [[ -n "$daemon_entry" ]] && [[ "$command_line" == *"$daemon_entry"* ]]
}

resolve_daemon_entry() {
  local opencli_path
  local opencli_real
  opencli_path=$(command -v opencli) || return 1
  opencli_real=$(node -e 'console.log(require("node:fs").realpathSync(process.argv[1]))' "$opencli_path") || return 1
  daemon_entry="$(dirname "$opencli_real")/daemon.js"
  node_bin=$(command -v node) || return 1
  [[ -f "$daemon_entry" ]] && [[ -x "$node_bin" ]]
}

acquire_start_lock() {
  local lock_status
  local lock_wait_ms
  lock_wait_ms=$(remaining_until_ms "$start_deadline_ms")
  [[ "$lock_wait_ms" -gt 0 ]] || return 75
  [[ -r "$LOCK_HOLDER" ]] || return 78
  lock_status_file=$(mktemp "$RUNTIME_DIR/opencli-health-lock.XXXXXX") || return 78
  python3 "$LOCK_HOLDER" "$LOCK_FILE" "$lock_status_file" "$lock_wait_ms" "$$" &
  lock_holder_pid=$!
  while [[ "$(remaining_until_ms "$start_deadline_ms")" -gt 0 ]]; do
    if [[ -s "$lock_status_file" ]]; then
      lock_status=$(<"$lock_status_file")
      if [[ "$lock_status" -eq 0 ]] && kill -0 "$lock_holder_pid" 2>/dev/null; then
        lock_owned=true
        return 0
      fi
      release_start_lock
      [[ "$lock_status" -eq 75 ]] && return 75
      return 78
    fi
    if ! kill -0 "$lock_holder_pid" 2>/dev/null; then
      wait "$lock_holder_pid" 2>/dev/null || true
      release_start_lock
      return 78
    fi
    sleep 0.02
  done
  release_start_lock
  return 75
}

prepare_runtime_dir() {
  [[ -n "${HOME:-}" ]] && [[ "$HOME" == /* ]] || return 1
  [[ ! -L "$HOME/tmp" ]] || return 1
  mkdir -p "$HOME/tmp" 2>/dev/null || return 1
  [[ -d "$HOME/tmp" ]] && [[ -O "$HOME/tmp" ]] || return 1
  [[ ! -L "$RUNTIME_DIR" ]] || return 1
  mkdir -p "$RUNTIME_DIR" 2>/dev/null || return 1
  chmod 700 "$RUNTIME_DIR" 2>/dev/null || return 1
  [[ -d "$RUNTIME_DIR" ]] && [[ -O "$RUNTIME_DIR" ]] && [[ -w "$RUNTIME_DIR" ]]
}

emit() {
  local ok_value="$1"
  local state="$2"
  local daemon="$3"
  local extension="$4"
  local next="$5"
  local status_json="${6:-}"
  local elapsed
  local daemon_version=""
  local extension_version=""
  elapsed=$(elapsed_ms)

  if [[ -n "$status_json" ]]; then
    daemon_version=$(jq -r '.daemonVersion // empty' <<<"$status_json" 2>/dev/null || true)
    extension_version=$(jq -r '.extensionVersion // empty' <<<"$status_json" 2>/dev/null || true)
  fi

  jq -cn \
    --argjson ok "$ok_value" \
    --arg state "$state" \
    --arg daemon "$daemon" \
    --arg extension "$extension" \
    --argjson started_daemon "$started_daemon" \
    --argjson restored_daemon "$restored_daemon" \
    --argjson elapsed_ms "$elapsed" \
    --arg next "$next" \
    --arg daemon_version "$daemon_version" \
    --arg extension_version "$extension_version" '
      {
        ok: $ok,
        state: $state,
        daemon: $daemon,
        extension: $extension,
        started_daemon: $started_daemon,
        restored_daemon: $restored_daemon,
        elapsed_ms: $elapsed_ms,
        next: $next
      }
      + (if $daemon_version == "" then {} else {daemon_version: $daemon_version} end)
      + (if $extension_version == "" then {} else {extension_version: $extension_version} end)
    '
}

restore_started_daemon() {
  local current_status="${1:-}"
  local observed_pid=""
  local stop_deadline
  local stop_start
  local term_deadline
  local remaining_ms
  local probe_budget_ms
  [[ "$started_daemon" == true ]] || return
  if [[ -n "$current_status" ]]; then
    observed_pid=$(jq -r '.pid // empty' <<<"$current_status" 2>/dev/null || true)
    [[ "$observed_pid" != "$started_daemon_pid" ]] || current_status=""
  fi

  stop_start=$(now_ms)
  stop_deadline=$((stop_start + STOP_TOTAL_BUDGET_MS))
  [[ "$stop_deadline" -le "$overall_deadline_ms" ]] || stop_deadline="$overall_deadline_ms"
  if process_is_done "$started_daemon_pid"; then
    wait "$started_daemon_pid" 2>/dev/null || true
    restored_daemon=true
  elif ! started_daemon_is_current; then
    restored_daemon_state=unknown
    return
  else
    # 只向本次直接生成且启动指纹仍一致的 PID 发信号；绝不经全局
    # /shutdown 端点，以免身份核验后端口 owner 被替换而误停别的任务。
    kill -TERM "$started_daemon_pid" 2>/dev/null || true
    term_deadline=$(min_ms "$stop_deadline" "$(( $(now_ms) + 500 ))")
    while started_daemon_is_current; do
      [[ "$(now_ms)" -lt "$term_deadline" ]] || break
      sleep 0.02
    done
    if started_daemon_is_current; then
      kill -KILL "$started_daemon_pid" 2>/dev/null || true
    fi
    while started_daemon_is_current; do
      [[ "$(now_ms)" -lt "$stop_deadline" ]] || break
      sleep 0.02
    done
    if ! started_daemon_is_current; then
      wait "$started_daemon_pid" 2>/dev/null || true
      restored_daemon=true
    else
      restored_daemon_state=unknown
      return
    fi
  fi

  remaining_ms=$(remaining_until_ms "$stop_deadline")
  if [[ "$remaining_ms" -gt 0 ]]; then
    probe_budget_ms=$(min_ms "$remaining_ms" 100)
    current_status=$(read_status "$probe_budget_ms" || true)
  fi
  if [[ -n "$current_status" ]] && jq -e 'type == "object" and .ok == true' >/dev/null 2>&1 <<<"$current_status"; then
    restored_daemon_state=running
  else
    restored_daemon_state=stopped
  fi
}

handle_signal() {
  trap '' HUP INT TERM
  overall_deadline_ms=$(( $(now_ms) + STOP_TOTAL_BUDGET_MS ))
  restore_started_daemon
  release_start_lock
  exit 130
}

defer_signal() {
  signal_pending=true
}

trap release_start_lock EXIT
trap handle_signal HUP INT TERM

start_deadline_ms=$((start_ms + START_BUDGET_MS))
overall_deadline_ms=$((start_ms + TOTAL_BUDGET_MS))
if ! prepare_runtime_dir; then
  emit false "lock_unavailable" "unknown" "unknown" "create_home_tmp" ""
  exit 78
fi
status_json=$(read_status)
status_result=$?

if [[ "$status_result" -eq 0 ]] && [[ -n "$status_json" ]] && jq -e 'type == "object" and .ok == true' >/dev/null 2>&1 <<<"$status_json"; then
  if jq -e '.profileRequired == true' >/dev/null 2>&1 <<<"$status_json"; then
    emit false "profile_required" "running" "connected" "select_ego_lite_profile" "$status_json"
    exit 78
  fi
  if jq -e '.profileDisconnected == true' >/dev/null 2>&1 <<<"$status_json"; then
    emit false "profile_disconnected" "running" "disconnected" "select_connected_ego_lite_profile" "$status_json"
    exit 78
  fi
  if status_is_ready "$status_json"; then
    emit true "ready" "running" "connected" "use_opencli" "$status_json"
    exit 0
  fi
  if jq -e '.extensionConnected == true' >/dev/null 2>&1 <<<"$status_json"; then
    emit false "profile_mismatch" "running" "connected" "rebind_ego_lite_profile" "$status_json"
    exit 78
  fi
  emit false "extension_disconnected" "running" "disconnected" "start_or_enable_opencli_extension_in_ego_lite" "$status_json"
  exit 69
fi

if [[ "$status_result" -ne 7 ]]; then
  emit false "daemon_unresponsive" "running" "unknown" "check_opencli_daemon" "$status_json"
  exit 75
fi

acquire_start_lock
lock_status=$?
if [[ "$lock_status" -ne 0 ]]; then
  if [[ "$lock_status" -eq 78 ]]; then
    emit false "lock_unavailable" "unknown" "unknown" "check_home_tmp_permissions" ""
    exit 78
  fi
  emit false "daemon_start_lock_timeout" "unknown" "unknown" "retry_opencli_health" ""
  exit 75
fi

# 另一并发任务可能已在持锁期间启动 daemon；锁内必须重新探活后才能认领。
remaining_ms=$(remaining_until_ms "$start_deadline_ms")
[[ "$remaining_ms" -gt 0 ]] || {
  emit false "daemon_start_lock_timeout" "unknown" "unknown" "retry_opencli_health" ""
  exit 75
}
remaining_ms=$(min_ms "$remaining_ms" 1000)
status_json=$(read_status "$remaining_ms")
status_result=$?
if [[ "$status_result" -eq 0 ]] && [[ -n "$status_json" ]] && jq -e 'type == "object" and .ok == true' >/dev/null 2>&1 <<<"$status_json"; then
  if jq -e '.profileRequired == true' >/dev/null 2>&1 <<<"$status_json"; then
    emit false "profile_required" "running" "connected" "select_ego_lite_profile" "$status_json"
    exit 78
  fi
  if jq -e '.profileDisconnected == true' >/dev/null 2>&1 <<<"$status_json"; then
    emit false "profile_disconnected" "running" "disconnected" "select_connected_ego_lite_profile" "$status_json"
    exit 78
  fi
  if status_is_ready "$status_json"; then
    emit true "ready" "running" "connected" "use_opencli" "$status_json"
    exit 0
  fi
  if jq -e '.extensionConnected == true' >/dev/null 2>&1 <<<"$status_json"; then
    emit false "profile_mismatch" "running" "connected" "rebind_ego_lite_profile" "$status_json"
    exit 78
  fi
  emit false "extension_disconnected" "running" "disconnected" "start_or_enable_opencli_extension_in_ego_lite" "$status_json"
  exit 69
fi
if [[ "$status_result" -ne 7 ]]; then
  emit false "daemon_unresponsive" "running" "unknown" "check_opencli_daemon" "$status_json"
  exit 75
fi

last_status=""
if ! resolve_daemon_entry; then
  emit false "daemon_entry_missing" "stopped" "unknown" "reinstall_opencli" ""
  exit 78
fi

# 直接运行 OpenCLI 安装包自己的 daemon 入口，PID 在生成瞬间即由本门禁持有。
# 启动临界区只暂存信号，记下 PID 与启动指纹后立刻恢复完整处理，避免
# detached 子进程尚未监听时无法证明归属。
trap defer_signal HUP INT TERM
python3 -c 'import os, sys; os.setsid(); os.execv(sys.argv[1], sys.argv[1:])' \
  "$node_bin" "$daemon_entry" 9>&- >/dev/null 2>&1 &
spawned_daemon_pid=$!
claim_spawned_daemon "$spawned_daemon_pid" || true
trap handle_signal HUP INT TERM
if [[ "$signal_pending" == true ]]; then
  handle_signal
fi

while :; do
  remaining_ms=$(remaining_until_ms "$start_deadline_ms")
  [[ "$remaining_ms" -gt 0 ]] || break
  probe_budget_ms=$(min_ms "$remaining_ms" 250)
  status_json=$(read_status "$probe_budget_ms" || true)
  if [[ -n "$status_json" ]] && jq -e 'type == "object" and .ok == true' >/dev/null 2>&1 <<<"$status_json"; then
    last_status="$status_json"
    if jq -e '.profileRequired == true' >/dev/null 2>&1 <<<"$status_json"; then
      restore_started_daemon "$status_json"
      emit false "profile_required" "$restored_daemon_state" "connected" "select_ego_lite_profile" "$status_json"
      exit 78
    fi
    # 本次刚启动的 daemon 可能先监听端口、随后才等到 ego lite 扩展重连；
    # 预算内保留断连状态继续轮询，既有 daemon 的稳定断连仍在上方立即失败。
    if status_is_ready "$status_json"; then
      emit true "ready" "running" "connected" "use_opencli" "$status_json"
      exit 0
    fi
    if jq -e '.extensionConnected == true' >/dev/null 2>&1 <<<"$status_json"; then
      restore_started_daemon "$status_json"
      emit false "profile_mismatch" "$restored_daemon_state" "connected" "rebind_ego_lite_profile" "$status_json"
      exit 78
    fi
  fi

  if process_is_done "$started_daemon_pid" && [[ -z "$last_status" ]]; then
    restore_started_daemon "$last_status"
    emit false "daemon_start_failed" "$restored_daemon_state" "unknown" "reinstall_opencli" ""
    exit 69
  fi

  sleep 0.25
done

restore_started_daemon "$last_status"
if [[ -n "$last_status" ]]; then
  if jq -e '.profileDisconnected == true' >/dev/null 2>&1 <<<"$last_status"; then
    emit false "profile_disconnected" "$restored_daemon_state" "disconnected" "select_connected_ego_lite_profile" "$last_status"
    exit 78
  fi
  emit false "extension_disconnected" "$restored_daemon_state" "disconnected" "start_or_enable_opencli_extension_in_ego_lite" "$last_status"
  exit 69
fi

emit false "daemon_timeout" "$restored_daemon_state" "unknown" "check_opencli_daemon" ""
exit 75
