# 搜索与网页路由

用于全网搜索、AI 资讯、已知网页、本机浏览历史和站点经验。平台内搜索改读 `platform-routing.md`。

## 目录

- [选择入口](#选择入口)
- [结构化结果优先](#结构化结果优先)
- [中文与英文搜索](#中文与英文搜索)
- [AI 资讯](#ai-资讯)
- [读取已知网页](#读取已知网页)
- [本机历史与站点经验](#本机历史与站点经验)
- [时效与原文核实](#时效与原文核实)

## 选择入口

| 目标 | 首选 | 备注 |
|---|---|---|
| 中文全网搜索 | 豆包搜索 | 支持发布时间与天数过滤，月额度有限 |
| 英文、全球、技术论据 | Exa | 返回 highlights，通常不用再抓整页 |
| AI 圈动态 | aihot | 先发现，再回原文核实 |
| 英文搜索兜底 | WebSearch | Exa 无结果或不可用时 |
| 已知博客、文档、新闻 | `fetch.sh` | 静态抓取首选 |
| 自己访问过的页面 | `find-url.mjs` | 查 ego lite、Chrome、Edge 书签与历史 |
| 动态、登录、交互网页 | ego-browser | 长尾站点最后使用 |

## 结构化结果优先

按以下层级拿数据，能停在上一层就不下沉：

1. API／CLI 已结构化字段；
2. 定向正文或目标节点；
3. 整页内容。

对 JSON 结果先裁字段，再放进上下文。只保留回答问题需要的标题、作者、时间、URL、正文摘要和必要指标。

## 中文与英文搜索

英文与技术搜索：

```bash
mcporter call 'exa.web_search_exa(query: "<词>", numResults: 3)'
```

中文搜索：

```bash
mcporter call 'huashu-doubao-search.doubao_search(query: "<词>", count: 5, max_age_days: 7)'
```

- 用户问「最新、最近、今天」时传 `max_age_days`；不要求时效时省略，避免无理由缩窄结果。
- 豆包额度为 500 次/月；不用于轮询或批量爬取。
- Exa 适合英文技术和出处检索；中文实时话题优先豆包。
- 搜索摘要只能支持初筛；引用具体事实时回原始 URL 核实。

## AI 资讯

```bash
curl -fsSL "https://aihot.virxact.com/api/v1/items?mode=selected&window=24h&limit=10"
curl -fsSL "https://aihot.virxact.com/api/v1/dailies/latest"
```

aihot 是单一编辑管道，适合发现，不替代源头：

- 特定人物动态：回 X 或其官方来源；
- 分钟级突发：回实时平台搜索；
- 具体事实和时间点：打开条目原文核对；
- 非 AI 领域：改用豆包、Exa 或 WebSearch。

## 读取已知网页

静态页面首选：

```bash
bash ~/.agents/skills/read/scripts/fetch.sh <url>
```

失败时先判形态：反爬、空壳、动态渲染、登录态、二进制或内容无关。普通公开 URL 可用 Jina Reader 作为远端降级，但 URL 会发送给第三方，敏感和内网页面禁用：

```bash
curl -fsSL "https://r.jina.ai/<url>"
```

`opencli web read` 不作默认入口：当前实现依赖浏览器，默认创建输出目录并下载图片。只有确需 iframe、等待选择器或渲染诊断时，才在理解窗口代价后使用 `--stdout` 和关闭图片下载；普通动态网页优先 ego-browser。

抓取结果必须通过 `SKILL.md` 的内容有效性校验。公众号搜狗跳转链是已知例外，必须读 `weixin-article.md`。

## 本机历史与站点经验

公网搜不到的内部后台、内网域名和自己访问过的页面，先查本机：

```bash
node scripts/find-url.mjs <关键词> [--browser ego|chrome|edge] [--only bookmarks|history] [--since 7d]
```

已知 URL 或域名开工前匹配站点经验：

```bash
node scripts/match-site.mjs "<用户输入或目标域名>"
```

找不到就如实说明，不猜地址。验证过的模式写回 `~/.agents/data/site-patterns/<域名>.md`，不得写凭据和私人正文。

## 时效与原文核实

- 搜索结果必须带可核对的发布时间，才能回答「最近」。
- 服务端窗口只能证明候选经过时间筛选；不带单条时间字段时，不能编造具体时点。
- 热门排序不等于最新排序。
- 聚合器、搜索摘要和第三方转述不等于原文；重要事实至少打开一个源头。
