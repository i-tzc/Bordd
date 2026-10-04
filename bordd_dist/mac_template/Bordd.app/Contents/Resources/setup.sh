#!/bin/bash
# ============================================================
#  Bordd 首次运行安装脚本
#
#  做的事：
#    1. 找一个 Python 3.10+
#    2. 在 ~/Library/Application Support/Bordd/ 下建独立运行环境
#    3. 安装 Pillow（必需）与 pikepdf（可选，仅 PDF 模式用）
#    4. 启动图形界面
#
#  安装过程会同时写入日志：~/Library/Logs/Bordd/setup.log
# ============================================================

set -u

_HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
. "$_HERE/lib.sh"

say "================================================================"
say "  Bordd — 首次运行准备"
say "================================================================"
say ""
say "所有组件都会装到："
say "  $SUPPORT"
say "不会改动系统自带的 Python。"
say ""

# ------------------------------------------------------------
# 1. 找 Python
# ------------------------------------------------------------
say "第 1 步 / 共 3 步：检查 Python"

if ! PY="$(find_python)"; then
    say "  ✗ 没有找到 Python 3.10 或更高版本。"
    say ""
    say "  请先安装 Python："
    say "    1) 浏览器会打开 https://www.python.org/downloads/macos/"
    say "    2) 点最上面那个大按钮下载 .pkg 安装包"
    say "    3) 双击 .pkg，一路点「继续 / 同意 / 安装」"
    say "    4) 安装完成后，重新双击 Bordd"
    open_python_download
    dialog "还没有安装 Python 3.10 或更高版本。已为你打开下载页面，装好后请重新双击 Bordd。"
    exit 1
fi

say "  ✓ 使用 Python：$PY"
say "    版本：$("$PY" -c 'import sys; print(sys.version.split()[0])')"

if ! "$PY" -c 'import tkinter' >/dev/null 2>&1; then
    say "  ✗ 这个 Python 缺少图形库 tkinter，无法显示界面。"
    dialog "这个 Python 缺少图形库 tkinter。请到 python.org 重新安装官方版 Python。"
    exit 1
fi
say "  ✓ 图形库 tkinter 正常"
say ""

# ------------------------------------------------------------
# 2. 建独立运行环境
# ------------------------------------------------------------
say "第 2 步 / 共 3 步：准备运行环境"

mkdir -p "$SUPPORT" 2>/dev/null || true

if [ ! -x "$VENV/bin/python" ]; then
    say "  正在创建独立环境（不会影响系统）…"
    if ! "$PY" -m venv "$VENV" >>"$SETUP_LOG" 2>&1; then
        say "  ✗ 创建失败，详情见 $SETUP_LOG"
        dialog "创建运行环境失败。请重新安装 Python（使用 python.org 官方安装包）后再试。"
        exit 1
    fi
    say "  ✓ 已创建"
else
    say "  ✓ 已存在，跳过"
fi
VPY="$VENV/bin/python"
say ""

# ------------------------------------------------------------
# 3. 安装依赖
# ------------------------------------------------------------
say "第 3 步 / 共 3 步：安装组件（需要联网）"

if [ -f "$DEPS_STAMP" ]; then
    say "  ✓ 组件已就绪，跳过下载"
else
    say ""
    say "  正在下载，请耐心等待（约 1~3 分钟）…"
    say ""

    "$VPY" -m pip install --upgrade pip --quiet --disable-pip-version-check \
        >>"$SETUP_LOG" 2>&1 || true

    say "  [1/2] 安装 Pillow（图像处理，必需）…"
    if ! "$VPY" -m pip install --only-binary=:all: "Pillow==12.3.0" \
            --disable-pip-version-check --quiet >>"$SETUP_LOG" 2>&1; then
        say "        指定版本装不上，改用其它兼容版本重试…"
        if ! "$VPY" -m pip install --only-binary=:all: "Pillow>=10" \
                --disable-pip-version-check >>"$SETUP_LOG" 2>&1; then
            say ""
            say "  常见原因："
            say "    · 网络不通（请检查 Wi-Fi，或换用手机热点重试）"
            say "    · Python 版本过旧（需要 3.10 或更高）"
            say ""
            say "  详细日志：$SETUP_LOG"
            dialog "Pillow 安装失败。请检查网络后重新双击 Bordd；若仍失败，请把终端里的文字截图发给对方。"
            exit 1
        fi
    fi
    say "        ✓ 完成"

    say "  [2/2] 安装 pikepdf（仅「PDF 容器保真」模式需要，可选）…"
    # 不锁版本 + 只允许预编译包：让 pip 自动挑选与当前 macOS 版本兼容的版本。
    # 装不上不影响其它功能，只是无法输出 PDF。
    if "$VPY" -m pip install --only-binary=:all: "pikepdf<11" \
            --disable-pip-version-check --quiet >>"$SETUP_LOG" 2>&1; then
        say "        ✓ 完成，PDF 保真模式可用"
    else
        say "        ! 未能安装（不影响使用，只是没有 PDF 输出功能）"
    fi

    printf 'ok\n' > "$DEPS_STAMP"
    say ""
    say "  ✓ 全部就绪"
fi

say ""
say "================================================================"
say "  正在打开 Bordd 主界面…"
say "================================================================"
say ""
say "小提示："
say "  · 界面如果没跳到最前面，点一下 Dock 里的 Bordd 图标即可。"
say "  · 这个终端窗口可以直接关掉，不影响程序使用。"
say "  · 以后直接双击 Bordd（应用程序图标）即可，不再需要终端。"
say ""

cd "$APP_SRC" 2>/dev/null || true
"$VPY" "$APP_SRC/bordd_gui.py"
RC=$?

say ""
if [ "$RC" -eq 0 ]; then
    say "程序已正常退出。"
else
    say "程序异常退出（代码 $RC）。"
    say "错误日志：$LOG_DIR/error.log"
    dialog "程序异常退出（代码 $RC）。错误日志在 ~/Library/Logs/Bordd/error.log，请把它发给对方。"
fi
say ""
say "（这个终端窗口可以直接关掉）"
