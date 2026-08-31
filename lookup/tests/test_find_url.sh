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
mkdir -p "$ego_dir" "$chrome_dir" "$fake_bin"

printf '%s\n' '{"roots":{"bookmark_bar":{"children":[{"type":"url","name":"Ego Internal Portal","url":"https://ego.invalid/internal"}]}}}' > "$ego_dir/Bookmarks"
printf '%s\n' '{"roots":{"bookmark_bar":{"children":[{"type":"url","name":"Chrome Internal Portal","url":"https://chrome.invalid/internal"}]}}}' > "$chrome_dir/Bookmarks"
: > "$ego_dir/History"

printf '%s\n' \
  '#!/usr/bin/env bash' \
  'printf "%s" "$3" > "$FIND_URL_DB_PATH_LOG"' \
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

history_output=$(HOME="$fake_home" FIND_URL_DB_PATH_LOG="$history_path_log" PATH="$fake_bin:$PATH" node "$SCRIPT" --only history)
history_tmp_path=$(<"$history_path_log")
if [[ "$history_output" != *"Ego History"* ]] || [[ "$history_tmp_path" != "$fake_home/tmp/"* ]]; then
  printf 'FAIL：历史库临时副本没有固定在 $HOME/tmp：path=%s output=%s\n' "$history_tmp_path" "$history_output"
  exit 1
fi

printf 'find-url 回归：通过 3，失败 0\n'
