# lookup

> The single entry point for all network lookups. Skill content is in Chinese.

联网查信息的唯一入口：搜索、抓网页正文、读第三方平台内容、检索本机浏览历史。所有联网操作从这里选路。

它解决的不是「怎么调某个抓取工具」，而是**在有限的上下文窗口里，怎么用最少的 token 拿回够用且真实的信息**：

- **分层选通道** — 能停在「已结构化的结果」就不要下沉到「整页拉回自己读」。实测抓同一个 X 主页，整页快照与页面内跑 JS 只取 `article` 节点，信息量相同、token 差一个数量级。
- **内容有效性校验** — 抓取工具返回 `status=ok` 不等于拿到了内容。小红书、B站、YouTube 三个平台都出现过 `ok` 但内容是导航菜单、二进制乱码、页脚版权的情况；公众号那条路更是返回反爬验证码页却报成功。四条判据写在 SKILL.md 里，命中即判失败、换通道。
- **失效域建模** — 两个工具名不同不代表是两条路。`ego-browser` 和 OpenCLI 共享同一个浏览器进程与登录态，所以浏览器崩了换谁都没用；但 OpenCLI 多依赖 daemon、扩展和站点适配器两层，那两层坏的时候换 `ego-browser` 是有效兜底。判断故障在哪一层，比盲目重试省一轮。

## 这个 Skill 能不能直接拿走用

**能拿走的是决策结构，不是命令本身。**

与本仓库另两个 Skill 不同，lookup 里的具体命令绑定了作者的本机工具链——其中 `ego lite` 浏览器和 OpenCLI 适配器不是通用可得的软件。你直接安装后，六平台那部分命令大概率跑不起来。

真正可复用的是这几层判断：省 token 的三层优先级、内容有效性的四条判据、失效域是否真正独立的判据、以及「搜索结果是列表不是正文」这类反复踩过的坑。把命令换成你自己的工具，这套结构照样成立。

底层工具是可替换的取水口，换工具不改决策结构——这是 SKILL.md 开头就写明的设计前提。

## 依赖

| 依赖 | 用途 | 缺了会怎样 |
|---|---|---|
| `ego lite` | agent 专用浏览器，提供 `ego-browser` 命令 | X / 小红书 / 抖音 / 公众号全部不可用 |
| `opencli` | 平台适配器，六平台的结构化搜索 | 同上，且失去登录态判断手段 |
| `yt-dlp` | YouTube 搜索与字幕 | YouTube 通道不可用 |
| `bili` | B站免登录搜索 | B站搜索退化为走 OpenCLI |
| `mcporter` | 调 Exa 与豆包搜索（MCP stdio） | 英文语义搜索与中文全网搜索不可用 |
| `fetch.sh` | 静态抓取博客/文档/新闻 | 需换其他静态抓取方式 |
| `node` ≥ 18 | 跑 `scripts/*.mjs` | 本机历史检索与站点经验匹配不可用 |
| `python3`、`curl` | 探活时间戳与 HTTP 请求 | 零窗口探活不可用 |

`fetch.sh` 来自 Waza 的 `read` skill（`~/.agents/skills/read/scripts/fetch.sh`）。该 skill 可以处于禁用状态，脚本仍可直接调用；若 `read` 被删除则此路径失效。

`yt-dlp`、`bili` 装在 uv tool 隔离环境（`uv tool list` 可查），可执行文件在 `~/.local/bin/`。

## 安装

多客户端共用时装到共享全局目录：

```bash
git clone https://github.com/ldl8818/skills.git
mkdir -p ~/.agents/skills
rsync -a --delete --exclude '.DS_Store' \
  skills/lookup/ ~/.agents/skills/lookup/
```

再给各客户端建**单 Skill 软链**（不要整目录链接）：

```bash
mkdir -p ~/.claude/skills ~/.codex/skills
ln -s ~/.agents/skills/lookup ~/.claude/skills/lookup
ln -s ~/.agents/skills/lookup ~/.codex/skills/lookup
```

只给 Claude Code 用时，把 rsync 的目标换成 `~/.claude/skills/lookup/` 即可。

