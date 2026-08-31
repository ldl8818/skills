#!/usr/bin/env bash
set -uo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT="$ROOT_DIR/scripts/find-url.mjs"
TEST_ROOT="$HOME/tmp/lookup-find-url-test.$$"

cleanup() {
  case "$TEST_ROOT" in
    "$HOME"/tmp/lookup-find-url-test.*) rm -rf -- "$TEST_ROOT" ;;
  esac
}
trap cleanup EXIT

fake_home="$TEST_ROOT/home"
ego_dir="$fake_home/Library/Application Support/Citro Labs/ego lite/Default"
chrome_dir="$fake_home/Library/Application Support/Google/Chrome/Default"
fake_bin="$TEST_ROOT/bin"
history_path_log="$TEST_ROOT/history-path.log"
history_mode_log="$TEST_ROOT/history-mode.log"
sqlite_pid_log="$TEST_ROOT/sqlite-pid.log"
mkdir -p "$ego_dir" "$chrome_dir" "$fake_bin"

printf '%s\n' '{"roots":{"bookmark_bar":{"children":[{"type":"url","name":"Ego Internal Portal","url":"https://ego.invalid/internal"}]}}}' > "$ego_dir/Bookmarks"
printf '%s\n' '{"roots":{"bookmark_bar":{"children":[{"type":"url","name":"Chrome Internal Portal","url":"https://chrome.invalid/internal"}]}}}' > "$chrome_dir/Bookmarks"
: > "$ego_dir/History"

printf '%s\n' \
  '#!/usr/bin/env bash' \
  'printf "%s" "$3" > "$FIND_URL_DB_PATH_LOG"' \
  'if mode=$(stat -f '\''%Lp'\'' "$3" 2>/dev/null); then :; else mode=$(stat -c '\''%a'\'' "$3" 2>/dev/null || true); fi' \
  'printf "%s" "$mode" > "$FIND_URL_DB_MODE_LOG"' \
  '[[ -z "${FIND_URL_SQLITE_PID_LOG:-}" ]] || printf "%s" "$$" > "$FIND_URL_SQLITE_PID_LOG"' \
  '[[ "${FIND_URL_SQLITE_SLEEP:-0}" == 0 ]] || exec sleep "$FIND_URL_SQLITE_SLEEP"' \
  'printf "Ego History\thttps://ego.invalid/history\t2026-08-31 10:00:00\t1\n"' \
  > "$fake_bin/sqlite3"
chmod +x "$fake_bin/sqlite3"

output=$(HOME="$fake_home" node "$SCRIPT" internal --only bookmarks)
if [[ "$output" != *"Ego Internal Portal"* ]] || [[ "$output" == *"Chrome Internal Portal"* ]]; then
  printf 'FAIL：默认检索没有严格限制为 ego lite：%s\n' "$output"
  exit 1
fi

set +e
rejected=$(HOME="$fake_home" node "$SCRIPT" internal --only bookmarks --browser chrome 2>&1)
status=$?
set -e
if [[ "$status" -ne 1 ]] || [[ "$rejected" != *"固定只读 ego lite"* ]]; then
  printf 'FAIL：显式 Chrome 请求没有被拒绝：status=%s output=%s\n' "$status" "$rejected"
  exit 1
fi

history_output=$(HOME="$fake_home" FIND_URL_DB_PATH_LOG="$history_path_log" FIND_URL_DB_MODE_LOG="$history_mode_log" PATH="$fake_bin:$PATH" node "$SCRIPT" --only history)
history_tmp_path=$(<"$history_path_log")
history_mode=$(<"$history_mode_log")
runtime_dir="$fake_home/tmp/lookup-runtime"
if runtime_mode=$(stat -f '%Lp' "$runtime_dir" 2>/dev/null); then :; else runtime_mode=$(stat -c '%a' "$runtime_dir" 2>/dev/null || true); fi
if [[ "$history_output" != *"Ego History"* ]] \
  || [[ "$history_tmp_path" != "$runtime_dir/"* ]] \
  || [[ "$runtime_mode" != "700" ]] \
  || [[ "$history_mode" != "600" ]]; then
  printf 'FAIL：历史库临时副本权限不安全：path=%s dir_mode=%s file_mode=%s output=%s\n' \
    "$history_tmp_path" "$runtime_mode" "$history_mode" "$history_output"
  exit 1
fi

if [[ -e "$history_tmp_path" ]]; then
  printf 'FAIL：历史库临时副本退出后仍存在：%s\n' "$history_tmp_path"
  exit 1
fi

orphan="$runtime_dir/browser-history-99999999-1-orphan.sqlite"
: > "$orphan"
chmod 600 "$orphan"
HOME="$fake_home" FIND_URL_DB_PATH_LOG="$history_path_log" FIND_URL_DB_MODE_LOG="$history_mode_log" PATH="$fake_bin:$PATH" \
  node "$SCRIPT" --only history >/dev/null
if [[ -e "$orphan" ]]; then
  printf 'FAIL：上次异常退出遗留的历史副本没有清理：%s\n' "$orphan"
  exit 1
fi

rm -f -- "$history_path_log" "$sqlite_pid_log"
HOME="$fake_home" FIND_URL_DB_PATH_LOG="$history_path_log" FIND_URL_DB_MODE_LOG="$history_mode_log" \
  FIND_URL_SQLITE_PID_LOG="$sqlite_pid_log" FIND_URL_SQLITE_SLEEP=10 PATH="$fake_bin:$PATH" \
  node "$SCRIPT" --only history >/dev/null &
reader_pid=$!
for _ in $(seq 1 100); do
  [[ -s "$history_path_log" ]] && [[ -s "$sqlite_pid_log" ]] && break
  sleep 0.01
done
interrupted_tmp=$(<"$history_path_log")
sqlite_pid=$(<"$sqlite_pid_log")
kill -TERM "$reader_pid" 2>/dev/null || true
kill -TERM "$sqlite_pid" 2>/dev/null || true
set +e
wait "$reader_pid" 2>/dev/null
set -e
if [[ -e "$interrupted_tmp" ]]; then
  printf 'FAIL：信号中断后历史副本仍存在：%s\n' "$interrupted_tmp"
  exit 1
fi

printf 'find-url 回归：通过 5，失败 0\n'
