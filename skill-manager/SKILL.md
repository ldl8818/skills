---
name: skill-manager
description: >
  Skill 生命周期管理器。列出、检查更新、更新、启用/禁用、定版本号、自检、删除已安装的 skill。
  覆盖全局直装（~/.claude/skills/）、项目级（<项目>/.claude/skills/）、
  插件（~/.claude/plugins/）三种来源，并区分「装了」和「真正生效」。
  触发词：列出技能、列出所有技能、我有哪些技能、查看 skill、skill 列表、
  检查更新、有没有新版本、更新 skill、启用 skill、禁用 skill、删除 skill、
  skill 体检、skill 自检、升版本号、这个 skill 哪来的、溯源、
  list skills、check updates、enable/disable skill、skill doctor、bump version、trace source。
zh_description: 管理 skill 全生命周期：列出、溯源、查更新、启停、定版本、自检
license: MIT
update_policy: frozen
version: 1.7.0
---

# Skill 生命周期管理器

管理所有 skill 的完整生命周期。

## 第一性原理：宁可说不知道，也不编一个

三条铁律，按重要性排序。违反任何一条造成的伤害，都大于它本想解决的麻烦。

**一、缺失的信息就报缺失，绝不用默认值填充。**
一个编出来的 `1.0.0` 看起来和真的一模一样，人会信它、依赖它、基于它做决定。
而一个诚实的「来源未登记」只是让人多跑一条命令。

**二、「没登记来源」不等于「没有来源」，而是「还没去找」。**
绝大多数 skill 都是从 GitHub 装的。信息通常存在，只是没人去查。
所以顺序永远是：**查安装器记录 → 联网搜 GitHub → 下载逐版比对内容 → 确认了才写**。
`trace` 就是干这个的。找不到才承认 unknown。

**三、版本号必须靠内容比对确认，不能靠推断。**
绝不用「上游最新版」倒推本地版本。本地 Waza 那 8 个装于 07-05，
上游最新是 v3.31.2（07-10 发的），实际本地是 **v3.31.1**——推断必错。

> 这三条是 2026-07-11 的事故换来的：当时把没有 `github_url` 的 skill 一律判成
> 「本地自建」，还给 84 个 skill 编了 `version: 1.0.0`。其中 8 个其实是
> tw93/Waza v3.31.1，74 个是 nexu-io/html-anything。权威记录一直躺在
> `~/.agents/.skill-lock.json` 里，只是没人去读。

其余原则：**只报告真实状态**——「硬盘上有」不等于「正在生效」，「本地版本」不等于「上游最新」。

## 触发条件

| 用户说 | 执行 |
|--------|------|
| 列出技能 / 我有哪些技能 / skill 列表 / list skills | `list` |
| 列出 [项目] 的技能 / 某个项目有哪些 skill | `list <项目名>` |
| 检查更新 / 有没有新版本 / check updates | `check` |
| 这个 skill 哪来的 / 溯源 / 来源不明 | `trace` |
| 更新 [名字] / update | `update <名字>` |
| 更新全部 / 都更新一下 / 把有新版的都更了 | `update`（无参 = 批量） |
| 启用 [名字] / enable | `enable` |
| 禁用 [名字] / disable | `disable` |
| 升版本号 / bump | `bump` |
| skill 体检 / 自检 / doctor | `doctor` |
| 删除 [名字] / delete | `delete` |

## 命令

```bash
/skill-manager list                      # 全局 + 当前目录的项目级 skill
/skill-manager list <项目名|路径>         # 指定项目：项目 skill 与全局 skill 分块列
/skill-manager list --all                # 全景：按最近活跃展开前 3 个项目，其余折叠
/skill-manager list --all -n 10          # 多展开几个（-n 0 = 全部展开）
/skill-manager check                     # 本地版本 vs 上游最新
/skill-manager trace <名字> [--repo <URL>] [--write]   # 溯源：查出处、定版本
/skill-manager trace --all --write       # 批量溯源所有来源不明的
/skill-manager update                    # 更新所有有新版的（先 check 再逐个更新）
/skill-manager update --dry-run          # 只列出将要更新的，不动手
/skill-manager update <名字>             # 更新单个；插件写裸名即可（自动补 @市场名）
/skill-manager enable  <名字> [--project <路径>]
/skill-manager disable <名字> [--project <路径>]
/skill-manager bump <名字> [patch|minor|major]   # 递增本地版本号
/skill-manager doctor [--fix]            # 自检；--fix 修可自动修的
/skill-manager delete <名字> [--dry-run] # 删除 skill 或插件；插件写裸名即可
```