装好后新开或重启客户端会话才会加载。之后说「搜一下…」「读一下这个网页」「这个视频讲了什么」即可触发。

### 可选：ego task space 自动收尾

ego lite 的每个 agent task space 底层是一个独立浏览器窗口，靠 Agent 主动收尾不可靠——会话被打断、上下文压缩，窗口就永久残留。`scripts/ego-spaces.mjs` 提供两层机制兜底：Stop hook 门禁（结束回复时若仍有 agent 持有的 space 就阻断并让模型处理）＋ SessionStart 闲置回收（全局超过 2 小时未用 ego 则清理孤儿 space）。

需要往 `~/.claude/settings.json` 加三条 hook，配置见 [`references/ego-space-hooks.md`](references/ego-space-hooks.md)。零依赖，只要 Node ≥ 18；不装也不影响其他功能。

## 验证

```bash
bash scripts/selftest.sh          # 零副作用：命令存在性 + 探活 + 登录态 + 子命令是否还在
bash scripts/selftest.sh --live   # 额外对每个平台发一条最小真实查询
```

默认模式不发任何平台业务请求，不消耗接口额度，可以随时跑。`--live` 会消耗额度并可能留下浏览器容器窗口，只在排查「命令是不是过时了」时用。

失败项按 `references/failure-domains.md` 的分层判据处理：探活失败是 L3，登录态失败是 L2，子命令消失是 L4。

## 测试用例

`evals/evals.json` 有 7 条用例，每条针对一个「不读 SKILL.md 就一定会做错」的点：X 搜最新漏 `--product live`、把搜索列表当正文交付、公众号走 `fetch.sh` 拿到反爬页、用 `timeline` 当「某人推文」、直接读原始 VTT、内网地址去公网搜、用 `opencli doctor` 探活留下关不掉的窗口。

`expectations` 里每条都能从 transcript 客观核验（发了哪条命令、有没有二次取正文、交付时怎么声明时效），不是主观评分。跑法见官方 skill-creator 的 eval 流程；用例本身与运行工具解耦，换测试框架不用改。

## 本机数据（在 Skill 目录之外）

站点抓取经验存在 `~/.agents/data/site-patterns/<域名>.md`，放在 skill 目录之外是为了增删、重装 skill 都不影响积累。

`references/site-patterns` 是指向那个目录的软链，**不入库**（它是绝对路径，且属于本机数据），所以克隆后需要自己建一次：

```bash
mkdir -p ~/.agents/data/site-patterns
ln -s ~/.agents/data/site-patterns ~/.agents/skills/lookup/references/site-patterns
```

没建也不会报错——`match-site.mjs` 会明确告诉你目录不存在，而不是静默返回空。

开工前查、收工写回：

```bash
node scripts/match-site.mjs "<用户输入或目标域名>"
```

检索本机浏览器书签与历史（覆盖 ego lite / Chrome / Edge），是公网搜不到的内部系统、后台、内网域名的唯一入口：

```bash
node scripts/find-url.mjs <关键词> [--browser ego|chrome|edge] [--only bookmarks|history] [--since 7d]
```

## 参考文件

SKILL.md 只留决策前置生效的内容，执行细节按需读：

| 文件 | 什么时候读 |
|---|---|
| [`references/failure-domains.md`](references/failure-domains.md) | 判断故障层级、评估某条通道值不值得加 |
| [`references/opencli-windows.md`](references/opencli-windows.md) | OpenCLI 留下的空白窗口关不掉时 |
| [`references/ego-space-hooks.md`](references/ego-space-hooks.md) | 装 task space 自动收尾的 hook、或 Stop 被它拦下时 |
| [`references/weixin-article.md`](references/weixin-article.md) | 取公众号文章正文（搜狗跳转链的处理） |
| [`references/youtube-subtitles.md`](references/youtube-subtitles.md) | 下 YouTube 字幕 |
| [`references/providers.json`](references/providers.json) | 候选台账：算失效域集中度、增删通道时同步（无执行器，不参与运行时路由） |

## License

MIT，见仓库根 [`LICENSE`](../LICENSE)。
