# OpenCLI 执行与升级边界

选用 OpenCLI、诊断连接或评估升级时读取。Lookup 维护任务边界，上游维护命令、异步执行、连接和浏览器资源。当前基线为正式发布2.0.2；随包入口接受 `>=2.0.2 <3`，版本范围不是所有后续版本已实测的承诺。

全部170站点、1,289条公开命令、5套指南与开发维护能力统一见 [完整融合入口](OpenCLI融合.md)。本文件只维护共享执行边界；providers.json 中没有登记的动作仍可从原生注册表发现。

## 发现能力与执行

```bash
node scripts/opencli-run.mjs list "<动作关键词>" --site "<site>" --limit 25
node scripts/opencli-run.mjs <site> <command> --help -f json
node scripts/opencli-run.mjs <site> <command> ...
```

- `list` 的 JSON 为 `{ok,data:{commands,total,nextOffset?}}`，只返回当前页；需要更多候选时沿 `nextOffset` 分页，不把首屏当完整注册表。选择 `access: read`，从单个命令帮助核对 `browser`、`positionals`、`command_options`、`browser_common_options` 和 `columns`。
- `opencli-run.mjs` 原样调用公开 CLI，不导入包内模块、不修改 Commander。它固定 `LOOKUP_OPENCLI_PROFILE`（默认 `ego-lite`）、拒绝冲突 Profile／隐式 CDP transport、限定认证检查站点，并设置 `OPENCLI_CLOSE_OWNED_TAB=1`。需改用另一 Profile 时先确认任务授权与实际别名；显式获准的 CDP 路线用 [专用入口](OpenCLI融合.md#显式-cdp-路线)，默认不切换。
- 该入口优先使用 [托管维护](上游更新.md) 已验收的 Lookup 专用版本，否则使用原系统安装。能力发现、帮助与业务执行都通过同一入口；上游指南中的裸 `opencli` 命令也经此入口调用，不混用系统旧版帮助与托管新版执行。没有 Python 或更新提醒不可用时保留原执行能力；有效版本指针异常则先核实，不静默改用其他版本。
- `OPENCLI_CONFIG_DIR` 可指定已有 OpenCLI 配置目录；health 与 runner 必须使用同一环境。切目录或 Profile 不能作为绕过失败依赖的证明。
- Ego Lite 是基于 Chromium 的浏览器，可安装 OpenCLI 的 Chrome 扩展；OpenCLI 通过该扩展执行，`ego-browser` Skill 通过浏览器自身接口执行。两者可使用同一个 Ego Lite 浏览器，无需另开原版 Chrome。换执行接口仍须核对共同的进程、Profile 与站点登录态。
- Profile 是 OpenCLI 的连接别名，不是浏览器产品或 Skill 名称。默认别名 `ego-lite` 本身不证明实际连接与登录态；有环境疑点时核对当前连接和目标站点会话，不根据别名推断。
- `LOOKUP_OPENCLI_TIMEOUT_MS` 默认90秒，包含版本检查与执行等待；超时或收到中止信号时只终止本次 CLI 子进程，浏览器动作可能继续，返回结果未知，不自动重派。旧 `OPENCLI_RUN_IMPORT_TIMEOUT_MS`／`OPENCLI_RUN_HARD_TIMEOUT_MS` 已退役；旧 `OPENCLI_DAEMON_PORT` 必须移除，不再自行管理端口。
- 普通结果默认为 `{ok:true,data:...}`，失败为 `{ok:false,error:...}` 并使用非零退出码；日志在 stderr。帮助、版本和流式输出有各自格式，不统一当业务信封。保留实际 exit code、stdout 和 stderr；归一化按 [failure-domains.md](failure-domains.md)。

## 登录准备与恢复

本节维护 CLI 所需站点登录的准备、人工交接与恢复流程。登录准备可在适配器修复之前发生，不属于通用浏览器抓取兜底，不计入 [适配器修复轮次](failure-domains.md#适配器修复与浏览器兜底)。

1. **按动作判断依赖。** 从当前帮助、执行指南及必要的实际结果判断具体动作是否需要站点登录。`browser: true` 或台账 `auth: browser-session` 仅说明浏览器／会话依赖，不能证明当前未登录，也不能据此要求整个平台先登录。公开动作或已完整取得目标时直接继续；出现不阻断内容的登录按钮或提示不触发登录准备。
2. **在需要时提前说明。** 已知动作需要登录且原绑定环境有当前未登录证据时，在派发该动作前告知用户受影响的站点、动作及登录环境，进入登录准备。状态未知且当前版本支持该站点的认证检查时，可在同一环境执行一次定向 `auth status --site <site>`；`unknown`、不支持检查或 bridge 故障不能当作未登录。有连接条件且没有明确账号／权限阻断时，仍以最小业务动作核实。实际动作返回 `AUTH_REQUIRED` 或会话失效时，先保留结果并停止该站点账号的自动抓取，再转入登录准备；不等失败多次才告知。
3. **在 CLI 原绑定环境打开入口。** 核对 runner 的 Profile、配置目录、传输方式，以及该连接实际对应的浏览器和 Profile／context；Profile 别名不证明绑定身份。优先使用同一连接中不启用网络捕获的 OpenCLI Browser 入口，在本任务页面打开已确认的目标站点登录入口；也可用经核对能指向同一环境的原生启动或正式交接接口。无需为已获授权的登录准备重复确认。2.0.2的 `browser open` 会默认启动响应捕获，人工登录使用独立 `--session` 下的 `browser tab new <url> --window foreground`；具体参数与后续版本行为须读取当前帮助及对应实现。交接前停止本任务已启用的网络捕获或调试，不能读取、保存登录请求／响应或凭据；无法安全交接时说明限制，不能猜停用命令。已有挑战页时优先交接原页面，不另开页面绕过。只有已确认同一绑定环境时才使用 Ego 接口辅助打开，不能任取默认浏览器、无痕窗口或另一 Profile。bridge 未恢复时不派发其上的打开命令；有已核实的同环境原生入口可用于登录准备，否则说明具体限制。环境无法确认或远端／无头环境无法人工操作时，说明正确入口与缺少的条件，不改默认 Profile、不迁移 Cookie。
4. **交接并等待用户。** 告知用户在指定页面手动登录或完成验证，完成后通知继续；按当前工具交接控制，暂停该站点账号的自动操作。不得填写或读取密码、采集／导出 Cookie、自动解验证码、循环刷新挑战或擅自换账号。用户接管、验证码及风控期间不自动轮询认证或重派业务；权限拒绝不能假定可由重新登录解决。交接期间保留用户正在操作的页面，不执行会关闭它的 session／space 收尾；不依赖该账号的已授权任务可继续。
5. **核对后回到原 CLI。** 用户明确通知已登录／验证完成或通过工具明确交回控制后，先核对是否在原绑定环境完成，确认旧动作已结束，再在该环境核对目标可访问并执行原 `site+action`。核对可由适用的定向认证检查或原目标最小只读请求完成，不额外重复已足够的请求；登录首页、昵称或另一个 Profile 的成功不证明目标可访问。仍有挑战时重新暂停；未消除的 bridge／权限阻断按原作用域处理。目标恢复后保留原对象、参数、输出目录、已取得证据与修复轮次，按实际 CLI 内容／文件验收。不得因登录时打开了浏览器而继续用其抓全文或素材；只有仍存在适配缺陷时才接回既有修复流程。

只记录任务动作、非身份化的环境代号、阻断类别、登录入口的打开／交接结果、用户恢复信号、原 CLI 验收和资源归属，不保存凭据或无关账号信息。用户操作中的页面保持交接状态；交回后仅按原生接口清理本任务创建且不再需要的资源，用户或未知归属页面保留。选用 Ego 辅助交接时仍遵循 [空间与收尾规则](ego-space-hooks.md#本任务生命周期入口)，不得在用户接管期间运行自动 `finish`。

## 浏览器接口与资源

选路确定使用 OpenCLI Browser 后，直接读取安装包匹配的执行文档：

```bash
node scripts/opencli-run.mjs skills read opencli-browser -f plain
node scripts/opencli-run.mjs browser <command> --help -f json
```

不为读取执行文档再安装一个自动触发的通用路由 Skill。页面会话、frame、等待、截图与动作参数以上述当前文档为准；Lookup 不复制另一份 API 手册。

接口返回空列表或执行回执时，仍按 [动态页面读取](动态页面读取.md) 与 [媒体读取](媒体读取.md) 核对目标；工具声明支持 frame、点击或视频不等于当前页面已通过这些能力的验证。

一次任务使用自己的 `--session`，只操作明确归属的页面。多步浏览器任务结束时执行该 session 的 `browser close`；登录交接期间按上一节保留用户正在操作的页面。一次性 adapter 使用帮助支持的 `--site-session ephemeral --keep-tab false`，由 runner 开启原生 owned tab 清理。`--window background` 只控制焦点。

清理必须有上游回执；警告或未知结果单独核对。旧扩展可能拒绝清理；不要把已取得业务结果重派，也不要强关未知页面或停止共享 daemon。bound 用户页面按原生解绑规则保留。

## 连接诊断

`bash scripts/opencli-health.sh` 委托原生 `doctor`，仅将报告转换为连接诊断，不探测固定端口、读取 Profile 内部文件、启动或杀死 daemon。doctor 可以按需启动 daemon，并用专用探针验证 bridge；不发目标站点业务查询。

正常读取不强制先做全环境体检；有连接疑点或执行 selftest 时再调用。必须同时核对 `daemonRunning`、`extensionConnected`、`connectivity.ok` 及 stale／flaky 状态，doctor 的退出0与外层 `ok:true` 只说明报告生成成功。通过仍不证明站点登录、动作能力或正文完整。

诊断输出的 `scope: bridge_profile`、`diagnostic_only: true`、`action_tested: false` 说明它只检查连接，不决定平台动作是否可用。按以下证据继续：

报告中的明确失败字段优先保留；其他字段缺失不能将已证实的断连改判为“诊断不足”，也不能据此继续发送共享失败连接上的请求。

| 诊断／执行结果 | 后续动作 |
|---|---|
| `ready`，或原动作已经成功 | 执行目标最小业务请求并验内容；原动作已有足够结果时直接复用，不重复请求 |
| `diagnostic_inconclusive`、无效报告或只有历史 `not_ready` | 核对退出码与原生错误；缺少明确连接失败、权限／账号阻断或未知执行证据时，以目标最小动作验证，不把缺证据当成不可用 |
| `daemon_stopped / daemon_stale / connection_unstable / profile_disconnected / connectivity_failed` | 读取 `reason_codes` 与原始报告，定位选定连接；有明确恢复依据时允许一次原生诊断复核，不重启共享进程、不切账号；已恢复后在剩余预算内验证目标动作 |
| `doctor_failed` | 先按实际错误判断参数、配置、执行环境或连接问题，不推断扩展没开启；Profile 错配、权限拒绝及结果未知沿用其停止条件 |
| `not_applicable` | 当前选中 CDP，Bridge 探针不适用；按已授权的 CDP 环境验证目标动作，不切回另一连接 |

同一任务不循环诊断。已核实的连接失败或目标动作缺口只确定处理作用域，不自动批准通用浏览器兜底；单次探针不代表 OpenCLI、Agent Reach 或全部 CLI 能力不可用。适配器报结构／选择器错误时读取当前 `opencli-autofix`，按 [适配器修复与浏览器兜底](failure-domains.md#适配器修复与浏览器兜底) 优先完成已有授权覆盖的本地修复与验证。普通查询不自动安装或发布修复；不得将既有修复授权误读为每轮均需重新确认。

### 小红书新版搜索适配

OpenCLI 2.0.2的搜索动作只识别旧 `input` 与 `/search_result`。部分页面已经使用 `textarea` 与 `/search_result_ai`，出现 `search_input_not_available` 或已显示结果却报导航超时。此问题只影响对应搜索适配，不证明连接或 note／download 失效。

已确认遇到该布局且获准修复适配器时，使用原生 `adapter eject xiaohongshu` 创建可编辑 override，再应用随包[补丁](../patches/opencli-2.0.2-xiaohongshu-search.patch)。先核对当前版本、trace 指向的源码及已有 override；已有本地改动时先比较，不覆盖。首次创建且来源仍与2.0.2一致时，可在该 override 目录先运行 `patch --dry-run -p1 -F 0 < <补丁绝对路径>`，通过后用相同命令去掉 `--dry-run` 应用。补丁不由 runner 自动注入，也不修改固定来源快照或 npm 包。

该补丁保留唯一可见控件、账号／风控检查及结果校验，仅支持已确认的新输入框、提交控件、结果路径与额外一层关键词编码。修复后须重跑原真实查询及同站正文／下载动作。升级时按[定制比较](上游更新.md)检查新上游是否已覆盖，不能长期盲套旧补丁。恢复本次新建 override 时，先核对其间没有新改动，再使用原生 `adapter reset xiaohongshu`；存在其他改动时仅还原本补丁。

同版本的搜索卡片会随排序显示点赞、收藏或评论数，原适配器统一写入 `likes`，因此“最多收藏”的数字不能当作点赞数。确认此布局后，在已有 override 上按同一比较与 dry-run 流程应用[搜索指标基础补丁](../patches/opencli-2.0.2-xiaohongshu-search-metrics.patch)：收藏与评论分别写入 `collects`、`comments`，未取得的点赞保留为空。该补丁作为下文完整指标修复的前置差异保留。搜索的 `published_at` 由笔记 ID 推算，不是页面确认的发布时间或更新时间。

### X 单帖媒体下载适配

OpenCLI 2.0.2的单帖下载在等待3秒后扫描整个页面的媒体节点；媒体未进入 DOM 时可能误报空结果，回复区图片也可能被错算到目标帖。已经确认该问题且获准维护时，按上述 override 流程使用 `adapter eject twitter` 与[下载补丁](../patches/opencli-2.0.2-twitter-download.patch)。该补丁同时修改 `download.js` 和 `thread.js`，必须完整应用，不能只复制一个文件。

单帖下载复用原生 thread 的读取实现，按精确帖子 ID 选择媒体，图片请求 `name=orig`；已有 API／账号错误原样停止。目标缺失或声明有媒体却缺 URL 为提取失败，只有目标已取得且确实无媒体才报空结果。用户媒体列表路径保留原实现。维护后核对单帖有图、无媒体和原 thread 动作，实际文件仍须验格式、尺寸、归属与完整性。恢复与升级遵循同一 override 比较边界。

### 小红书与 X 的互动指标

已经确认指标错配、遗漏或缺失误报0时，使用[完整指标补丁](../patches/opencli-2.0.2-engagement.patch)与[小红书 helper](../patches/opencli-engagement/xiaohongshu-engagement.js)、[X helper](../patches/opencli-engagement/twitter-engagement.js)。维护入口、覆盖范围和离线验证见[补丁用法](../patches/opencli-engagement/README.md)。不修改 npm 包或固定来源快照。

完整补丁保留原字段名，统一以 `null` 表示未提供或无法识别的指标，真实0继续保留0。小红书计数保留原始数字／缩写文本；`1.2万`不能宣称是精确计数。X 保留各动作既有的浏览量字符串／数字类型。

| 平台 | 字段 | 对应来源 |
| --- | --- | --- |
| 小红书 | `likes`、`collects`、`comments` | 笔记自身的 `likedCount`、`collectedCount`、`commentCount`（兼容 snake_case），或当前详情面板的对应控件 |
| 小红书 | `shares` | 精确匹配当前笔记 ID 的 `shareCount`；没有计数的分享按钮不能证明分享数为0 |
| X | `likes`、`replies`、`bookmarks` | 当前帖的 `favorite_count`、`reply_count`、`bookmark_count` |
| X | `retweets`、`quotes`、`views` | 当前帖的 `retweet_count`、`quote_count`、`views.count`；转帖与引用分开保留，不能混作独立分享数 |

小红书搜索卡片只显示当前排序对应的一项指标，其他三项为 `null`。需要同时比较点赞、收藏和评论时，读取 `note` 详情；详情中的 `metric_sources` 说明字段来自精确笔记状态还是详情 DOM。合集、用户笔记和 feed 只返回其实际来源提供的指标。评论点赞限定在该条评论的点赞控件内，不借用回复数。创作者后台未提供的值不补0，也不把 `undefined` 字符串当计数。

X 的搜索、详情、时间线、作者推文、收藏与点赞读取路径共用同一指标映射；引用帖指标保留在自己的 `quoted_tweet` 对象内。页面可能将转帖与引用合计显示，比较时必须核对页面标签与两个独立字段。X 未提供独立分享菜单计数时，`shares` 保持 `null`；分享不是核心验收门槛。

验证应覆盖字段归属、引用／包装对象、真实0、缺失值及搜索排序。原生 `adapter check <site>` 只检查定义；真实验收仍需搜索、详情和页面对照，未执行的私人收藏或后台动作不能计为实测通过。

## 升级验收

使用时提醒、`lookup update`、按依赖授权及隔离维护见 [上游更新.md](上游更新.md)。本节维护 OpenCLI 特有执行契约，不另建更新策略。

维护时先核对正式发布包、安装版本、扩展及公开帮助。在隔离目录遍历完整注册表、核对常用动作参数／字段，再测试明确 Profile、显式／隐式 CDP、延迟结果、业务失败、超时结果未知与原生清理；需要换服务时先核对是否有其他任务使用，不能用杀共享进程解决。

已有 helper 的唯一实现若被上游可靠覆盖，删去该实现及对应旧测试，保留本地边界回归。新增版本适配不得退回包内 monkey patch。升级不通过时保留原可用版本；已切换后按维护前记录恢复原版本与必要配置，不清空登录资料。

2.0.2已原生等待 `parseAsync()`，因此 Lookup 不再维护1.8.6–1.8.8的异步注入与自写 daemon 生命周期。命令列表、JSON 输出和清理属于新版契约，旧版无法继续使用本入口。

## 设计取舍

- 首次业务读取不再强制预跑 health：明确 Profile 的实际动作负责连接并返回错误，doctor 仅在连接有疑点时补证，减少重复探测。Profile 错误必须失败，不能借在线账号兜底。
- 连接启动与恢复交给原生 doctor，不再承诺旧 helper 的5秒失败／22秒冷启动时序。runner 保留整次默认90秒预算，公开 CLI 的版本检查最多5秒；超时后的未知结果边界保持。
- 接受已验证的2.0.2及后续2.x公开契约，取消对包内源码特征的绑定；必要命令帮助、自检与受影响实测负责发现契约漂移。升主版本或合约不符时先维护验收，不盲目继续。
- selftest 从整份旧注册表与站点级 `verify` 改为逐项核对所需动作的公开帮助，覆盖只读权限、必要参数和字段。它不承担全站 adapter 开发检查；命令存在、业务成功与资源释放分别验收。

来源：[2.0.2发布](https://github.com/jackwener/opencli/releases/tag/v2.0.2)、[原生 CLI](https://github.com/jackwener/opencli/blob/v2.0.2/src/cli.ts)、[doctor](https://github.com/jackwener/opencli/blob/v2.0.2/src/doctor.ts)、[随包浏览器 Skill](https://github.com/jackwener/opencli/blob/v2.0.2/skills/opencli-browser/SKILL.md)。
