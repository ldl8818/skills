#!/usr/bin/env bash
# lookup 通道自检：验证本地依赖、OpenCLI 桥接与注册表合约。
#
# 默认模式不查登录态，也不发平台搜索/正文请求。--auth 才使用有界
# quickCheck；--live 包含 --auth，并额外发一条最小真实查询。
#
# 用法：
#   bash scripts/selftest.sh
#   bash scripts/selftest.sh --auth
#   bash scripts/selftest.sh --live
#
# --live 会发真实查询、消耗额度并可能留下容器窗口，只在明确排障时使用。

set -uo pipefail

AUTH=0
LIVE=0
case "${1:-}" in
  "") ;;
  --auth) AUTH=1 ;;
  --live) AUTH=1; LIVE=1 ;;
  *)
    printf '用法：bash scripts/selftest.sh [--auth|--live]\n'
    exit 2
    ;;
esac

PASS=0
FAIL=0
SKIP=0

ok() { printf '  \033[32m✓\033[0m %s\n' "$1"; PASS=$((PASS + 1)); }
bad() { printf '  \033[31m✗\033[0m %s\n' "$1"; FAIL=$((FAIL + 1)); }
skip() { printf '  \033[33m–\033[0m %s\n' "$1"; SKIP=$((SKIP + 1)); }
head_() { printf '\n\033[1m%s\033[0m\n' "$1"; }

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "$SELF_DIR/.." && pwd)"
PROVIDERS_JSON="$SKILL_DIR/references/providers.json"
# Bash 3.2 在 set -u 下展开真正的空数组会报 unbound variable；保留空哨兵。
TEMP_FILES=("")
TEMP_ROOT="${HOME:-}/tmp/lookup-runtime"
SELFTEST_LOCK_FILE="$TEMP_ROOT/lookup-selftest.v2.flock"
SELFTEST_LOCK_OWNED=0
SELFTEST_LOCK_HOLDER="$SELF_DIR/flock-holder.py"
SELFTEST_LOCK_HOLDER_PID=""
SELFTEST_LOCK_STATUS_FILE=""

