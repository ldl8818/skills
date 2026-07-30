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
  version: "1.6.3"
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
| 公众号、博客、文档、新闻 | `bash <read-skill>/scripts/fetch.sh <url>` |
| 六大常用平台 | 见下方「常用六平台」 |
| 需要交互、登录、自由探索的长尾站点 | ego-browser |

浏览器一律用 **ego-lite**。完整 API 见 `~/.agents/skills/ego-browser/SKILL.md`，下面只列最容易违反的纪律。

## 常用六平台

用户日常只用这六个：**X、YouTube、小红书、B站、公众号、抖音**。以下命令 2026-07-29 全部实测通过，可直接抄，不要自己另发明用法。OpenCLI 系命令保留 `--window background`：适配器命令的默认值本来就是 background，但默认值是 per-command 可声明的（`cmd.defaultWindowMode ?? 'background'`），显式写上防某个适配器单独声明 foreground。它只管抢不抢焦点，**消不掉窗口本身**，见下方「OpenCLI 的容器窗口」。

**搜索命令拿回来的是列表，不是正文。**除 B站/公众号外，取正文都要拿列表里的 id 或 URL 再发一条命令。把搜索结果当正文交付是已经犯过的错。

| 平台 | 搜索（拿列表） | 取正文（拿到 id/URL 后） |
|---|---|---|
| **X** | `opencli twitter search "<词>" --product live -f yaml --limit N --window background` | 长文 `opencli twitter article <tweet-id>`；整串 `thread <tweet-id>`；某人时间线 `timeline <用户名>` |
| **YouTube** | `yt-dlp "ytsearch5:<词>" --flat-playlist --print "%(title)s \| %(channel)s \| %(duration_string)s \| %(url)s"` | 字幕见下方「YouTube 字幕」 |
| **小红书** | `opencli xiaohongshu search "<词>" -f yaml --limit N --window background` | **`opencli xiaohongshu note <note-id>`**；评论 `comments <note-id>` |
| **B站** | `bili search "<词>" --type video -n 5`（免登录，最省） | 字幕 `opencli bilibili subtitle <BV号>` |
| **公众号** | `opencli weixin search "<词>" -f yaml --limit N --window background` | `bash ~/.agents/skills/read/scripts/fetch.sh <url>` |
| **抖音** | `opencli douyin search "<词>" -f yaml --limit N --window background` | 搜索结果**没有发布时间**，见下方「时效性」 |

### 时效性：默认排序不是按时间

**X 的 `search` 默认 `--product top`（热门），不是最新。**实测同一个词：默认返回 7月2日、7月22日、**5月24日**的推文；加 `--product live` 返回的全是当天几分钟前的。

**用户问「最新」「最近」「今天」时，漏掉 `--product live` 等于交付错误信息。**这条已经犯过，写死在上面的命令里了，不要图省事删掉它。

**抖音搜索结果没有任何时间字段**（只有 desc、author、url、plays、likes、comments、shares）。用它回答「最近抖音上怎么说」时，**必须说明无法证明时效**，不要默认它是新的。

公众号走搜狗源，返回的 `publish_time` 可信；但 URL 是搜狗跳转链，`fetch.sh` 取正文前先确认能跳到 mp.weixin.qq.com。

X 首选 OpenCLI 而非 ego-browser：实测它返回的是六到八个字段的结构化记录，而浏览器整页快照要拉回大量导航与侧栏。ego-browser 只在 OpenCLI 失效时退化使用。

## ego-browser 纪律（违反过，逐条记账）

- **一个用户目标只开一个 task space。**后续追问、纠正、重试、验证都复用同一个，即使你以为任务已经结束。只有用户明确开启不相关的新目标才新建，且要说明为什么。按子步骤各建一个是错的。
- **一个 heredoc 写完整件事。**ego 是 code base 不是 CLI base：它把能力包成 JS 函数让你组合，官方基准是复杂任务比 CLI 模式快 2.5 倍、工具调用次数远少。「先打开页面、看一眼、再取内容」拆成两轮，正是它设计上要消灭的循环。
- **收尾必须调 `completeTaskSpace(id, { keep: false })`，且独占最后一个 heredoc。**实测（2026-07-29 对照实验）：**每个 agent space 底层就是一个独立浏览器窗口**，complete 会连窗口一起回收；不调则窗口永久残留，用户会在 Mission Control 里看到窗口越堆越多——已因此被用户指出过一次。只有用户明确要求留页面、或需要用户在该页面手动操作时才 `keep: true`。
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

