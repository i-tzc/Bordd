# Bordd — 图片批量加边框 / 无损封装 / 纯压缩

为图片加边框以统一宽高比，或做字节级无损封装与纯压缩。
提供**图形界面**与**命令行**两种用法。

| 平台 | 图形界面（双击使用） | 命令行 |
| --- | --- | --- |
| Windows | `Bordd_gui.exe` | `Bordd.exe` |
| macOS | `Bordd.app` | `Bordd` |

---

## 目录结构

```
Bordd/                                （工作区根目录本身未改名，便于沿用现有工程）
├─ bordd.py                         核心逻辑 + 命令行入口
├─ bordd_gui.py                     图形界面（Tkinter，跨平台）
├─ assets/                          程序图标
│  ├─ Bordd.ico / Bordd.icns        Windows / macOS 图标（make_icon.py 生成）
│  ├─ icon_png/                     各尺寸 PNG
│  └─ make_icon.py                  图标生成器（纯 Python，无需 macOS）
├─ docs/                            文档与界面截图
│  └─ 给朋友的Mac安装运行指南.md      把程序分享给 Mac 用户的全流程
├─ tests/                           测试与截图工具
│  ├─ smoke_test.py                 源码级冒烟测试（30 项）
│  ├─ verify_frozen.py              冻结产物验收（20 项）
│  ├─ test_launcher_logic.py        Mac 启动器逻辑测试（5 项，需 bash）
│  ├─ verify_mac_package.py         Mac 传输包验收（40 项，需 bash）
│  ├─ capture_gui.py / capture_window.py / click_start.py   界面截图与自动点击
└─ bordd_dist/                      打包相关
   ├─ Bordd_gui.spec                PyInstaller 规格（GUI 版）
   ├─ Bordd_cli.spec                PyInstaller 规格（命令行版）
   ├─ build.py                      跨平台构建驱动（两平台共用）
   ├─ build_windows.bat             Windows 一键构建
   ├─ build_mac.sh                  macOS 一键构建
   ├─ mac_template/                 Mac 传输包模板（Bordd.app 骨架）
   ├─ make_mac_share.py             组装并打包「发给 Mac 用户」的 zip
   └─ requirements.txt              运行依赖
```

---

## 一、关于「双击闪退」——原因与处理

**这不是崩溃，是命令行程序的正常退出。**

`Bordd.exe` 是纯命令行工具，`--input` 与 `--output` 是**必需参数**。
双击运行时没有携带任何参数，于是：

1. Windows 打开一个控制台窗口并启动程序；
2. `argparse` 发现缺少必需参数，打印用法说明，以退出码 `2` 结束；
3. 进程结束 → 控制台窗口随之关闭。

整个过程通常在几十毫秒内完成，视觉上就是「窗口闪一下就没了」。

**现在的处理方式：**

| 场景 | 之前 | 现在 |
| --- | --- | --- |
| 双击 GUI 版 `Bordd_gui.exe` | 不存在 | 直接打开图形界面 |
| 双击命令行版 `Bordd.exe` | 闪退，看不到任何提示 | 显示完整帮助 + 指引，并**暂停等待回车** |
| 在 cmd / PowerShell 里运行 `Bordd.exe` | 打印用法，退出码 2 | 完全不变（不会多此一举地暂停） |

> 双击检测的实现见 `bordd.py` 的 `_launched_by_double_click()`：
> 通过当前控制台挂载的进程数判断是否由资源管理器新建控制台启动。
> onefile 的引导进程会额外占一个进程（onedir 不会），代码用
> `sys._MEIPASS` 的位置自动区分两种模式并调整阈值。
> 检测不出来的场合一律安全降级为旧行为，不会误暂停。

---

## 二、图形界面（推荐）

**无需任何命令行参数，双击即可。** 窗口标题就是 `Bordd`。

