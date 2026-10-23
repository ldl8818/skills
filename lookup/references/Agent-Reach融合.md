# Agent Reach 融合与能力映射

平台能力、环境配置、诊断或转写任务读取对应部分。Lookup 统一决定任务路线和完成条件；下面的上游资料提供具体平台知识与工具用法，不重做通用选路。

## 来源与加载

完整来源为 [Agent Reach](https://github.com/Panniantong/Agent-Reach/tree/94f06c1969dfc1834001269d79d3ad0972d9dee6)，主分支基线 `94f06c1969dfc1834001269d79d3ad0972d9dee6`，上游版本1.5.0。本地融合版本独立记录在 Lookup 入口。正式 tag v1.5.0只有13个渠道，同版本号不能证明覆盖当前16个渠道。

- 原始仓库的121个文件完整保存为 [源快照](../upstream/agent-reach.tar.gz)，逐文件清单、大小、哈希及本地运行适配归 [来源回执](../upstream/agent-reach.json)，原 [MIT 许可](../upstream/LICENSE-agent-reach) 保留。
- 原始 `SKILL.md`、英文入口和7类参考均保留原文，存于压缩快照中，不能被客户端当成另一个 Skill 自动发现。不要将解包目录链接到客户端的 skills 目录。
- 按当前任务读取一个完整分类，不全量加载：`python3 scripts/reach.py reference social`。分类为 `search / social / career / dev / web / video / finance`；安装与更新原文分别使用 `install / update`。
- 5份原始设置指南同样按需读取：`reference setup-exa / setup-groq / setup-reddit / setup-twitter / setup-xiaohongshu`；指南原文、脚本和公开 Python 接口均在完整能力门禁中登记。
- 读取上游参考后，命令参数仍须核对实际版本帮助。OpenCLI 动作通过 [执行入口](opencli-windows.md) 调用；上游 `agent-reach ...` 在本组合中对应 `python3 scripts/reach.py run ...`。用户输入作为独立参数传入，不复制模板作为 Shell source 执行。

## 完整渠道

下表逐项登记上游16个渠道的入口、动作、环境和成功判据。它是能力映射，不是实际平台已通过的声明。详细命令只在对应上游参考与当前工具帮助中维护；机器可核对清单归 [能力清单](../upstream/capabilities.json)。

| 渠道 | 分类 | 可执行动作 | 环境与验收 |
|---|---|---|---|
| 全网搜索 Exa | search | 网页与技术资料搜索 | 沿用 [搜索接入](search-routing.md) 的 Exa／Tavily／豆包策略；核对相关内容、原始来源和免费边界 |
| 普通网页 | web | 原站正文、Jina Reader、Web Reader MCP | 优先原站与适用连接器；第三方 reader 仅接收允许外发的公开 URL；核对真实正文 |
| RSS／Atom | web | 获取并解析 feed 条目、标题、日期和链接 | 可用 feedparser；解析一次不等于已创建订阅或定时监控；空源、错误页和截断分别判断 |
| GitHub | dev | 仓库与代码搜索、Issue／PR、Actions／Release、API 阅读 | 当前连接器或 gh；私有资源须有授权身份；创建、Fork、发布等写能力交相应授权流程 |
| X | social | 搜索、推文与回复、长文、用户资料及时间线、首页、本人 likes | 优先当前已授权的可用后端；twitter-cli 凭据仅在目标子进程显式提供；核对作者、时间及目标范围 |
| Reddit | social | 搜索、正文与评论、subreddit、热门、Popular、元信息 | OpenCLI 或已配置 rdt；需登录态，不把匿名失败当空结果；核对评论分页 |
| 小红书 | social | 搜索、笔记、评论及楼中楼、feed、用户笔记 | OpenCLI／MCP／存量 CLI 按实际条件选；保留完整访问 URL 与 xsec_token，不自动登录或读取 Cookie |
| B站 | social／video | 搜索、详情、热门、排行、字幕、音频提取 | bili-cli／OpenCLI；字幕和音频分别验收；不将 yt-dlp 对 YouTube 的可用性推广到 B站 |
| Facebook | social | 搜索、Profile、Feed、当前账号可见群组及动态 | OpenCLI 与目标账号现有会话；群组列表不等于任意群帖子或完整评论 |
| Instagram | social | 用户搜索、Profile、用户最近帖子、Explore、本人收藏 | OpenCLI 与现有会话；用户搜索不等于全站帖子关键词搜索；429或账号挑战停止相关路径 |
| LinkedIn | career | 人员资料、人才搜索、公司资料、岗位搜索、公开页 | 已配置 LinkedIn MCP；公开页可在外发允许时用 reader；受限页面不能由摘要冒充 |
| Boss直聘 | career | 专用浏览器链路体检、职位搜索与 JD 全文 | 严格 existing-browser／CDP；用户确认登录，区分本地 session 与浏览器登录；账号或环境风险立即停止 |
| YouTube | video | 视频搜索、元数据、人工／自动字幕、有限评论、音轨转写 | yt-dlp／OpenCLI／已配置 ASR；评论为尽力获取，字幕不证明画面；完整口播按 [转写规则](youtube-subtitles.md) |
| 小宇宙 | video | 单集音频转写、按需标点与分段增强 | ffmpeg 与已配置 Groq；增强另有模型调用和外发，需核对条件；不默认启用或承诺永久免费 |
| 雪球 | finance | 会话核对、股票搜索、行情、热门内容与热门股票 | OpenCLI 或明确配置的最小 Cookie；HTTP 400不当股票不存在；返回代码、价格、时间或真实非空列表 |
| V2EX | social | 热门、节点主题、主题详情与回复、用户资料 | 公开 API 或上游 Channel 方法；核对主题 ID、回复范围及分页，不把热门列表当全站搜索 |

Lookup 已有的公众号、Douyin、其他搜索服务、浏览器操作、本地 UI 验收、历史检索与媒体证据继续使用各自现行参考；不因上游未登记这些渠道而移除。

V2EX 原始 Channel 方法只取回复第一页，且将回复请求失败降成空列表。融合运行时保留正文并补充 `replies_complete / replies_error`，失败和未取全均不能认定为无回复；需要完整回复时沿公开 replies API 分页，并核对返回范围与总数。原始来源不改写，修正记录在来源回执的运行适配中。

## 配置、诊断与维护

首次需要 Agent Reach 的 Python 引擎时，先检查隔离运行时。普通查询不自动准备环境：

```bash
python3 scripts/reach.py verify
python3 scripts/reach.py status
# 明确安装授权后执行；只安装私有 Python 环境，不注册客户端 Skill。
python3 scripts/reach.py prepare
python3 scripts/reach.py run --version
python3 scripts/reach.py run doctor --json
```

运行时位于 `XDG_DATA_HOME/lookup/agent-reach/<commit>-<integration-id>`，未设置时使用 `~/.local/share/lookup/agent-reach/<commit>-<integration-id>`。integration-id 绑定本地适配，适配变化时准备新环境并保留旧环境。准备需要 Python ≥3.10、已有 uv 和下载 Python 依赖的网络；不安装全局 CLI，不调用模型、读取浏览器账号或查询业务站点。准备失败只清理本次创建的环境，已有未知残留保持原状；同一来源重复准备不重装。配置仍沿用上游的 `~/.agent-reach/`，不会在来源快照中保存凭据。

| 流程 | Lookup 内的执行方式与完成条件 |
|---|---|
| 环境安装与渠道配置 | 读取 `reference install` 及所选分类，核对计划与授权后调用 `run install --env=local --system --channels=<name>`；默认 `run install --env=local` 仅检查。安装器保留全部渠道安装能力；明确选择渠道时跳过无关的全局核心工具与 Exa 配置，只诊断所选渠道，缺少该渠道的必要依赖则据实际错误定向处理。默认完整安装或显式 all 保留原流程；客户端 Skill 注册统一关闭。安装后核对 [发现入口](#客户端发现与恢复) |
| 交互设置与凭据配置 | `run setup` 或 `run configure <key>`；优先隐藏输入，管道输入用 `--stdin`；不把值写进命令、日志或回复。浏览器 Cookie 读取须有明确的平台与 Profile 授权，只采所需字段；X／小红书仍使用用户提供的 Cookie-Editor 导出，不自动登录或更换账号 |
| doctor 与状态 | `run doctor --json`／`run doctor`；只在用户要求或能消除具体环境疑点时运行，不固定每次全渠道体检；结合探针覆盖判断 active_backend，最终仍验目标内容 |
| 字幕与通用音频转写 | `run transcribe <public-url-or-local-file>`；核对 ffmpeg、服务商、费用、外发与完整音轨；默认不跨服务商切换，显式 fallback 另核授权 |
| 小宇宙单集与增强 | 读取 video，显式安装所需渠道后调用原生 transcribe.sh；单集转写与增强分别记录实际服务、覆盖范围及费用条件 |
| 输出格式整理 | `run format xhs` 接收已捕获内容；格式整理不联网、不证明字段真实，也不能把未知互动数补成0 |
| 版本与更新检查 | `run version`／`run check-update` 保留原生能力；常规更新提醒与维护沿用已有 `lookup update agent-reach`，不复制原文中的整批升级链或修改当前安装来源 |
| 健康观察 | `run watch` 仅执行一次原生健康与更新检查，不因此建立定时任务或守护进程 |
| MCP 状态接口 | `python3 scripts/reach.py mcp` 直接运行原始 integrations/mcp_server.py，公开能力为 get_status；默认 Python 依赖不含 MCP，且上游未声明 mcp extra。需要时明确安装所需 MCP SDK 到隔离运行时；不误称为搜索／阅读 MCP，也不自动注册服务 |
| 卸载与恢复 | 原生 `run uninstall --dry-run` 可预览；真正卸载须核对它会删除的配置、凭据和 Skill 范围，按明确授权执行；私有融合运行时与原生独立安装分别处理 |
| 原生 Skill 管理 | 原始 skill 命令与完整触发原文保留在源快照中；融合运行入口拒绝重新注册它，改由 Lookup 的 entrypoints.py 管理唯一入口 |

### 设置指南、MCP 与 Python 接口

准备引擎后，`python3 scripts/reach.py status` 返回已核验环境的 Python 路径。原始公开 Python 接口可用该解释器调用，不要求重新安装独立 Agent Reach，不复制实现。输入作为独立 argv 传入，输出继续按 Lookup 的目标与证据规则验收。

| 接口 | 保留的能力与边界 |
|---|---|
| get_channel／get_all_channels、Channel、AgentReach | 渠道 URL 识别、后端顺序、探针和状态报告；探针通过不替代业务内容 |
| WebChannel.read | 通过 Jina 读取公开网页；第三方外发限制、反爬与响应大小检查沿用，不用于敏感或内网 URL |
| V2EXChannel | 热门、节点主题、详情／回复、用户；search 方法原本只返回不支持搜索的错误及候选建议，不能把接口存在说成真实全站搜索 |
| XueqiuChannel | 原生股票搜索、行情、热门帖子和热门股票；与 OpenCLI 路线并存，认证和数据完整性分别验收 |
| YouTubeChannel.transcribe、format_xhs_result | 原生音频转写和结果格式整理；格式整理不联网，不使未知字段变成事实 |
| Cookie 与 Config 接口 | 具名浏览器 Profile、显式单平台最小 Cookie 提取和配置读写；X／小红书的完整域自动提取仍禁用，不因函数名 extract_all 而读取所有平台 |
| transcribe_xiaoyuzhou.sh | 原脚本随私有运行时的 source/agent_reach/scripts/ 保留；读取 video 及实际脚本前提后调用，不从宿主 PATH 猜测脚本位置 |

完整符号和资源映射归 [能力清单](../upstream/capabilities.json)。需要 MCP 或 Cookie 可选依赖时，在已明确授权的隔离环境中安装原声明所需 SDK，例如：

```bash
uv pip install --python /absolute/runtime/python 'mcp[cli]>=1.0,<2'
python3 scripts/reach.py mcp
```

原 MCP 使用 SDK 1.x 的 Server 装饰器；SDK 2.x 已移除该接口。融合适配将上游 all 可选依赖限定为 `mcp[cli]>=1.0,<2`，原始源码快照不改写；独立安装 MCP SDK 同样使用上述范围。

这不修改全局 Python、不自动注册 MCP、不导出 Cookie。MCP 的 initialize／tools/list 只证明协议与状态工具可发现；调用 get_status 另会执行原生诊断，不在普通查询中强制运行。Cookie 可选依赖与浏览器访问还须满足目标平台和 Profile 的实际授权。

## 重叠规则的适配

1. 全网搜索沿用 [搜索策略](search-routing.md)，浏览器沿用 [浏览器选路](浏览器选路.md)。上游分类里的首选后端是候选经验；先满足用户指定、当前授权、实际环境和直接证据要求，再选可用后端。
2. OpenCLI 统一使用当前 Profile 与 [原生执行入口](opencli-windows.md)。原文提到 Chrome 不等于必须切换用户已经配置的其他 Chromium 浏览器；Boss 的专用 Chrome／严格 CDP 要求单独保留。
3. 平台失败按 [有界恢复与失败作用域](failure-domains.md) 处理。原文中“升级后再试”、固定重试次数或换首页等建议不自动扩大授权，也不能改变用户需要的对象和证据范围。
4. 多平台研究按问题的内容缺口选择来源，已有材料足够就交付，不强制固定组合。研究综合继续遵循 [研究综合](研究综合.md)。
5. 上游“免费”“无需配置”等陈述需与当前来源、环境及额度回执核对。向 ASR 或标点增强模型外发音频／文稿前，分别核对服务商和用户授权。
6. 来源完整、命令存在、doctor 就绪、真实目标通过分别记录；不以任一项替代其他项。

## 客户端发现与恢复

只让 Lookup 出现在客户端的联网与浏览器 Skill 自动发现目录。上游压缩快照保留原触发字段，不修改它们来消除竞争；OpenCLI 用 `opencli skills read opencli-browser -f plain`，Ego 用当前 `ego-browser skill` 按需读取完整执行指南。

```bash
python3 scripts/entrypoints.py audit --lookup-root /absolute/lookup
python3 scripts/entrypoints.py apply --lookup-root /absolute/lookup
```

apply 只处理已有客户端目录中的已识别竞争入口，保留其原始来源与恢复记录到 `~/.local/share/lookup/execution-skills/`，并给这些客户端建立直达同一 Lookup 源码的单跳链接。首次安装尚无客户端目录时只创建共享入口。同名 Lookup 真目录与选定源码不同、链接指向其他源码或保留目标冲突时保持原状，不覆盖；选定目录本身作为唯一源码时可直接使用。它不安装尚不存在的客户端，不修改应用自带 Skill 或插件缓存。

新机恢复和上游安装／更新后重新检查发现入口，防止安装器注册新的竞争 Skill；chezmoi 的 V3、旧模板与 WorkBuddy 映射复用本入口。已有会话可能保留旧 Skill 清单，磁盘验收通过仍须用新会话核对自然选择。

## 更新与完整性

原生独立包和平台工具的更新继续由既有 `lookup update` 维护流程承担。融合快照随 Lookup 源码维护，不能用“原生包版本相同／已升级”替代融合验收，也不让原生包更新覆盖本地入口。

候选包的离线能力门禁为 `python3 scripts/reach.py contract --package-root /absolute/candidate/agent_reach`。既有 `lookup update agent-reach` 在原生包验证中调用同一门禁，核对当前融合所需的16个渠道、11类 CLI 流程、7类参考、5份设置指南、MCP／播客脚本与公开 Python 接口；缺项、未知注册方式或解析失败时沿既有备份恢复，不把同为1.5.0的13渠道包认定为等价。门禁通过仍不证明业务站点、账号或新增上游能力已验收。

原生更新成功后，在同一维护锁内检查客户端发现入口并迁出重新注册的竞争 Skill。发生身份、来源或目标冲突时保留内容，返回 `discovery_pending`；消除冲突后重跑原命令只接续入口处理，不重复原生升级。运行版本已变化时先核对结果，不以旧回执继续。完整接续规则见 [上游更新](上游更新.md)。

更新融合来源时，取得选定通道的完整仓库快照，比较旧来源／本地适配／新来源，更新完整文件清单、commit、压缩包哈希与能力映射；核对原始路由字段完整保留、7类参考、渠道注册和 CLI 流程。对运行适配重新验证并在干净 HOME 准备候选环境，失败时保持旧来源与运行时。版本相同而 commit 不同也必须比较。不得直接用13渠道的正式包覆盖16渠道的融合基线。

离线检查命令为 `python3 scripts/reach.py verify`；完整来源与能力测试为 `python3 -m unittest discover -s tests -p 'test_reach.py'`。新机安装和发现流程还须在干净 HOME 实跑；具体平台账号和另一台设备须分别取得真实证据。