其 Browser Bridge 扩展装在 ego lite 的 Profile 3，通过 `ws://localhost:19825/ext` 连本地 daemon（不是 native messaging，所以装在哪个 Chromium 都能连）。**ego lite 没运行时扩展必然断连**；确认连通用下方「探活」，不要急着重装。

## OpenCLI 的容器窗口（用户已投诉，2026-07-30 定案）

**OpenCLI 绕过 Space 机制**——它是标准 Chrome 扩展，用 tabs/windows API 开普通窗口，不受 ego 的 Space 隔离约束。扩展按 role 维护两个「容器窗口」（`ownedContainers`，`chrome.windows.create` 建 1280x900 普通窗口），role 由命令的 surface 决定：

| 容器 role | 谁触发 | 默认焦点 | 橙色「OpenCLI Browser」标签组 | 注册表丢失后 |
|---|---|---|---|---|
| `automation` | 适配器命令（六平台 search 等） | background | 无 | **无法再识别，下条命令新建 → 孤儿累积** |
| `interactive` | `opencli browser ...`、`opencli doctor` | **foreground（抢焦点弹窗）** | 有 | 能按标签组标题全局找回，有限自愈 |

**这些窗口关不掉，只能靠不触发。**扩展在 `releaseLease()` 里把最后一个标签导航回 `about:blank` 当可复用占位符，全文件没有一处 `chrome.windows.remove`；`opencli browser <sess> close`、`tab close` 实测都只释放 lease，窗口不动；占位标签在 `tab list` 里根本不出现。

**探活用无窗口通道，不要用 `opencli doctor`。**doctor 硬编码 `surface: 'browser'` 且没有 `--window` 选项，每跑一次就在用户面前弹一个前台空白窗口并永久留下。改用下面这条，实测 `{"ok":true,"data":[]}` 且窗口数不变（走完 daemon → WebSocket → 扩展 → 回程，不解析 tab、不建 lease）：

```bash
curl -sS -H 'X-OpenCLI: 1' -H 'Content-Type: application/json' \
  --data '{"id":"probe-'$RANDOM'","action":"cookies","session":"health-probe","surface":"browser","domain":"opencli-probe.invalid","timeout":10,"deadlineAt":'$(python3 -c 'import time;print(int(time.time()*1000)+15000)')'}' \
  http://127.0.0.1:19825/command
```

`opencli profile list` 和 `opencli daemon status` 同样零窗口，但它们只读 daemon 记忆里的连接状态，不做端到端往返，只能用来看「daemon 起没起」。确需 doctor 的详细诊断时，前面加 `OPENCLI_WINDOW=background`（`sendCommandRaw` 读这个环境变量）压掉抢焦点——窗口仍会创建并留下。

OpenCLI 的登录态判断比读页面文字准，别用「页面上有内容」推断已登录。

## 候选表与健康账本

`providers.json` 是路由的**唯一权威定义**：18 个 action 的命令模板、字段裁剪、失效域、校验器都在里面。上面的六平台速查表是它的人类可读摘要——**改动一律先改 `providers.json`**，否则两处必然漂移。

### 失效域集中度（把候选表结构化后算出来的）

| 事实 | 数字 |
|---|---|
| 有真降级（≥2 个不同失效域）的 action | **2 / 18（11%）** |
| 单点压在 `ego-lite-browser` 上的 action | **8 个** |

那 8 个是：X 的 search / article / thread、小红书的 search / detail / comments、抖音 search、B站 subtitle。

**ego lite 一挂，X、小红书、抖音三个平台全部瘫痪，B站只剩搜索。**

### 但 ego-browser 仍然是有效兜底

失效域不是一整块，OpenCLI 要过四层，ego-browser 只过两层：

```
L1  ego lite 浏览器进程          ← 两者共享
L2  Profile 登录态 / 账号风控     ← 两者共享
L3  OpenCLI daemon + 扩展         ← 只有 OpenCLI 依赖
L4  OpenCLI 站点适配器逻辑        ← 只有 OpenCLI 依赖
```

