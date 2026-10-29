# Agent Reach 融合与能力映射

平台能力、环境配置、诊断或转写任务读取对应部分。lookup 统一决定任务路线和完成条件；下面的上游资料提供具体平台知识与工具用法，不重做通用选路。

## 来源与加载

完整来源为 [Agent Reach 1.6.0 main 固定快照](https://github.com/Panniantong/Agent-Reach/tree/14c213405669414492bda0f8d52cc6531d062c45)，commit 为 `14c213405669414492bda0f8d52cc6531d062c45`。1.6重写了命令、状态与渠道接口；版本标签不能代替文件与能力核对。

- 完整仓库118个文件保存在 [源快照](../upstream/agent-reach.tar.gz)，逐文件清单、大小、哈希及运行适配归 [来源回执](../upstream/agent-reach.json)，[MIT 许可](../upstream/LICENSE-agent-reach) 保留。原始中英文 Skill 及所有参考保持原文，处于自动发现目录之外。
- 当前上游参考为 `capabilities / sessions / maintenance` 三份。按任务读取一份完整原文：`python3 scripts/reach.py reference capabilities`。安装和更新分别使用 `reference install / update`。旧的7类分类名和5个 `setup-*` 读取名保留为新版完整指南的别名，不声称旧文件仍存在。
- 上游命令在本组合中通过 `python3 scripts/reach.py run ...` 调用；先用 `run channels` 查看当前动作、参数和后端。用户输入作为独立 argv 传入。上游的浏览器、登录复用、安装和更新建议不能覆盖 lookup 的当前选路与授权。

## 完整渠道

lookup 保留原16类任务路线。1.6原生引擎注册14个渠道、40个动作：独立 Exa 渠道并入 `web search`，RSS 从原生注册表退役，继续按 lookup 的直接路线处理。下表描述整个组合的能力，不表示每项都是原生 Reach 命令，也不表示真实账号已通过。原生渠道、全部动作、CLI、Python 接口及直接路线分别登记在 [能力清单](../upstream/capabilities.json)；候选验证不能用直接路线冒充原生注册。

原生动作以 `run channels` 为准。YouTube 是 `read/search/subtitle/transcribe`，B站是 `search/read/hot/subtitle`，X 是 `search/profile/tweets/thread`；旧版额外动作仍按现有 OpenCLI／专用工具路线发现和验收，不从名称相近推断新引擎提供相同动作。

| 渠道 | 分类 | 可执行动作 | 环境与验收 |
|---|---|---|---|
| 全网搜索 Exa | search | 网页与技术资料搜索 | 沿用 [搜索接入](search-routing.md) 的 Exa／Tavily／豆包策略；核对相关内容、原始来源和免费边界 |
| 普通网页 | web | 原站正文、Jina Reader、Web Reader MCP | 优先原站与适用连接器；第三方 reader 仅接收允许外发的公开 URL；核对真实正文 |
| RSS／Atom | web | 获取并解析 feed 条目、标题、日期和链接 | 按任务环境显式使用 feedparser；1.6不再随包安装或报告 RSS 就绪。解析一次不等于已创建订阅或监控；错误页、空源和截断分别判断 |
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
| 播客单集 | video | 单集音频转写、按需标点与分段增强 | ffmpeg 与已配置 Groq；增强另有模型调用和外发，需核对条件；不默认启用或承诺永久免费 |
| 雪球 | finance | 会话核对、股票搜索、行情、热门内容与热门股票 | OpenCLI 或明确配置的最小 Cookie；HTTP 400不当股票不存在；返回代码、价格、时间或真实非空列表 |
| V2EX | social | 热门、节点主题、主题详情与回复、用户资料 | 公开 API 或上游 Channel 方法；核对主题 ID、回复范围及分页，不把热门列表当全站搜索 |

lookup 已有的公众号、Douyin、其他搜索服务、浏览器操作、本地 UI 验收、历史检索与媒体证据继续使用各自现行参考；不因上游未登记这些渠道而移除。

V2EX 1.6的 `read` 只取回复第一页，回复请求失败还会丢弃已取正文。融合运行时保留正文，并在 `items[].raw` 补充 `replies_complete / replies_error`；失败和未取全均不能认定为无回复。需要完整回复时沿公开 replies API 分页，核对总数与范围。原始快照不改写，修正归运行适配。

## 配置、诊断与维护

首次需要 Agent Reach 的 Python 引擎时，先检查隔离运行时。普通查询不自动准备环境：

```bash
python3 scripts/reach.py verify
python3 scripts/reach.py status
# 明确安装授权后执行；只安装私有 Python 环境，不注册客户端 Skill。
python3 scripts/reach.py prepare
python3 scripts/reach.py run --version
python3 scripts/reach.py run doctor
```

运行时位于 `XDG_DATA_HOME/lookup/agent-reach/<commit>-<integration-id>`，未设置时使用 `~/.local/share/lookup/agent-reach/<commit>-<integration-id>`。integration-id 绑定本地适配，适配变化时准备新环境并保留旧环境。准备需要 Python ≥3.10、已有 uv 和下载 Python 依赖的网络；不安装全局 CLI，不调用模型、读取浏览器账号或查询业务站点。准备失败只清理本次创建的环境，已有未知残留保持原状；同一来源重复准备不重装。配置仍沿用上游的 `~/.agent-reach/`，不会在来源快照中保存凭据。

CLI 与 MCP 使用已核验环境的隔离 Python 导入模式，忽略工作目录、`PYTHONPATH` 和用户级 Python 包，避免同名包替换实际执行来源；不生成字节码缓存。

| 流程 | lookup 内的执行方式与完成条件 |
|---|---|
| 原生内容动作 | `run channels` 查看14渠道与40个动作，再用 `run <channel> <action> ...`。公开摘要、正文、评论和字幕分别验收；原生 `ok: true` 不替代 lookup 的完整性判断 |
| 环境与渠道准备 | 明确安装授权后用 `run setup` 或 `run add <channel>`。所选渠道只安装自身所需工具；涉及 Reach 专用浏览器的渠道在任何安装前返回 `NEED_SETUP`，改由 lookup 既有 OpenCLI／浏览器路线准备。不会新装 Cloak／Chrome，不删除旧 pipx／venv，不注册竞争 Skill |
| 配置 | `run configure <key> --stdin`；交互终端使用隐藏输入。只处理具名配置，不回显凭据。已有平台登录与 Cookie 按 lookup 的平台／Profile 授权处理，不调用原生自动复制流程 |
| doctor 与真实检查 | `run doctor` 默认输出 JSON，`run doctor --text` 可读文本；doctor 只读本地状态。需要真实探针时显式 `run check <channel>`，诊断和内容成功分别报告 |
| 登录、退出与浏览器 | `run login/logout/browser` 在执行前拒绝；使用 lookup 的原绑定环境人工交接和既有浏览器选路。私有引擎同时阻止隐式浏览器启动、安装和 Cookie 复制，不因站点动作自动改 Profile |
| 音频与字幕 | 原生 `run youtube subtitle/transcribe <url>`；通用本地文件／URL 转写仍可调用私有环境的 `agent_reach.transcribe.transcribe`，保留服务商和显式 fallback 参数。完整音轨、费用和外发分别验收；旧 `run transcribe` 不再是原生命令 |
| 播客单集 | 原生 `run xiaoyuzhou transcribe <url>` 与随包 `source/agent_reach/scripts/transcribe_xiaoyuzhou.sh`；Groq 和增强步骤各按实际条件验收 |
| 格式整理 | 1.6统一返回 `items/raw`，旧 `format xhs` 已删除；已有内容需要整理时用 lookup 的结果归一化流程。未知值不补0，不以整理证明真实抓取 |
| 版本与更新 | `run version`；`run --version` 保留为对应别名，旧 `doctor --json` 也可读取。只读原生检查可用 `run update --check`；真正升级统一走 Skill Manager 委派的 lookup 维护器，原生整批升级入口拒绝 |
| 状态观察 | 新版 `doctor` 是本地快照，`check` 是显式真实探针；不自动建立原 `watch` 的定时任务或守护进程 |
| MCP 状态 | `python3 scripts/reach.py mcp` 运行 lookup 的薄适配器，唯一工具 `get_status` 调用新版原生 doctor。原上游 MCP 模块已删除，不再称为原始模块；不自动注册或安装 SDK |
| 卸载 | `run uninstall --dry-run` 预览原生对象；真正删除须核对其配置、工具与数据范围。融合运行时和原生独立安装分别处理 |
| 原生 Skill 管理 | 完整模板留在源快照；运行入口拒绝 `skill` 注册，内部安装流程也关闭注册，唯一发现入口仍由 lookup 管理 |

### 设置指南、MCP 与 Python 接口

`reach.py status` 返回已核验私有解释器。公开 Python 能力改用1.6原生接口，不保留一套旧实现；每项旧接口的去向记在 [能力清单的 legacy_migrations](../upstream/capabilities.json)。

| 原用途 | 当前接口与边界 |
|---|---|
| 渠道识别与后端 | `channels.get_channel/get_all_channels`、`Channel.actions`、`runtime.dispatch.run_action`；原 `ordered_backends/check` 方法已替换，40个原生动作单独验收 |
| 状态报告 | `runtime.manage.doctor`；原 `core.AgentReach` 已删除，真实联网探针另用 `runtime.manage.run_checks` |
| 公开网页与 Exa | `WebChannel.read` 和 `web search/read`；lookup 搜索服务顺序、公开 URL 外发限制继续适用 |
| V2EX 与雪球 | 统一渠道动作或对应当前方法；V2EX 完整回复需核对分页，雪球行情与社区认证各验 |
| 通用音频 | `transcribe.transcribe` 保留 URL／本地文件、服务商与显式 fallback；也可用 YouTube／播客原生动作 |
| 配置与登录 | `Config.get/set/delete/load/save` 处理具名字段；原批量配置转储和 Cookie 提取模块已退役，不用宽泛枚举替代平台授权 |
| 参考与资源 | 三份当前指南、播客脚本、统一 CLI／dispatch／manage 均受候选门禁核对；不把已删除的旧指南登记为仍存在 |

MCP 适配器沿用原状态工具的 MIT 实现方式，依赖 SDK 1.x 装饰器。仅在已获授权的私有运行时明确安装兼容 SDK：

```bash
uv pip install --python /absolute/runtime/python 'mcp[cli]>=1.0,<2'
python3 scripts/reach.py mcp
```

不修改全局 Python，不自动注册服务，不导出 Cookie。initialize／tools/list 证明协议与工具可发现；本任务的隔离 get_status 还需核对14渠道状态，均不等于真实平台业务通过。

## 重叠规则的适配

1. 全网搜索沿用 [搜索策略](search-routing.md)，浏览器沿用 [浏览器选路](浏览器选路.md)。上游分类里的首选后端是候选经验；先满足用户指定、当前授权、实际环境和直接证据要求，再选可用后端。
2. OpenCLI 统一使用当前 Profile 与 [原生执行入口](opencli-windows.md)。原文提到 Chrome 不等于必须切换用户已经配置的其他 Chromium 浏览器；Boss 的专用 Chrome／严格 CDP 要求保留为上游能力事实；无法在已确认 ego-lite 绑定中满足时报告该渠道阻塞，不切换 Chrome。
3. 平台失败按 [有界恢复与失败作用域](failure-domains.md) 处理。原文中“升级后再试”、固定重试次数或换首页等建议不自动扩大授权，也不能改变用户需要的对象和证据范围。
4. 多平台研究按问题的内容缺口选择来源，已有材料足够就交付，不强制固定组合。研究综合继续遵循 [研究综合](研究综合.md)。
5. 上游“免费”“无需配置”等陈述需与当前来源、环境及额度回执核对。向 ASR 或标点增强模型外发音频／文稿前，分别核对服务商和用户授权。
6. 来源完整、命令存在、doctor 就绪、真实目标通过分别记录；不以任一项替代其他项。

## 客户端发现与恢复

只让 lookup 出现在客户端的联网与浏览器 Skill 自动发现目录。上游压缩快照保留原触发字段，不修改它们来消除竞争；OpenCLI 用 `opencli skills read opencli-browser -f plain`，Ego 用当前 `ego-browser skill` 按需读取完整执行指南。

```bash
python3 scripts/entrypoints.py audit --lookup-root /absolute/lookup
python3 scripts/entrypoints.py apply --lookup-root /absolute/lookup
```

apply 只处理已有客户端目录中的已识别竞争入口，保留其原始来源与恢复记录到 `~/.local/share/lookup/execution-skills/`，并给这些客户端建立直达同一 lookup 源码的单跳链接。首次安装尚无客户端目录时只创建共享入口。同名 lookup 真目录与选定源码不同、链接指向其他源码或保留目标冲突时保持原状，不覆盖；选定目录本身作为唯一源码时可直接使用。它不安装尚不存在的客户端，不修改应用自带 Skill 或插件缓存。

共享真身与客户端软链同批迁出时，先解析整批链接，再将归档链接映射到对应的归档真身。迁移完成前检查来源可读；中途失败恢复原目录与原始链接。重复执行不重复迁移；原发现位置以后重新注册新版时，旧归档仍指向原来保存的版本。

新机恢复和上游安装／更新后重新检查发现入口，防止安装器注册新的竞争 Skill；chezmoi 的 V3、旧模板与 WorkBuddy 映射复用本入口。已有会话可能保留旧 Skill 清单，磁盘验收通过仍须用新会话核对自然选择。

## 更新与完整性

原生独立包和平台工具的更新继续由既有 `lookup update` 维护流程承担。融合快照随 lookup 源码维护，不能用“原生包版本相同／已升级”替代融合验收，也不让原生包更新覆盖本地入口。

候选包的离线能力门禁为 `python3 scripts/reach.py contract --package-root /absolute/candidate/agent_reach`。原生包维护复用同一门禁，分别核对14个原生渠道、全部40个动作、15类 CLI、3份当前参考、播客与运行模块、34个公开 Python 符号及现行 lookup 直接路线。缺项、未知注册、删除动作或解析失败时拒绝切换；升级前后的版本读取同时支持旧 `--version` 与1.6的 JSON `version`。门禁通过不证明业务站点、账号或新增能力已验收。

原生更新返回成功、等待或失败后，在同一维护锁内检查客户端发现入口并迁出重新注册的竞争 Skill，入口归档不提升原生升级状态。发生身份、来源或目标冲突时保留内容，返回 `discovery_pending`；消除冲突后重跑原命令只接续入口处理，不重复原生升级。等待中的原操作后来完成时先核对版本与指南，再按原事务恢复；其他运行版本变化不以旧回执继续。完整接续规则见 [上游更新](上游更新.md)。

更新融合来源时，取得选定通道的完整仓库快照，比较旧来源／本地适配／新来源，更新完整文件清单、commit、压缩包哈希与能力映射；核对原始路由字段完整保留、3份当前参考、全部渠道动作、CLI 流程和旧能力的明确迁移。对运行适配重新验证并在干净 HOME 准备候选环境，失败时保持旧来源与运行时。版本相同而 commit 不同也必须比较。不能因新版删除旧入口而跳过迁移说明，也不能通过删掉所需动作或门禁来接受不完整候选。

离线检查命令为 `python3 scripts/reach.py verify`；完整来源与能力测试为 `python3 -m unittest discover -s tests -p 'test_reach.py'`。新机安装和发现流程还须在干净 HOME 实跑；具体平台账号和另一台设备须分别取得真实证据。