**脚本输出原文展示给用户，不要总结、改写或转成自己的格式。**

## 溯源（trace）

来源不明的 skill，**不要标成「本地」了事，去把它查出来**。三级递进：

1. **安装器记录** `~/.agents/.skill-lock.json` —— 最权威。Waza / vercel skills CLI
   装的 skill 都会在这里留下仓库、路径、安装时间。先查这里。
2. **GitHub 搜索** —— lock 里没有就联网搜候选仓库，列给用户挑。
3. **内容比对定版** —— 拿到仓库后，下载它各个 tag（无 tag 就比 HEAD），
   用内容指纹逐一比对，**完全一致才认定版本**。

同一仓库下的多个 skill 会**批量溯源**（一次下载比对全部），
否则 74 个 skill × 12 个版本 = 888 次下载，根本跑不完。

比对时会自动剥掉 `zh_description`、`version` 这些我们自己写进去的字段
（见 `MANAGED_FIELDS`），否则永远比不中。

## 状态模型（这个 skill 存在的理由）

真实状态散落在 7 个地方，任何一处对不上都会导致「看起来在用、其实没生效」：

| # | 位置 | 管什么 |
|---|------|--------|
| 1 | `~/.claude/skills/<名>/SKILL.md` | 全局直装（`.disabled` 后缀 = 禁用） |
| 2 | `<项目>/.claude/skills/<名>/SKILL.md` | 项目级直装 |
| 3 | `~/.claude/plugins/installed_plugins.json` | 插件的安装路径与版本 |
| 4 | `~/.claude/settings.json` → `enabledPlugins` | 插件的**全局**启用开关 |
| 5 | `<项目>/.claude/settings.json` → `enabledPlugins` | 插件的**项目级**启用开关（覆盖全局） |
| 6 | `~/.claude/commands/*.md`、`<插件>/commands/*.md` | 斜杠命令 |
| 7 | **`~/.agents/.skill-lock.json`** | **安装器记录：每个 skill 从哪个仓库、哪个路径装来的** |

`scripts/core.py` 把这 7 处归集成唯一事实来源，所有命令都走它。
**不要在其他脚本里另起一套收集逻辑**——这正是历史事故的根源。

第 7 项是 2026-07-11 才补上的。在此之前它一直存在，只是没人读——于是 8 个
tw93/Waza 装的 skill 被判成「本地自建」。**加新检查前，先确认权威记录是不是已经躺在某个文件里了。**

### 一个插件可以「全局关、单项目开」

baoyu-skills 就是这么配的：`~/.claude/settings.json` 里是 `false`，
`~/creative/.claude/settings.json` 里是 `true`。所以它只在 `~/creative` 下生效，
其他项目一点上下文都不占。`list` 会把它显示为「项目:creative」。

## 版本规范

版本号回答两个不同的问题——**「我这份是哪一版」**和**「我改过它没有」**。
前者靠版本号，后者靠内容指纹。

### 三个正交维度（别再塞进一列）

旧版把「来源」一列塞了三样东西（`GitHub` / `本地` / `冻结` / `插件@xxx`），怎么归类都别扭：
「冻结」是更新策略不是来源，「插件」是装载形态不是来源，而「聚合仓库」压根不是一类——
**它就是 GitHub，只是一个仓库里放了多个 skill**（靠 `github_path` 区分子目录）。
而且「GitHub」这词几乎零信息量：除本地自建外基本全是 GitHub，有用的是**哪个仓库**。