- 输入 / 输出目录选择，输出目录默认自动填为「输入目录名 + `_bordered`」
- 目标比例：预设 `4:3 / 3:4 / 9:16 / 16:9 / 1:1`，也可直接输入自定义比例，如 `21:9`
- 边框颜色：黑色 / 白色（带色块预览）
- 边框宽度：滑杆调节，0% ~ 40%，步进 0.5%
- 输出格式：保持原格式 / 统一无损 PNG / PDF 容器保真
- JPEG 质量：1 ~ 100（仅「保持原格式」时可用）
- 纯压缩模式：不加边框，画布 = 原图尺寸
- **实时效果预览**：显示第一张图片加边框后的实际效果、源图与输出尺寸、比例
- 后台线程处理，界面不卡死；可随时点「停止」
- 彩色日志（成功 / 失败 / 警告）与进度条

界面语言为中文，字体按平台自动选择（Windows 用微软雅黑，macOS 用苹方），
并针对高 DPI 屏幕做了缩放适配。窗口尺寸会夹紧到屏幕范围内，小屏不会被截断。
在 macOS 上从 `.app` 启动时会主动把窗口提到最前面。

### 从源码运行

```bash
pip install -r bordd_dist/requirements.txt
python bordd_gui.py                    # 打开界面
python bordd_gui.py /path/to/photos    # 打开界面并预填该目录
```

---

## 三、命令行用法

```bash
Bordd --version
Bordd -i ./photos -o ./out -r 4:3 -c black                       # 加边框（默认 q95）
Bordd -i ./photos -o ./out -r 4:3 -f pdf -c white                # PDF 容器（JPEG 字节级无损）
Bordd -i ./photos -o ./out -r 4:3 -f png                         # 统一无损 PNG
Bordd -i ./photos -o ./compressed --no-border --jpeg-quality 90  # 纯压缩
```

| 参数 | 说明 |
| --- | --- |
| `-i, --input` | 输入图片目录（必填） |
| `-o, --output` | 输出目录（必填；不得与输入目录相同） |
| `-r, --ratio` | 目标宽高比：`4:3` / `3:4` / `9:16` / `16:9` / `1:1`，或自定义如 `21:9`；`--no-border` 时可省略 |
| `-c, --color` | 边框颜色：`black`（默认）/ `white` |
| `--border-percent` | 长边每侧边框占比（默认 `0.02`，即每边 2%） |
| `-f, --format` | `keep`（默认）/ `png`（统一无损 PNG）/ `pdf`（PDF 容器，仅 JPEG） |
| `--jpeg-quality` | keep 模式下的 JPEG 质量（默认 95，1–100） |
| `--no-border` | 不加边框，画布 = 原图尺寸（纯压缩模式） |
| `--version` | 显示版本号 |

**退出码**：全部成功 `0`；有图片处理失败或参数/目录错误 `1`；参数缺失 `2`。
便于脚本与批处理判断结果。

---

## 四、保真度说明

| 模式 | 保真程度 |
| --- | --- |
| `-f pdf` | 原始 JPEG 字节**原样嵌入** PDF（`/DCTDecode` 透传，`compress_streams=False`），图像数据与源文件逐字节一致，可校验 SHA 完全相同；边框是 PDF 矢量矩形，不产生任何像素修改。PDF 不承载 EXIF |
| `-f png` | 像素级无损（含 16 位 PNG、EXIF / ICC / 位深） |
| `keep` | JPEG 只能有损重编码，默认 `quality=95` + `subsampling=0`（4:4:4）；其余格式无损 |

三种模式都会自动保留 **EXIF / ICC 色彩配置 / DPI**。
输出与输入同路径、或转换后重名（如 `a.jpg` 与 `a.png` 都变成 `a.png`）时会直接报错阻止覆盖。

**加边框策略**：不缩放原图，只在长边方向每侧留固定比例边框，画布严格等于目标比例，原图居中。
原图更宽则加在左右，更高则加在上下；比例已相等时仍按左右留边框以保持风格统一。

---

## 五、双平台构建

### 前置条件

| 项目 | 要求 |
| --- | --- |
| Python | 3.10 ~ 3.13（需包含 tkinter，官方安装包默认包含） |
| 运行依赖 | `pip install -r bordd_dist/requirements.txt`（Pillow、pikepdf） |
| 构建依赖 | `pip install pyinstaller` |
| 操作系统 | Windows 版只能在 Windows 构建，macOS 版只能在 macOS 构建（PyInstaller **不支持交叉编译**） |

