---
name: lookup
description: >
  联网查信息的唯一入口：搜索、抓取网页正文、读第三方平台内容、检索本机浏览历史。
  按目标选通道，校验内容有效性，用最少 token 拿回够用的信息。
  触发词：搜一下、查一下、找一下、搜索、看看这个链接、读一下这个网页、抓取网页、
  去小红书搜、去B站搜、去X上看、YouTube 上找、抖音上搜、公众号文章、推特上、
  查字幕、下字幕、这个视频讲了什么、最新消息、最近有什么、
  AI 资讯、AI 热点、我之前看过的、我访问过的、书签里找、历史记录里找、
  search、fetch this url、read this page、what's the latest。
license: MIT
metadata:
  version: "1.7.0"
  source: local
  zh_description: 联网查信息的唯一入口：分层选通道、校验有效性、省 token
---

# lookup — 联网查信息的唯一入口

本 skill 只负责**取回干净的信息**，不负责落盘归档。取回后要不要存进知识库，由当次任务决定。

所有联网操作从这里选路。底层工具是可替换的取水口，换工具不改本文的决策结构。

## 第一原则：省 token 优先于省事

在 CUI 窗口里做决策时，最贵的不是抓取失败，是把整页原始 HTML 塞进上下文——那会直接拖垮当前窗口的判断质量。按这个顺序选，能停在上一层就不要下沉：

| 层 | 做法 | 例子 |
|---|---|---|
| 1 | **取已结构化的** | aihot 的 JSON 摘要、Exa 带 highlights 的结果、OpenCLI 的 YAML 字段 |
| 2 | **定向提取** | WebFetch 带 prompt 让小模型代读；ego-browser 里跑 JS 只取目标节点 |
| 3 | 整页拉回自己读 | 最后手段 |

实测差距：抓同一个 X 主页，`snapshotText()` 整页拉回是一堆导航和侧边栏，改成页面内跑 JS 只取 `article` 节点，信息量相同，token 差一个数量级。

## 选通道

### 发现层（不知道 URL，要先找）

| 目标 | 通道 |
|---|---|
| AI 圈动态、最新资讯 | aihot REST API（下方「免安装接口」），匿名只读免 Key |
| 中文全网搜索 | **豆包搜索**（见下方「豆包搜索」），字节系信源 + 发布时间到秒 + 时效过滤 |
| 英文/全球搜索、找论据与出处 | **Exa 语义搜索**（下方「Agent-Reach 提供的通道」），直接返回带 highlights 的摘要，属第 1 层 |
| 英文/全球搜索（兜底） | WebSearch |
| 平台内搜索 | 见下方「常用六平台」 |
| **我自己访问过的页面** | `node scripts/find-url.mjs <关键词>` |

`find-url.mjs` 检索本机 ego lite / Chrome / Edge 的书签与历史，是公网搜不到的内部系统、后台、内网域名的唯一入口。支持 `--browser ego|chrome|edge`、`--only bookmarks|history`、`--since 7d`、`--sort recent|visits`。

### 获取层（已知目标，取正文）

| 目标 | 通道 |
|---|---|
| 公众号、博客、文档、新闻 | `bash ~/.agents/skills/read/scripts/fetch.sh <url>` |
| 六大常用平台 | 见下方「常用六平台」 |
| 需要交互、登录、自由探索的长尾站点 | ego-browser |

浏览器一律用 **ego lite**。本文的术语分工：**ego lite** 指浏览器本体（进程、Profile、窗口），**ego-browser** 指驱动它的 skill 与 JS API（完整 API 见 `~/.agents/skills/ego-browser/SKILL.md`）。下面只列最容易违反的纪律。

## 常用六平台

用户日常只用这六个：**X、YouTube、小红书、B站、公众号、抖音**。以下命令 2026-07-29 全部实测通过，可直接抄，不要自己另发明用法。OpenCLI 系命令保留 `--window background`：适配器命令的默认值本来就是 background，但默认值是 per-command 可声明的（`cmd.defaultWindowMode ?? 'background'`），显式写上防某个适配器单独声明 foreground。它只管抢不抢焦点，**消不掉窗口本身**，见下方「OpenCLI 的容器窗口」。

