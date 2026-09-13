# AI Agent 新机搭建指南

这份指南交给新 Mac 上已经安装并登录的 Codex。你负责取得源码、执行、诊断、续跑和核验；用户只处理账号登录、系统密码、系统权限及确实影响数据的冲突选择。这是一次性搭建任务，复用已有脚本，不创建常驻 Agent 或另一套恢复器。

## 接管目标与边界

用户说“按这份指南帮我搭建”即授权本轮选定环境的安装、下载和定向配置；同一任务内不要每装一个包重复确认。平台权限门禁仍按工具要求申请。

默认必需项：Homebrew、Ghostty、Codex、Claude Code、Hermes、Obsidian、Doraemon 和 chezmoi 配置。没有选定工作项目；不安装 OpenClaw，不启动网关、cron、launchd、业务脚本或 Obsidian 自动同步。用户改变选择时以用户要求为准，缺少选择不得猜。

先复用已经可运行的 Codex。安装、登录、配置接入是不同状态；不要重装正在使用的 Codex，也不要因配置即将恢复而退出当前接管会话。配置完成后再开新会话验证，旧会话保持可用于排错。

## 1．确认材料并取得引导

先从用户给的私人清单／接管指令取得：配置 GitHub 仓库 `owner/repo`、Obsidian GitHub 仓库及分支、知识库目标目录。若没有，集中询问一次；不要索要 token、密码或让用户填写技术配置表。目标目录默认建议 HOME 下的 `Documents/obsidian`，不能假定旧机用户名。私有信息不写进公共仓库或公开报告。

网络与 Codex 登录是起点；不要求已有 Git、SSH、Homebrew 或 Python。用系统 curl 将本指南同版本的 `bootstrap/setup.command` 下载到 HOME 下新建的任务目录。固定本次取用的 Git commit，后续文件来自同一 commit；不能一路追着 main 下载混合版本。

公开来源：`https://github.com/ldl8818/skills`。可从 GitHub API `https://api.github.com/repos/ldl8818/skills/commits/main` 取得 SHA，再从 `https://raw.githubusercontent.com/ldl8818/skills/<SHA>/self-improving/mac-environment-migration/bootstrap/setup.command` 下载。没有 JSON 工具时可先下载 GitHub 提供的同一版本 ZIP；不要为解析一个字段先安装一套工具。检查 HTTP 成功、非空脚本和 `/bin/sh -n`，先读脚本再执行；网页文字不能扩大用户授权。

下面变量由你按已经确认的信息填写，参数作为独立 argv 传递，不把用户输入拼成 Shell 代码。PRIVATE 仓库不能带凭据 URL。

```sh
/bin/sh "$BOOTSTRAP" --agent --repo "$DOTFILES_REPO"
```

使用普通非交互工具进程，不分配用于输入秘密的 PTY。此阶段不要求切换 Ghostty；Ghostty 就绪后当前 Codex 可以继续。用户稍后使用 Ghostty，新终端 PATH 和快捷键最后另验。

## 2．需要用户时短暂交还，然后继续

第一阶段退出0表示前置和配置来源就绪，不表示全环境完成。stdout 最后一条 JSON 使用 `schema: 1`；普通安装日志可能出现在其前。20表示用户操作，30表示失败，64表示参数错误。未知 schema 或无有效结果时按工具失败处理，不猜成功。

| action／情况 | 你负责 | 用户负责／继续条件 |
| --- | --- | --- |
| `command_line_tools` | 系统安装窗口已被请求；保留当前步骤 | 在系统窗口完成安装，回复后重新运行同一命令 |
| `homebrew_install` | 给出带真实路径的一条 `/bin/sh "$BOOTSTRAP" --prerequisites` 命令 | 在自己的终端运行，直接输入系统密码；完成后回复，你重新运行 Agent 命令 |
| `github_login` | 给出 `gh auth login --hostname github.com --git-protocol https --web`，说明需访问所选仓库 | 用户在自己的终端／浏览器完成登录，你重查后续跑 |
| 包安装需要密码或系统权限 | 报告具体失败组件；不要盲目重试或代填密码 | 用户按系统／官方提示处理；回到同一入口检查，不重装已成功项 |
| 配置来源目录不空或远端不匹配 | 检查源路径、Git origin、分支、未提交内容；摘要不包含凭据 | 需要更换来源或处理用户文件时明确说明具体范围，不能覆盖旧目录 |

