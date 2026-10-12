# 搜索与网页路由

用于全网搜索、AI 资讯、已知网页、本机历史和站点经验。平台内搜索读 [platform-routing.md](platform-routing.md)。

## 选择入口

| 目标 | 路径 |
|---|---|
| 已指定服务、产品文档、代码仓库 | 专用官方资料／已连接服务／对应 Skill；对版本敏感信息核对当前来源 |
| 普通全网搜索 | 当前 Agent 已有搜索能力；若已有配置，按语言与覆盖范围选 Exa、豆包等 |
| 中文实时话题 | 能提供可核验时间的搜索服务；已有豆包配置时可用其时效参数 |
| 英文、全球、技术出处 | 已有 Exa 或宿主搜索，回到必要的第一手资料 |
| AI 圈动态 | aihot 等聚合源发现候选，再核对相关原始出处 |
| 已知静态网页 | 随包 `scripts/fetch.sh` 本地提取 |
| 动态、登录、需交互页面 | 当前 Agent 合适且已授权的浏览器，最后 ego-browser |
| 用户访问过的内部页面 | 用户指明的历史／书签能力；现有 `find-url.mjs` 只查 ego lite |

不要因为一个可选工具缺失就声称不能联网，也不要为了普通检索临时安装整个工具链。宿主和用户明确的来源／浏览器要求优先。

## 结构化结果与足够性

优先 API／CLI 字段，再取定向正文或节点，最后才读整页。只保留问题需要的标题、作者、时间、URL、相关正文和必要指标。

按结果是否覆盖问题决定下一步：完整短帖或足够的官方段落可直接引用；搜索摘要、转述或截断片段只支持发现和有限结论。重要具体事实需要相应源头证据，但不强制同一完整内容重复读取。多来源分析见 [研究综合.md](研究综合.md)。

## 已配置搜索服务示例

下面仅说明参数结构；动态关键词要经结构化参数或安全 argv 传入，不能插入未经转义的调用表达式。

```bash
mcporter call exa.web_search_exa query="<词>" numResults=3
mcporter call huashu-doubao-search.doubao_search query="<词>" count=5 max_age_days=7
```

- 先确认工具存在且参数与当前 schema 一致；未配置时使用宿主搜索，不自动索取新 Key。
- 用户要求最新／最近／今天时使用支持的时效参数，并核对逐条发布时间；未要求时效时不无故缩窄。
- 配额和费用以实际配置与当前服务为准，不把历史月额度写成永久规则；普通检索不变成后台轮询或批量抓取。
- 无匹配、限流、网络失败与结构缺失分别判断；保留已取到的证据，按缺口选择不同覆盖范围的服务。

## AI 资讯

已有 aihot 可作为候选发现来源：

```bash
curl -fsSL "https://aihot.virxact.com/api/v1/items?mode=selected&window=24h&limit=10"
```

聚合器适合发现，不证明实时性或事实本身。人物动态回其公开原始来源，技术变更回官方文档／仓库，非 AI 领域使用合适搜索。单条没有时间字段时不编造发布时间。

## 读取已知网页

从 Lookup 根目录执行：

```bash
bash scripts/fetch.sh "<url>"
```

脚本随 Skill 分发，默认只请求原站、本地提取，不自动安装依赖、不自动发送到第三方。支持 HTML、纯文本与 Markdown；不执行页面 JS，纯文本中的代码标签保持字面含义。

`--prefer auto|readability|stdlib` 选择提取器，`--max-output-chars N` 控制完整 stdout 预算（默认 40,000 字符，兼容 `--max-chars`）。stdout 是正文 Markdown，`Source` 记录最终重定向 URL；stderr 提供 `provider: lookup/fetch` 的 JSON 状态、提取器、媒体类型、截断及错误字段；成功／partial 还包含原始 `requested_url`、最终 `final_url` 和实际 UTC 抓取时间 `fetched_at`，后者不代表文章发布时间。exit 0 表示完整提取，3 表示已有正文但截断，1 表示错误；参数错误为 2。保留三路结果，不把 exit 3 的有效正文丢掉，也不把提取成功当内容真实性证明。

失败时区分反爬、空壳、动态渲染、认证、非文本和内容无关。静态公开 URL 确认允许外发时可以考虑 Jina；认证、敏感或内网链接不得发送：

```bash
curl -fsSL "https://r.jina.ai/<公开url>"
```

动态或需登录页面优先使用当前宿主合适浏览器，再用正式 ego-browser；仅在独立路径确有帮助时换工具。OpenCLI `web read` 是否创建文件、下载图片、需要浏览器由当前帮助确认；普通阅读不默认归档。

公众号搜狗跳转另读 [weixin-article.md](weixin-article.md)，不要把中转验证页当正文。

## 本机历史与站点经验

用户明确找访问过的页面时，可运行：

```bash
node scripts/find-url.mjs "<关键词>" --since 7d
node scripts/match-site.mjs "<域名或任务>"
```

`find-url.mjs` 仅支持 ego lite，默认只读 `Local State` 中 `profile.last_used` 指向的一个 Profile，未设置则用 `Default`。用户指定其他已登记 Profile 时用 `--profile "<目录名>"`；这里是本机 Profile 目录名，不是 OpenCLI 别名。不为了查不到就遍历所有 Profile，也不读取 Cookie。

`--json` 返回 `profile / bookmarks / history / more_available`；stderr 的 `provider: lookup/find-url` 状态区分 `ok / empty / partial / error`。默认 `--limit 20` 是两个集合共享的总额度，书签优先、历史占用剩余额度；只需历史时显式用 `--only history`。普通 top-N 成功仍可带 `more_available`，`--limit 0` 总共最多返回 1,000 项，触及该上限且仍有结果才是 partial / exit 3。关键词按字面 AND 匹配；ASCII 大小写不敏感，非 ASCII 字符按原字面匹配。数据库读取失败或文件缺失不是无匹配；按实际状态说明范围，不猜地址、不把内部关键词发送公网。其他浏览器的历史要发现独立的已授权能力。

`match-site.mjs` 对真实 URL 按主机／子域边界匹配，真实主机优先于文本别名；不要因相似域名或查询参数里的别名命中就套用站点规则。站点经验在 `~/.agents/data/site-patterns/`，只保存验证过的公开结构和版本／日期。先匹配已有经验即可，不把一次失败写成永久封禁，不记录私人正文或凭据。

## 时效与来源

- 最新排序、可见发布时间、服务端时间窗口分别说明；热门不等于最新，窗口过滤不等于每条时间已核实。
- 缺失时间、作者、正文或访问定位时标记未知／部分；不要为了完整格式虚构。
- 把本次实际读取、来源自身宣称和推理区分开。研究涉及多种证据时按问题组合，不固定来源数量或阶段。
