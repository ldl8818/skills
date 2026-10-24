# skill-manager

> Cross-agent Skill lifecycle manager. CLI output is in Chinese.

Grok、Claude Code、Gemini CLI、Google Antigravity、OpenAI Codex 和 WorkBuddy 的 Skill 生命周期管理器：**列出、溯源、查更新、启停、定版本、自检、删除**。

一台机器上的 Skill 通常分为三大类：**全局直装、项目级、插件**。其中全局直装再按共享范围细分：

- **全局直装**：共享全局 `~/.agents/skills/`；客户端全局 `~/.claude/skills/`、`~/.codex/skills/`、`~/.gemini/skills/`、`~/.grok/skills/`、`~/.gemini/config/skills/`、`~/.gemini/antigravity/skills/`、`~/.gemini/antigravity-cli/skills/`、`~/.workbuddy-ai/skills/`。
- **项目级**：`<项目>/.agents/skills/`、`.claude/skills/`、`.codex/skills/`、`.gemini/skills/`、`.grok/skills/`、`.codebuddy/skills/`，以及 Antigravity 向后兼容的 `.agent/skills/`。
- **插件**：Claude 插件纳入生命周期管理；Codex 插件只做状态盘点。

此外，Codex 还会在 `~/.codex/skills/.system/` 提供客户端内置 Skill。它们不是用户安装，也不是插件，本工具单列为「Codex 内置」并只读盘点。

安装来源、启用开关和版本信息还散落在多个配置位置里。于是「硬盘上有」不等于「正在生效」，「本地版本」也不等于「上游最新」。

同一个 Skill 可能通过多个软链接入口暴露给不同客户端。工具按真实路径去重，只显示一次；这是内部识别机制，不改变上面的用户分类。完整的客户端目录矩阵、官方来源和兼容边界见 [`references/client-paths.md`](references/client-paths.md)。

这个 Skill 把这些位置与配置归集起来，并坚持一条原则：**宁可说不知道，也不编一个**。
查不到来源就如实报「未登记」，绝不用默认值（比如凭空捏一个 `version: 1.0.0`）填充。

## 安装

Codex 或希望多个兼容客户端共用时，推荐装到共享全局目录：

```bash
git clone https://github.com/ldl8818/skills.git
mkdir -p ~/.agents/skills
if test -e ~/.agents/skills/skill-manager || test -L ~/.agents/skills/skill-manager; then
  printf '%s\n' 'Target exists; follow the update workflow.' >&2
  false
else
  rsync -a \
    --exclude '.DS_Store' --exclude '__pycache__' --exclude '*.pyc' \
    --exclude 'fingerprints.json' --exclude 'projects.json' \
    --exclude 'evolution.json' --exclude 'descriptions_zh.json' \
    skills/skill-manager/ ~/.agents/skills/skill-manager/
fi
```

Claude Code 单独使用时，可把上面的目标目录换成 `~/.claude/skills/skill-manager/`；需要共享同一份实体时，也可只给 Claude 建单 Skill 软链接：

```bash
mkdir -p ~/.claude/skills
ln -s ~/.agents/skills/skill-manager ~/.claude/skills/skill-manager
```

以上步骤用于首次安装；已有目录、正确或错误目标的软链及断链均转入更新或恢复核对，不直接覆盖。手工复制同样先确认目标尚未安装。命令里排除的几个 json 是老版本可能残留在 Skill 目录里的本机数据；2.4.0 起运行数据统一住 `~/.skill-manager/data/`，源码与本地定制按下文更新流程维护。

装好后新开或重启客户端会话才会加载。之后说「列出我的技能」「检查更新」即可触发；Claude Code 也可以直接用斜杠命令。

**要求**：`python3` ≥ 3.9（macOS / Linux 自带）和 `git`（检查更新、溯源、更新时用到）。**零第三方依赖**，全部标准库，不需要 pip install。

## 命令

```bash
/skill-manager list                      # 全局 + 当前目录的项目级 skill
/skill-manager list <项目名|路径>         # 指定项目：项目 skill 与全局 skill 分块列
/skill-manager list --all                # 全景：按最近活跃展开前 3 个项目，其余折叠
/skill-manager list --all -n 10          # 多展开几个（-n 0 = 全部展开）
/skill-manager check                     # 本地版本 vs 上游最新
/skill-manager trace <名字> [--repo <URL>] [--path <子目录>] [--write]  # 溯源：查出处、内容比对定版
/skill-manager trace --all --write       # 批量溯源所有来源不明的
/skill-manager update [名字] [--project <路径>] # 更新直装 Skill 或 Claude 插件；无名字 = 批量
/skill-manager update --dry-run          # 只列出将要更新的，不动手
/skill-manager update <名字> --ref main    # 改跟上游主分支的未发版提交（通道有粘性）
/skill-manager update <名字> --ref release # 退回最新发布 tag
/skill-manager enable  <名字>            # 启用直装 Skill 或 Claude 插件
/skill-manager disable <名字>            # 禁用直装 Skill 或 Claude 插件
/skill-manager bump <名字> [patch|minor|major] [--project <路径>] # 递增版本号
/skill-manager doctor [--fix]            # 自检 10 项；--fix 只做有依据的补录
/skill-manager delete <名字> [--project <路径>] [--dry-run] # 归档删除直装 Skill 或 Claude 插件
```

任何脚本加 `--help` 都能看完整用法说明。
Codex 插件由 `list` 和 `doctor` 只读盘点；启停、更新和删除仍使用 Codex 自身机制。

几个设计要点：

