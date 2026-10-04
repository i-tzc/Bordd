#!/bin/bash
# ============================================================
#  Bordd 共用函数库（被 MacOS/Bordd 与 Resources/setup.sh 引用）
#
#  只使用 macOS 自带 bash 3.2 就支持的语法。
# ============================================================

# 本文件位于 Bordd.app/Contents/Resources/lib.sh
_LIB_DIR="$(cd "$(dirname "$0")" && pwd)"
BUNDLE="$(cd "$_LIB_DIR/../.." && pwd)"      # .../Bordd.app
RES="$_LIB_DIR"                              # .../Bordd.app/Contents/Resources
APP_SRC="$RES/app"                           # 打包进去的 Python 源码

# 运行环境放在用户目录，而不是 .app 内部：
#   1) 应用可能被放进 /Applications，那里普通用户没有写权限；
#   2) 升级 .app 时不会连带丢掉已装好的依赖。
SUPPORT="$HOME/Library/Application Support/Bordd"
VENV="$SUPPORT/venv"
DEPS_STAMP="$VENV/.bordd_deps_ok"
LOG_DIR="$HOME/Library/Logs/Bordd"
SETUP_LOG="$LOG_DIR/setup.log"

mkdir -p "$LOG_DIR" 2>/dev/null || true

say() { printf '%s\n' "$*"; }

# 弹一个系统对话框；没有图形会话时静默失败，不影响终端里的文字提示
dialog() {
    osascript -e "display dialog \"$1\" buttons {\"好\"} default button 1 with title \"Bordd\"" \
        >/dev/null 2>&1 || true
}

# macOS 自带 bash 3.2 也支持的版本判断
ok_version() {
    "$1" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 10) else 1)' \
        >/dev/null 2>&1
}

# 找一个 Python 3.10+：
#   1) 先看常见安装位置（python.org / Homebrew），避免误用 Xcode 自带的旧版本；
#   2) 再逐个扫描 PATH —— 不能只看第一个，第一个可能是系统自带的旧版本。
find_python() {
    local p dir
    for p in \
        /usr/local/bin/python3 \
        /opt/homebrew/bin/python3 \
        /Library/Frameworks/Python.framework/Versions/*/bin/python3 \
        /usr/local/bin/python3.13 /usr/local/bin/python3.12 /usr/local/bin/python3.11 \
        /opt/homebrew/bin/python3.13 /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3.11
    do
        [ -x "$p" ] || continue
        if ok_version "$p"; then printf '%s' "$p"; return 0; fi
    done
    local IFS=:
    for dir in $PATH; do
        [ -n "$dir" ] || dir="."
        p="$dir/python3"
        [ -x "$p" ] || continue
        if ok_version "$p"; then printf '%s' "$p"; return 0; fi
    done
    return 1
}

# Python 就绪（含 venv 与依赖）时返回 0
runtime_ready() {
    [ -x "$VENV/bin/python" ] && [ -f "$DEPS_STAMP" ]
}

# 打开 python.org 下载页
open_python_download() {
    open "https://www.python.org/downloads/macos/" >/dev/null 2>&1 || true
}
