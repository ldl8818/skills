#!/usr/bin/env bash
# luobo-ppt one-click installer for macOS / Linux
#
#   bash install.sh                      auto-detect installed agents, install, check and install deps
#   bash install.sh --agent codex        install for one agent (claude-code|codex|gemini|cursor|copilot|agents|all)
#   bash install.sh --project ~/myrepo   install into a project instead of the user folder
#   bash install.sh --dest /some/skills  install into any skills folder
#   bash install.sh --skip-deps          copy files only
#   bash install.sh --uninstall          remove from the selected agents
set -euo pipefail

NAME="luobo-ppt"
SRC="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
AGENT="auto"; DEST=""; PROJECT=""; SKIP_DEPS=0; UNINSTALL=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --agent) AGENT="$2"; shift 2 ;;
    --dest) DEST="$2"; shift 2 ;;
    --project) PROJECT="$(cd "$2" && pwd)"; shift 2 ;;
    --skip-deps) SKIP_DEPS=1; shift ;;
    --uninstall) UNINSTALL=1; shift ;;
    -h|--help) sed -n '2,11p' "$0"; exit 0 ;;
    *) echo "unknown option: $1"; exit 2 ;;
  esac
done

BASE="${PROJECT:-$HOME}"

agent_dir() {
  case "$1" in
    claude-code) echo "$BASE/.claude/skills" ;;
    codex|agents) echo "$BASE/.agents/skills" ;;
    gemini) echo "$BASE/.gemini/skills" ;;
    cursor) echo "$BASE/.cursor/skills" ;;
    copilot) if [[ -n "$PROJECT" ]]; then echo "$PROJECT/.github/skills"; else echo "$HOME/.copilot/skills"; fi ;;
    *) echo "" ;;
  esac
}

TARGETS=()
if [[ -n "$DEST" ]]; then
  TARGETS+=("$DEST")
elif [[ "$AGENT" == "all" ]]; then
  for a in claude-code agents gemini cursor copilot; do TARGETS+=("$(agent_dir "$a")"); done
