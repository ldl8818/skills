# 平台检索路由

用于 X、YouTube、小红书、B站、公众号、Douyin 及临时请求的其他平台。命令事实以 OpenCLI 当前注册表为准，本文只保存稳定策略和必须覆写的默认值。

## 目录

- [通用发现流程](#通用发现流程)
- [六个平台速查](#六个平台速查)
- [时效与正文](#时效与正文)
- [OpenCLI 失败处理](#opencli-失败处理)
- [Agent-Reach 的位置](#agent-reach-的位置)
- [浏览器兜底](#浏览器兜底)

## 通用发现流程

1. 从注册表确认站点、动作、读写权限和依赖：

   ```bash
   opencli list -f json | jq --arg site "<site>" \
     '[.[] | select(.site == $site and .access == "read") | {site,name,strategy,browser,domain,args,columns}]'
   ```

2. 只选 `access: read`，再读取命令的当前参数。download、export 等本地落盘命令另看 `local_effect`，不能仅凭 read 自动执行：

   ```bash
   opencli <site> <command> --help -f yaml
   ```

3. adapter 存在且正好覆盖目标时先用 adapter；不存在所需动作时直接换其他 CLI、API 或 ego-browser，不空试。
4. 列表输出用 JSON 并裁字段；正文命令可用 `plain`。搜索列表不能直接当正文。
5. 命中 `AUTH_REQUIRED` 是 L2，不切 ego-browser；结构变化、空结果和适配器异常才是 L4。

OpenCLI 注册表是命令签名的事实源；`references/providers.json` 只记录跨工具优先级、失败域、必要参数和验收条件。

## 六个平台速查

下表保存经过验证的首选动作和不可省略的策略参数。执行前仍需从注册表核对当前命令。

| 平台 | 搜索／发现 | 正文／详情 | 稳定约束 |
|---|---|---|---|
| X | `twitter/search` | `twitter/article`、`twitter/thread`、`twitter/tweets` | 最新搜索显式传 `--product live`；看某人用 `tweets`，不用 `timeline` |
| YouTube | `yt-dlp ytsearch` | `yt-dlp` 字幕 | 直连失效域独立于 ego lite；字幕读 `youtube-subtitles.md` |
| 小红书 | `xiaohongshu/search` | `xiaohongshu/note`、`xiaohongshu/comments` | 从搜索结果取完整 URL／ID，再读正文 |
| B站 | `bili search` | `bilibili/subtitle` | 搜索优先免登录 `bili`；不要用 yt-dlp 抓 B站 |
| 公众号 | `weixin/search` | ego-browser 跳转后取 DOM | 搜索返回搜狗跳转链，正文读 `weixin-article.md`；归档另走显式落盘流程 |
| Douyin | `douyin/search` | 以搜索结果可见内容为限 | 结果没有发布时间，不能证明「最近」 |

常用命令示例：

```bash
opencli twitter search "<词>" --product live -f json --limit 5 --window background
opencli twitter article <tweet-id> -f plain --window background
opencli twitter thread <tweet-id> -f json --window background
opencli twitter tweets <用户名> -f json --limit 20 --window background

yt-dlp "ytsearch5:<词>" --flat-playlist --print "%(title)s\t%(channel)s\t%(duration_string)s\t%(url)s"

opencli xiaohongshu search "<词>" -f json --limit 5 --window background
opencli xiaohongshu note <完整URL或ID> -f plain --window background
opencli xiaohongshu comments <note-id> -f json --window background

bili search "<词>" --type video -n 5
opencli bilibili subtitle <BV号> -f json --window background

opencli weixin search "<词>" -f json --limit 5 --window background
opencli douyin search "<词>" -f json --limit 5 --window background
```

`--window background` 只控制焦点，不保证不创建 automation 容器窗口。不要把它描述成无窗口模式。

`weixin/download` 虽然在注册表中是 `access: read`，但会创建目录和文件；普通正文读取不得把它当自动 fallback。只有用户明确要求归档时，才显式指定输出目录并关闭不需要的图片下载。

## 时效与正文

- X `search` 默认热门排序；用户问最新时必须用 `--product live`。
- Douyin 结果没有时间字段；交付时明确写「无法证明发布时间」，不能按播放量猜新旧。
- 小红书当前搜索字段包含 `published_at`，仍要检查实际值是否存在，不能只看 schema。
- 公众号搜索的 `publish_time` 可用于初筛；搜狗跳转链本身不是正文。
- 六个平台的搜索结果都是列表；用户要「讲了什么、怎么评价、完整内容」时必须再取正文、帖子串、详情、评论或字幕。

## OpenCLI 失败处理

先按结构化错误和失效层级处理：

- `auth_required`：L2，核对 `opencli auth status --site <site> --timeout 8 -f json`；不换同登录态浏览器。
- daemon／extension 失败：L3，改用 ego-browser。
- 命令存在但字段缺失、空结果、解析异常：L4；重试一次并加 `--trace retain-on-failure`，仍失败改用 ego-browser。
- 命令不存在：不猜旧命令；回注册表找同目标的只读动作，找不到就换工具。

不要用 `opencli verify --smoke` 证明真实平台可用；当前发布包的 smoke 依赖环境测试目录，不能替代实际请求。`convention-audit` 面向 adapter 开发，不作为日常路由门禁。

## Agent-Reach 的位置

Agent-Reach 是安装、选型和跨工具体检层；读取仍由上游工具执行。它的 Skill 保持禁用，避免与 lookup 抢「搜索、URL、平台」触发词。

遇到以下情况才用：

- 用户明确请求六平台之外的 Agent-Reach 渠道；
- 不确定某个平台当前有哪些非 OpenCLI 后端；
- 需要判断 CLI、MCP、登录配置是否存在。

```bash
agent-reach doctor --json
```

`status: warn` 或 `active_backend: null` 只表示 doctor 没有完成实时验证，不等于通道不可用。继续检查实际 CLI 注册表、登录态和最小只读请求。不要因为 doctor 的配置级结果跳过真实验证。

Agent-Reach 更新可能重新生成并启用它自己的 Skill；更新后重新确认启停状态。它的参考命令可按需读取，但运行时触发权只留给 lookup。

## 浏览器兜底

OpenCLI adapter 有精确动作时先用它；没有动作，或 L3/L4 失败时用 ego-browser。不要改用 `opencli browser` 作为故障兜底，因为它与 adapter 同样依赖 L3，且 owned container 的窗口不能可靠回收。

ego-browser 执行纪律：

- 一个用户目标只开一个 task space；追问、重试、验证继续复用。
- 在一个 heredoc 内完成能确定的多步读取，减少往返。
- 页面变化后重新观察，不复用旧 selector／ref。
- 结束时独占最后一次调用执行 `completeTaskSpace(id, { keep: false })`。
- 用户接管时立即停止；不得调用跨 space CDP 关闭其他 target。