prepare_runtime_dir() {
  [[ -n "${HOME:-}" ]] && [[ "$HOME" == /* ]] || return 1
  [[ ! -L "$HOME/tmp" ]] || return 1
  mkdir -p "$HOME/tmp" 2>/dev/null || return 1
  [[ -d "$HOME/tmp" ]] && [[ -O "$HOME/tmp" ]] || return 1
  [[ ! -L "$TEMP_ROOT" ]] || return 1
  mkdir -p "$TEMP_ROOT" 2>/dev/null || return 1
  chmod 700 "$TEMP_ROOT" 2>/dev/null || return 1
  [[ -d "$TEMP_ROOT" ]] && [[ -O "$TEMP_ROOT" ]] && [[ -w "$TEMP_ROOT" ]]
}

if ! prepare_runtime_dir; then
  printf '临时目录不可用：%s\n' "$TEMP_ROOT"
  exit 78
fi

acquire_selftest_lock() {
  local lock_status
  local attempt
  command -v python3 >/dev/null 2>&1 || return 78
  [[ -r "$SELFTEST_LOCK_HOLDER" ]] || return 78
  SELFTEST_LOCK_STATUS_FILE=$(mktemp "$TEMP_ROOT/lookup-selftest-lock.XXXXXX") || return 78
  TEMP_FILES+=("$SELFTEST_LOCK_STATUS_FILE")
  python3 "$SELFTEST_LOCK_HOLDER" "$SELFTEST_LOCK_FILE" "$SELFTEST_LOCK_STATUS_FILE" 0 "$$" &
  SELFTEST_LOCK_HOLDER_PID=$!
  for attempt in $(seq 1 100); do
    [[ -s "$SELFTEST_LOCK_STATUS_FILE" ]] && break
    kill -0 "$SELFTEST_LOCK_HOLDER_PID" 2>/dev/null || break
    sleep 0.01
  done
  if [[ -s "$SELFTEST_LOCK_STATUS_FILE" ]]; then
    lock_status=$(<"$SELFTEST_LOCK_STATUS_FILE")
  else
    lock_status=78
  fi
  if [[ "$lock_status" -eq 75 ]]; then
    kill -TERM "$SELFTEST_LOCK_HOLDER_PID" 2>/dev/null || true
    wait "$SELFTEST_LOCK_HOLDER_PID" 2>/dev/null || true
    SELFTEST_LOCK_HOLDER_PID=""
    printf '已有 selftest 在跑。等它结束再试。\n'
    return 2
  fi
  if [[ "$lock_status" -ne 0 ]] || ! kill -0 "$SELFTEST_LOCK_HOLDER_PID" 2>/dev/null; then
    kill -TERM "$SELFTEST_LOCK_HOLDER_PID" 2>/dev/null || true
    wait "$SELFTEST_LOCK_HOLDER_PID" 2>/dev/null || true
    SELFTEST_LOCK_HOLDER_PID=""
    return 78
  fi
  SELFTEST_LOCK_OWNED=1
  return 0
}

cleanup_temp_files() {
  local temp_file
  for temp_file in "${TEMP_FILES[@]}"; do
    [[ -n "$temp_file" ]] || continue
    case "$temp_file" in
      "$TEMP_ROOT"/lookup-selftest-*)
        [[ ! -e "$temp_file" ]] || rm -f -- "$temp_file"
        ;;
    esac
  done
  if [[ "$SELFTEST_LOCK_HOLDER_PID" =~ ^[0-9]+$ ]]; then
    kill -TERM "$SELFTEST_LOCK_HOLDER_PID" 2>/dev/null || true
    wait "$SELFTEST_LOCK_HOLDER_PID" 2>/dev/null || true
  fi
  SELFTEST_LOCK_HOLDER_PID=""
  SELFTEST_LOCK_OWNED=0
}
trap cleanup_temp_files EXIT

acquire_selftest_lock
lock_status=$?
[[ "$lock_status" -eq 0 ]] || exit "$lock_status"

# ---------- 1. 本地依赖 ----------
head_ "命令可用性"
for cmd in curl jq python3; do
  if command -v "$cmd" >/dev/null 2>&1; then
    ok "${cmd}（selftest 依赖）"
  else
    bad "$cmd 不在 PATH —— selftest 无法完成"
  fi
done

PROVIDERS_OK=0
if command -v jq >/dev/null 2>&1 && jq -e '
  (.version == 2)
  and ((.actions | type) == "object" and (.actions | length) > 0)
  and all(.actions[]; ((.providers | type) == "array" and (.providers | length) > 0))
  and all(.actions[]; (([.providers[].id] | length) == ([.providers[].id] | unique | length)))
  and all(.actions[].providers[];
    ((.id | type) == "string" and (.id | length) > 0)
    and (.type == "opencli" or .type == "cli" or .type == "http" or .type == "mcp-cli" or .type == "manual")
    and (.status == "active" or .status == "conditional" or .status == "broken")
  )
  and all(.actions[].providers[] | select(.type == "opencli" and (.status == "active" or .status == "conditional"));
    ((.command | type) == "string" and (.command | test("^[^/]+/[^/]+$")))
    and (.required_access == "read")
    and (.auth == "browser-session" or .auth == "none")
    and ((.required_args | type) == "array" and (.required_args | length) > 0)
    and ((.required_columns | type) == "array" and (.required_columns | length) > 0)
    and (((.policy_args // []) | type) == "array")
    and (((.local_effect // "none") == "none") or (.local_effect == "write" and .status == "conditional"))
    and all((.policy_args // [])[];
      ((.name | type) == "string" and (.name | length) > 0)
      and ((.value | type) == "string" and (.value | length) > 0)
    )
  )
  and (([.actions[].providers[] | select(.type == "opencli" and (.status == "active" or .status == "conditional")) | .command] | length) == ([.actions[].providers[] | select(.type == "opencli" and (.status == "active" or .status == "conditional")) | .command] | unique | length))
' "$PROVIDERS_JSON" >/dev/null 2>&1; then
  ok "providers.json v2 schema 与 OpenCLI 合约字段完整"
  PROVIDERS_OK=1
else
  bad "providers.json 不可解析、schema 错误或 OpenCLI 合约字段不完整"
fi

if [[ "$PROVIDERS_OK" -eq 1 ]]; then
  while IFS= read -r cmd; do
    if command -v "$cmd" >/dev/null 2>&1; then
      ok "${cmd}（provider 依赖）"
    else
      bad "$cmd 不在 PATH —— 依赖它的通道不可用"
    fi
  done < <(jq -r '[.actions[].providers[] | select(.status == "active" or .status == "conditional") | if .type == "opencli" then "opencli" elif .bin then .bin else empty end] | unique[]' "$PROVIDERS_JSON")
else
  skip "策略台账无效，无法派生 provider 依赖"
fi

FETCH_SH="$HOME/.agents/skills/read/scripts/fetch.sh"
if [[ -f "$FETCH_SH" ]]; then
  ok "fetch.sh 存在"
else
  bad "fetch.sh 不在 $FETCH_SH —— 静态抓取通道失效"
fi

for script in find-url.mjs match-site.mjs ego-spaces.mjs opencli-run.mjs; do
  if [[ -f "$SELF_DIR/$script" ]] && node --check "$SELF_DIR/$script" 2>/dev/null; then
    ok "scripts/$script 可解析"
  else
    bad "scripts/$script 缺失或有语法错误"
  fi
done

runner_version=$(node "$SELF_DIR/opencli-run.mjs" --version 2>&1)
runner_status=$?
if [[ "$runner_status" -eq 0 ]] && [[ "$runner_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  ok "OpenCLI 兼容入口可执行（${runner_version}）"
else
  bad "OpenCLI 兼容入口运行失败：${runner_version:0:160}"
fi

# ---------- 2. OpenCLI L3 健康门禁 ----------
head_ "OpenCLI 连通性（零业务请求健康门禁）"
L3_OK=0
if [[ -x "$SELF_DIR/opencli-health.sh" ]] && command -v jq >/dev/null 2>&1; then
  health_output=$(bash "$SELF_DIR/opencli-health.sh")
  health_status=$?
  if [[ "$health_status" -eq 0 ]] && jq -e '.ok == true and .state == "ready"' >/dev/null 2>&1 <<<"$health_output"; then
    ok "daemon + ego lite 扩展连通（L3 正常）"
    L3_OK=1
  else
    state=$(jq -r '.state // "invalid_health_output"' <<<"$health_output" 2>/dev/null || printf 'invalid_health_output')
    next=$(jq -r '.next // "check_opencli_health"' <<<"$health_output" 2>/dev/null || printf 'check_opencli_health')
    bad "OpenCLI 门禁未就绪：${state}；下一步：${next}"
  fi
else
  bad "scripts/opencli-health.sh 缺失、不可执行或 jq 不可用"
fi

# ---------- 3. OpenCLI 实时注册表与策略合约 ----------
head_ "OpenCLI 注册表合约"
REGISTRY_JSON=""
if command -v opencli >/dev/null 2>&1 && command -v jq >/dev/null 2>&1; then
  registry_stderr=$(mktemp "$TEMP_ROOT/lookup-selftest-registry.XXXXXX")
  TEMP_FILES+=("$registry_stderr")
  if REGISTRY_JSON=$(opencli list -f json 2>"$registry_stderr") && jq -e '(type == "array") and (length > 0)' >/dev/null 2>&1 <<<"$REGISTRY_JSON"; then
    registry_count=$(jq 'length' <<<"$REGISTRY_JSON")
    ok "opencli list 返回 $registry_count 条结构化命令"
  else
    bad "opencli list 未返回非空 JSON 数组"
    printf '      返回：%s\n' "${REGISTRY_JSON:0:160}"
    REGISTRY_JSON=""
  fi
  unlink "$registry_stderr"
else
  skip "opencli 或 jq 缺失，跳过注册表合约"
fi

if [[ -n "$REGISTRY_JSON" ]] && [[ "$PROVIDERS_OK" -eq 1 ]]; then
  expected_contracts=$(jq '[.actions[] | .providers[] | select(.type == "opencli" and (.status == "active" or .status == "conditional"))] | length' "$PROVIDERS_JSON")
  checked_contracts=0

  while IFS= read -r spec; do
    checked_contracts=$((checked_contracts + 1))
    command_id=$(jq -r '.command' <<<"$spec")
    site=${command_id%%/*}
    name=${command_id#*/}
    required_access=$(jq -r '.required_access // "read"' <<<"$spec")
    required_args=$(jq -c '.required_args // []' <<<"$spec")
    required_columns=$(jq -c '.required_columns // []' <<<"$spec")
    policy_args=$(jq -c '.policy_args // []' <<<"$spec")

    if jq -e \
      --arg site "$site" \
      --arg name "$name" \
      --arg access "$required_access" \
      --argjson required_args "$required_args" \
      --argjson required_columns "$required_columns" \
      --argjson policy_args "$policy_args" '
        ([.[] | select(.site == $site and .name == $name)] | first) as $cmd
        | ($cmd != null)
          and ($cmd.access == $access)
          and (($required_args - ($cmd.args | map(.name))) | length == 0)
          and (($required_columns - ($cmd.columns // [])) | length == 0)
          and (all($policy_args[];
            . as $policy
            | any($cmd.args[];
                .name == $policy.name
                and (.positional == false)
                and (((.choices // []) | index($policy.value)) != null)
              )
          ))
      ' >/dev/null <<<"$REGISTRY_JSON"; then
      ok "$command_id 仍满足只读参数、策略取值与字段合约"
    else
      bad "$command_id 缺失、变为写操作或参数／策略／字段合约漂移"
    fi
  done < <(jq -c '.actions[] | .providers[] | select(.type == "opencli" and (.status == "active" or .status == "conditional")) | {command, required_access, required_args, required_columns, policy_args}' "$PROVIDERS_JSON")

  if [[ "$expected_contracts" -gt 0 ]] && [[ "$checked_contracts" -eq "$expected_contracts" ]]; then
    ok "实际检查 $checked_contracts 条 OpenCLI 合约，与策略台账一致"
  else
    bad "OpenCLI 合约检查数异常：应检查 ${expected_contracts}，实际 ${checked_contracts}"
  fi

  expected_sites=$(jq '[.actions[] | .providers[] | select(.type == "opencli" and (.status == "active" or .status == "conditional")) | .command | split("/")[0]] | unique | length' "$PROVIDERS_JSON")
  checked_sites=0
  verified_sites=0
  while IFS= read -r site; do
    checked_sites=$((checked_sites + 1))
    if verify_output=$(node "$SELF_DIR/opencli-run.mjs" verify "$site" 2>&1); then
      ok "opencli verify $site"
      verified_sites=$((verified_sites + 1))
    else
      skip "opencli verify $site 的站点级检查失败，不覆盖上方精确只读合约：${verify_output:0:120}"
    fi
  done < <(jq -r '[.actions[] | .providers[] | select(.type == "opencli" and (.status == "active" or .status == "conditional")) | .command | split("/")[0]] | unique[]' "$PROVIDERS_JSON")

  if [[ "$expected_sites" -gt 0 ]] && [[ "$checked_sites" -eq "$expected_sites" ]]; then
    ok "已逐项发起 $checked_sites 个站点 verify，其中 $verified_sites 个成功"
  else
    bad "OpenCLI 站点 verify 数异常：应检查 ${expected_sites}，实际 ${checked_sites}"
  fi
else
  skip "注册表或策略台账不可用，跳过合约验证"
fi

# ---------- 4. --auth 有界登录态检查 ----------
head_ "平台登录态（有界 quickCheck）"
if [[ "$AUTH" -ne 1 ]]; then
  skip "未加 --auth，跳过登录态检查"
elif [[ "$L3_OK" -eq 1 ]] && [[ "$PROVIDERS_OK" -eq 1 ]] && command -v jq >/dev/null 2>&1; then
  expected_auth_set=$(jq -c '[.actions[] | .providers[] | select(.type == "opencli" and (.status == "active" or .status == "conditional") and .auth == "browser-session") | .command | split("/")[0]] | unique | sort' "$PROVIDERS_JSON")
  auth_sites=$(jq -r 'join(",")' <<<"$expected_auth_set")
  expected_auth=$(jq 'length' <<<"$expected_auth_set")
  if [[ "$expected_auth" -eq 0 ]]; then
    skip "策略台账没有需要浏览器登录态的 OpenCLI 站点"
  else
    auth_stderr=$(mktemp "$TEMP_ROOT/lookup-selftest-auth.XXXXXX")
    TEMP_FILES+=("$auth_stderr")
    auth_output=$(node "$SELF_DIR/opencli-run.mjs" auth status --site "$auth_sites" --timeout 8 --concurrency 1 -f json 2>"$auth_stderr")
    auth_status=$?
    if [[ "$auth_status" -eq 0 ]] && jq -e 'type == "array"' >/dev/null 2>&1 <<<"$auth_output"; then
      actual_auth=$(jq 'length' <<<"$auth_output")
      actual_auth_set=$(jq -c '[.[].site] | unique | sort' <<<"$auth_output")
      if [[ "$actual_auth" -eq "$expected_auth" ]] && [[ "$actual_auth_set" == "$expected_auth_set" ]]; then
        ok "auth status 完整覆盖 $actual_auth 个目标站点"
      else
        bad "auth status 站点集合不符：期望 ${expected_auth_set}，实际 ${actual_auth_set}"
      fi

      while IFS= read -r row; do
        site=$(jq -r '.site' <<<"$row")
        status=$(jq -r '.status' <<<"$row")
        case "$status" in
          logged_in) ok "$site 登录态在" ;;
          not_logged_in) bad "$site 未登录 —— L2 问题，不换同登录态浏览器" ;;
          unknown) bad "$site quickCheck 不支持或无法判断 —— 登录态未验证，不自动升级为 full 检查" ;;
          error) bad "$site 登录态检查失败：$(jq -r '.error // "unknown"' <<<"$row" | cut -c1-120)" ;;
          *) bad "$site 返回未知状态：$status" ;;
        esac
      done < <(jq -c '.[]' <<<"$auth_output")
    else
      bad "opencli auth status 未返回 JSON 数组"
      printf '      返回：%s\n' "${auth_output:0:160}"
    fi
    unlink "$auth_stderr"
  fi
else
  skip "L3 不通、策略台账无效或 jq 缺失，跳过登录态检查"
fi

# ---------- 5. --live 真实最小查询 ----------
if [[ "$LIVE" -eq 1 ]]; then
  head_ "真实查询（可能留下 automation 容器）"
  probe_word="ai"
  export OPENCLI_BROWSER_COMMAND_TIMEOUT=15

  valid_live_output() {
    local validator="$1"
    local out="$2"
    case "$validator" in
      json-list) jq -e '(type == "array") and (length > 0)' >/dev/null 2>&1 <<<"$out" ;;
      text) [[ -n "${out//[[:space:]]/}" ]] ;;
      *) return 2 ;;
    esac
  }

  run_live() {
    local label="$1"
    local validator="$2"
    local out
    local stderr_file
    local stderr
    shift 2

    stderr_file=$(mktemp "$TEMP_ROOT/lookup-selftest-live.XXXXXX") || {
      bad "$label 无法创建 stderr 临时文件"
      return
    }
    TEMP_FILES+=("$stderr_file")

    if out=$("$@" 2>"$stderr_file"); then
      if valid_live_output "$validator" "$out"; then
        ok "$label 返回有效内容"
      else
        bad "$label 退出 0，但内容无效：${out:0:120}"
      fi
    else
      stderr=$(<"$stderr_file")
      bad "$label 查询失败：${stderr:0:120}"
    fi
    rm -f -- "$stderr_file"
  }

  run_live "OpenCLI B站 search" json-list node "$SELF_DIR/opencli-run.mjs" bilibili search "$probe_word" --type video -f json --limit 1 --window background --site-session ephemeral --keep-tab false
else
  head_ "真实查询"
  skip "未加 --live，跳过平台业务请求"
fi

# ---------- 汇总 ----------
printf '\n\033[1m结果\033[0m  通过 %d  失败 %d  跳过 %d\n' "$PASS" "$FAIL" "$SKIP"
if [[ "$FAIL" -gt 0 ]]; then
  printf '失败项按 references/failure-domains.md 分层：L3/L4 才换 ego-browser；L1/L2 处理浏览器或登录态。\n'
  exit 1
fi
exit 0