### Windows

```bat
cd bordd_dist
build_windows.bat
```

| 产物 | 用途 |
| --- | --- |
| `dist\Bordd_gui\Bordd_gui.exe` | 图形界面版，**双击使用** |
| `dist\Bordd_cli\Bordd.exe` | 命令行版，保留控制台输出 |

指定解释器（例如某个 conda 环境）：

```bat
set PYTHON=D:\miniconda3\envs\PyTorch\python.exe
build_windows.bat
```

### macOS

```bash
cd bordd_dist
chmod +x build_mac.sh && ./build_mac.sh
```

| 产物 | 用途 |
| --- | --- |
| `dist/Bordd.app` | 图形界面版，**双击使用**（含 Dock 图标） |
| `dist/Bordd_cli/Bordd` | 命令行版 |

默认先尝试 `universal2`（Apple Silicon + Intel 二合一）；若当前 Python 不是
universal2 版本，脚本会自动回退为只构建当前架构。也可手动指定：

```bash
./build_mac.sh --arch native       # 只构建当前架构
PYTHON=/opt/homebrew/bin/python3 ./build_mac.sh
```

首次打开若提示「来自身份不明的开发者」（未签名的正常现象）：

```bash
xattr -dr com.apple.quarantine dist/Bordd.app
```

### 为什么用 onedir（目录）而不是 onefile（单文件）

两者都能双击运行，但 **onefile 每次启动都要把自身解压到系统临时目录**
（`%TEMP%\_MEIxxxx`），由此带来三个真实问题：

1. **临时目录不可写就直接启动失败**。而窗口版没有控制台，报错完全看不见——
   用户看到的就是「双击没反应」，极难排查。实际上本次就是踩到了这个坑
   （受限环境下连一个 hello-world 的 onefile 程序都会报
   `Could not create temporary directory!`）。
2. 部分杀毒 / 终端防护软件会拦截这种「自己解压自己再执行」的行为。
3. 每次启动都要解压 20+ MB，慢 1~2 秒。

onedir 直接从同目录的 `_internal/` 加载，**不写任何临时目录**，
启动更快、兼容性更好。

> ⚠️ 代价：产物是一个文件夹。**发布时必须整个文件夹一起拷，不能只拷 exe**，
> 否则会因为缺少 `_internal/` 而无法启动。

### 构建脚本说明

`build_windows.bat` 与 `build_mac.sh` 都只是**启动器**，真正的构建逻辑在
`bordd_dist/build.py`，两个平台共用同一套流程。

> 为什么批处理里不直接写逻辑？Windows 的 `cmd.exe` 按「控制台代码页」
> （简体中文系统通常是 936/GBK）读取 `.bat` 文件。如果 `.bat` 存成 UTF-8，
> 中文会被错误解码，某些汉字的尾字节甚至会被当成 `|` 或 `>` 之类的特殊符号，
> 导致脚本报语法错误而无法执行。因此两个启动器只保留 ASCII，所有中文提示
> 都放在 UTF-8 的 `build.py` 中。

### 自动构建（云端出 Mac 版，推荐给没有 Mac 的人）

仓库已包含 `.github/workflows/build.yml`：推送到 `main` / `master`
（或在 Actions 页面手动触发）后，会在 Windows 与 macOS 上各构建一份，
从 Actions 页面下载即可。

> 该工作流假设**仓库根目录是包含 `bordd.py`、`bordd_gui.py`、`assets/`
> 与 `bordd_dist/` 的那一层**，因此文件位于仓库根的 `.github/workflows/` 下。

⚠️ **一个必须避开的坑**：GitHub 官方文档明确写着
*"File permissions are not maintained during artifact upload"* ——
直接把 `Bordd.app` 交给 `upload-artifact`，下载回来时
`Contents/MacOS/` 里的可执行位就没了，朋友双击**没有任何反应**；
符号链接也可能被压成普通文件导致 `.app` 损坏。