**搜索命令拿回来的是列表，不是正文。**六个平台无例外，都要从列表里取 id 或 URL 再发第二条命令才有正文——B站和公众号只是第二步换了工具（`opencli bilibili` / `fetch.sh`），不是不用发。把搜索结果当正文交付是真实踩过的坑。

| 平台 | 搜索（拿列表） | 取正文（拿到 id/URL 后） |
|---|---|---|
| **X** | `opencli twitter search "<词>" --product live -f yaml --limit N --window background` | 长文 `opencli twitter article <tweet-id>`；整串 `opencli twitter thread <tweet-id>`；某人推文 `opencli twitter tweets <用户名>` |
| **YouTube** | `yt-dlp "ytsearch5:<词>" --flat-playlist --print "%(title)s \| %(channel)s \| %(duration_string)s \| %(url)s"` | 字幕见 `references/youtube-subtitles.md` |
| **小红书** | `opencli xiaohongshu search "<词>" -f yaml --limit N --window background` | **`opencli xiaohongshu note <note-id>`**；评论 `opencli xiaohongshu comments <note-id>` |
| **B站** | `bili search "<词>" --type video -n 5`（免登录，最省） | 字幕 `opencli bilibili subtitle <BV号>` |
| **公众号** | `opencli weixin search "<词>" -f yaml --limit N --window background` | `bash ~/.agents/skills/read/scripts/fetch.sh <url>` |
| **抖音** | `opencli douyin search "<词>" -f yaml --limit N --window background` | 搜索结果**没有发布时间**，见下方「时效性」 |

`opencli twitter timeline` 取的是**登录账号自己的首页推荐流**，不接用户名参数；要看指定某人发了什么用 `opencli twitter tweets <用户名>`。别把 timeline 当「某人时间线」用。

### 时效性：默认排序不是按时间

**X 的 `search` 默认 `--product top`（热门），不是最新。**实测同一个词：默认返回 7月2日、7月22日、**5月24日**的推文；加 `--product live` 返回的全是当天几分钟前的。

**用户问「最新」「最近」「今天」时，漏掉 `--product live` 等于交付错误信息。**`--product live` 已经写死在上面的命令里，不要图省事删掉。

**抖音搜索结果没有任何时间字段**（只有 desc、author、url、plays、likes、comments、shares）。用它回答「最近抖音上怎么说」时，**必须说明无法证明时效**，不要默认它是新的。

公众号走搜狗源，返回的 `publish_time` 可信；但 URL 是搜狗跳转链，`fetch.sh` 取正文前先确认能跳到 mp.weixin.qq.com。

X 首选 OpenCLI 而非 ego-browser：实测它返回的是六到八个字段的结构化记录，而浏览器整页快照要拉回大量导航与侧栏。ego-browser 只在 OpenCLI 失效时退化使用。

## ego-browser 纪律

- **一个用户目标只开一个 task space。**后续追问、纠正、重试、验证都复用同一个，即使你以为任务已经结束。只有用户明确开启不相关的新目标才新建，且要说明为什么。按子步骤各建一个是错的。
- **一个 heredoc 写完整件事。**ego 是 code base 不是 CLI base：它把能力包成 JS 函数让你组合，官方基准是复杂任务比 CLI 模式快 2.5 倍、工具调用次数远少。「先打开页面、看一眼、再取内容」拆成两轮，正是它设计上要消灭的循环。
- **收尾必须调 `completeTaskSpace(id, { keep: false })`，且独占最后一个 heredoc。**实测（2026-07-29 对照实验）：**每个 agent space 底层就是一个独立浏览器窗口**，complete 会连窗口一起回收；不调则窗口永久残留，用户会在 Mission Control 里看到窗口越堆越多。只有用户明确要求留页面、或需要用户在该页面手动操作时才 `keep: true`。
  这条只管 task space。用户看到的空白窗口还有另一个来源，且 complete 回收不到，见下方「OpenCLI 的容器窗口」——别把它误判成 task space 没收尾。
