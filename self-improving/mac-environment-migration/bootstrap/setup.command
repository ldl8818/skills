#!/bin/sh
# V3: only prerequisites and handoff. No global chezmoi apply.
set -eu

say() { printf '%s\n' "$*" >&2; }
ask() {
    printf '%s ' "$1" >&2
    IFS= read -r answer </dev/tty || return 20
}
brew_find() {
    if command -v brew >/dev/null 2>&1; then command -v brew
    elif [ -x /opt/homebrew/bin/brew ]; then printf '%s\n' /opt/homebrew/bin/brew
    else return 1
    fi
}
installer() {
    # Download completely before execution; curl failure cannot look like sh success.
    install_tmp=$(mktemp -d "${TMPDIR:-/tmp}/mac-setup.XXXXXXXX") || return 1
    trap 'rm -rf "$install_tmp"' EXIT
    curl --fail --show-error --location --proto '=https' --tlsv1.2 "$1" -o "$install_tmp/install.sh" || return 1
    /bin/bash "$install_tmp/install.sh"
}
brew_package() {
    if command -v "$1" >/dev/null 2>&1; then
        "$1" --version >/dev/null 2>&1 || { say "$1 已存在但无法运行，请处理后续跑。"; return 30; }
    else
        "$BREW" install "$1" || return 30
        "$1" --version >/dev/null 2>&1 || return 30
    fi
}
ghostty_ready() {
    for ghost in /Applications/Ghostty.app "$HOME/Applications/Ghostty.app"; do
        if [ -d "$ghost" ]; then
            "$ghost/Contents/MacOS/ghostty" --version >/dev/null 2>&1 || return 30
            return 0
        fi
    done
    return 10
}
main() {
    [ "$#" -eq 0 ] || { say '用法：/bin/sh setup.command'; return 64; }
    [ "$(uname -s)" = Darwin ] && [ "$(uname -m)" = arm64 ] || {
        say '仅支持 Apple Silicon macOS；请勿在 Rosetta 终端运行。'; return 30;
    }
    [ "$(id -u)" -ne 0 ] || { say '请以普通用户运行，不要 sudo 整个入口。'; return 30; }
    mac_version=$(sw_vers -productVersion)
    [ "${mac_version%%.*}" -ge 15 ] || { say '当前 Homebrew 支持要求 macOS 15以上，请先处理系统版本。'; return 30; }
    if ! xcode-select -p >/dev/null 2>&1; then
        xcode-select --install || true
        say '请完成系统 Command Line Tools 安装，再运行同一入口。'
        return 20
    fi
    if ! BREW=$(brew_find); then
        say '正在运行 Homebrew 官方安装器；密码由系统直接读取。'
        installer https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh || return 30
        BREW=$(brew_find) || return 30
    fi
    "$BREW" --version >/dev/null || return 30
    [ "$BREW" = /opt/homebrew/bin/brew ] || {
        say 'Homebrew 路径不是 Apple Silicon 标准入口，请处理多安装冲突。'; return 30;
    }
    eval "$("$BREW" shellenv)"
    # Preserve existing profiles: only create a missing one. Conflicts are manual.
    if ! /usr/bin/env -i HOME="$HOME" PATH=/usr/bin:/bin:/usr/sbin:/sbin /bin/zsh -lc 'command -v brew >/dev/null' </dev/null; then
        if [ -e "$HOME/.zprofile" ] || [ -L "$HOME/.zprofile" ]; then
            say '现有 .zprofile 未接通 brew；请修正 PATH 后续跑，不覆盖现有文件。'
            return 20
        fi
        (umask 077; set -C; printf '%s\n' 'eval "$(/opt/homebrew/bin/brew shellenv)"' > "$HOME/.zprofile") || return 30
        /usr/bin/env -i HOME="$HOME" PATH=/usr/bin:/bin:/usr/sbin:/sbin /bin/zsh -lc 'command -v brew >/dev/null' </dev/null || return 30
    fi
    ghost_rc=0
    ghostty_ready || ghost_rc=$?
    case "$ghost_rc" in
        10) "$BREW" install --cask ghostty || return 30; ghostty_ready || return 30 ;;
        0) : ;;
        *) say 'Ghostty 安装不完整，请处理后续跑。'; return 30 ;;
    esac
    if [ "${TERM_PROGRAM:-}" != ghostty ]; then
        say 'Ghostty 已就绪。请在 Ghostty 中重新运行同一 setup.command，继续后续步骤。'
        ask '已经切到 Ghostty？输入 continue 继续，其他输入暂停：' || return 20
        [ "$answer" = continue ] || return 20
    fi
    git --version >/dev/null 2>&1 || brew_package git || return 30
    brew_package gh || return 30
    brew_package chezmoi || return 30
    # Python is a dependency of the downstream checks, not of this bootstrap.
    if [ ! -x /opt/homebrew/bin/python3 ]; then
        "$BREW" install python || return 30
    fi
    /opt/homebrew/bin/python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' || {
        say '后续检查需要 Python 3.11以上；现有版本未升级，请处理后续跑。'; return 30;
    }
    source_dir=$(chezmoi source-path) || return 30
    if [ ! -e "$source_dir/.git" ]; then
        gh auth status >/dev/null 2>&1 || gh auth login --hostname github.com --git-protocol https --web || return 20
        gh auth setup-git --hostname github.com || return 20
        ask '配置仓库（仅 owner/repo，不含 token）：' || return 20
        repo=$answer
        case "$repo" in *[!a-zA-Z0-9_./-]*|/*|*..*|*/|''|*/*/*) say '仓库格式无效。'; return 64;; esac
        case "$repo" in */*) :;; *) return 64;; esac
        if [ -e "$source_dir" ] && [ -n "$(ls -A "$source_dir")" ]; then
            say '配置来源目录非空，请保留内容并手动处理。'; return 30
        fi
        # init config is deliberately not rendered here: no age prompt or scripts.
        git clone -- "https://github.com/$repo.git" "$source_dir" || return 30
    fi
    [ -f "$source_dir/bin/restore" ] && [ -f "$source_dir/bin/lib/setup.py" ] || {
        say '配置仓库尚无 V3 setup 入口，请取得已交付版本；不会执行旧全量恢复。'; return 30;
    }
    say "使用配置来源：$source_dir"
    ask '确认信任该配置仓库并运行其 setup？输入 continue：' || return 20
    [ "$answer" = continue ] || return 20
    exec /bin/zsh "$source_dir/bin/restore" setup
}

# Functions can be sourced by tests without invoking system installation.
case "$0" in */setup.command|setup.command) main "$@" ;; esac
