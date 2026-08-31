#!/usr/bin/env bash
set -uo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEST_ROOT="$HOME/tmp/lookup-match-site-test.$$"
PASS=0
FAIL=0

cleanup() {
  case "$TEST_ROOT" in
    "$HOME"/tmp/lookup-match-site-test.*) rm -rf -- "$TEST_ROOT" ;;
  esac
}
trap cleanup EXIT

mkdir -p "$TEST_ROOT/home/.agents/data/site-patterns"
printf '%s\n' \
  '---' \
  'aliases: [example]' \
  '---' \
  '# example.test' \
  '' \
  '- 合成站点经验。' \
  > "$TEST_ROOT/home/.agents/data/site-patterns/example.test.md"

output=$(HOME="$TEST_ROOT/home" node "$ROOT_DIR/scripts/match-site.mjs" 'https://example.test/article')
if [[ "$output" == *'--- 站点经验: example.test ---'* ]] \
  && [[ "$output" == *'合成站点经验'* ]] \
  && [[ "$output" != *'lookup/references/site-patterns'* ]]; then
  printf '  ✓ 从 ~/.agents/data/site-patterns 读取站点经验\n'
  PASS=$((PASS + 1))
else
  printf '  ✗ 站点经验真身读取失败：%s\n' "$output"
  FAIL=$((FAIL + 1))
fi

printf 'match-site 回归：通过 %d，失败 %d\n' "$PASS" "$FAIL"
[[ "$FAIL" -eq 0 ]]