- **禁止用 CDP 关别的 space 的 target。**在 task space 里调 `cdp('Target.closeTarget', …)` 关跨 space 的标签，实测**直接让 ego lite 主进程 SIGSEGV 崩溃**（2026-07-30，`EXC_BAD_ACCESS` at `0xefefefefefeff087`，use-after-free 特征），用户正在用的标签全部丢失。`cdp('Target.getTargets')` 只读可用，但**拿到 targetId 也不许去关**。关标签只用 `closeTab(id)`，且只关本 space 自己的。
- **临时页随手关**（`closeTab(id)`），别攒到最后。搜索结果页、交叉验证页都算临时页。
- **不要用 `open -a` 拉起浏览器**，交给 ego-browser 自己管生命周期。
- **「user is controlling」是硬停止**，不是要绕开的障碍：用户主动收回了控制权，通常意味着当前做法有问题。只能问用户并等待，不得重试、不得 `takeOverTaskSpace` 自行夺回。

## OpenCLI 与 ego-browser 的分工

**默认规则：OpenCLI 优先，走不通才降级到 ego-browser。**OpenCLI 一条命令拿结构化结果，token 比开浏览器抓页面少一个数量级。

但**先判断有没有适配器再决定试不试**，别对着长尾站点空试一轮：

| 情况 | 怎么走 |
|---|---|
| 站点有适配器，**且有你要的那个子命令** | **先 OpenCLI**，报错或返回空再降级 ego-browser |
| 站点有适配器，**但没有你要的子命令** | **直接 ego-browser**。例：`wechat-channels` 只有 `login/publish/whoami`，读不了内容 |
| 无适配器（`opencli <站点>` 报 `error: unknown command`） | **直接 ego-browser**，不必先试 OpenCLI |
| 要交互：登录、扫码、验证码、多步表单、跨页面组合 | **直接 ego-browser**。OpenCLI 是单命令模型，做不了来回交互 |

**判据是「所需子命令存不存在」，不是「站点名在不在列表里」。**先跑 `opencli <站点> --help` 看有没有你要的动作，别凭站点名推断能力。`opencli list` 列全部站点。

子命令标了 `[write]` 的（post、publish、like、follow、delete 等）**一律不碰**，除非用户在当次对话里明确要求发布或互动。

`AUTH_REQUIRED` 是例外，**不算走不通**，换 ego-browser 一样没登录，降级毫无意义。但也**不要直接叫用户扫码**——它可能是 profile 选错、会话过期或适配器误判。先跑 `opencli <平台> whoami` 核实：

- 返回账号 → 登录态在，问题出在命令用法或适配器，别去打扰用户
- 返回未登录 → 才请用户在 ego lite 里扫码，然后重试**同一条**命令
- 返回 `error: unknown command 'whoami'` → 该适配器没有账号体系（公众号走搜狗源就是这样），别把它当未登录去叫用户扫码

其 Browser Bridge 扩展装在 ego lite 的 Profile 3，通过 `ws://localhost:19825/ext` 连本地 daemon（不是 native messaging，所以装在哪个 Chromium 都能连）。**ego lite 没运行时扩展必然断连**；确认连通用下方「探活」，不要急着重装。

## OpenCLI 的容器窗口

**OpenCLI 的命令会开普通 Chrome 窗口，而且关不掉，只能靠不触发。**它绕过 ego 的 Space 机制，`completeTaskSpace()` 回收不到——别把它留下的空白窗口误判成 task space 没收尾。`--window background` 只管抢不抢焦点，消不掉窗口本身。机制细节与 role 分工见 `references/opencli-windows.md` 。

**探活用无窗口通道，不要用 `opencli doctor`。**doctor 每跑一次就在用户面前弹一个前台空白窗口并永久留下。改用下面这条，实测 `{"ok":true,"data":[]}` 且窗口数不变（走完 daemon → WebSocket → 扩展 → 回程，不解析 tab、不建 lease）：

```bash
curl -sS -H 'X-OpenCLI: 1' -H 'Content-Type: application/json' \
  --data '{"id":"probe-'$RANDOM'","action":"cookies","session":"health-probe","surface":"browser","domain":"opencli-probe.invalid","timeout":10,"deadlineAt":'$(python3 -c 'import time;print(int(time.time()*1000)+15000)')'}' \
  http://127.0.0.1:19825/command
```

