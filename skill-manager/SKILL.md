---
name: skill-manager
description: >
  Skill 生命周期管理器。列出、检查更新、更新、启用/禁用、定版本号、自检、删除已安装的 skill。
  覆盖 Claude Code、OpenAI Codex、Grok、Gemini CLI、Google Antigravity 的
  共享全局、客户端全局、项目级 Skill 目录、Claude 插件生命周期和 Codex 插件状态盘点，
  同时只读盘点 Codex 内置 Skill；按真实路径去重，并区分「已安装、已启用、本会话已生效」。
  触发词：列出技能、列出所有技能、我有哪些技能、查看 skill、skill 列表、
  检查更新、有没有新版本、更新 skill、启用 skill、禁用 skill、删除 skill、
  skill 体检、skill 自检、升版本号、这个 skill 哪来的、溯源、
  list skills、check updates、enable/disable skill、skill doctor、bump version、trace source。
license: MIT
metadata:
  version: "2.5.1"
  zh_description: 管理 skill 全生命周期：列出、溯源、查更新、启停、定版本、自检
  update_policy: frozen
---

# Skill 生命周期管理器

所有操作通过 `scripts/` 下的脚本执行——脚本是唯一的数据收集与判定层，
不要绕开脚本手工拼装状态。**脚本输出原文展示给用户，不要总结、改写或转成自己的格式。**

## 核心原则：宁可说不知道，也不编一个

1. **缺失的信息就报缺失，绝不用默认值填充。**
   编出来的版本号和真的一模一样，人会信它、基于它做决定；
   诚实的「来源未登记」只是让人多跑一条命令。
2. **「没登记」不等于「没有」，而是「还没去找」。**
   权威记录往往已经存在（安装器 lock、上游仓库），顺序永远是：
   查记录 → 联网搜 → 内容比对 → 确认了才写。找不到才承认 unknown。
3. **版本号靠内容比对确认，不靠推断。**
   「上游最新版」不等于「本地这份」——本地可能装于任何历史时点，倒推必错。

推论：只报告真实状态（「硬盘上有」≠「正在生效」，「本地版本」≠「上游最新」）；
遇到歧义（同名项目、同名插件）一律列出候选让用户挑，绝不猜。

## 命令

| 用户意图 | 命令 | 脚本 |
|---------|------|------|
| 列出技能 | `list`（全局 + 当前项目）；`list <项目>`；`list --all [-n N]` 全景，展开最近活跃前 3 个、其余折叠 | `list_skills.py` |
| 检查更新 | `check`（本地版本 vs 上游最新） | `scan_and_check.py` |
| 溯源 | `trace <名字> [--repo <URL>] [--write]`；`trace --all --write` 批量 | `trace_source.py` |
| 更新 | `update <名字> [--project <路径>]`；直装或 Claude 插件；无参 = 批量；`--dry-run` 只列不做 | `update_skill.py` |
| 启用 / 禁用 | `enable\|disable <名字> [--project <路径>]`；直装或 Claude 插件 | `toggle_skill.py` |
| 升版本号 | `bump <名字> [patch\|minor\|major] [--project <路径>]` | `bump_skill.py` |
| 体检 | `doctor [--fix]`（`--fix` 只做有依据的补录，绝不发明数据） | `doctor.py` |
| 删除 | `delete <名字> [--project <路径>] [--dry-run]`；直装或 Claude 插件 | `delete_skill.py` |

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
| 全局直装（客户端） | `~/.claude/skills/`、`~/.gemini/skills/`、`~/.grok/skills/`、`~/.gemini/config/skills/`、`~/.gemini/antigravity/skills/`、`~/.gemini/antigravity-cli/skills/`、`~/.codex/skills/` | 各客户端的用户级入口 |
| 项目级 | `<项目>/.agents/skills/`、`.claude/skills/`、`.codex/skills/`、`.gemini/skills/`、`.grok/skills/`、`.agent/skills/` | 通用入口、客户端专用入口与 Antigravity 旧别名 |
| Codex 内置 | `~/.codex/skills/.system/<名>/` | Codex 管理的内置能力；只读盘点，不当作用户安装或插件 |
| Claude 插件 | `~/.claude/plugins/installed_plugins.json`、缓存、全局／项目 `enabledPlugins` | 插件位置、版本及全局／项目启用状态 |
| Codex 插件 | `~/.codex/config.toml`、`~/.codex/plugins/cache/` | 插件开关、缓存 manifest 与版本 |
| 辅助状态 | `~/.agents/.skill-lock.json`、`~/.claude/commands/` | 安装来源记录与斜杠命令；不算独立安装来源 |

Claude 插件可以「全局关、单项目开」，`list` 显示为「项目:<项目名>」。
Codex 插件由 `list` 和 `doctor` 只读盘点；其启停、更新、删除仍使用 Codex 自身机制，避免把 Claude 的 JSON 写入逻辑误用于 Codex TOML 配置。
各客户端对目录的官方承诺并不相同；遇到「某 Agent 是否真会加载这个目录」，
读 `references/client-paths.md`，不要根据目录名猜。

## 溯源（trace）

来源不明的 skill，不要标成「本地」了事，去把它查出来。三级递进：

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
| unknown | 以上都不是 | `来源未登记` → 去 `trace`，别猜 |

- 来源列直接写仓库名（如 `tw93/Waza`），不写「GitHub」。
- GitHub 来源**不套 semver**（身份是上游 commit）；要脱离上游自己管，先标 `frozen`。
- unknown 不是兜底分类，是待办：`doctor` 报出它，`trace` 消灭它。
- **版本号末尾 `*` = 内容改过、版本号没跟上**（`fingerprints.json` 自动监督，别手改），
  `bump` 平账；会自我改写的 skill 标 `self_mutating: true` 豁免。

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
  keep_local_description: true
```

`keep_local_description` 存在的原因：`description` 是决定 Claude 选不选这个 skill 的
那句话，被上游静默盖掉只会在下次选错 skill 时才显形。必须显式声明，不做自动推断。

中文描述查找顺序：`zh_description` > `descriptions_zh.json` > 原始 description。
`doctor` 只揪**生效中**却还是英文描述的 skill（未启用的不占上下文，不强求）。

## 项目视图

判定生效范围拿全量项目算，展示按当前视野筛，视野外折叠成一行摘要。
「最近活跃」按 Claude Code 会话记录排；git worktree 归并到主仓统计，不重复计数。

## 安全设计

- **删除是移走**：移进 `~/.skill-manager/archive/deleted/<名>.<时间戳>/`，后悔可搬回；
  连带登记（指纹、中文描述、插件缓存/登记/开关）由脚本对称清理。
- **更新前整目录备份**到 `~/.skill-manager/archive/update-backups/`；在 staging 中完成
  合并与验证后原子替换，本地独有文件与本地定制字段保留；失败不改在线目录。
- **插件更新结构验证通过才写登记表**；失败保留旧版继续可用。

## 其他约定

- 安装 GitHub skill 仓库前，先看 `skills/` 下的 SKILL.md 是否已定义 slash command，
  有则跳过 `commands/` 目录（否则命令重复显示）。

## 维护本 skill

改 `scripts/` 代码、排查自身 bug、或想知道某条设计为何如此 →
**先读 `references/maintenance.md`**（数据层契约、实现细节、事故来历）。
本文件只写「怎么用」。
