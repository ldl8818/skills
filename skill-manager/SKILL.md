---
name: skill-manager
description: "管理已安装 Skills：盘点、溯源、更新、启停、删除、定版与自检；统一发起已接入工具更新。内容编写走 skill-creator。"
when_to_use: "列出已安装 Skill、查 Skill 来源、检查 Skill 更新、合并上游 Skill、启用或禁用 Skill、删除 Skill、冻结版本、Skill 安装状态自检、update skills、更新 ego-lite、更新 ego-browser、更新 lark-cli、更新 OpenCLI、更新 Agent Reach"
dispatch_intent: "已安装 Skills 的盘点、溯源、完整上游合并更新、启停、删除、定版与自检；已接入工具更新按所属维护器委派，验收定制、配置及发现入口；Skill 内容编写交给 skill-creator。"
license: MIT
metadata:
  version: "2.11.0"
  zh_description: 管理 skill 全生命周期：列出、溯源、查更新、启停、定版本、自检
  update_policy: frozen
---

# Skill 生命周期管理器

使用 `scripts/` 作为状态收集与判定层，不手工编造状态。默认按用户问题汇总结果，保留名称、来源、版本、启用状态和错误等必要核对字段；用户明确要求原文时完整展示原始输出，不改写关键值。

## 核心原则：宁可说不知道，也不编一个

1. **缺失的信息就报缺失，绝不用默认值填充。**
   编出来的版本号和真的一模一样，人会信它、基于它做决定；
   诚实的「来源未登记」只是让人多跑一条命令。
2. **「没登记」不等于「没有」。**
   先查已有权威记录；普通列表和体检可以如实报告 unknown，不自动联网溯源。
   用户要求溯源，或当前操作确实需要确定来源时，再搜索候选、比对内容；写登记仍须在授权范围内。
3. **版本号靠内容比对确认，不靠推断。**
   「上游最新版」不等于「本地这份」——本地可能装于任何历史时点，倒推必错。

推论：只报告真实状态（「硬盘上有」≠「正在生效」，「本地版本」≠「上游最新」）；
遇到歧义（同名项目、同名插件）一律列出候选让用户挑，绝不猜。

## 更新的完成条件

用户要求更新时，取得选定通道的完整源快照，以旧上游基线、本地现状和新上游做三方合并。逐项判断新版是否已支持本地定制：已支持时采用新上游实现，尚未支持时保留必要定制，并验证原用途、失败边界和新版新增能力。有效路由与约束仍须满足；逐项处理新增、修改、删除及冲突，不得只挑选少量条款后宣布更新完成。

普通直装更新的脚本负责机械合并、完整性检查和写入 `upstream-merge.json`；语义判断由维护 Agent 完成。有执行或业务定制时先在隔离目录完成判断与相称验证，再应用结果，不能以文本无冲突或脚本成功代替判断。无法确定旧基线或存在未解决冲突时保持在线目录原状。插件先核对安装内容与旧基线；存在本地差异时转入隔离合并，不直接替换。

命令、自然语言及已授权托管遵循同一要求，具体流程、当前脚本能力和提醒／接续机制的接入要求见[升级与定制合并](references/升级与定制合并.md)。脚本返回待判断或拒绝覆盖时，Agent 在已有授权内继续处理；`frozen` 只禁止自动覆盖，不表示用户明确要求的合并任务已经完成。冻结集合的来源、许可及登记按[冻结版本维护](references/冻结版本维护.md)，无须重复请求已授权的更新。

交付前必须核对完整源文件清单、Markdown 章节保留／明确改名映射、每项本地适配的原因、源文件与合并结果哈希、本地特有文件，以及相关行为验证。`audit_upstream.py --repo <仓库> --upstream <源仓库>` 验证固定源快照；省略 `--upstream` 只能证明当前文件与登记回执一致，不能证明上游最新或语义正确。哈希或版本相同、下载成功、结构／链接／测试通过均不能单独证明合并完整。

上游路由字段按下文「路由字段」逐项验收。必须查看原始字段与本地结果的完整差异，分别列出原文保留情况和本地增补；不得将“保留适用表达”“本地定制”或已登记的适配理由作为删减、翻译、改写原字段的依据。schema 2回执绑定源字段原文，旧回执须使用已核实的固定源快照重新登记，不直接改 schema 或签入当前哈希冒充验收。

