# luobo-ppt 安装说明

本地冻结版1.0.2的源码入口与更新边界见 [本地定制维护.md](本地定制维护.md)，不要用通用安装器覆盖已有冻结源码。下述通用 `install.sh` 在同一文件系统暂存并检查副本后替换目标，保留已有 `config.json`；复制或发布失败时保留／恢复旧安装。若恢复本身失败，会保留备份并打印位置，需先处理该错误再重试。

通过目录软链运行时按物理路径判断源和目标；安装到自身跳过复制，源与目标互相包含时拒绝。需要只复制文件、避免安装依赖时使用 `bash install.sh --dest /path/to/skills --skip-deps`。

luobo-ppt（萝卜 PPT）能从零生成 PPT，也能按参考图美化现有 PPT。它就是之前的 ppt-studio 和更早的 ppt-beautify，改了名字，安装脚本会自动移除旧名字的版本，并把旧版里的生图配置带过来。

这个 skill 遵循 SKILL.md 开放标准，Claude、Codex、Gemini CLI、Cursor、GitHub Copilot 等支持 skill 的 Agent 都能装。
装好之后，Agent 需要能执行命令、能看图片，skill 才能完整跑起来。

安装脚本会做三件事：把 skill 复制到对应 Agent 的 skills 目录，检查并安装依赖，最后生成一份两页的小样做自测。

## 方式零：从 GitHub 安装

仓库根目录就是 skill 本身，克隆到 Agent 的 skills 目录即可，目录名用 `luobo-ppt`：

```bash
git clone https://github.com/zhouwei713/luobo-ppt.git ~/.claude/skills/luobo-ppt
```

其他 Agent 的目录见下面"方式三"的表格。也可以直接对 Agent 说"帮我安装这个 skill：https://github.com/zhouwei713/luobo-ppt"。

## 方式一：Claude 应用（Cowork / claude.ai）

在对话里点 `.skill` 文件卡片上的保存按钮即可。
第一次使用时，skill 会自动运行环境检查并补装缺少的 Python 包，Claude 的云端环境里依赖基本是现成的，通常几秒就结束。

## 方式二：本地 Agent 一键安装（推荐）

1. 解压 `luobo-ppt.skill`。它本质是 zip 文件，Windows 上可以先把后缀改成 `.zip` 再右键解压。
2. 进入解压出来的 `luobo-ppt` 文件夹，运行安装脚本。

macOS / Linux

```bash
bash install.sh
```

Windows

双击 `install.bat`，或者在 PowerShell 里运行 `.\install.ps1`。

脚本会自动识别你电脑上装了哪些 Agent，分别装进去。想指定 Agent 或位置，可以加参数。

| 参数 | 作用 |
|---|---|
| `--agent codex`（Windows 用 `-Agent codex`） | 只装给某个 Agent，可选 claude-code、codex、gemini、cursor、copilot、agents、all |
| `--project 路径` | 装进某个项目目录（只在这个项目里生效） |
| `--dest 路径` | 装进任意 skills 目录 |
| `--skip-deps` | 只复制文件，不检查依赖 |
| `--uninstall` | 卸载 |

## 方式三：手动安装

把整个 `luobo-ppt` 文件夹复制到下表对应的目录，然后运行一次依赖检查。

```bash
python3 <skill目录>/scripts/setup_check.py --install --selftest
```

Windows 上把 `python3` 换成 `python` 或 `py -3`。

| Agent | 个人目录（所有项目可用） | 项目目录 |
|---|---|---|
| Claude Code | `~/.claude/skills/` | `.claude/skills/` |
| OpenAI Codex CLI | `~/.agents/skills/` | `.agents/skills/` |
| Gemini CLI | `~/.gemini/skills/` | `.gemini/skills/` |
| Cursor | `~/.cursor/skills/` | `.cursor/skills/` |
| GitHub Copilot（VS Code） | `~/.copilot/skills/` | `.github/skills/` |
| 其他支持开放标准的 Agent | `~/.agents/skills/` | `.agents/skills/` |

`~` 在 Windows 上是 `C:\Users\你的用户名`。Cursor 也会读取 Claude 和 Codex 的目录，所以装过这两个的话，一键脚本不会再给 Cursor 重复装一份。
各家目录偶尔会调整，装完 Agent 认不出来时，以它的官方文档为准。

## 依赖清单

| 级别 | 组件 | 用途 | 缺了会怎样 |
|---|---|---|---|
| 必需 | Python 3.8+ | 运行脚本 | 无法使用 |
| 必需 | python-pptx、Pillow、numpy、lxml | 读写 PPT、画插画 | 无法使用 |
| 必需 | 中文字体 | 计算字号、检查溢出 | 排版不准。Windows、macOS 自带，Linux 需要 fonts-noto-cjk |
| 推荐 | LibreOffice | 把 PPT 渲染成预览图，做视觉检查 | 美化版 PPT 照常生成，预览改用内置的近似画法（图表简化），没有前后对比图 |
| 推荐 | pdftoppm 或 PyMuPDF | PDF 转图片 | 同上。PyMuPDF 用 pip 就能装，Windows 上最省事 |
| 推荐 | scipy、requests | AI 插画去白底、调用生图接口 | 只影响 AI 插画，程序化插画不受影响 |
| 可选 | rembg | 写实风格 AI 插画抠图更干净 | 用内置的去白底方法 |
| 可选 | 生图模型配置 | AI 插画 | 自动改用程序化插画，配置方法见 `references/imagegen_config.md` |

`--install` 会自动安装缺少的部分。Python 包用 pip 装；LibreOffice 和字体属于系统组件，Linux 上有 sudo 权限时用 apt/dnf/pacman 装，macOS 用 Homebrew，Windows 用 winget 或 Chocolatey。
没有对应权限或工具时，脚本会打印一条建议命令，照着手动装即可。LibreOffice 安装包比较大，首次可能要几分钟。

## 检查结果

检查通过后，结果缓存在 `~/.config/luobo-ppt/setup.json`，之后 Agent 每次使用前只做秒级的快速确认。
随时可以手动重新检查。

```bash
python3 scripts/setup_check.py            # 只检查
python3 scripts/setup_check.py --install  # 检查并安装
python3 scripts/setup_check.py --selftest # 额外跑一遍小样
```

## 常见问题

- **Windows 双击 install.bat 一闪而过**：右键用 PowerShell 运行 `install.ps1`，看具体报错。脚本执行被系统策略拦截时，install.bat 已经带了临时放行参数。
- **提示 externally-managed-environment**：这是新版 Linux 发行版对系统 Python 的保护，脚本会自动加 `--break-system-packages` 重试。介意的话可以先建一个虚拟环境，用虚拟环境里的 python 运行 setup_check.py。
- **没有 sudo 权限装不了 LibreOffice**：可以先不装，预览会改用内置的近似画法，版式和溢出照样能检查。PDF 转图只需要 `pip install pymupdf`。
- **Agent 识别不到 skill**：确认目录结构是 `skills/luobo-ppt/SKILL.md`，多套一层文件夹是最常见的原因；然后重启 Agent。

## 卸载

```bash
bash install.sh --uninstall --agent all     # Windows：.\install.ps1 -Uninstall -Agent all
```

检查缓存和生图配置放在 `~/.config/luobo-ppt/`，不需要可以手动删除。