elif [[ "$AGENT" == "auto" ]]; then
  found=()
  [[ -d "$HOME/.claude" ]] && found+=("claude-code")
  { [[ -d "$HOME/.codex" ]] || [[ -d "$HOME/.agents" ]]; } && found+=("codex")
  [[ -d "$HOME/.gemini" ]] && found+=("gemini")
  # Cursor also reads ~/.claude/skills and ~/.codex|~/.agents skills, avoid listing the skill twice
  if [[ -d "$HOME/.cursor" ]] && [[ ! " ${found[*]:-} " =~ " claude-code " ]] && [[ ! " ${found[*]:-} " =~ " codex " ]]; then
    found+=("cursor")
  fi
  [[ -d "$HOME/.copilot" ]] && found+=("copilot")
  [[ ${#found[@]} -eq 0 ]] && found=("agents")
  echo "检测到的 Agent：${found[*]}"
  for a in "${found[@]}"; do TARGETS+=("$(agent_dir "$a")"); done
else
  d="$(agent_dir "$AGENT")"
  [[ -z "$d" ]] && { echo "未知 agent：$AGENT"; exit 2; }
  TARGETS+=("$d")
fi

if [[ $UNINSTALL -eq 1 ]]; then
  for t in "${TARGETS[@]}"; do
    if [[ -d "$t/$NAME" ]]; then rm -rf "$t/$NAME"; echo "已移除 $t/$NAME"; fi
  done
  echo "缓存文件 ~/.config/luobo-ppt 保留（里面可能有你的生图配置），不需要可以手动删除。"
  exit 0
fi

install_copy() (
  # Stage beside the destination so publication and rollback use same-filesystem renames.
  txn="$(mktemp -d "$t/.luobo-ppt.install.XXXXXX")"
  staged="$txn/new"; backup="$txn/old"; committed=0; publishing=0
  cleanup() {
    rc=$?
    trap - EXIT HUP INT TERM
    if [[ $committed -eq 0 ]]; then
      if [[ $publishing -eq 1 && ! -e "$staged" ]]; then
        rm -rf "$dst" || { echo "回滚失败，旧安装保留在：$backup" >&2; exit 1; }
      fi
      if [[ ( -e "$backup" || -L "$backup" ) ]] && { [[ -e "$dst" || -L "$dst" ]] || ! mv "$backup" "$dst"; }; then
        echo "回滚失败，旧安装保留在：$backup" >&2
        exit 1
      fi
    fi
    rm -rf "$txn" || exit 1
    exit "$rc"
  }
  trap cleanup EXIT
  trap 'exit 129' HUP
  trap 'exit 130' INT
  trap 'exit 143' TERM
  mkdir "$staged"
  (cd "$SRC" && tar cf - --exclude='__pycache__' --exclude='./.git' --exclude='./.github' --exclude='./docs' \
    --exclude='./tools' --exclude='./dist' --exclude='./README.md' --exclude='./.gitignore' .) | (cd "$staged" && tar xf -)
  if [[ ! -s "$staged/SKILL.md" || ! -f "$staged/install.sh" || ! -f "$staged/scripts/setup_check.py" ]]; then
    echo "安装副本不完整，原安装未改动。" >&2
    exit 1
  fi
  if [[ -f "$dst/config.json" ]]; then
    rm -f "$staged/config.json"
    cp "$dst/config.json" "$staged/config.json"
  fi
  chmod +x "$staged/install.sh"
  if [[ -e "$dst" || -L "$dst" ]]; then mv "$dst" "$backup"; fi
  publishing=1
  mv "$staged" "$dst"
  committed=1
)

FIRST=""
for t in "${TARGETS[@]}"; do
  dst="$t/$NAME"
  mkdir -p "$t"
  t="$(cd -P "$t" && pwd -P)"
  dst="$t/$NAME"
  physical_dst="$dst"
  if [[ -d "$dst" ]]; then physical_dst="$(cd -P "$dst" && pwd -P)"; fi
  if [[ "$SRC" == "$physical_dst" ]]; then
    echo "已在目标位置：$dst"
  else
    if [[ "$physical_dst/" == "$SRC/"* || "$SRC/" == "$physical_dst/"* ]]; then
      echo "源目录与目标目录互相包含，拒绝安装：$SRC -> $physical_dst" >&2
      exit 1
    fi
    install_copy
    echo "已安装到：$dst"
  fi
  for oldname in ppt-studio ppt-beautify; do   # earlier names of this skill
    old="$t/$oldname"
    if [[ -d "$old" ]]; then
      old_physical="$(cd -P "$old" && pwd -P)"
      if [[ "$SRC/" == "$old_physical/"* ]]; then
        echo "保留仍在使用的源目录：$old"
        continue
      fi
      [[ -f "$old/config.json" && ! -f "$dst/config.json" ]] && cp "$old/config.json" "$dst/config.json"
      rm -rf "$old"
      echo "已移除旧版 $oldname（已改名为 luobo-ppt，生图配置已带过来）"
    fi
  done
  [[ -z "$FIRST" ]] && FIRST="$dst"
done

[[ $SKIP_DEPS -eq 1 ]] && { echo "已跳过依赖检查。之后可运行：python3 \"$FIRST/scripts/setup_check.py\" --install"; exit 0; }

PY="$(command -v python3 || command -v python || true)"
if [[ -z "$PY" ]]; then
  echo "没有找到 Python 3。"
  case "$(uname -s)" in
    Darwin) echo "请先安装：brew install python  （或从 https://www.python.org/downloads/ 下载）" ;;
    *) echo "请先安装：sudo apt-get install python3 python3-pip  （或用你的发行版包管理器）" ;;
  esac
  exit 1
fi

echo ""
echo "检查并安装依赖（首次可能需要几分钟）……"
"$PY" "$FIRST/scripts/setup_check.py" --install --selftest
