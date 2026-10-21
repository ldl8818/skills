# 平台检索路由

用于平台内搜索、帖子／文章正文、评论和视频信息。OpenCLI 当前安装版本的注册表是命令事实源；本文件只保存跨工具策略与证据边界。

## 目录

- [发现与执行](#发现与执行)
- [平台速查](#平台速查)
- [时效与内容](#时效与内容)
- [失败与浏览器降级](#失败与浏览器降级)
- [Agent Reach 与维护](#agent-reach-与维护)

## 发现与执行

1. 用户明确指定的服务、专用官方能力或已连接只读工具先用。已有结果足以支持问题时不额外抓取。
2. 需要 OpenCLI 时按 [执行与升级边界](opencli-windows.md) 发现只读动作、读取当前帮助并执行；命令与参数只维护这一入口。
3. 保留 exit code、stdout、stderr；按任务裁字段。download/export 即便标为 read 仍可能落盘，仅保存任务所需素材并限定输出目录。临时素材使用本任务独立目录，结束时只清理本任务不再需要的文件；长期归档按用户保存要求执行。
4. `providers.json` 只保留必要合约与证据边界，不复制完整注册表，也不自动执行降级。

## 平台速查

| 平台 | 常用路径 | 必须保留的边界 |
|---|---|---|
| X | OpenCLI `twitter/search`；按需 `tweets / thread / article` | 最新搜索显式用当前支持的实时排序；作者时间和原始 URL 可核对。完整短帖已够用时不再请求详情 |
| YouTube | yt-dlp 搜索、人工／自动字幕；按需 OpenCLI transcript、已配置 ASR | 字幕参考 [youtube-subtitles.md](youtube-subtitles.md)；元数据、字幕、口播和画面分别标记 |
| 小红书 | OpenCLI `xiaohongshu/search / note / comments` | 保留搜索结果中的完整可访问 URL、`xsec_token`／`xsec_source`；不能删参数后用裸 ID 盲读 |
| B站 | bili-cli 搜索／详情；OpenCLI 搜索／字幕；按需音频转写 | 搜索、字幕、音频是不同动作；实际结果缺时间时不能证明最新 |
| 公众号 | 专用工具或 OpenCLI `weixin/search` 发现；浏览器解析跳转与正文 | 搜狗中转链不是文章地址；按 [weixin-article.md](weixin-article.md) 核对落地页 |
| Douyin | OpenCLI `douyin/search / detail`；有需要再发现 `user-videos` 等动作 | 详情或播放地址不等于转写；完整口播按 [字幕与音频参考](youtube-subtitles.md#完整音频转写)；缺少发布时间不证明最近；不可见互动数保持未知 |

具体参数从当前命令帮助读取；必要合约由台账与 selftest 核对，不在本文重复保存平台命令清单。

平台有适配器只证明注册了部分动作。按用户实际需要分别核对搜索、排序、正文、字幕、转写和下载；记录实际使用的执行工具与换路原因，不以浏览器取得内容证明该平台的 OpenCLI 已通过。OpenCLI 的扩展路径和 ego-browser 都可以使用 Ego Lite，浏览器名称不能用来区分这两条执行路径。

`LOOKUP_OPENCLI_PROFILE` 统一选择已配置的 OpenCLI Profile，默认 `ego-lite`；不要暗中换到另一账号。`--window background` 控制焦点，不等于所有命令都不创建窗口。

## 时效与内容

- X 的热门与实时排序不同。用户问最近时，使用支持的实时参数并核对逐条时间；某人最近发帖选用户帖子动作，不把首页推荐流当该用户时间线。
- B站或 Douyin 的当前命令不支持所需排序／时间范围，或实际结果没有发布时间时，按 [浏览器选路.md](浏览器选路.md) 检查页面可见筛选与时间。展开实际筛选菜单，核对排序和时间选中状态，并按 [目标内容等待](动态页面读取.md#目标内容与等待) 等待结果刷新；悬停／点击回执、选中标签或仍显示的旧卡片不能证明筛选完成。逐条核对返回项时间；声称取全还须检查分页或结束标记。综合结果可能包含图文，不一概当视频；缺少日期时不能用热度或搜索窗口猜发布时间。
- 小红书优先保留完整访问 URL 到 `access_url`；用于显示或去重的 URL 不能覆盖它。仅有裸 ID 时通过搜索／feed／原始分享链接恢复合法定位信息。
- 用户只要几个讨论观点，完整短帖即可构成证据；需要整串讨论、长文、上下文或评论时才追加对应动作。截断片段与搜索摘要不能代表全文。
- 视频结果先标明 `metadata / subtitles / asr / visual`。字幕或 ASR 能支持口播摘要；讲解界面、演示结果或画面细节需要实际画面证据。拿不到时只完成可证明的部分，不换成另一个视频冒充原目标。
- 已核对的 [Douyin搜索实现](https://github.com/jackwener/opencli/blob/b06ab7780e73d3021e12e0f170086c2d55675776/clis/douyin/search.js#L168-L175) 用 `0` 填充不可见的 plays/comments/shares，这类值应视为未知；不把字段存在当实测。当前命令是否可读取评论或用户视频，仍需核对帮助和实际非空结果。
- 已足够的内容直接交付；仅为影响结论的具体缺口补充必要读取，每个请求有界，不固定限制整个任务只能再请求一次。结果归一化见 [failure-domains.md](failure-domains.md)。

## 失败与浏览器降级

连接有疑点时使用原生诊断，后续复用同任务结果。连接失败只暂停共享 bridge/Profile 的 browser-backed 命令；站点动作失败只暂停相同 `site+action`；认证失败只影响相同站点／账号；合法空结果和部分证据不触发全局故障。精确规则见 [failure-domains.md](failure-domains.md)。

同一失败路径不循环尝试；业务超时先确认旧动作结束，不自动重派。需要补救时先考虑已可用的专用 API／CLI；仍需浏览器时按 [浏览器选路.md](浏览器选路.md) 选择，本机日常外部网页默认正式 ego-browser。必须核对候选是否绕开失败依赖，不能用 `opencli browser` 绕过同一失效 bridge。

宿主浏览器功能名、操作 API、快照和收尾机制按其实际工具／Skill 文档发现，不假设所有 Agent 都有名为 BrowserUse 的工具。ego 只按正式安装 Skill 使用；不复制它的旧 API，见 [ego-space-hooks.md](ego-space-hooks.md)。

## Agent Reach 与维护

职责、加载与诊断边界统一见 [任务选路.md](任务选路.md#职责与加载边界)。按需读取对应平台 reference，命令以安装版本帮助和真实输出为准；不再维护第二套平台目录。