OpenCLI 的登录态判断比读页面文字准，别用「页面上有内容」推断已登录。

## OpenCLI 失败了，先判断层级再决定换不换

OpenCLI 要过四层依赖，ego-browser 只过前两层——**ego-browser 的依赖是 OpenCLI 依赖的真子集**。所以：

- **L3/L4 症状 → 上 ego-browser，别放弃。**探活 curl 返回非 `ok:true` 是 L3（daemon/扩展）；探活通了但取数为空、字段缺失、结构变了是 L4（适配器）。这两层最容易坏，也恰好是 ego-browser 不依赖的。
- **L1/L2 症状 → 真没路，别浪费一轮。**ego lite 进程没起或崩了是 L1；`AUTH_REQUIRED`、账号被风控是 L2，换 ego-browser 一样没登录。去处理浏览器或登录态本身。

**别为了分层去跑 `opencli doctor`**——它会留下一个关不掉的空白窗口，用上面那条探活 curl。

哪些 action 是单点、什么才算真正的独立失效域、`references/providers.json` 台账怎么用，见 `references/failure-domains.md` 。一句话预警：**ego lite 一挂，X、小红书、抖音三个平台全部瘫痪，B站只剩搜索。**

## 内容有效性校验（强制）

**抓取工具返回成功不代表拿到了内容。**实测：小红书、B站、YouTube 三个平台，`fetch.sh` 全部返回 `status=ok`，实际内容分别是导航菜单、二进制乱码、页脚版权信息。

交付前逐条过一遍，命中任一条即判定失败，换下一条通道重试：

- 正文疑似只剩导航词（「创作中心」「业务合作」「登录后查看」「About Press Copyright」等）
- 出现连续不可读字符（压缩流未正确解码）
- 拿到了标题但正文为空或不足 100 字，而目标本应是长文
- 内容与请求的 URL 主题明显无关

判定失败时明说「哪条通道、失败形态是什么」，不要把垃圾当结果交出去。

## 通道还活着吗

怀疑某条通道过时或环境坏了，别逐条手试，跑自检：

```bash
bash scripts/selftest.sh          # 零副作用：命令存在性 + 探活 + 登录态 + 子命令是否还在
bash scripts/selftest.sh --live   # 额外发一条最小真实查询；会留容器窗口、耗额度，仅排查用
```

默认模式不发任何平台请求，可以随时跑。失败项按 `references/failure-domains.md` 的分层判据处理。

## 参考文件（按需读，别预先全读）

| 文件 | 什么时候读 |
|---|---|
| `references/failure-domains.md` | OpenCLI 失败要判层级、评估某条通道值不值得加、想知道哪些 action 是单点 |
| `references/opencli-windows.md` | 用户抱怨又多了空白窗口、或你想找办法关掉它们 |
| `references/youtube-subtitles.md` | 真要下 YouTube 字幕时 |
| `references/providers.json` | 算失效域集中度、增删通道时同步台账（无执行器，不参与运行时路由） |

## 站点经验

开工前查、收工写回：

```bash
node scripts/match-site.mjs "<用户输入或目标域名>"
```

验证过的抓取模式写回 `~/.agents/data/site-patterns/<域名>.md`（`references/site-patterns` 是它的软链）。数据在 skill 目录之外，增删 skill 不影响积累。

## 免安装接口

**aihot（AI 资讯聚合）** — 匿名只读，无需 Key。它已聚合 X、微信公众号、RSS、官方博客数百个信源并由 LLM 打分精选，问「AI 圈最近怎么样」直接调它，不要自己去抓 X。

**优先不等于取代**，以下场景仍去源头：深挖具体话题（它只有摘要级 → 豆包）；看特定人的推文（编辑筛选不保证覆盖 → `opencli twitter tweets <用户名>`）；分钟级突发（它有采集打分周期 → X `--product live`）；非 AI 领域（它只做 AI 资讯）。正确用法是**「aihot 发现 → 原文核实」两段式**：它是单一编辑管道（作者的信源清单 + 打分口味），条目也不带发布时间字段，引用具体事实或时间点前必须回它给的原文 URL 核对。

