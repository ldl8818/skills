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
2. 需要 OpenCLI 时按站点裁剪注册表，选择 `access: read`，再读取匹配命令帮助：

   ```bash
   opencli list -f json | jq --arg site "<site>" \
     '[.[] | select(.site == $site and .access == "read") | {site,name,strategy,browser,domain,args,columns}]'
   opencli <site> <command> --help -f yaml
   ```

3. 用 `strategy / browser / domain` 判断是否依赖浏览器；browser-backed 命令先过 `scripts/opencli-health.sh`，再经 `node scripts/opencli-run.mjs ...`。纯 API／本地命令不承担无关浏览器探测。
4. 保留命令的 exit code、stdout、stderr；结构化结果按任务裁字段。download/export 即便标为 read 仍可能写本地文件，任务所需的字幕、音频等临时素材可存于独立临时目录并仅清理本任务文件；长期归档按用户保存需求执行，均限定输出范围。
5. `references/providers.json` 只供 Agent 选择和验收，并非自动执行器。不要把台账模板直接拼成 shell 命令，也不要复制完整注册表。

## 平台速查

| 平台 | 常用路径 | 必须保留的边界 |
|---|---|---|
| X | OpenCLI `twitter/search`；按需 `tweets / thread / article` | 最新搜索显式用当前支持的实时排序；作者时间和原始 URL 可核对。完整短帖已够用时不再请求详情 |
| YouTube | yt-dlp 搜索、人工／自动字幕；按需 OpenCLI transcript、已配置 ASR | 字幕参考 [youtube-subtitles.md](youtube-subtitles.md)；元数据、字幕、口播和画面分别标记 |
| 小红书 | OpenCLI `xiaohongshu/search / note / comments` | 保留搜索结果中的完整可访问 URL、`xsec_token`／`xsec_source`；不能删参数后用裸 ID 盲读 |
| B站 | bili-cli 搜索／详情；OpenCLI 搜索／字幕；按需音频转写 | 搜索、字幕、音频是不同动作；实际结果缺时间时不能证明最新 |
| 公众号 | 专用工具或 OpenCLI `weixin/search` 发现；浏览器解析跳转与正文 | 搜狗中转链不是文章地址；按 [weixin-article.md](weixin-article.md) 核对落地页 |
| Douyin | OpenCLI `douyin/search`；有需要再发现 `user-videos` 等动作 | 搜索卡片不等于视频全文；缺少发布时间不证明最近；不可见互动数保持未知 |

以下只展示参数结构，执行前核对本机帮助；外部输入通过独立 argv 传入：

```bash
node scripts/opencli-run.mjs twitter search "<词>" --product live -f json --limit 5 --window background
node scripts/opencli-run.mjs twitter tweets "<账号>" -f json --limit 20 --window background
node scripts/opencli-run.mjs twitter thread "<推文ID>" -f json --window background
node scripts/opencli-run.mjs twitter article "<推文ID>" -f plain --window background
node scripts/opencli-run.mjs xiaohongshu search "<词>" -f json --limit 5 --window background
node scripts/opencli-run.mjs xiaohongshu note "<含访问参数的完整URL>" -f plain --window background
bili search "<词>" --type video -n 5
node scripts/opencli-run.mjs bilibili subtitle "<BV号>" -f json --window background
node scripts/opencli-run.mjs weixin search "<词>" -f json --limit 5 --window background
node scripts/opencli-run.mjs douyin search "<词>" -f json --limit 5 --window background
```

`LOOKUP_OPENCLI_PROFILE` 统一选择已配置的 OpenCLI Profile，默认 `ego-lite`；不要暗中换到另一账号。`--window background` 控制焦点，不等于所有命令都不创建窗口。

## 时效与内容

