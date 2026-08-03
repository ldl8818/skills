#!/usr/bin/env bash
# lookup 通道自检：验证本地依赖、OpenCLI 桥接、注册表合约和登录态。
#
# 默认模式不发平台搜索/正文请求。L3 cookies 探活不建 lease；auth status
# 使用 quickCheck、单并发和每站超时，但首次仍可能创建或复用 automation 容器。
#
# 用法：
#   bash scripts/selftest.sh
#   bash scripts/selftest.sh --live
#
# --live 会发真实查询、消耗额度并可能留下容器窗口，只在明确排障时使用。

set -uo pipefail

LIVE=0
case "${1:-}" in
  "") ;;
  --live) LIVE=1 ;;
  *)
    printf '用法：bash scripts/selftest.sh [--live]\n'
    exit 2
    ;;
esac

# OpenCLI daemon 串行处理浏览器命令；并发自检会制造假超时。
others=$(pgrep -f '[s]elftest\.sh' 2>/dev/null | grep -vx "$$" | tr '\n' ' ' || true)
if [[ -n "${others// /}" ]]; then
  printf '已有 selftest 在跑（PID: %s）。等它结束再试。\n' "${others% }"
  exit 2
fi

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

# ---------- 1. 本地依赖 ----------
head_ "命令可用性"
for cmd in jq python3; do
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

for script in find-url.mjs match-site.mjs ego-spaces.mjs; do
  if [[ -f "$SELF_DIR/$script" ]] && node --check "$SELF_DIR/$script" 2>/dev/null; then
    ok "scripts/$script 可解析"
  else
    bad "scripts/$script 缺失或有语法错误"
  fi
done