```bash
curl -fsSL "https://aihot.virxact.com/api/v1/items?mode=selected&window=24h&limit=10"
curl -fsSL "https://aihot.virxact.com/api/v1/dailies/latest"     # 最新日报
curl -fsSL "https://aihot.virxact.com/api/v1/selected/snapshot"  # 全量快照，后续用 changes 增量
```

字段与错误码见 `https://aihot.virxact.com/openapi-v1.json` 。

## Agent-Reach 提供的通道

Agent-Reach 是**选型与体检层**，不是包装层——它负责「哪条路现在能走」，读取仍由上游工具直接完成。本文负责「什么情况下走哪条、拿回来的东西算不算数」，两者不重复。

它的 skill 已禁用（description 与本文正面抢触发词）。命令参考仍可直接读 `~/.agents/skills/agent-reach/references/*.md`。

**运维注意**：每次跑 `agent-reach install` 或 `update` 都会重建两份实体 skill 并撤销禁用，跑完必须复原，否则它又开始抢触发词：

```bash
trash ~/.claude/skills/agent-reach && ln -s ../../.agents/skills/agent-reach ~/.claude/skills/agent-reach
# 再用 skill-manager 禁用：/skill-manager disable agent-reach
```

`skill-manager doctor` 把它报成「来源未登记」是**预期状态，不要去 trace 补录**——它的 SKILL.md 由 `agent-reach` 自己生成和覆盖，补进去的元数据下次 install 就没了。版本跟 `agent-reach --version` 走。

### Exa 语义搜索

```bash
mcporter call 'exa.web_search_exa(query: "<词>", numResults: 3)'
```

免 Key。返回标题、URL、正文 highlights，不用再 fetch 一次原页，是英文技术类问题的首选。

## 豆包搜索（中文全网搜索主干）

```bash
mcporter call 'huashu-doubao-search.doubao_search(query: "<词>", count: 5, max_age_days: 7)'
```

2026-07-29 实测接入（经 `alchaincyf/huashu-doubao-search` MCP，走 mcporter stdio，与 Exa 同模式）。返回千字级正文摘要 + 发布时间到秒 + 每条 token 计数，字节系信源（今日头条正文高频返回）。

- **查「最新/最近」必须带 `max_age_days`**——它是纯代码过滤不花钱，实测精准
- 不查时效就省掉该参数，别把过滤当默认
- `snippet_length`（50-2000）控制每条摘要长度，深读调大、扫一眼调小
- **额度 500 次/月**（global/custom 共用），一次调用算一次，日常够用但别拿它当爬虫轮询
- Key 在 `~/.config/doubao-search.key`（600 权限）与 mcporter env，控制台改 Key 后两处都要换
- 中文实时话题它优先于 WebSearch/Exa；英文技术文档仍走 Exa

## 未接入

装好后回本文更新对应行，不要另起 skill：

- **Agent-Reach 的其余渠道** — Reddit、Facebook、Instagram、LinkedIn、雪球、小宇宙播客。用户明确不用，**不要主动提议安装**。哪天真需要再查 `agent-reach install --channels=<名>`。

**接入原则：全部装成 CLI 或 HTTP API 调用，一个都不注册成 skill。**只有注册成 skill 才会争抢触发词、常驻占用上下文。能力从本文调用，触发权只留给本文。

## 依赖

- `fetch.sh` 属于 Waza `read` skill（`~/.agents/skills/read/scripts/`）。该 skill 当前处于禁用状态，但脚本文件仍在、可直接调用。若 `read` 被删除，此路径失效，需改用其他静态抓取方式。
- `ego-browser` 命令由 ego lite 提供。
- `agent-reach`、`yt-dlp`、`bili` 装在 uv tool 隔离环境（`uv tool list` 可查，`uv tool uninstall <名>` 卸载），可执行文件在 `~/.local/bin/`。
- `mcporter` 是 Homebrew 装的，Agent-Reach 只往它的 home scope 加了一条 Exa server，没有重装。