**ego-browser 的依赖是 OpenCLI 的真子集**，所以 L3、L4 故障时它照样能取——而这两层恰恰最容易坏（适配器跟不上平台改版、扩展断连、daemon 没起）。

| OpenCLI 失败形态 | ego-browser 能救 |
|---|---|
| 返回空、字段缺失、结构变了（L4） | ✅ 直接读页面 |
| `Extension: not connected`、daemon 无响应（L3） | ✅ 不走那条通道 |
| `AUTH_REQUIRED`、账号被风控（L2） | ❌ 换它也一样没登录 |
| ego lite 进程没起或崩了（L1） | ❌ 它也要这个浏览器 |

**所以 OpenCLI 失败时先判断层级**：L3/L4 症状就上 ego-browser，别放弃；L1/L2 症状才是真没路，去处理浏览器或登录态本身。

怎么区分：上方「探活」那条 curl 返回非 `ok:true` 是 L3；探活通了但取数为空是 L4；平台报 `AUTH_REQUIRED` 是 L2。**别为了分层去跑 `opencli doctor`**——它会留下一个关不掉的空白窗口。

### 什么才算真正的独立失效域

判据是**不经 ego lite、不共享登录态**（即绕开 L1+L2），不是「换了个工具名」。目前只有两处：B站搜索（`bili` 直连 ⇄ OpenCLI）、任意网页（`fetch.sh` 本机 ⇄ Jina Reader 远端）。

X、小红书、抖音在 L1/L2 层仍是单点，这是客观缺口——需要的是自己管 cookie、不走 ego lite 的独立实现。

### 健康账本

`~/.agents/data/lookup-health.json`，与 site-patterns 同级、在 skill 目录之外，增删 skill 不影响积累。

**只记运行状态，不记查询词、正文、账号。**条目 key 是 `<action>::<provider_id>::<执行环境>`：

```json
{
  "x/search::opencli-twitter-search::darwin-local": {
    "last_success": "2026-07-29T16:44:00Z",
    "last_failure": null,
    "last_failure_class": null,
    "consecutive_failures": 0,
    "cooldown_until": null
  }
}
```

带执行环境是因为**同一条命令在不同环境下结果不同**：OpenCLI 在 Codex 的只读沙箱里必然 `BROWSER_CONNECT` 失败，在这个会话里却正常。不区分环境就会把某个 shell 的失败写成全机事实。

账本的作用是**跨会话故障记忆和熔断，不是日常提速**：

- 静态 `priority` 仍是主序，账本只在连续失败 3 次后开熔断、冷却 30 分钟
- **只有存在其他 active 且失效域不同的候选时才熔断**——单候选动作熔断等于自断退路，只记状态
- `auth_required` **不计入**熔断计数，它是登录态问题不是通道故障
- 不做「最近成功优先」全量重排：排第一的被调用最多、成功时间自然最新，备用的因没被调用而越来越旧，那衡量的是使用频率不是可靠性

## 内容有效性校验（强制）

**抓取工具返回成功不代表拿到了内容。**实测：小红书、B站、YouTube 三个平台，`fetch.sh` 全部返回 `status=ok`，实际内容分别是导航菜单、二进制乱码、页脚版权信息。

交付前逐条过一遍，命中任一条即判定失败，换下一条通道重试：

- 正文疑似只剩导航词（「创作中心」「业务合作」「登录后查看」「About Press Copyright」等）
- 出现连续不可读字符（压缩流未正确解码）
- 拿到了标题但正文为空或不足 100 字，而目标本应是长文
- 内容与请求的 URL 主题明显无关

判定失败时明说「哪条通道、失败形态是什么」，不要把垃圾当结果交出去。

## 站点经验

开工前查、收工写回：

```bash
node scripts/match-site.mjs "<用户输入或目标域名>"
```

验证过的抓取模式写回 `~/.agents/data/site-patterns/<域名>.md`（`references/site-patterns` 是它的软链）。数据在 skill 目录之外，增删 skill 不影响积累。

## 免安装接口

**aihot（AI 资讯聚合）** — 匿名只读，无需 Key。它已聚合 X、微信公众号、RSS、官方博客数百个信源并由 LLM 打分精选，问「AI 圈最近怎么样」直接调它，不要自己去抓 X。