## 命令

更新统一从本管理器进入，再按[更新对象与执行入口](references/升级与定制合并.md#更新对象与执行入口)委派实际维护器。随程序分发的指南跟随所属程序维护，不作为独立 Skill 另行覆盖；原生更新后仍须核对定制、发现入口与实际运行版本。未接入的工具先明确保护与验收方式，不直接绕过管理器调用安装器。

lookup 的更新由其实际安装目录内的维护器执行。“更新／升级 lookup”或 `update lookup` 默认包含本体与已安装上游；`update lookup --self-only` 只更新本体，`--upstream-only` 只维护上游。检查和批量更新同样识别本地来源的 lookup，不因没有 `github_url` 而跳过。缺少维护接口的旧安装先按完整来源与定制流程迁移；定制待判断时由当前 Agent 连续合并、验证并接续，不能把委派或退出码当作完成。命令与结果协议见 [lookup 更新入口](../lookup/references/上游更新.md#命令与范围)。

| 用户意图 | 命令 | 脚本 |
|---------|------|------|
| 列出技能 | `list`（全局 + 当前项目）；`list <项目>`；`list --all [-n N]` 全景，展开最近活跃前 3 个、其余折叠 | `list_skills.py` |
| 检查更新 | `check [--include-frozen]`（冻结项只读比较，不解冻） | `scan_and_check.py` |
| 溯源 | `trace <名字> [--repo <URL>] [--write]`；`trace --all --write` 批量 | `trace_source.py` |
| 更新 | `update <名字> [--project <路径>] [--ref main\|release]`；lookup 另支持 `--self-only`／`--upstream-only`，不通过 `--ref` 切换通道；无参 = 批量；`--dry-run` 只列不做 | `update_skill.py` |
| 更新已接入工具 | `update ego-lite`／`ego-browser`／`opencli`／`agent-reach` 委派 lookup 指定依赖；`update lark-cli` 使用本机飞书按需入口保护 | `update_skill.py`、`lifecycle.py`、`native_tools.py` |
| 启用 / 禁用 | `enable\|disable <名字> [--project <路径>]`；直装或 Claude 插件 | `toggle_skill.py` |
| 升版本号 | `bump <名字> [patch\|minor\|major] [--project <路径>]` | `bump_skill.py` |
| 体检 | `doctor [--fix]`（`--fix` 只做有依据的补录，绝不发明数据） | `doctor.py` |
| 删除 | `delete <名字> [--project <路径>] [--dry-run]`；直装或 Claude 插件 | `delete_skill.py` |

### 跟随通道：release 与 main

默认跟上游最新发布 tag。上游把改进压在未发版提交里时，用 `update <名字> --ref main`
改跟主分支；通道有粘性，之后无参 `update` 继续跟 main，`--ref release` 是退回发布版的唯一方式。
跟 main 的 skill 版本号标成 `3.32.0+main`，明确自己领先发布版。

`check` 对两种通道分别比对：跟 release 的比 tag，跟 main 的比 HEAD，都不会出现「更新完还报有新版」。
跟 release 的 skill 若上游 main 另有未发版提交，单独列在 🌿 段落，**不计入待更新**——
上游未发版是常态，让它天天亮黄灯只会让人学会无视整列灯。

禁用状态的 skill（入口是 `SKILL.md.disabled`）同样可以更新，更新后保持禁用。

Claude 插件写裸名即可，脚本会自动补全 `@市场名`。全部脚本零第三方依赖，
`python3`（≥ 3.9）直接跑；check / trace / update 需要本机装有 `git`。
所有脚本支持 `--help` 查看完整用法。

## 状态模型

先按用户能理解的作用域与安装方式分类，再从配置判断是否启用。软链接不是另一份安装，
指向同一真实路径的条目会合并显示，避免重复计数。

列表中的「生效」表示配置与文件状态允许客户端加载；已经打开的旧会话是否完成加载，
仍以客户端当前会话的 Skill 清单为准，必要时重启会话后确认。

| 分类 | 位置 | 含义 |
|---|---|---|
| 全局直装（共享） | `~/.agents/skills/<名>/` | Agent Skills 通用位置；Codex 官方全局作用域，多客户端也可共同采用 |
| 全局直装（客户端） | `~/.claude/skills/`、`~/.gemini/skills/`、`~/.grok/skills/`、`~/.gemini/config/skills/`、`~/.gemini/antigravity/skills/`、`~/.gemini/antigravity-cli/skills/`、`~/.codex/skills/`、`~/.workbuddy-ai/skills/` | 各客户端的用户级入口 |
| 项目级 | `<项目>/.agents/skills/`、`.claude/skills/`、`.codex/skills/`、`.gemini/skills/`、`.grok/skills/`、`.codebuddy/skills/`、`.agent/skills/` | 通用入口、客户端专用入口与 Antigravity 旧别名 |
| Codex 内置 | `~/.codex/skills/.system/<名>/` | Codex 管理的内置能力；只读盘点，不当作用户安装或插件 |
| Claude 插件 | `~/.claude/plugins/installed_plugins.json`、缓存、全局／项目 `enabledPlugins` | 插件位置、版本及全局／项目启用状态 |
| Codex 插件 | `~/.codex/config.toml`、`~/.codex/plugins/cache/` | 插件开关、缓存 manifest 与版本 |
| 辅助状态 | `~/.agents/.skill-lock.json`、`~/.claude/commands/` | 安装来源记录与斜杠命令；不算独立安装来源 |

Claude 插件可以「全局关、单项目开」，`list` 显示为「项目:<项目名>」。
Codex 插件由 `list` 和 `doctor` 只读盘点；其启停、更新、删除仍使用 Codex 自身机制，避免把 Claude 的 JSON 写入逻辑误用于 Codex TOML 配置。
各客户端对目录的官方承诺并不相同；遇到「某 Agent 是否真会加载这个目录」，
读 `references/client-paths.md`，不要根据目录名猜。

## 溯源（trace）

来源不明时报告「来源未登记」，不猜成本地。仅在用户要求溯源或当前操作确需来源时，对指定对象递进检查；批量溯源须有批量任务范围：

1. **安装器记录** `~/.agents/.skill-lock.json` —— 最权威，先查这里。
2. **GitHub 搜索** —— lock 里没有就联网搜候选仓库，列给用户挑。
3. **内容比对定版** —— 下载仓库各个 tag（无 tag 比 HEAD）逐一比对，
   **完全一致才认定版本**。

## 版本语义

版本号回答「我这份是哪一版」，内容指纹回答「我改过它没有」。

| 来源 | 判定依据 | 版本列显示 |
|------|---------|-----------|
| github | 有 `github_url`（或 lock 有记录） | 上游版本号；上游没给就「日期 · 短哈希」 |
| local | **显式声明** `source: local` | 人工 semver |
| frozen | `update_policy: frozen` | 人工 semver + 🔒 |
| plugin | 在 `installed_plugins.json` 里 | 上游 plugin.json 的版本 |
| unknown | 以上都不是 | `来源未登记`；按任务需要执行 `trace`，别猜 |

- 来源列直接写仓库名（如 `tw93/Waza`），不写「GitHub」。
- GitHub 来源**不套 semver**（身份是上游 commit）；要脱离上游自己管，先标 `frozen`。
- unknown 表示证据不足：`doctor` 报出它，是否执行 `trace` 由本次任务范围决定，不因列表出现 unknown 自动扩大工作。
- **版本号末尾 `*` = 内容改过、版本号没跟上**（`fingerprints.json` 自动监督，别手改），
  `bump` 平账；会自我改写的 skill 标 `self_mutating: true` 豁免。

## 路由字段

在 `SKILL.md` 的 frontmatter 顶层维护以下字段：

- `description`：有 GitHub 上游时完整同步选定通道的上游原文，不另写本地摘要；中文说明存入 `metadata.zh_description`。无上游时自行维护，须独立表达适用范围。
- `when_to_use`：上游存在时先完整复制原字段，保留词句、顺序和标点，不翻译、改写或加前置限定。本地触发词可作为独立条目插入合适位置，不限于末尾；不得以新增词替换原词，也不得重写原词后声称原意相同。
- `dispatch_intent`：上游存在时完整保留原字段；确需增补时按独立意图条目插入，不翻译、概括、重排或改写原文。该字段不代表执行授权。

上游缺少某字段时可自行编写，但须明确标为本地内容，不能伪称来自原作者。中文说明只放 `metadata.zh_description`，不覆盖上述源字段。不得先筛选“适用”部分再合入；本地执行与授权约束保留在对应规则和正文中，不通过给源字段加限定来表达。

`audit_upstream.py` 对 `description` 做原始 YAML 字段块比对，对另外两个字段检查源字符与原条目有序保留，只允许独立条目增补；文件、字段缺项或原文改写时，登记与验收均失败，适配理由不能豁免。普通更新在候选写入前执行同一检查；字段冲突时在隔离目录按完整新上游和本地新增条目重新合并，不关闭检查。通过机械检查后仍须审阅增补是否为真实触发词、是否给原文附加限定；检查不证明真实客户端触发效果。

Claude Code 支持将 `when_to_use` 追加到 `description` 供模型选择 Skill；Codex 官方文档未声明读取该扩展字段。`dispatch_intent` 是 Waza 调度生成器使用的自定义字段，本仓库保留意图信息，不承诺宿主会读取它。两者不属于通用 Agent Skills 标准字段，需要向仅接受标准字段的入口分发时单独适配，不修改唯一源码。

依据：[Claude Code 字段说明](https://code.claude.com/docs/en/skills#frontmatter-reference)、[OpenAI Skills 文档](https://learn.chatgpt.com/docs/build-skills)、[Agent Skills 标准](https://agentskills.io/specification)。

## 元数据字段

写在各 skill 自己的 SKILL.md frontmatter 的 `metadata` 中；旧版顶层字段仍可读取，
后续写入会迁移到规范位置：

```yaml
metadata:
  version: 3.31.1               # GitHub 来源用上游版本号；本地/冻结用人工 semver
  zh_description: 一句话中文用途  # 直装写这里，插件走 descriptions_zh.json
  source: local                 # 显式声明「自己写的」
  github_url: https://github.com/example/skills
  github_hash: 0123456789abcdef0123456789abcdef01234567
  github_date: 07-05
  github_path: skills/example
  update_policy: frozen
  self_mutating: true
```

旧 `keep_local_description` 不再用于覆盖上游描述，不能绕过字段原文检查。`description` 跟随上游，中文说明通过 `zh_description` 独立维护。

中文描述查找顺序：`zh_description` > `descriptions_zh.json` > 原始 description。
`doctor` 只揪**生效中**却还是英文描述的 skill（未启用的不占上下文，不强求）。

冻结版的维护流程见 [references/冻结版本维护.md](references/冻结版本维护.md)。上游更新在隔离目录评估，保持 `update_policy: frozen`，不通过解除冻结来合并。

## 项目视图

判定生效范围拿全量项目算，展示按当前视野筛，视野外折叠成一行摘要。
「最近活跃」按 Claude Code 会话记录排；git worktree 归并到主仓统计，不重复计数。

## 安全设计

- **删除是移走**：移进 `~/.skill-manager/archive/deleted/<名>.<时间戳>/`，后悔可搬回；
  连带登记（指纹、中文描述、插件缓存/登记/开关）与**各 Agent 入口软链**由脚本对称清理，
  不留断链；归档失败时目录与软链一并复原。
- **更新前整目录备份**到 `~/.skill-manager/archive/update-backups/`；在 staging 中完成
  三方合并与完整性验证后原子替换，本地独有文件、本地同名文件改造与定制字段保留；冲突或验证失败不改在线目录。
- **插件更新结构验证通过才写登记表**；失败保留旧版继续可用。

## 其他约定

- 安装 GitHub skill 仓库前，先看 `skills/` 下的 SKILL.md 是否已定义 slash command，
  有则跳过 `commands/` 目录（否则命令重复显示）。

## 维护本 skill

改 `scripts/` 代码、排查自身 bug、或想知道某条设计为何如此 →
**先读 `references/maintenance.md`**（数据层契约、实现细节、事故来历）。
本文件只写「怎么用」。