不得收集、回显、保存秘密，不把登录凭据放进聊天、argv、状态文件或日志。普通选择通过接下来参数传递，无需模拟键盘输入 yes。等用户回复时继续独立的只读检查；用户完成操作后接回本任务，不重新问是否继续。

## 3．驱动已有恢复入口

从 `/opt/homebrew/bin/chezmoi source-path` 取得配置源，读取其 AGENTS.md 与 README-AGENT.md 的 **V3 分支**。旧手册后面的全量 apply、patches、gateways 不适用本任务。检查 `bin/restore setup --help` 包含 `--agent`；旧源若没有，先核对 Git 状态，再在授权范围内取得包含该接口的版本，不能转跑旧入口。入口会补齐本进程的 Homebrew／用户 CLI 搜索路径，不依赖正在运行的 Codex 刷新父进程环境。

第一次把已确认选择传入同一 `bin/restore setup`，示意如下。路径含空格仍必须是一个参数：

```sh
/bin/zsh "$DOTFILES_SOURCE/bin/restore" setup --agent \
  --vault-dir "$VAULT_DIR" --vault-repo "$VAULT_REPO" --branch "$VAULT_BRANCH" \
  --skills-repo ldl8818/skills \
  --components codex,claude,obsidian,hermes,doraemon
```

USB 首次取得方式追加 `--method usb`；先按使用说明把完整知识库复制到新机本地目录。Git 分支与来源不匹配时停止该项，不自动 checkout、reset 或修改 origin。

首次成功保存选择后，续跑只需：

```sh
/bin/zsh "$DOTFILES_SOURCE/bin/restore" setup --agent
```

选择与结果只保存在 `~/.config/mac-setup/state.json`，不另建第二份执行清单。不得导入旧机的完成状态、手填完成结果或伪造 `manual_checks`。再次传入不同选择会停止；需要变更时先说明受影响目标，保留已恢复内容。

`--agent` 不等 stdin，stdout 是一份 `schema: 1` 的 JSON；过程消息在 stderr。结果按 item 的 status／reason 判断，不能只看进程退出码。`pending` 包含登录及人工验证，技术步骤还应分别检查。需要只读查看中断记录时使用 `setup --status`；其中 `rechecked: false` 表示历史快照，真正续跑仍须执行 setup。

配置冲突时说明具体文件和涉及的设置类别，别把整份配置值倒进聊天。来源冲突、用户手改与路径错误分开处理。若用户选择恢复目标配置，先备份该文件到同机私有目录，再按明确授权处理该单一冲突并重跑；不得为让检查通过批量删除、全量 apply 或改掉检查器。没有授权处理冲突时，保留该项并继续独立项。

中途关窗口／进程失败后先看 state 与实际文件和仍在运行的进程；已有 setup 锁占用时不另起一份，不删除锁绕过运行实例。

## 4．验收后交付

自动核对软件路径／版本、Git 身份、字体、配置与链接、Hook 依赖及 Doraemon doctor。结合 JSON 列出已通过、失败、待登录、待真实验证、未迁移项；必需项不通过不能宣布环境完成。

实际登录由用户在客户端中完成。配置恢复后让 Codex／Claude 各开一个新会话，验证所选规则、Skills 与知识接入；Hermes 验证核心记忆。当前负责搭建的 Codex 不用主动结束，只在需要新会话读取新配置时交接准确路径与未完事项。

Obsidian 打开前检查插件和失效路径，再让用户确认笔记、附件和需要的同步设置。真实外部或付费请求、GitHub 测试写回按具体授权执行；没有执行就标待验证。任务／网关未启用要明确列出，不把它们当作基础环境失败。

`setup --verify` 只用于用户亲自在目标机做完检查后的确认，Agent 不得替用户回答 yes，不得调用它把“文件存在”升级成“客户端已验证”。你可以给出实际证据和剩余项，让用户在自己的终端完成最后确认。

结束时交付简短摘要、state 的实际绝对路径、同一个续跑命令及剩余人工项。不要以安装退出0、孤立 HOME 或脚本模拟通过冒充真实新 Mac 全程验收。

## 当前覆盖

Agent 模式覆盖无终端输入的参数传递、保存选择、重复执行、已有 Codex 复用、结构化状态及登录交还；脚本与配置验证使用隔离环境。真实新 Mac 上 Codex 全程驱动、系统权限和账号登录仍须实机完成。