- X 的热门与实时排序不同。用户问最近时，使用支持的实时参数并核对逐条时间；某人最近发帖选用户帖子动作，不把首页推荐流当该用户时间线。
- B站或Douyin的注册表没有最新排序参数、实际结果没有发布时间时，改用当前 Agent 合适的浏览器检查页面可见时间与排序；必要时再用 ego-browser。缺失就明确说明，不能用播放量、热度或搜索窗口猜发布时间。
- 小红书优先保留完整访问 URL 到 `access_url`；用于显示或去重的 URL 不能覆盖它。仅有裸 ID 时通过搜索／feed／原始分享链接恢复合法定位信息。
- 用户只要几个讨论观点，完整短帖即可构成证据；需要整串讨论、长文、上下文或评论时才追加对应动作。截断片段与搜索摘要不能代表全文。
- 视频结果先标明 `metadata / subtitles / asr / visual`。字幕或 ASR 能支持口播摘要；讲解界面、演示结果或画面细节需要实际画面证据。拿不到时只完成可证明的部分，不换成另一个视频冒充原目标。
- 已核对的 [Douyin搜索实现](https://github.com/jackwener/opencli/blob/b06ab7780e73d3021e12e0f170086c2d55675776/clis/douyin/search.js#L168-L175) 用 `0` 填充不可见的 plays/comments/shares，这类值应视为未知；不把字段存在当实测。当前命令是否可读取评论或用户视频，仍需核对帮助和实际非空结果。
- 已足够的内容直接交付；仅为影响结论的具体缺口补充必要读取，每个请求有界，不固定限制整个任务只能再请求一次。结果归一化见 [failure-domains.md](failure-domains.md)。

## 失败与浏览器降级

首次使用同一 browser bridge/Profile 时探活，后续复用该任务内结果。连接失败只暂停共享 bridge/Profile 的 browser-backed 命令；站点动作失败只暂停相同 `site+action`；认证失败只影响相同站点／账号；合法空结果和部分证据不触发全局故障。精确规则见 [failure-domains.md](failure-domains.md)。

同一失败路径不循环尝试；业务超时先确认旧动作结束，不自动重派。需要补救时依次考虑已可用的专用 API／CLI、当前 Agent 合适的浏览器，最后 ego lite 的正式 `ego-browser` Skill。必须核对候选是否绕开失败依赖，不能用 `opencli browser` 绕过同一失效 bridge。

宿主浏览器功能名、操作 API、快照和收尾机制按其实际工具／Skill 文档发现，不假设所有 Agent 都有名为 BrowserUse 的工具。ego 只按正式安装 Skill 使用；不复制它的旧 API，见 [ego-space-hooks.md](ego-space-hooks.md)。

## Agent Reach 与维护

Agent Reach 是可选的工具选型、安装与诊断辅助，不是所有请求必经的 OpenCLI 包装层。常用查询直接调用上游工具。只有环境维护、查找其他后端或使用已配置的 `agent-reach transcribe` 时才加载相应资料。

```bash
agent-reach doctor --json
```

doctor 主要说明配置和探测范围；`active_backend: null` 可能是缺工具或刻意跳过实时验证，结合 status/message 判断，不直接宣称平台可用或不可用。已核对的 [Twitter backend 选择代码](https://github.com/Panniantong/Agent-Reach/blob/94f06c1969dfc1834001269d79d3ad0972d9dee6/agent_reach/channels/twitter.py#L44-L77) 仅在 `ok` 时设置 active backend。它也不证明 Lookup 选定的 Profile、账号或具体目标内容可用。

只保留 Lookup 自动接管通用联网检索，Agent Reach 和 OpenCLI `smart-search` 的通用路由 Skill 不同时抢触发；具体平台说明可以按需引用。查询失败不自动升级或重装；维护时记录工具版本与来源 commit，更新后复核必要合约和受影响动作。Agent Reach 的持续维护不等于本机实时更新；已核对的 [`check-update` 实现](https://github.com/Panniantong/Agent-Reach/blob/94f06c1969dfc1834001269d79d3ad0972d9dee6/agent_reach/cli.py#L2271-L2332) 主要比较 Release 版本号，版本号相同也不证明 main 修复已安装。
