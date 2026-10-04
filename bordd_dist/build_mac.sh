#!/usr/bin/env bash
# ============================================================
# Bordd — macOS 构建启动器
#
# 这里只负责找到解释器；全部构建逻辑与中文提示都在 build.py 中，
# 两个平台共用同一套流程，避免 .bat / .sh 各写一份而行为不一致。
#
# 产物：dist/Bordd.app（图形界面，双击使用）、dist/Bordd（命令行）
#
# 用法：
#   ./build_mac.sh
#   ./build_mac.sh --gui-only
#   PYTHON=/opt/homebrew/bin/python3 ./build_mac.sh --arch native
# ============================================================
set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"

if ! command -v "$PY" >/dev/null 2>&1; then
  echo "[错误] 找不到解释器：$PY"
  echo "        请安装 Python 3.10+，或设置 PYTHON 环境变量指向它。"
  exit 1
fi

exec "$PY" build.py "$@"
