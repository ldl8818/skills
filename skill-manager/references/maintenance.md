# 维护者手册（改 scripts/ 前必读）

> 日常执行不用读这份文件。只在修改 skill-manager 自身代码、排查其 bug、
> 或想知道某条设计为何如此时读。每条规则附「来历」——它对应的真实事故。

## 目录

- [本 skill 的来源](#本-skill-的来源)
- [数据层契约](#数据层契约)
- [实现细节备忘](#实现细节备忘)
- [安全与事务边界](#安全与事务边界)
- [事故簿](#事故簿)

## 本 skill 的来源

原上游 KKKKhazix/Khazix-Skills 已改版下架本 skill，本地版即唯一版本，故标 `frozen`。
neat-freak 仍可从该仓库更新。

## 数据层契约

### core.py 是唯一数据层
7 处状态位置的收集与判定全部走 `core.py`，不要在其他脚本里另起一套收集逻辑。
加新检查前，先确认权威记录是不是已经躺在某个文件里了。
> 来历（2026-07-11，最严重的一次）：`_source_of()` 旁路判定「没有 github_url → local」，
> `doctor --fix` 顺势给 84 个 skill 编了 `version: 1.0.0`。实际 8 个是 tw93/Waza
> v3.31.1（猜上游最新版 v3.31.2 也会错），74 个是 nexu-io/html-anything。
> 权威记录一直躺在 `~/.agents/.skill-lock.json` 里没人读。
> 修复 = `unknown` 来源 + `trace` 命令 + 删掉编版本号的 fixer。这就是三条铁律的出处。

### update 与 delete 共用 core.resolve_target
裸名解析（直装优先 → 插件前缀匹配补 `@市场名`，唯一命中才补、撞名列候选）只有一份实现，
别各写一份——两边行为漂移就是操作错对象的开端。

### 字段名单：MANAGED_FIELDS 与 PRESERVE_FIELDS
- `core.MANAGED_FIELDS`：算指纹时剥掉的「skill-manager 自己写的字段」。
- `update_skill.PRESERVE_FIELDS`：更新时从本地 SKILL.md 原样保下来的字段
  （`zh_description` / `update_policy` / `keep_local_description`）。

加新元数据字段时两份名单都要过一遍。漏 PRESERVE = 每次更新悄悄回滚一次用户定制，且无声。
> 来历（2026-07-11）：`description` 不在 PRESERVE 里，3 个本地调优过触发描述的 skill
> 一 update 全被上游盖回去。修复 = `keep_local_description` 开关。

### keep_local_description 牵动三处，少改一处就露馅
| 处 | 不改会怎样 |
|----|-----------|
| `update_skill.py::merge_skill_md` | 本地描述被上游冲掉 |
| `core.strip_managed_fields` | 打个保留标记就多一颗假 dirty 星 |
| `core.fingerprint` + `trace_batch` | trace 永远比不中，定不了版本 |

不做「两边不一样就自动保留」的推断——上游改进的描述会永远拿不到，且用户不知情。

### 版本判定是方向性比对，不是指纹相等
「本地是哪一版」用 `core.content_matches_upstream(local, upstream)` 判：上游每个文件
都须在本地存在且一致；**本地多出的文件不参与**——skill 运行时自生成的文件（配置、
自学笔记）和 update 保留的本地独有文件不改变它装自哪一版。整目录指纹相等只用于
dirty 检测（`fingerprint` + `fingerprints.json`），别拿它比上游。
比对口径也在这里统一：`keep_local_description` 只写在本地那份 SKILL.md 里，
剥哪些字段由本地声明决定、对两边同时生效，一边剥一边不剥就永远比不中。
> 来历（2026-07-11，官方 skill 评估跑出来的）：web-access 自生成的 config.env 和
> site-patterns/ 让整目录指纹和上游哪个 tag 都对不中，trace 永远定不了版。
> 同一次还连出两个 bug：单个 trace 不读已登记的 github_url（批量路径读、单个路径漏）；
> find_skill_dir 认不出「仓库根就是 skill」的单 skill 仓库（解压临时目录名随机，
> 靠目录名匹配必失败，改为看 frontmatter 的 name）。

### 运行数据存放在 skill 自身目录（已知取舍）
`fingerprints.json` / `projects.json` / `descriptions_zh.json` 落在
`~/.claude/skills/skill-manager/` 里。这个选址的代价是四处补偿：指纹的自指排除
（`SM_DATA_FILES`）、仓库根 `.gitignore`、README 安装命令的 `--exclude` 清单、
update 合并时「本地独有文件保留」；好处是零配置、数据跟着 skill 走。
若未来迁移，方向是 `~/.claude/data/skill-manager/`（新位置优先、旧位置读旧写新一次性搬迁）。
在那之前：**新增数据文件或改名时，上述四处都要同步过一遍，漏一处就是自指 dirty 或数据被更新冲掉。**

### check 与 update 口径一致
update 更到最新 tag，check 就拿 tag 比（拿 HEAD 比会永远报「有新版」）；
插件按 commit 装，就拿 commit 比。

### User-Learned 段与本地独有文件
`update_skill.py` 合并更新时保留目标 skill 的 `## User-Learned Best Practices` 段
（`USER_SECTION_RE`）和本地独有文件。改合并逻辑别弄丢。

## 实现细节备忘

- **项目发现** = `projects.json` 注册表 ∪ 有会话记录且带 `.claude/skills`（或
  `.claude/settings.json`）的目录。**HOME 和 `~/.claude` 在 `is_project_dir` 源头排除**
  （HOME 下有 `~/.claude/skills`，不排除会把全局 skill 重列成「项目:<用户名>」）。
- **最近活跃** = `~/.claude/projects/<路径编码>/*.jsonl` 最新 mtime。不要用
  `projects.json` 的 `last_seen`（只记「上次在这儿跑 skill-manager」，仅作兜底排序）。
  路径编码反解有歧义，jsonl 里的 `cwd` 字段才是权威路径。
- **git worktree 归并**：worktree 的 `.claude/skills` 是主仓的旧副本，不是另一个项目。
  `worktree_main()` 识别（`.git` 是文件、内容 `gitdir: .../worktrees/<名>`）后归并计数；
  doctor 第 10 项显式报落后的 worktree——归并是防重复数，不是藏。
  > 来历（2026-07-11）：worktree 落后 38 个提交，doctor 报的是旧副本里早已修好的
  > 29 个问题，用户反复怀疑自己没修好。
- **批量溯源**：同一仓库的多个 skill 一次下载比对全部（逐个下载是 74×12=888 次的组合爆炸）。
- **tag 解析统一走 `core.remote_tags()`**：annotated tag 在 `ls-remote` 里返回 tag 对象
  自己的 sha，真 commit 在 `^{}` 行；手写过滤会把错误 sha 记进 `github_hash`。

## 安全与事务边界

- 所有外部名字先过 `core.safe_component`，所有派生路径再过 `core.contained_path`；
  两层都不能省。插件登记表和上游 manifest 都是不可信输入。
- 远端归档通过 Python 下载和解包，不允许 `shell=True`，并拒绝路径逃逸、软链接、
  硬链接和设备文件。
- JSON 只对“文件不存在”使用默认值；损坏、权限错误必须硬失败。写入统一走同目录
  临时文件、`fsync`、`os.replace`。
- 直装更新先在相邻 staging 目录完成合并与校验，再原子替换在线目录；在线目录不能
  在校验完成前逐文件覆盖。
- **直装更新流程**：frozen 拒绝 → ls-remote 比 hash → 整目录备份 → tarball 按
  `github_path` 定位 → 合并落盘（保留 PRESERVE 字段、User-Learned 段、本地独有文件，
  同步上游 `VERSION` 到 version 字段）→ **落盘后自检**（`validate_skill_md`：新
  `SKILL.md` 解析不出 `name`/`description` 就判定合并出坏文件，从整目录备份回滚，
  不当成功）→ **打印变更摘要**（`summarize_change`：description 变了 / 章节增减，
  避免「hash 换了但没人知道换了什么」的静默更新）→ 失败不改本地。
- **插件更新流程**：tarball 定位真身（仓库根 → `plugins/<名>` → `external_plugins/<名>` →
  浅层扫描；判据 = `.claude-plugin/plugin.json` 或 `marketplace.json`+`skills/`）→
  结构验证通过才写登记表 → 同步 `descriptions_zh.json`。
- **删除清理**：直装清 2 处（`fingerprints.json` 的 key 是 **`global:<名>`** 不是裸名、
  `descriptions_zh.json`）；插件清 4 处（缓存目录连父目录、`installed_plugins.json`、
  旗下 skill 的中文描述、全局与各项目的 `enabledPlugins`）。两条路径必须对称维护。
  注意 `--dry-run` **列表为空和函数没扫到长得一模一样**，改代码后要单独验证「确实没有」。

## 独立事故（不对应上面某条规则，但别再犯）

- **doctor 报「已修复 N 项」曾用条目数而非成功数**：修复失败还说已修复，
  违反第一条铁律。只报实际成功数。
- **登记表可以指向不存在的目录且静默失效**：`installPath` 指向被清掉的版本目录
  （更新中断残留），插件下所有 skill 静默加载不出来。doctor 第 1 项为此而设。
- **插件可以没有 `skills/` 目录**（claude-hud 全在 `commands/`）：两处都要收，
  只扫 `skills/` 它就整个消失。
- **frontmatter 只认开头那个 `---` 块**：正文里的 yaml 代码示例不是元数据，
  曾因 grep 抓错误判被污染。
- **monorepo 插件曾被装成空壳仓库根**（2026-07-03，codex/imessage）：
  修复 = 真身定位 + 结构验证后才写登记表。
- **PyYAML 依赖曾致系统 python3 崩**（2026-07-03 移除）：保持零第三方依赖。
- **删除曾不清指纹和中文描述**：指纹拿裸名查 `global:` 前缀 key 永远查不中，
  doctor 第 3 项（死条目）一直在替它兜底——事后能查出，根子上不该留。
