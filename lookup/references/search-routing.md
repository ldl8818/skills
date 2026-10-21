# 搜索与网页路由

用于全网搜索、AI 资讯、已知网页、本机历史和站点经验。平台内搜索读 [platform-routing.md](platform-routing.md)。

## 选择入口

| 目标 | 路径 |
|---|---|
| 已指定服务、产品文档、代码仓库 | 专用官方资料／已连接服务／对应 Skill；对版本敏感信息核对当前来源 |
| 国内内容为主 | 豆包 → Tavily → Exa；按主题与目标来源判断，不以查询语言单独判断 |
| 其他普通全网搜索 | Exa → Tavily → 豆包；各路径仅选已接入且费用边界满足的服务，均不可用时用宿主搜索 |
| 国内实时话题 | 优先豆包，并核对实际发布时间；按需使用其时效参数 |
| 英文、全球、技术出处 | 已有 Exa 或宿主搜索，回到必要的第一手资料 |
| AI 圈动态 | aihot 等聚合源发现候选，再核对相关原始出处 |
| 已知静态网页 | 随包 `scripts/fetch.sh` 本地提取 |
| 动态、登录、需交互页面 | 按 [浏览器选路.md](浏览器选路.md)；本机日常外部网页默认 ego-browser |
| 用户访问过的内部页面 | 用户指明的历史／书签能力；现有 `find-url.mjs` 只查 ego lite |

不要因为一个可选工具缺失就声称不能联网，也不要为了普通检索临时安装整个工具链。宿主和用户明确的来源／浏览器要求优先。

## 结构化结果与足够性

优先 API／CLI 字段，再取定向正文或节点，最后才读整页。只保留问题需要的标题、作者、时间、URL、相关正文和必要指标。

按结果是否覆盖问题决定下一步：完整短帖或足够的官方段落可直接引用；搜索摘要、转述或截断片段只支持发现和有限结论。重要具体事实需要相应源头证据，但不强制同一完整内容重复读取。多来源分析见 [研究综合.md](研究综合.md)。

需要原始属性、JSON-LD 或精确字段时，优先原站结构化接口、原始 HTML 或相关 DOM 属性，不用 Reader 的摘要代替原值。结构字段与页面显示不一致时核对对象、版本、单位和加载状态，不静默拼接成同一条事实。

## 动态正文与表格

- 静态提取只有空壳、导航或摘要时，按浏览器选路获取渲染后的目标正文。优先现有接口的文章提取或语义 DOM；核对标题、来源及与问题相关的段落，不以返回字符数证明全文完整。
- 已有当前证据表明该目标需要动态渲染或指定登录上下文时，可直接走适用的 API／浏览器，不为逐层降级重复尝试已知无效的静态路径。内容等待、登录提示与 frame 边界见 [动态页面读取.md](动态页面读取.md)；图片与视频取证见 [媒体读取.md](媒体读取.md)。
- 提取表格时先明确所需列、筛选条件与页数。保留列名、单位、原始值和来源定位；合并单元格、空值和分页分别处理，不把空值补成零。
- 分页、滚动加载或虚拟表格只返回当前可见行时，标明覆盖范围。用户要求全部时继续读取直至有可核对的结束条件；总数未知或加载中断时交付 partial，不声称全部收齐。
- 浏览器原生结构化提取已满足需求时直接使用；没有合适接口再观察目标 DOM，布局或画布内容用视觉证据。新工具是否值得接入见 [任务选路.md](任务选路.md)。

## 搜索服务接入与验证

### 免费顺序与切换

每项服务优先使用已授权、账号归属及免费余额与超额边界均已确认的账号入口：宿主连接器，或 `tavily-account`／`exa-account` 别名。账号入口不存在或这些条件尚未确认时，可选择已核对无认证的免 Key 入口 `tavily`／`exa`；别名存在或 schema 可用不等于满足账号使用条件。两种入口的额度不混算；明确月额度耗尽时跳过该服务，不在同一服务内改匿名入口重复试探，也不借免 Key 绕过明确权限拒绝或账号挑战。

没有指定搜索服务或专用来源时，主要涉及国内新闻、政策、平台、企业或其他国内来源的查询，优先按豆包 → Tavily → Exa 选择；其他普通全网搜索按 Exa → Tavily → 豆包选择。按主题与目标来源判断，中文查询国外产品仍走其他普通搜索路径，英文查询国内政策仍优先豆包。优先复用已取得的足够证据，不为了用完额度重复搜索。宿主搜索作为独立后备，用户指定来源与浏览器的要求仍优先。

