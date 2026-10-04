#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证 macOS 启动器里的 Python 探测逻辑（find_python / ok_version）。

做法：从真实的 Bordd.app/Contents/Resources/lib.sh 中抽出这两个函数，
配合伪造的 python3（一个伪装成 3.9、一个伪装成 3.12）在 bash 下跑，
确认版本过滤和 PATH 扫描都正确。

用法：python tests/test_launcher_logic.py "D:\\Git\\bin\\bash.exe"
"""
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIB = (ROOT / "bordd_dist" / "mac_template" / "Bordd.app"
       / "Contents" / "Resources" / "lib.sh")

BASH = sys.argv[1] if len(sys.argv) > 1 else r"D:\Git\bin\bash.exe"


def extract_functions(text: str) -> str:
    start = text.index("ok_version() {")
    end = text.index("\n}", text.index("find_python() {")) + 2
    return text[start:end]


def main() -> int:
    if not LIB.exists():
        print(f"找不到 lib.sh：{LIB}")
        return 2

    text = LIB.read_text(encoding="utf-8")
    funcs = extract_functions(text)

    tmp = Path(tempfile.mkdtemp(prefix="ab_launcher_test_"))
    old_dir, new_dir = tmp / "old", tmp / "new"
    old_dir.mkdir()
    new_dir.mkdir()

    # 伪造的 python3：对 `-c` 分别返回“版本够”或“版本不够”
    old_stub = "#!/bin/bash\n[ \"$1\" = \"-c\" ] && exit 1\nexit 1\n"      # 3.9：一切检查都失败
    new_stub = "#!/bin/bash\n[ \"$1\" = \"-c\" ] && exit 0\nexit 0\n"      # 3.12：一切检查都通过
    (old_dir / "python3").write_text(old_stub, encoding="utf-8", newline="\n")
    (new_dir / "python3").write_text(new_stub, encoding="utf-8", newline="\n")

    def q(p: Path) -> str:
        """Windows 路径 -> Git Bash 路径"""
        s = str(p).replace("\\", "/")
        return "/" + s[0].lower() + s[2:]

    script = f"""#!/bin/bash
{funcs}

chmod +x "{q(old_dir)}/python3" "{q(new_dir)}/python3"

pass=0; fail=0
t() {{
  local label="$1" expect="$2" path="$3"
  local got
  PATH="$path"
  got="$(find_python)"
  if [ "$expect" = "none" ]; then
    if [ -z "$got" ]; then echo "  PASS  $label"; pass=$((pass+1));
    else echo "  FAIL  $label (不该找到，却得到 $got)"; fail=$((fail+1)); fi
  else
    case "$got" in
      *"$expect"*) echo "  PASS  $label -> $got"; pass=$((pass+1));;
      *) echo "  FAIL  $label (期望包含 $expect，实际 '$got')"; fail=$((fail+1));;
    esac
  fi
}}

echo "--- find_python 行为验证 ---"
t "只有 3.9 时判定为找不到"        none  "{q(old_dir)}:/usr/bin:/bin"
t "3.9 在前、3.12 在后时选中 3.12"  new   "{q(old_dir)}:{q(new_dir)}:/usr/bin:/bin"
t "只有 3.12 时选中它"              new   "{q(new_dir)}:/usr/bin:/bin"
t "PATH 为空时判定为找不到"         none  ""
t "PATH 里没有 python3 时找不到"    none  "/usr/bin:/bin"

echo ""
echo "通过 $pass 项，失败 $fail 项"
[ "$fail" -eq 0 ] || exit 1
"""
    # noqa: E501
    test_file = tmp / "run_test.sh"
    test_file.write_text(script, encoding="utf-8", newline="\n")

    # 先做语法检查
    syntax = subprocess.run([BASH, "-n", q(test_file)],
                            capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    print(f"bash -n 语法检查：{'通过' if syntax.returncode == 0 else '失败'}")
    if syntax.returncode != 0:
        print(syntax.stderr)
        return 1

    ver = subprocess.run([BASH, "--version"], capture_output=True, text=True,
                         encoding="utf-8", errors="replace").stdout.splitlines()
    print(f"bash 版本：{ver[0] if ver else '?'}")
    print()
    proc = subprocess.run([BASH, q(test_file)], capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    print(proc.stdout)
    if proc.stderr.strip():
        print("STDERR:", proc.stderr.strip())

    if proc.returncode != 0:
        print("=" * 60)
        print("生成的测试脚本如下（便于定位断言问题）：")
        print("=" * 60)
        for i, line in enumerate(script.splitlines(), 1):
            print(f"{i:3}: {line}")
        print("=" * 60)
        print(f"临时目录保留：{tmp}")
        return proc.returncode

    shutil.rmtree(tmp, ignore_errors=True)
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