| 维度 | 取值 | 显示在 |
|------|------|--------|
| **类型**（怎么加载的） | 技能 / 插件 / 命令 | 类型列 |
| **来源**（哪来的） | `tw93/Waza`、`本地`、`未登记 ❓` | 来源列（直接写仓库名） |
| **更新策略** | 跟随上游 / 冻结 | 版本列的 🔒 |

来源列写仓库名后，**聚合仓库自然浮现**——Waza 那 8 个连成一片，一眼可见，
不需要给它发明一个类别。

### 版本取值

| 来源 | 判定依据 | 版本列 |
|------|---------|--------|
| **github** | 有 `github_url`（或 lock 里有记录） | 上游版本号 `3.31.2`，没有则 `07-02 · d4e43c9` |
| **local** | **显式声明** `source: local` | 人工 semver `1.0.0` |
| **frozen** | `update_policy: frozen`（已脱离上游） | 人工 semver + 🔒 |
| **plugin** | 在 `installed_plugins.json` 里 | 上游 plugin.json 的版本 |
| **unknown** | **以上都不是** | `来源未登记` → **去 `trace`，别猜** |

GitHub 来源的版本取值优先级：**上游版本号（VERSION 文件 / tag）> 「发布日期 · 短哈希」**。
上游没给版本号的，诚实显示「哪天的哪一份」——`07-02 · d4e43c9` 比一个编出来的 `1.0.0` 有用得多。

**末尾的 `*` = 内容改过了，版本号没跟上。** `bump` 一下就平账。

### unknown 不是一种「兜底分类」，是一张待办

旧版没有 unknown：没有 `github_url` 就直接判 local，然后 `doctor --fix` 顺手编了个 1.0.0。
现在 unknown 是显式状态，`doctor` 会把它报出来，`trace` 负责消灭它。
**`doctor --fix` 只做有依据的补录（查 lock、查 GitHub API），绝不发明数据。**

### 内容指纹

`fingerprints.json` 存每个 skill 的整目录内容哈希。人工维护版本号必然会忘，
指纹的职责是**监督**它：内容变了、版本号没动 → 打 `*`。`bump` 或 `update` 后自动重新记账。

GitHub 来源的 skill **不套 semver**（身份是上游 commit，硬塞 1.0.0 会跟人家的版本号打架）。
真要脱离上游自己管版本，先加 `update_policy: frozen`。

## 中文描述

查找顺序：**SKILL.md 的 `zh_description` > `descriptions_zh.json` > 原始 description**。

- **直装 skill** → 写进自己的 `SKILL.md` frontmatter。跟着 skill 走，搬去项目、拷给别人都不丢。
- **插件 skill** → 只能写 `descriptions_zh.json`。插件的 SKILL.md 会被上游更新整个覆盖。

`update` 时 `zh_description` 和 `update_policy` 会被原样保下来
（见 `update_skill.py` 的 `PRESERVE_FIELDS`），否则每更新一次就丢一次。

`doctor` 只揪**生效中**却还是英文描述的 skill（未启用的不占上下文，不强求）。

## 项目视图：只列你在看的项目

**「插件在哪些项目生效」和「要列哪些项目」是两码事，别用同一个集合。**

判定生效范围必须拿**全量项目**算，否则「baoyu 全局关、只在 creative 开」这种配置
根本看不出来。但算完要**按视野筛**——旧版算完不筛，于是在 caipiao 里跑 `list`
会把 creative 的 21 行整块印出来。项目越多，默认 `list` 越刷屏。
视野外的项目折叠成一行摘要（项目名 · skill 数 · 最近活跃 · 怎么看）。

三种视野：

| 命令 | 视野 |
|------|------|
| `list` | 全局 + 当前目录 |
| `list <项目>` | 全局 + 该项目（分两块列，全局那块每个项目都一样） |
| `list --all` | 全局 + 最近活跃的前 3 个项目，其余折叠 |

### 「最近活跃」= 会话记录，不是 last_seen

`~/.claude/projects/<路径编码>/*.jsonl` 是 Claude Code 的会话记录，最新一份的 mtime
就是**最后一次在这个项目里干活**的时间。这才是「我最近在写哪个项目」。