- **默认按问题汇总**，保留名称、来源、版本和状态等可核对字段；用户要求原文时才原样展示。来源未登记只报告，不自动启动联网溯源；`trace` 按用户要求或当前操作需要，对明确范围执行。
- **上游字段先完整保留，再增补**。三个路由字段逐项核对原文与本地增补，中文展示与源描述分开；schema 2回执会拒绝字段删改，适配理由不能豁免。具体规则与客户端差异见 [SKILL.md 的路由字段](SKILL.md#路由字段)。
- **删除是移走，不是抹掉**。一律移进 `~/.skill-manager/archive/deleted/`，后悔了搬回去就行。
- **溯源靠内容比对，不靠推断**。下载上游各个 tag 逐一比对指纹，完全一致才认定版本；
  绝不用「上游最新版」倒推本地版本（那必错）。
- **Claude 插件名不用记市场名**。`codex` 会自动补全成 `codex@openai-codex`；撞名则列候选让你挑，不猜。

## 更新与本地定制

Skill、已接入的 CLI 和应用更新统一从本管理器进入。`update ego-lite`／`ego-browser`／`opencli`／`agent-reach` 委派实际 lookup 维护器，`update lark-cli` 结合本机飞书按需入口调用官方更新。随包指南跟随程序版本，原生更新后仍需核对本地定制和发现布局。尚未接入的工具先核对保护与验收方式；详细分工见[更新对象与执行入口](references/升级与定制合并.md#更新对象与执行入口)。

“更新 lookup”默认更新本体与已安装的上游；`/skill-manager update lookup` 调用同一流程，追加 `--self-only` 或 `--upstream-only` 可限定范围。扫描和批量更新同样包含本地来源的 lookup；缺少维护接口的旧版会明确报告，不冒充无需更新。完整命令、来源与接续见 [lookup 更新说明](../lookup/references/上游更新.md#命令与范围)。

更新时比较完整旧上游、本地与新上游。新版已满足定制用途和失败边界时，采用新版原生实现并退出重复覆盖；尚未满足时，把必要定制合入新上游，验证定制和新增能力。来源不明、冲突或并发变更时保留内容和依据，在授权范围内继续核对，不能凭安装成功宣布完成。

判断、提醒与托管边界、候选上下文、原生状态和恢复要求统一见[升级与定制合并](references/升级与定制合并.md)。现有脚本提供机械合并与完整性检查，语义判断由维护 Agent 完成；使用时后台提醒和托管执行以各执行器实际接入为准。具体命令仍以上表和脚本帮助为准。

## 本机数据文件（仓库里没有，首次运行自动生成）

新机恢复使用 `scripts/install_frozen.py --repo <Skills仓库> --home <目标HOME>` 建立5个冻结 Skill 的单跳入口。默认兼容 Claude／Codex；仅需要 Codex 时追加 `--clients codex`，只创建共用 Agent 和 Codex 入口，不创建 `.claude`。已有冲突先停止，不覆盖目录。

这些 json 记录的是「**这台机器的状态**」，换台机器毫无意义，且含本机绝对路径，
所以既不入仓库、也不放在任何客户端目录里，统一存放在 **`~/.skill-manager/data/`**
（2.4.0 起；旧的 `~/.claude/data/skill-manager/` 和 Skill 目录残留会在首次读写账本时自动搬过去）：

| 文件 | 内容 | 维护方式 |
|------|------|---------|
| `fingerprints.json` | 每个 skill 的整目录内容哈希，用来发现「内容改了、版本号没跟上」 | 自动 |
| `projects.json` | 跑过本 skill 的项目注册表 | 自动 |
| `descriptions_zh.json` | **插件** skill 的中文描述外挂表 | 手工 |

自动维护的文件会在首次需要写入时生成；手工维护的 `descriptions_zh.json` 缺失时按空表读取。
JSON 一旦存在但损坏或不可读，命令会硬失败并指名坏的是哪个文件，避免用空表覆盖真实配置。

为什么插件的中文描述要走外挂表：直装 skill 的中文描述写进各自 `SKILL.md` 的
`zh_description` 字段（跟着 skill 走，搬家、拷给别人都不丢）；**插件的 SKILL.md
会被上游更新整个覆盖**，写进去下次更新就没了。这张表是手工维护的，换机器时值得单独备份。

（skill 代码目录里还可能出现 `evolution.json`——那是另一个 skill（skill-evolution-manager）的
数据文件，本 skill 不读写它，只负责不把它算进指纹。）

## 验证

```bash
cd skill-manager
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
python3 -m compileall -q scripts
```

## 设计文档

`SKILL.md` 是给 Agent 读的行为定义，只写「怎么用」；每条规则背后的事故与权衡在
`references/maintenance.md`（数据层契约、实现细节、事故簿）。客户端目录单源在
`references/client-paths.md`。想改这个 skill，先读对应文档。

## License

MIT

## 定制冻结版

`python3 scripts/scan_and_check.py --include-frozen` 只读比较冻结版的登记来源与上游发布点；状态始终保持 frozen，不进入自动更新列表。比较结果表示 commit 相同或不同，不表示本地改造版落后。查询失败明确显示证据不足。

普通直装更新采用旧上游、本地、新上游三方合并，完整核对源文件后写入 `upstream-merge.json`；同名本地改造按前述语义判断处理。冲突或基线不明时保留在线目录，插件存在本地差异时同样转隔离合并。

定制冻结版必须完成完整源快照合并与验收；冻结只禁止自动覆盖，不能替代用户授权的合并任务。`python3 scripts/audit_upstream.py --repo <仓库> --upstream <上游Git仓库>` 核对固定源快照，省略 `--upstream` 仅核对离线回执，不能证明最新版或语义完整。本仓库的五项定制版采用独立本地版本，另有保留完整上游原版的 think；六项来源核验与各自安装流程见 [冻结版本维护](references/冻结版本维护.md)。