因此 CI 里多了一步：先用 `bordd_dist/make_app_zip.py` 把 `.app` 压成
一个**内部记录了 0755 权限与符号链接**的 zip，再把「这个 zip 文件」
当普通文件上传。传输过程只需保证文件内容不变，这一点是可靠的。
脚本自带校验——入口若缺可执行位会返回非 0，让 CI 直接失败而不是
悄悄产出一个打不开的 App。

---

## 六、分享给没有构建条件的 Mac 用户

Windows 的 `.exe` 在 Mac 上无法运行，而 PyInstaller **不支持交叉编译**。
两种给法：

**（一）轻量版：源码 + 现成的 `Bordd.app` 外壳（130 KB）**

朋友需要先装一次 Python（python.org，约 3 分钟），之后双击即用。
好处是包极小、传输快。

```bash
python bordd_dist/make_mac_share.py
```

生成 `mac_share/Bordd_mac.zip`（约 130 KB），发给对方即可。
他解压后**双击 `Bordd` 图标**：

- 环境已就绪 → 直接启动图形界面（**不弹终端窗口**，与 Windows 双击
  `Bordd_gui.exe` 一致）
- 首次运行 → 弹窗说明后自动打开终端安装依赖（1~3 分钟），装完自动开界面

`Bordd.app` 内部结构：

```
Bordd.app/Contents/
├── Info.plist                     名字/图标/可执行入口
├── MacOS/Bordd                    ★ 双击 .app 时由 macOS 执行的入口脚本
└── Resources/
    ├── lib.sh                     共用函数（找 Python、弹窗、路径）
    ├── setup.sh                   首次运行：建环境 + 装组件 + 开界面
    ├── Bordd.icns                 应用图标
    └── app/                       程序本体（bordd.py / bordd_gui.py / assets）
```

> **三个关键细节**
> - 打包 zip 时用 Python 的 `zipfile` 手工写入 Unix 权限位（入口脚本 `0755`）。
>   Windows 的压缩工具不写这个，解压后 `.app` 会丢掉可执行标记，
>   macOS 上双击没反应。
> - `.icns` 图标由 `assets/make_icon.py` **直接按 ICNS 容器格式拼出来**
>   （内部放 PNG 块），因此不需要 macOS 的 `iconutil`，在 Windows 上也能
>   为 Mac 版准备好图标。
> - `pikepdf` 的 macOS 安装包有系统版本门槛（10.x 需要 macOS 14+），
>   所以安装脚本**不锁版本**并加 `--only-binary=:all:`，交由 pip 选择与
>   当前系统兼容的最新版本；装不上时只损失 PDF 输出，其余功能照常。
>
> 运行环境装在 `~/Library/Application Support/Bordd/`，不写进 `.app`
> 内部——这样应用可以自由拖进「应用程序」文件夹，升级时也不会丢依赖。

完整的分步说明见 [`docs/给朋友的Mac安装运行指南.md`](docs/给朋友的Mac安装运行指南.md)。

**（二）免安装版：云端构建自包含 `Bordd.app`（约 50 MB）**

朋友**什么都不用装**（连 Python 都不需要），解压双击即用。
代价是要先把工程推到 GitHub，用 Actions 在云端 Mac 上构建
（见上文「自动构建」），然后下载 `Bordd-macos` 产物转交给他。

> 注意区分：这里的 `.app` 是 PyInstaller 打出来的**自包含**应用；
> 轻量版里的 `Bordd.app` 只是一个「外壳 + 本机 Python 环境」的启动器。
> 两者对使用者来说都是「双击图标」，区别只在需不需要装 Python。

---

## 七、测试

```bash
python tests/smoke_test.py                              # 源码级（30 项）
python tests/verify_frozen.py                           # Windows 产物（20 项）
python tests/test_launcher_logic.py  <bash路径>          # Mac 探测逻辑（5 项）
python tests/verify_mac_package.py   <bash路径>          # Mac 传输包（40 项）
```