不要用 `projects.json` 的 `last_seen`——它只记「最后一次在这儿跑过 skill-manager」，
和开发活跃度毫无关系。它现在只用于给没有会话记录的项目兜底排序。

目录名是把 `/` 换成 `-` 编码的，**反解有歧义**（`-Users-dylan-dev-caipiao-feature`
既可能是 `dev/caipiao-feature` 也可能是 `dev/caipiao/feature`）。别猜——jsonl 文件里的
`cwd` 字段是权威路径，读它。

### 项目发现：注册表 ∪ 会话记录 − worktree

`projects.json` 记录跑过 skill-manager 的项目。但光靠它不够：你天天开发却没在那儿跑过
skill-manager 的项目，永远不会被登记。所以已知项目 = 注册表 **∪** 有会话记录且带
`.claude/skills`（或 `.claude/settings.json`）的目录——后者能自动发现前者漏掉的。

HOME 和 `~/.claude` 必须排除：`~/.claude/skills` 就是全局目录，把 HOME 当项目会让
27 个全局 skill 又被当成「项目:dylan」重列一遍。

**git worktree 不是另一个项目，是同一个仓库的另一份检出。** 项目级 skill 是 git
跟踪的文件，所以 worktree 里的 `.claude/skills` 只是主仓那批 skill 的旧副本。
`worktree_main()` 认出它们（`.git` 是**文件**而非目录，内容 `gitdir: .../worktrees/<名>`），
归并到主仓头上，不重复计数。

> 2026-07-11 事故：`caipiao-task1` 是 `caipiao` 的 worktree，停在 4 天前的分支上，
> 落后 38 个提交。用户早在 main 上给 29 个 skill 补了 `source: local` 并提交了，
> doctor 却一直报这 29 个「来源未登记」——**报的是那份旧副本**。
> 用户以为自己没修好，反复怀疑人生。

**但归并 ≠ 假装不存在。** doctor 第 10 项专门报 worktree：落后主仓多少个提交、
里面的 skill 是旧副本。排除是为了不重复数，不是为了藏。

`list <项目名>` 同名撞车（`/a/caipiao` 和 `/b/caipiao`）→ **列候选让用户挑，绝不猜**。

## 元数据字段

```yaml
version: 3.31.1               # GitHub 来源用上游版本号；本地/冻结用人工 semver
zh_description: 一句话中文用途  # 列表里显示的描述
source: local                 # 显式声明「这是我自己写的」——不写就是 unknown，不靠推断
github_url: https://github.com/tw93/Waza      # 来源仓库
github_hash: <40 位 commit sha>              # 装的是哪个 commit（trace 内容比对确认）
github_date: 07-05                           # 该 commit 的发布日期（上游无版本号时显示用）
github_path: skills/hunt                     # 聚合仓库里的子目录（聚合仓库必填）
update_policy: frozen                        # 绝版/深度定制：check 显示 🔒，update 拒绝
self_mutating: true                          # 设计上会自我改写（如 self-improving 的 hook），豁免 dirty 报警
keep_local_description: true                        # description 已本地调优，update 时别用上游那份盖掉
```

`source: local` 必须**显式写**。不写 = `unknown` = 「还没查」，而不是「本地自建」。

### `keep_local_description`：护住调优过的触发描述

`description` **不是给人看的说明，是决定 Claude 选不选这个 skill 的那句话**——
注入模型的 skill 清单用的就是它（`zh_description` 只喂 skill-manager 自己的列表）。
所以有人把它改写得更好触发之后，`update` 会拿上游那份**悄悄盖回去**：不报错、
不提示，只在下次选错 skill 时才显形。

声明 `keep_local_description: true` 即保住本地那份，其余照常跟上游更新。这一个开关牵动三处，
少改一处就露馅：

| 处 | 不改会怎样 |
|----|-----------|
| `update_skill.py::merge_skill_md` | 本地描述被上游冲掉（本体问题） |
| `core.strip_managed_fields` | 打个保留标记就把 skill 标成「改过了」，多一颗假 dirty 星 |
| `core.fingerprint` + `trace_source.py::trace_batch` | trace 永远判「内容对不上」，这些 skill 永远定不了版本 |

