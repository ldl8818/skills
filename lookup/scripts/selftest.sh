#!/usr/bin/env bash
# lookup 通道自检：确认 SKILL.md 里的六平台命令现在还能不能走。
#
# 默认模式不发任何平台业务请求：只查命令是否存在、daemon 是否连通、登录态是否在。
# 不消耗接口额度、不碰风控。实测连跑多次 whoami 窗口数不变（automation 容器被复用），
# 但若该容器尚不存在，首次可能创建一个——机制见 references/opencli-windows.md。
#
# 用法：
#   bash scripts/selftest.sh           # 本地条件检查（默认，安全）
#   bash scripts/selftest.sh --live    # 额外对每个平台发一条最小真实查询
#
# --live 的代价：每个 OpenCLI 平台会在 automation 容器里留下窗口（关不掉，
# 见 references/opencli-windows.md），豆包会消耗一次月额度。只在排查
# 「命令是不是过时了」时用。

set -uo pipefail

LIVE=0
[[ "${1:-}" == "--live" ]] && LIVE=1

PASS=0 FAIL=0 SKIP=0

ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; PASS=$((PASS+1)); }
bad()  { printf '  \033[31m✗\033[0m %s\n' "$1"; FAIL=$((FAIL+1)); }
skip() { printf '  \033[33m–\033[0m %s\n' "$1"; SKIP=$((SKIP+1)); }
head_() { printf '\n\033[1m%s\033[0m\n' "$1"; }

# ---------- 1. 命令是否存在 ----------
head_ "命令可用性"
for cmd in opencli yt-dlp bili mcporter node curl; do
  if command -v "$cmd" >/dev/null 2>&1; then
    ok "$cmd"
  else
    bad "$cmd 不在 PATH —— 依赖它的通道全部不可用"
  fi
done

FETCH_SH="$HOME/.agents/skills/read/scripts/fetch.sh"
if [[ -f "$FETCH_SH" ]]; then
  ok "fetch.sh 存在"
else
  bad "fetch.sh 不在 $FETCH_SH —— read skill 可能已被删除，静态抓取通道失效"
fi

# ---------- 2. OpenCLI 端到端探活（零窗口） ----------
# 用 cookies action 打一个不存在的域：走完 daemon → WebSocket → 扩展 → 回程，
# 不解析 tab、不建 lease，所以不产生窗口。判据见 SKILL.md「探活」。
head_ "OpenCLI 连通性（零窗口探活）"
if command -v opencli >/dev/null 2>&1; then
  deadline=$(python3 -c 'import time;print(int(time.time()*1000)+15000)')
  probe=$(curl -sS --max-time 20 \
    -H 'X-OpenCLI: 1' -H 'Content-Type: application/json' \
    --data "{\"id\":\"selftest-$$\",\"action\":\"cookies\",\"session\":\"health-probe\",\"surface\":\"browser\",\"domain\":\"opencli-probe.invalid\",\"timeout\":10,\"deadlineAt\":$deadline}" \
    http://127.0.0.1:19825/command 2>&1)
  if [[ "$probe" == *'"ok":true'* ]]; then
    ok "daemon + 扩展连通（L3 正常）"
  else
    bad "探活未返回 ok:true —— L3 故障，OpenCLI 系全部不可用，改走 ego-browser"
    printf '      返回：%s\n' "${probe:0:160}"
  fi
else
  skip "opencli 缺失，跳过探活"
fi

# ---------- 3. 各平台登录态 ----------
# whoami 不发平台业务请求，是判断 L2 的正规手段（见 SKILL.md 的 AUTH_REQUIRED 一节）。
# 但不是每个适配器都有 whoami——公众号走搜狗源、无账号体系，就没有。
# 对没有 whoami 的平台报「未登录」是假失败，会让人去做无用的扫码，所以先探测再判断。
head_ "平台登录态（L2）"
if command -v opencli >/dev/null 2>&1; then
  for plat in twitter xiaohongshu weixin douyin bilibili; do
    if ! opencli "$plat" --help 2>&1 | grep -qE '^[[:space:]]+whoami([[:space:]]|$)'; then
      skip "$plat 无 whoami 子命令，无登录态可查（不代表通道有问题）"
      continue
    fi
    if out=$(opencli "$plat" whoami --window background 2>&1) \
       && [[ -n "$out" && "$out" != *AUTH_REQUIRED* ]]; then
      ok "$plat 登录态在"
    else
      bad "$plat 未登录或 whoami 失败 —— 请用户在 ego lite 里扫码，别急着换通道"
    fi
  done
else
  skip "opencli 缺失，跳过登录态检查"
fi

# ---------- 4. 子命令是否还在（防适配器改版后命令消失） ----------
# 只读 --help，不发请求。SKILL.md 里写死的子命令必须在这里出现，
# 否则说明适配器改版、速查表已过时。
head_ "SKILL.md 引用的子命令是否仍存在"
check_sub() { # $1=平台 $2..=子命令
  local plat="$1"; shift
  # 不判 --help 的退出码（各适配器不统一），只看有没有拿到帮助文本
  local help
  help=$(opencli "$plat" --help 2>&1)
  if [[ -z "$help" ]]; then bad "$plat --help 无输出"; return; fi
  for sub in "$@"; do
    if grep -qE "^[[:space:]]+$sub([[:space:]]|$)" <<<"$help"; then
      ok "opencli $plat $sub"
    else
      bad "opencli $plat $sub 不存在了 —— SKILL.md 速查表需更新"
    fi
  done
}
if command -v opencli >/dev/null 2>&1; then
  check_sub twitter     search article thread tweets
  check_sub xiaohongshu search note comments
  check_sub weixin      search
  check_sub douyin      search
  check_sub bilibili    subtitle
else
  skip "opencli 缺失，跳过子命令检查"
fi

# ---------- 5. --live：真实最小查询 ----------
if [[ $LIVE -eq 1 ]]; then
  head_ "真实查询（--live，会留下容器窗口并消耗额度）"
  probe_word="ai"

  run_live() { # $1=标签 $2..=命令
    local label="$1"; shift
    if out=$("$@" 2>&1) && [[ -n "$out" ]]; then
      ok "$label 返回 $(wc -c <<<"$out" | tr -d ' ') 字节"
    else
      bad "$label 无输出或失败：${out:0:120}"
    fi
  }

  run_live "X search"       opencli twitter search "$probe_word" --product live -f yaml --limit 1 --window background
  run_live "小红书 search"   opencli xiaohongshu search "$probe_word" -f yaml --limit 1 --window background
  run_live "公众号 search"   opencli weixin search "$probe_word" -f yaml --limit 1 --window background
  run_live "抖音 search"     opencli douyin search "$probe_word" -f yaml --limit 1 --window background
  run_live "B站 search"      bili search "$probe_word" --type video -n 1
  run_live "YouTube search"  yt-dlp "ytsearch1:$probe_word" --flat-playlist --print "%(title)s"
else
  head_ "真实查询"
  skip "未加 --live，跳过（默认不发平台请求）"
fi

# ---------- 汇总 ----------
printf '\n\033[1m结果\033[0m  通过 %d  失败 %d  跳过 %d\n' "$PASS" "$FAIL" "$SKIP"
if [[ $FAIL -gt 0 ]]; then
  printf '失败项按 references/failure-domains.md 的分层判据处理：探活失败是 L3，登录态失败是 L2，子命令消失是 L4。\n'
  exit 1
fi
exit 0