| 脚本 | 覆盖内容 |
| --- | --- |
| `smoke_test.py` | 界面构建、控件联动、参数校验、预览生成、三种输出格式真实处理、纯压缩画布、防覆盖保护、取消功能、异常钩子 |
| `verify_frozen.py` | 产物存在性、`--version` / `--help`、三种格式真实处理、画布比例与边框像素、纯压缩画布、**PDF 图像流与源 JPEG 逐字节一致**、防覆盖、退出码、非法参数、**双击时暂停不闪退** |
| `test_launcher_logic.py` | `find_python` 的版本过滤与 PATH 扫描（伪造 3.9 / 3.12 解释器） |
| `verify_mac_package.py` | `.app` 结构、`Info.plist` 字段、脚本 LF/无 BOM/`bash -n`、source 路径可解析、zip 权限位、zip 内容逐字节一致 |

界面截图工具（开发用）：

```bash
python tests/capture_gui.py <图片目录> docs/shot.png [border|noborder|pdf|error]
python tests/capture_window.py "Bordd" docs/shot.png     # 抓已运行窗口（PrintWindow）
```

---

## 八、常见问题

- ⚠️ **打包好的程序必须放到本工程目录之外再运行。**
  开发环境（DSH 会话）会把**位于 `D:\PyCharm\work\add_border` 内部的
  可执行文件**限制为「只能往这个目录里写」。表现就是处理别的目录时报
  `[WinError 5] 拒绝访问` / `无法创建输出目录`，但把同一份程序拷到
  `D:\Bordd`、桌面等位置就完全正常。
  已实测：同一个 PyInstaller 程序放在工作区内失败、拷到桌面后成功；
  未打包的 `python.exe` 不受影响。**发布时把 `Bordd_gui` 文件夹拷到
  工程外再运行即可。**
- **Windows SmartScreen 拦截**：未签名的 exe 首次运行会提示
  「Windows 已保护你的电脑 / 发布者未知」。点「更多信息」→「仍要运行」，
  或右键 exe → 属性 → 勾选「解除锁定」。
- **朋友是 Mac，怎么给他？** 传 `mac_share/Bordd_mac.zip`（用
  `make_mac_share.py` 生成），**不要传 `.exe`**。详见
  [给朋友的Mac安装运行指南](docs/给朋友的Mac安装运行指南.md)。
- **Mac 上双击 `Bordd` 没反应？** zip 传输中丢了可执行权限。在终端里
  `chmod -R +x ` + 拖入 `Bordd` 图标即可修复；用本项目的
  `make_mac_share.py` 打的 zip 已内置 `0755`，可避免此问题。
- **双击 `Bordd.exe` 只看到提示就没了？** 现在会暂停等待回车。想双击使用请运行 `Bordd_gui\Bordd_gui.exe`（macOS 为 `Bordd.app`）。
- **「双击没反应」怎么排查？** 窗口版（`Bordd_gui.exe`）没有控制台，
  启动阶段的错误看不见。先用命令行版 `Bordd_cli\Bordd.exe --version`
  对照：它保留控制台，任何报错都会打印出来。
- **只拷贝了 exe，启动不了**：onedir 产物是文件夹，
  必须整个 `Bordd_gui\` 一起拷（里面还有 `_internal\`）。
- **`Could not create temporary directory`**：onefile 模式往系统临时目录
  解压时才会出现。本项目已改用 onedir，不会再遇到。
- **杀毒软件误报**：PyInstaller 打包的程序偶发被 Windows Defender 误报，属已知现象，添加信任即可。
- **PDF 模式报「需要 pikepdf」**：说明打包未包含该依赖，请重新运行构建脚本。
- **PDF 模式跳过某些文件**：PDF 保真模式只支持 JPEG 输入，其它格式会记为失败；请改用 `-f png`。
- **Mac 上装不上 pikepdf**：官方新版只提供 macOS 14+ 的安装包；安装脚本会自动
  向下选择兼容版本，若仍失败则仅损失 PDF 输出，其它功能不受影响。
- **启动速度**：onedir 无需解压，双击后基本立刻出界面。
- **GUI 版启动报错**：窗口版没有控制台，异常会弹窗提示，详细堆栈写入
  `%LOCALAPPDATA%\Bordd\error.log`（macOS 为 `~/Library/Logs/Bordd/error.log`）。