**不做「本地和上游不一样就自动保留」的推断**——那样上游改进的描述永远拿不到，
用户还不知道自己的描述被锁住了。必须显式声明。

比对口径有个坑：这条声明只写在**本地**那份 SKILL.md 里，上游那份没有。所以剥哪些字段
必须**由本地的声明决定、对两边同时生效**（`fingerprint(dir, extra_strip)`）；
一边剥了一边没剥，口径不对称，永远比不中。

## 文件

| 文件 | 说明 |
|------|------|
| `scripts/core.py` | **统一数据层**，所有命令共用的收集与状态判定 |
| `scripts/list_skills.py` | 列出（按是否生效分组） |
| `scripts/trace_source.py` | **溯源**：查 lock → 搜 GitHub → 下载比对定版 |
| `scripts/scan_and_check.py` | 检查更新（本地 vs 上游，严格分列） |
| `scripts/update_skill.py` | 更新（直装整目录合并 / 插件真身定位） |
| `scripts/toggle_skill.py` | 启用 / 禁用（直装改文件名，插件改 settings.json） |
| `scripts/bump_skill.py` | 递增版本号 + 重新记账 |
| `scripts/doctor.py` | 自检（10 项对账，`--fix` 只做有依据的补录） |
| `scripts/delete_skill.py` | 删除（skill 或插件；移进归档区而非硬删） |
| `descriptions_zh.json` | 插件 skill 的中文描述（直装的写在自己的 SKILL.md 里） |
| `fingerprints.json` | 内容指纹（自动维护，别手改） |
| `projects.json` | 项目注册表（自动维护） |

全部脚本零第三方依赖（frontmatter 为内置轻量解析），任何 `python3` 直接跑。

## 名字解析：市场名由脚本补，不由人记

**`update` 与 `delete` 共用 `core.resolve_target`，别各写一份。**

插件的真实 key 是 `codex@openai-codex`，但后半截的市场名是**安装来源的内部标识**——
用户凭什么记得住 codex 是从 `openai-codex` 这个市场装的？裸名字先当直装 skill 找，
找不到再去 `installed_plugins.json` 前缀匹配，唯一命中就补全。

**唯一命中才补，撞名就列候选让人挑**（同名插件装在两个市场时）。这是本 skill
第一性原理的直接推论：猜一个的代价是操作错对象，让人多敲一次 `@市场名` 只是麻烦。

## 删除机制：移走，不是抹掉

删除**一律移进** `~/.claude/skills-archive/_deleted/<名>.<时间戳>/`（旧版是
`shutil.rmtree` 硬删，删错了没救）。后悔了搬回去就行，真要腾空间再手动清归档区。

**「删干净」= 清掉所有留了它名字的地方**，不是「我想得起来的地方」。
两条路径各有各的登记表，且必须对称——只把插件那条想周全，直装那条照样漏。

**删直装 skill 要清两处**：

| 清什么 | 在哪 |
|--------|------|
| 指纹记录 | `fingerprints.json` → key 是 **`global:<名>`**，不是裸名 |
| 中文描述 | `descriptions_zh.json` → 同名条目 |

> 这两处 2026-07-11 之前都没清：中文描述压根没写清理代码，指纹则是拿裸名去查
> `global:` 前缀的 key，永远查不中，等于从没清过。doctor 第 3 项（死条目检查）
> 一直在替这个 bug 擦屁股——事后能查出来，但根子上就不该留下。

**删插件要清四处**，漏一处就留下指向不存在插件的脏数据（doctor 第 1 项正是为这种残留加的）：

| 清什么 | 在哪 |
|--------|------|
| 缓存目录 | `plugins/cache/<市场>/<插件名>/`（连版本目录的父目录一起删，否则留个空壳） |
| 登记表 | `installed_plugins.json` |
| 中文描述 | `descriptions_zh.json` 里该插件旗下所有 skill |
| 启用开关 | 全局与各项目 `settings.json` 的 `enabledPlugins` |