# ---------- 2. OpenCLI L3 端到端探活 ----------
head_ "OpenCLI 连通性（零窗口 L3 探活）"
L3_OK=0
if command -v opencli >/dev/null 2>&1 && command -v curl >/dev/null 2>&1 && command -v python3 >/dev/null 2>&1; then
  deadline=$(python3 -c 'import time;print(int(time.time()*1000)+15000)')
  probe=$(curl -sS --max-time 20 \
    -H 'X-OpenCLI: 1' -H 'Content-Type: application/json' \
    --data "{\"id\":\"selftest-$$\",\"action\":\"cookies\",\"session\":\"health-probe\",\"surface\":\"browser\",\"domain\":\"opencli-probe.invalid\",\"timeout\":10,\"deadlineAt\":$deadline}" \
    http://127.0.0.1:19825/command 2>&1)
  if [[ "$probe" == *'"ok":true'* ]]; then
    ok "daemon + 扩展连通（L3 正常）"
    L3_OK=1
  else
    bad "探活未返回 ok:true —— L3 故障，OpenCLI adapter 不可用"
    printf '      返回：%s\n' "${probe:0:160}"
  fi
else
  skip "opencli、curl 或 python3 缺失，跳过 L3 探活"
fi

# ---------- 3. OpenCLI 实时注册表与策略合约 ----------
head_ "OpenCLI 注册表合约"
REGISTRY_JSON=""
if command -v opencli >/dev/null 2>&1 && command -v jq >/dev/null 2>&1; then
  REGISTRY_JSON=$(opencli list -f json 2>&1)
  if jq -e '(type == "array") and (length > 0)' >/dev/null 2>&1 <<<"$REGISTRY_JSON"; then
    registry_count=$(jq 'length' <<<"$REGISTRY_JSON")
    ok "opencli list 返回 $registry_count 条结构化命令"
  else
    bad "opencli list 未返回非空 JSON 数组"
    printf '      返回：%s\n' "${REGISTRY_JSON:0:160}"
    REGISTRY_JSON=""
  fi
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
    bad "OpenCLI 合约检查数异常：应检查 $expected_contracts，实际 $checked_contracts"
  fi

  expected_sites=$(jq '[.actions[] | .providers[] | select(.type == "opencli" and (.status == "active" or .status == "conditional")) | .command | split("/")[0]] | unique | length' "$PROVIDERS_JSON")
  checked_sites=0
  while IFS= read -r site; do
    checked_sites=$((checked_sites + 1))
    if verify_output=$(opencli verify "$site" 2>&1); then
      ok "opencli verify $site"
    else
      skip "opencli verify $site 的站点级检查失败，不覆盖上方精确只读合约：${verify_output:0:120}"
    fi
  done < <(jq -r '[.actions[] | .providers[] | select(.type == "opencli" and (.status == "active" or .status == "conditional")) | .command | split("/")[0]] | unique[]' "$PROVIDERS_JSON")

  if [[ "$expected_sites" -gt 0 ]] && [[ "$checked_sites" -eq "$expected_sites" ]]; then
    ok "实际 verify $checked_sites 个站点，与策略台账一致"
  else
    bad "OpenCLI 站点 verify 数异常：应检查 $expected_sites，实际 $checked_sites"
  fi
else
  skip "注册表或策略台账不可用，跳过合约验证"
fi

# ---------- 4. 有界登录态检查 ----------
head_ "平台登录态（有界 quickCheck）"
if [[ "$L3_OK" -eq 1 ]] && [[ "$PROVIDERS_OK" -eq 1 ]] && command -v jq >/dev/null 2>&1; then
  expected_auth_set=$(jq -c '[.actions[] | .providers[] | select(.type == "opencli" and (.status == "active" or .status == "conditional") and .auth == "browser-session") | .command | split("/")[0]] | unique | sort' "$PROVIDERS_JSON")
  auth_sites=$(jq -r 'join(",")' <<<"$expected_auth_set")
  expected_auth=$(jq 'length' <<<"$expected_auth_set")
  if [[ "$expected_auth" -eq 0 ]]; then
    skip "策略台账没有需要浏览器登录态的 OpenCLI 站点"
  else
    auth_output=$(opencli auth status --site "$auth_sites" --timeout 8 --concurrency 1 -f json 2>&1)
    if jq -e 'type == "array"' >/dev/null 2>&1 <<<"$auth_output"; then
      actual_auth=$(jq 'length' <<<"$auth_output")
      actual_auth_set=$(jq -c '[.[].site] | unique | sort' <<<"$auth_output")
      if [[ "$actual_auth" -eq "$expected_auth" ]] && [[ "$actual_auth_set" == "$expected_auth_set" ]]; then
        ok "auth status 完整覆盖 $actual_auth 个目标站点"
      else
        bad "auth status 站点集合不符：期望 $expected_auth_set，实际 $actual_auth_set"
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
  fi
else
  skip "L3 不通、策略台账无效或 jq 缺失，跳过登录态检查"
fi

# ---------- 5. --live 真实最小查询 ----------
if [[ "$LIVE" -eq 1 ]]; then
  head_ "真实查询（会留下窗口并消耗额度）"
  probe_word="ai"
  LIVE_TMP_FILES=()

  cleanup_live_tmp() {
    local tmp_file
    for tmp_file in "${LIVE_TMP_FILES[@]}"; do
      case "$tmp_file" in
        "$HOME"/tmp/lookup-selftest.*.err) rm -f -- "$tmp_file" ;;
      esac
    done
  }
  trap cleanup_live_tmp EXIT

  run_live() {
    local label="$1"
    local validator="$2"
    local out
    local stderr_file
    local stderr
    shift 2

    stderr_file=$(mktemp "$HOME/tmp/lookup-selftest.XXXXXX.err") || {
      bad "$label 无法创建 stderr 临时文件"
      return
    }
    LIVE_TMP_FILES+=("$stderr_file")

    if out=$("$@" 2>"$stderr_file"); then
      case "$validator" in
        json-list)
          if jq -e '(type == "array") and (length > 0)' >/dev/null 2>&1 <<<"$out"; then
            ok "$label 返回非空 JSON 列表"
          else
            bad "$label 退出 0，但没有返回非空 JSON 列表：${out:0:120}"
          fi
          ;;
        text)
          if [[ -n "${out//[[:space:]]/}" ]]; then
            ok "$label 返回 $(wc -c <<<"$out" | tr -d ' ') 字节有效 stdout"
          else
            bad "$label 退出 0，但 stdout 为空"
          fi
          ;;
        *)
          bad "$label 使用未知校验器：$validator"
          ;;
      esac
    else
      stderr=$(<"$stderr_file")
      bad "$label 查询失败：${stderr:0:120}"
    fi
    rm -f -- "$stderr_file"
  }

  run_live "X search" json-list env OPENCLI_BROWSER_COMMAND_TIMEOUT=30 opencli twitter search "$probe_word" --product live -f json --limit 1 --window background
  run_live "小红书 search" json-list env OPENCLI_BROWSER_COMMAND_TIMEOUT=30 opencli xiaohongshu search "$probe_word" -f json --limit 1 --window background
  run_live "公众号 search" json-list env OPENCLI_BROWSER_COMMAND_TIMEOUT=30 opencli weixin search "$probe_word" -f json --limit 1 --window background
  run_live "Douyin search" json-list env OPENCLI_BROWSER_COMMAND_TIMEOUT=30 opencli douyin search "$probe_word" -f json --limit 1 --window background
  run_live "B站 search" text bili search "$probe_word" --type video -n 1
  run_live "YouTube search" text yt-dlp --socket-timeout 10 "ytsearch1:$probe_word" --flat-playlist --print "%(title)s"
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
