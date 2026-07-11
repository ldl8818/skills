# skill-manager

Claude Code 的 skill 生命周期管理器：**列出、溯源、查更新、启停、定版本、自检、删除**。

一台机器上的 skill 通常来自三个地方——全局直装（`~/.claude/skills/`）、项目级
（`<项目>/.claude/skills/`）、插件（`~/.claude/plugins/`）——而真实状态散落在 7 个配置文件里。
于是「硬盘上有」不等于「正在生效」，「本地版本」也不等于「上游最新」。

这个 skill 把这 7 处归集成唯一事实来源，并坚持一条原则：**宁可说不知道，也不编一个**。
查不到来源就如实报「未登记」，绝不用默认值（比如凭空捏一个 `version: 1.0.0`）填充。

## 安装

```bash
git clone https://github.com/ldl8818/skills.git
cp -r skills/skill-manager ~/.claude/skills/
```

之后在 Claude Code 里说「列出我的技能」「检查更新」即可触发，也可以直接用斜杠命令。

**要求**：`python3`（macOS / Linux 自带）。**零第三方依赖**，全部标准库，不需要 pip install。

## 命令

```bash
/skill-manager list                      # 全局 + 当前目录的项目级 skill
/skill-manager list <项目名|路径>         # 指定项目：项目 skill 与全局 skill 分块列
/skill-manager list --all                # 全景：按最近活跃展开前 3 个项目，其余折叠
/skill-manager check                     # 本地版本 vs 上游最新
/skill-manager trace <名字> [--write]     # 溯源：查出处、靠内容比对定版本
/skill-manager trace --all --write       # 批量溯源所有来源不明的
/skill-manager update [名字]             # 更新单个；不给名字 = 更新所有有新版的
/skill-manager update --dry-run          # 只列出将要更新的，不动手
/skill-manager enable  <名字>            # 启用（直装改文件名，插件改 settings.json）
/skill-manager disable <名字>            # 禁用
/skill-manager bump <名字> [patch|minor|major]   # 递增本地版本号
/skill-manager doctor [--fix]            # 自检 9 项；--fix 只做有依据的补录
/skill-manager delete <名字> [--dry-run] # 删除（移进归档区，不硬删）
```

几个设计要点：

- **删除是移走，不是抹掉**。一律移进 `~/.claude/skills-archive/_deleted/`，后悔了搬回去就行。
- **溯源靠内容比对，不靠推断**。下载上游各个 tag 逐一比对指纹，完全一致才认定版本；
  绝不用「上游最新版」倒推本地版本（那必错）。
- **插件名不用记市场名**。`codex` 会自动补全成 `codex@openai-codex`；撞名则列候选让你挑，不猜。

## 本机数据文件（仓库里没有，首次运行自动生成）

这几个 json 记录的是「**这台机器的状态**」，换台机器毫无意义，且含本机绝对路径，
所以不入库（见根目录 `.gitignore`）：

| 文件 | 内容 | 维护方式 |
|------|------|---------|
| `fingerprints.json` | 每个 skill 的整目录内容哈希，用来发现「内容改了、版本号没跟上」 | 自动 |
| `projects.json` | 跑过本 skill 的项目注册表 | 自动 |
| `evolution.json` | 使用过程中积累的偏好与修正 | 自动 |
| `descriptions_zh.json` | **插件** skill 的中文描述外挂表 | 手工 |

代码在文件不存在时会兜底成空表（`core.py` 的 `read_json`），所以缺失不影响使用。

关于最后一个：直装 skill 的中文描述应写进各自 `SKILL.md` 的 `zh_description` 字段
（跟着 skill 走，搬家、拷给别人都不丢）；**插件只能走外挂表**——因为插件的 SKILL.md
会被上游更新整个覆盖，写进去下次更新就没了。这张表是手工维护的，换机器时值得单独备份。

## 设计文档

`SKILL.md` 是给 Claude 读的行为定义，也是唯一的行为真身，里面记着每条规则背后的事故与权衡。
想改这个 skill，先读它。

## License

MIT