`--dry-run` 会把将删什么逐条列出来。**列表为空和没扫到长得一模一样**——
改这段代码时务必单独验证「确实没有」而不是「函数坏了」。

## 更新机制

### 无参 = 批量更新

`update` 不给名字 = 先跑一遍 check，筛出 `outdated` 的逐个更新，末尾汇总成功/失败。
「先 check 再照着名单一个个 update」本来就是人必然会做的动作，没理由让人手动搬运。

- **复用 `scan_and_check` 的收集与比对**，不另起一套（状态模型那节的教训）。
- **逐个更新互相隔离**：单个抛异常只记失败，不中断整批。
- 连不上上游的（`error`）本轮跳过并列出来，不静默吞掉。
- `--dry-run` 只列不做。

### 直装 skill（有 `github_url`）—— 整目录合并
1. `frozen` → 拒绝
2. `git ls-remote` 比对 `github_hash`，已最新则结束
3. **整目录备份**到 `~/.claude/skills-archive/_update_backups/<名>.<时间戳>/`（回滚入口）
4. 下载 tarball，按 `github_path` 定位源目录（缺省依次试仓库根 / `skills/<名>/` / 浅层扫描）
5. **合并式落盘**：上游文件覆盖同名文件；本地独有文件（config.env、site-patterns/ 等）
   一律保留；回注元数据并保留 `zh_description` 与「## User-Learned」段
6. 任何一步失败都不改动本地（备份除外）

### 插件 —— monorepo 真身定位 + 验证后提交
1. 下载 tarball，**定位插件真身**（仓库根 → `plugins/<名>/` → `external_plugins/<名>/` → 浅层扫描），
   结构判定 = 有 `.claude-plugin/plugin.json`，或 baoyu 式 `marketplace.json` + `skills/`
2. **结构验证通过才写** `installed_plugins.json`；失败保留旧版继续可用
3. 更新后对比新旧 skill 列表，维护 `descriptions_zh.json`（新增补中文、删除的清掉）

## User-Learned Best Practices & Constraints

> 本节由 skill-evolution-manager 维护。

### User Preferences
- 安装 GitHub skill 仓库前，先检查 `skills/` 目录下的 SKILL.md 是否已定义 slash command，
  若有则跳过 `commands/` 目录的安装（否则命令重复显示）。

### Known Fixes & Workarounds
- **`update` 会静默冲掉调优过的 description**（2026-07-11）：`PRESERVE_FIELDS` 只保
  `zh_description` / `update_policy`，SKILL.md 直接用上游那份。但 `description` 才是
  **决定 Claude 选不选这个 skill 的那句话**——nexu-io/html-anything 那 3 个
  （card-twitter / flowai-team-dashboard / live-dashboard）的描述被本地调优过，
  特意标注了「非拟真 X UI」「可操作 vs 只看不操作」来区分彼此，一 update 就全没了。
  修复：新增 `keep_local_description: true`。**教训：本地定制的保留名单，漏一个字段就等于
  每次更新悄悄回滚一次用户的优化——而且是无声的，只在下次选错 skill 时才显形。**
- **比对两份内容时，剥字段的口径必须来自同一方**（2026-07-11）：`fingerprint` 按
  **每个文件自己的 frontmatter** 决定剥不剥 description，而这条声明只写在本地那份里 ——
  本地剥了、上游没剥，trace 永远比不中。剥哪些字段要由本地声明决定并对两边同时生效
  （`fingerprint(dir, extra_strip)`）。
- **默认 `list` 会把别的项目整块印出来**（2026-07-11）：`collect_all` 里插件的生效范围
  拿全量注册项目算（这没错，否则看不见 baoyu 只在 creative 开），**但算完不筛**——
  于是在 caipiao 里跑 `list`，creative 的 21 行照印。项目一多就是刷屏。
  修复：生效范围照旧全量算，展示时按视野筛，视野外折叠成一行。
  **教训：判定用的集合 ≠ 展示用的集合，别图省事复用同一个。**