**优先不等于取代**，以下场景仍去源头：深挖具体话题（它只有摘要级 → 豆包）；看特定人的推文（编辑筛选不保证覆盖 → `twitter timeline`）；分钟级突发（它有采集打分周期 → X `--product live`）；非 AI 领域（它只做 AI 资讯）。正确用法是**「aihot 发现 → 原文核实」两段式**：它是单一编辑管道（作者的信源清单 + 打分口味），条目也不带发布时间字段，引用具体事实或时间点前必须回它给的原文 URL 核对。

```bash
curl -fsSL "https://aihot.virxact.com/api/v1/items?mode=selected&window=24h&limit=10"
curl -fsSL "https://aihot.virxact.com/api/v1/dailies/latest"     # 最新日报
curl -fsSL "https://aihot.virxact.com/api/v1/selected/snapshot"  # 全量快照，后续用 changes 增量
```

字段与错误码见 `https://aihot.virxact.com/openapi-v1.json` 。

## Agent-Reach 提供的通道

Agent-Reach 是**选型与体检层**，不是包装层——它负责「哪条路现在能走」，读取仍由上游工具直接完成。本文负责「什么情况下走哪条、拿回来的东西算不算数」，两者不重复。

它的 skill 已禁用（`description` 写 "MUST USE ... anything on the internet"，与本文正面抢触发词；且其 standing rules 要求每次播报后端、收尾推销更新，纯噪音）。命令参考仍可直接读 `~/.agents/skills/agent-reach/references/*.md`。

**运维注意**：每次跑 `agent-reach install` 或 `update` 都会重建两份实体 skill 并撤销禁用。跑完必须补这两步：

```bash
trash ~/.claude/skills/agent-reach && ln -s ../../.agents/skills/agent-reach ~/.claude/skills/agent-reach
# 再用 skill-manager 禁用：/skill-manager disable agent-reach
```

`skill-manager doctor` 把它报成「来源未登记」是**预期状态，不要去 trace 补录**：它的 SKILL.md 由 `agent-reach` 自己生成和覆盖，补进去的元数据下次 install 就没了。它的版本跟 `agent-reach --version` 走。

### YouTube 字幕

```bash
# 1) 下载
yt-dlp --write-auto-sub --sub-lang "en,zh-Hans" --skip-download --sub-format vtt -o "$HOME/tmp/%(id)s" "<URL>"

# 2) 清洗后再读，别直接读 .vtt
sed -e '/-->/d' -e '/^WEBVTT/d' -e '/^Kind:/d' -e '/^Language:/d' -e 's/<[^>]*>//g' \
    "$HOME/tmp/<id>.en.vtt" | awk 'NF' | awk '!seen[$0]++'

# 3) 读完删掉，别留在 ~/tmp
trash "$HOME/tmp/<id>".*.vtt
```

**第 2 步不是可选的。**自动字幕带内联时间码和滚动重复（`We're<00:00:19.039><c> no</c>` 这种），实测 14807 字节清洗后只剩 1224 字节，**省 92%**。直接读原始 VTT 是在烧上下文。

`Error solving N challenge requests using "node" provider` / `Access to this API has been restricted` 这两条 WARNING **每次都会出现，且不影响字幕**——沙箱开、关两种情况实测都照常拿到中英文 VTT。它只影响需要签名求解的视频流格式，纯下字幕用不到。**不要为它关沙箱，也不要去查 YouTube 侧**，那是白费一轮。

视频没字幕时输出 `There are no subtitles for the requested languages`，是正常结果不是故障（首次实测撞上的是 YouTube 史上第一条视频，它本来就没字幕，别据此判定通道不通）。

B站字幕仍走 `opencli bilibili subtitle`，**不要用 yt-dlp 抓 B站**。

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
- `ego-browser` 命令由 ego lite app 提供。
- `agent-reach`、`yt-dlp`、`bili` 装在 uv tool 隔离环境（`uv tool list` 可查，`uv tool uninstall <名>` 卸载），可执行文件在 `~/.local/bin/`。
- `mcporter` 是 Homebrew 装的，Agent-Reach 只往它的 home scope 加了一条 Exa server，没有重装。