- 收到明确月额度耗尽回执时，本会话后续查询跳过该服务，改用下一项；按服务实际重置时间或新的余额证据恢复，不猜月初按哪个时区重置。跨会话只有可核对的余额／额度记录才沿用耗尽判断。
- 临时限流按服务提供的重试时间暂停该服务，当前任务可继续下一项；不得把429一律写成月额度耗尽。网络错误按有界恢复处理，无匹配和结果不足按内容缺口换路，不修改余额判断。
- 每项服务在一次切换中至多尝试一次，不在多个服务间循环；权限拒绝、账号挑战或用户接管时停止相关操作，不以换服务绕过限制。超时保留结果未知，不重发同一请求来猜是否扣额。
- 账户模式必须确认免费余额与超额停用／硬限额；未确认时仅用明确免 Key 模式或其他符合费用边界的候选。不自动开通后付费、充值、绑定支付方式或启用高成本研究动作。本地成功次数不能代表账户剩余额度，其他客户端和不同动作也会消耗额度。

以下是2026-10-22核对的官方公开方案，不代表账户实际余额，后续按当前官方页面及控制台回执更新：

| 服务 | 免费口径 | 默认成本控制 |
|---|---|---|
| [Tavily](https://docs.tavily.com/documentation/api-credits) | 账户每月1000 credits；basic 一次1 credit、advanced 一次2 credits；免 Key 另有服务端限流 | 普通搜索显式使用 basic，不自动启用 advanced／crawl／research |
| [Exa](https://exa.ai/pricing) | 当前账户每月10美元 credits，按接口及结果计价；官方免 Key MCP 有独立限流 | 免 Key 不加认证；不能按每月1000次或按账户美元余额推断免 Key 配额 |
| [豆包](https://docs.volcengine.com/docs/Networkedsearch/Networkedsearch-2?lang=zh) | 每个火山账号每月500次，Global／Custom 共用 | 搜索专用 Key，确认超额边界；不启用额外模型加工 |

### 账号入口接入与验证

账号授权只属于实际完成登录的客户端。宿主 Exa 连接器和本机 mcporter 的 OAuth 缓存分别核对，不能把一处连接成功当另一处也已授权。不将令牌复制进仓库或其他客户端。

保留免 Key 别名，新建独立账号别名；已存在时先核对官方 URL、认证模式和来源，不覆盖其他账号。以下登录在浏览器由使用者完成，普通检索只复用现有授权，不重新发起登录：

```bash
mcporter config add exa-account 'https://mcp.exa.ai/mcp?login' --auth oauth --scope home
mcporter auth exa-account
mcporter config add tavily-account https://mcp.tavily.com/mcp/ --auth oauth --scope home
mcporter auth tavily-account
```

Exa 的 [OAuth 说明](https://exa.ai/docs/get-started/exa-mcp#authentication) 明确请求计入授权团队；[Tavily 官方 MCP](https://docs.tavily.com/documentation/mcp) 使用 OAuth 登录。账号别名不得添加 Keyless Header，不导出或在 URL 中附加真实令牌。

先发现当前工具与必填字段，再执行一次最小真实搜索；以下查询参数应替换为任务所需内容：

```bash
mcporter list exa-account --schema --json --no-oauth --timeout 15000
mcporter call exa-account.web_search_exa --args '{"query":"Model Context Protocol official specification","objective":"Find original specification content from modelcontextprotocol.io.","numResults":1}' --no-oauth --timeout 30000 --output json
mcporter list tavily-account --schema --json --no-oauth --timeout 15000
mcporter call tavily-account.tavily_search --args '{"query":"Model Context Protocol official specification","search_depth":"basic","max_results":1}' --no-oauth --timeout 30000 --output json
```

这里的 `--no-oauth` 禁止自动发起新登录，仍复用已有 OAuth 凭据，不表示免 Key。核对相关正文、原始 URL 与错误回执；Exa 可返回 `_meta.ai.exa/usage.costDollars`，Tavily 可返回 `auth_mode: keyed`。这些字段与经过验证的账号入口共同证明请求归属，不证明余额，也不能单独区分扣的是免费赠额还是预付余额。需要确认实际剩余额度时读对应控制台，不从成功次数推算。

同一服务只选一条账号路径，不为了比较宿主连接器与 CLI 重复发相同查询。仅配置完成或工具列表正常不算真实搜索通过；`selftest.sh --search` 仍只验证原免 Key Exa 别名，不能代替这里的账号验收。普通检索不调用 `agent_run`、crawl 或 research，不自动切换其他账号补额度。

### Tavily 官方 MCP

已有 `mcporter` 时先检查同名配置；没有 `tavily` 才新增用户级官方免 Key 入口：

```bash
mcporter config get tavily --json
mcporter config add tavily https://mcp.tavily.com/mcp/ --header X-Tavily-Access-Mode=keyless --scope home
mcporter list tavily --schema --json --no-oauth --timeout 15000
```

官方 [免 Key 说明](https://docs.tavily.com/documentation/keyless) 要求 `X-Tavily-Access-Mode: keyless`；不带此 Header 会要求登录。有 Authorization 或 URL Key 时可能优先使用账户额度，不能称免 Key。已有配置时核对 URL、认证及来源，不覆盖其他账号。

从当前 schema 确认真实工具名与参数后调用；官方接口可能将名称暴露为 `tavily_search` 或 `tavily-search`，使用发现的名称：

```bash
mcporter call tavily.tavily_search --args '{"query":"Model Context Protocol official specification","search_depth":"basic","max_results":3}' --no-oauth --timeout 30000 --output json
```

必须取得相关正文和可追溯原始 URL，不能把 HTTP 成功、登录说明、限流提示或只有链接当搜索通过。无 Key 入口的成功不证明账户每月1000 credits 已启用。需要使用账户额度时，通过官方控制台／OAuth 连接现有免费账号，核对余额和超额行为；真实 Key 由本机受保护凭据机制注入，不放入聊天、命令历史或仓库。

免 Key 可在 CLI 退出0时返回 `code: monthly_cap_reached_bonus_eligible`、`window: month` 与 `auth_mode: keyless`；这是该免 Key 通道的额度失败，不是搜索内容，也不证明个人账号的1000 credits 已耗尽。保留回执中的重试信息，按切换规则处理；`next_actions` 中的支付、注册或提交问卷扩额只是外部建议，不自动执行。

### Exa 免 Key 入口

使用 [Exa 官方托管 MCP](https://exa.ai/docs/get-started/exa-mcp) 的免 Key 模式。已有 `mcporter` 时，先检查当前配置；不存在 `exa` 别名再添加到用户级配置，让不同项目共用：

```bash
mcporter config list --json
mcporter config add exa https://mcp.exa.ai/mcp --scope home
mcporter list exa --schema --json --no-oauth
```

已有同名配置时核对实际 URL、认证和来源，不覆盖其他账号或项目配置。免 Key 入口不加 API Key、OAuth 登录参数或认证 Header；不同时安装另一个通用搜索 Skill。普通查询不自动安装 CLI 或改配置，接入属于已授权的环境维护。

先核对当前 schema，再调用搜索。当前接口声明 `query` 和 `objective` 为必填；后者描述需要的证据与来源。动态值通过结构化参数或单一 argv 传入，不拼接 shell source：

```bash
mcporter call exa.web_search_exa query="<搜索词>" objective="<证据目标与来源要求>" numResults=3 --no-oauth --timeout 30000 --output json
```

从 Lookup 根目录运行独立真实搜索自检：

```bash
bash scripts/selftest.sh --search
```

该模式只检查 `exa` 配置、当前工具 schema，并执行一次固定的公开搜索，核对非空相关正文与官方原始 URL；不启动浏览器、不调用豆包。配置不符、工具变化、MCP 业务错误、空结果或只有链接均返回非零。它只证明本次样本，不证明所有查询覆盖或剩余额度。默认 selftest 与 `--live` 的 OpenCLI 验收不替代该检查。

免 Key 使用有服务端限流，不承诺固定免费次数。出现限流或要求认证时，保留错误并按任务选择宿主搜索等独立候选，不自动登录、添加 Key 或切换付费模式。

Exa 可在 CLI 退出0且未设置 `isError` 时，用 `_meta` 中的 `ai.exa/rateLimited: true` 返回限流提示；这不是搜索结果。自检将其报告为 `EXA_RATE_LIMITED`。固定样本成功不保证下一条不同查询可用，实际请求仍须单独验收，不能用自检结果覆盖真实限流回执。

#### 额度与恢复条件

以下为2026-10-22核对的官方说明与源码，服务端配置可能变化：

- 免 Key MCP 与免费账户额度分开计算。[账户计费说明](https://exa.ai/docs/admin/billing#free-tier-credits) 当前为首个团队每月10美元额度、完成 onboarding 后另有一次性10美元奖励；月额度在每月1日重置且不累积。现行说明不承诺每月20,000次搜索，账户额度也不自动分配给匿名入口。
- [托管端源码](https://github.com/exa-labs/exa-mcp-server/blob/0b499f095c4ca145eee07b09137641c037d58449/api/mcp.ts#L155) 的匿名限流默认按服务端识别的出口 IP 统计：每秒2次滑动窗口、每天50次固定窗口，可由服务端环境变量覆盖。只统计 `tools/call`，不统计初始化或 `tools/list`；`numResults=3` 不等于3次工具调用。共享出口可能共用计数，源码默认值不是线上额度保证。
- 托管端 IP 限流返回 HTTP 429及 `Retry-After`（秒）、`X-RateLimit-Reset`（Unix 毫秒）；按实际响应等待相应窗口。日窗口是固定边界，不是首次查询后滚动24小时；不得自行承诺某个本地时间恢复。`X-RateLimit-Limit: 0` 是源码有意隐藏限流维度，不能解读为免费额度为零。
- 下游 Exa API 的429可被[错误处理器](https://github.com/exa-labs/exa-mcp-server/blob/0b499f095c4ca145eee07b09137641c037d58449/src/utils/errorHandler.ts#L85) 包装为 HTTP 200的 MCP 限流提示，只保留上述 `_meta` 标记，不透传具体原因或重置时间。此时报告恢复时间未知，不能认定日额度耗尽、已经付费或必须添加 Key；也不能用固定样本成功证明缓存或其他查询必然可用。

### 豆包可选入口

当前参考路径是 [huashu-doubao-search](https://github.com/alchaincyf/huashu-doubao-search)，需要搜索专用 `DOUBAO_SEARCH_API_KEY`，不能用普通模型 Key 代替。先只读核对当前进程和已授权的搜索／Agent 配置是否已有该 Key；只报告存在与来源，不回显值、不扩大为全盘凭据扫描。

没有 Key 时保持未配置。需要接入的使用者先到 [豆包搜索控制台](https://console.volcengine.com/search-infinity/web-search-exp) 确认已有服务、免费额度与超额行为；涉及付费开通或后付费授权时停止，不由普通检索代办。[官方文档](https://docs.volcengine.com/docs/Networkedsearch/Networkedsearch-2?lang=zh) 当前说明每个火山账号每月500次，Global／Custom 共用；不等于账户当前还有500次，也不与其他联网插件额度混用。

已有适用 Key、已确认费用边界并准备好 Node／npx 后，可按上游说明配置。下面仅保存环境变量引用；真实 Key 由本机受保护的凭据机制注入使用该配置的 Agent 进程，不粘贴到聊天、公开仓库或命令历史：

```bash
mcporter config add huashu-doubao-search --scope home --command npx --arg -y --arg github:alchaincyf/huashu-doubao-search --env 'DOUBAO_SEARCH_API_KEY=${DOUBAO_SEARCH_API_KEY}'
```

npx 会按需获取上游包，执行安装与首次运行前核对其当前来源和帮助。普通搜索不配置 `ARK_API_KEY`，不启用额外模型加工。取得真实搜索授权且费用边界满足后，再发现 schema 并执行：

```bash
mcporter list huashu-doubao-search --schema --json --no-oauth
mcporter call huashu-doubao-search.doubao_search query="<词>" count=5 max_age_days=7 --no-oauth
```

桌面 Agent 未继承 Shell 环境变量时，可把 Key 存在本机独立的600权限文件，由支持 `--env-file` 的 Node 直接加载后启动已安装 MCP；只在 mcporter 配置中保存文件与程序路径。目录和启动参数按本机生成，凭据可通过使用者自己的加密 dotfiles 恢复；其他机器还需恢复运行依赖并完成 schema 与业务验收，复制配置不代表可用。恢复入口须保留其他 MCP 服务，遇到不同账号的同名配置时停止，不把本机绝对路径或明文 Key 固化进共享模板。此方案与上方环境变量注入二选一，不叠加安装两个搜索入口。

`--search` 只报告豆包配置是否可读取，始终不发豆包查询；即便已找到 Key，也不能把“已配置”当业务验证通过或免费额度已确认。

### 共用边界

- 先确认工具存在且参数与当前 schema 一致；未配置时使用宿主搜索，不自动索取新 Key。`mcporter` 已安装只证明 CLI 可用，不证明具体后端已接入。
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

动态或需登录页面按 [浏览器选路.md](浏览器选路.md) 选择；本机日常外部网页默认正式 ego-browser，指定环境及开发调试按任务处理。仅在独立路径确有帮助时换工具。OpenCLI `web read` 是否创建文件、下载图片、需要浏览器由当前帮助确认；普通阅读不默认归档。

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

出现 `HISTORY_LOCKED` 时，在同一 Ego Lite Profile 的本任务标签打开 `chrome://history/`，通过浏览器原生历史搜索查原关键词，核对结果日期与链接；按正式 ego-browser 接口执行及收尾。历史页的排序、关键词和日期范围须与用户目标核对，不能把首屏当全量。不得关闭用户浏览器、复制整份私人库，或用 `immutable=1`／`nolock=1` 忽略活动数据库的锁与日志；该错误不影响独立的书签读取，也不表示没有历史记录。原生历史页仍不可用时，保留具体缺口。

## 时效与来源

- 最新排序、可见发布时间、服务端时间窗口分别说明；热门不等于最新，窗口过滤不等于每条时间已核实。
- 缺失时间、作者、正文或访问定位时标记未知／部分；不要为了完整格式虚构。
- 把本次实际读取、来源自身宣称和推理区分开。研究涉及多种证据时按问题组合，不固定来源数量或阶段。