- **`is_project_dir(HOME)` 会返回 True**（2026-07-11）：`~/.claude/skills` 存在，
  所以 HOME 满足「项目」判据——一旦把 HOME 当项目扫，27 个全局 skill 会被重列成
  「项目:dylan」。旧版靠注册表里碰巧没有 HOME 才没炸；项目改成从会话记录自动发现后
  这个坑就在路上了。已在 `is_project_dir` 源头排除 HOME 与 `~/.claude`。
- **annotated tag 的 sha 不是 commit sha**（2026-07-11）：`git ls-remote --tags` 对
  annotated tag 返回的是 **tag 对象自己的 sha**，真正的 commit 在 `^{}` 那一行。
  过滤掉 `^{}` 就会把 tag 对象 sha 当 commit 记进 `github_hash`，GitHub API 查它直接报
  「No commit found」（vercel-labs/skills 中招）。Waza 用 lightweight tag 所以碰巧没暴露。
  解析统一走 `core.remote_tags()`。
- **`check` 和 `update` 的口径必须一致**（2026-07-11）：update 更新到最新 tag，
  check 若拿 HEAD 比，HEAD 永远领先 tag 几个未发版的 commit —— 更新完照样报「有新版」，
  黄灯永远消不掉。反过来插件是按 commit 装的，拿 tag 比同样会误报。
- **doctor 报「已修复 N 项」用的是条目数不是成功数**（2026-07-11）：修复失败了还说已修复，
  自己违反了自己的第一条铁律。现在只报实际成功数。
- **会自我改写的 skill 要豁免 dirty**（2026-07-11）：self-improving 的 hook 每次会话都把
  经验写回自己的 SKILL.md，指纹永远对不上，那颗 `*` 就成了噪声。加 `self_mutating: true` 豁免。
- **把「没登记来源」当成「本地自建」，编了 84 个假版本号**（2026-07-11，最严重的一次）：
  `_source_of()` 里「没有 github_url → local」，接着 `doctor --fix` 给它们全填了
  `version: 1.0.0`。实际上 8 个是 tw93/Waza **v3.31.1**（不是上游最新的 v3.31.2——
  猜最新版也会猜错），74 个是 nexu-io/html-anything，1 个是 vercel-labs/skills v1.5.15。
  而权威记录一直躺在 `~/.agents/.skill-lock.json` 里，从没被读过。
  修复：引入 `unknown` 来源 + `trace` 命令 + 删掉那个编造版本号的 fixer。
  **教训：缺信息就报缺失；「查不到」和「不存在」是两回事。**
- **更新完不同步版本号 = 新的谎言**（2026-07-11）：`update` 只写 hash 不写 version，
  Waza 更新到 3.31.2 后版本列还显示 3.31.1。现在会读上游 `VERSION` 文件同步。
- **登记表能指向不存在的目录，且静默失效**（2026-07-11）：`installed_plugins.json` 里 baoyu 的
  `installPath` 指向一个已被清掉的版本目录（更新中断留下的），结果 `~/creative` 里 21 个技能
  加载不出来——不报错、就是不加载。`doctor` 的第 1 项就是为它加的。
- **插件可以没有 `skills/` 目录**（2026-07-11）：claude-hud 的能力全在 `commands/` 里。
  只扫 `skills/` 会让它整个从列表里消失。两处都要收。
- **frontmatter 只认开头那个 `---` 块**：正文里的 yaml 代码示例不能被当成元数据
  （曾经 grep 抓错，误判 skill-manager 的 frontmatter 被污染）。
- monorepo 插件（openai-codex 在 `plugins/codex/`、claude-plugins-official 在
  `plugins|external_plugins/<名>/`）曾导致更新装成空壳仓库根（2026-07-03 实战修复 codex/imessage）。
  现已内置真身定位 + 结构验证后才写登记表。
- 脚本已于 2026-07-03 去除 PyYAML 依赖（此前系统 python3 缺 yaml 会崩）。
- skill-manager 的原上游仓库 KKKKhazix/Khazix-Skills 已改版下架本 skill，本地版即唯一版本，
  `update` 对它不适用（已标 `frozen`）；neat-freak 仍可从该仓库更新。
