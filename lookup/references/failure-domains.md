# 失败作用域与结果验收

遇到失败时先保留命令结果，再判断哪一条依赖坏了。不同工具可能共享浏览器、账号或网络；同一个 OpenCLI 的不同站点动作也不一定一起失败。

## 作用域

| 层或结果 | 证据 | 本任务的处理范围 |
|---|---|---|
| 浏览器进程／网络 | 进程不可达或已确认共同网络失败 | 暂停依赖该进程／网络的候选；检查已授权且实际独立的通道 |
| bridge + Profile | 门禁失败、结构化 `BROWSER_CONNECT` 或 Profile 未绑定／断连／错配 | 暂停共享该 bridge/Profile 的 browser-backed OpenCLI；不同已配置连接独立判断 |
| 站点 + 账号 | `AUTH_REQUIRED`、会话失效或账号挑战 | 暂停该站点／账号；不靠换同登录态浏览器重试，不擅自换账号或读取 Cookie |
| site + action | 命令缺失、结构漂移、解析异常、动作不支持 | 只暂停该动作；其他站点和独立动作继续 |
| `empty` | 请求成功且确认没有匹配项 | 如实报告，必要时调整一次查询范围；不是故障 |
| `partial` | 未证实空结果、关键字段缺失、截断或证据只覆盖部分问题 | 保留已验证部分；只为缺口补充相关读取，不全局熔断 |

Profile 选择由 `LOOKUP_OPENCLI_PROFILE` 决定，默认 `ego-lite`。`scripts/opencli-health.sh` 检查这一 Profile 的 bridge 状态；daemon 休眠可按需启动，但不发平台查询。门禁 ready 不能证明平台登录态、具体动作或内容通过。

`LOOKUP_OPENCLI_TIMEOUT_MS` 是包含入口加载的整次调用等待预算；到期意味着结果未知，不等于未执行。先确认旧动作结束，再决定是否换路，避免并发重派同一动作。入口加载超时由 `OPENCLI_RUN_IMPORT_TIMEOUT_MS` 控制，与业务超时分开。

## 有界恢复

1. 记录 provider、选定 Profile、动作、exit code、stdout、stderr 和已知错误码，不只保留 stdout。
2. 同一候选动作的普通失败，最多追加一次有明确依据的重试；验证码、认证失效、账号风控和共享连接已失败时不盲重试。为正文、评论、发布时间等不同证据缺口执行必要读取不算重复重试，取够即停。
3. 替换候选时明确绕开哪条失败依赖。优先可用专用 API／CLI；浏览器按 [浏览器选路.md](浏览器选路.md) 的任务条件选择，不把默认 ego-browser 当成所有故障的唯一恢复路径。
4. 暂停状态仅存在于本次任务，并按上述作用域记录；下一独立任务重新探活。历史失败保留日期与版本，不能永久禁用候选。
5. 平台读取任务不自动升级、重装或修复环境；用户明确要求排障时再使用 trace、doctor 和维护流程。

例如，小红书 `note` 解析失败不阻止 X 搜索；选定 Profile 的 bridge 断连会影响使用它的两个平台；小红书 Cookie 失效不证明 X 账号失效。真实无匹配、缺少发布时间、登录失败和目标已删除也不能互相代替。

## 哪些降级有效

| 候选路径 | 可绕开的依赖 | 仍可能共享的依赖 |
|---|---|---|
| 原站 HTTP／专用 CLI | 浏览器进程、扩展与 DOM 适配器 | 原站限制、本机网络、显式配置的账号 |
| OpenCLI → 宿主浏览器 | 若宿主实现不同，可绕开 OpenCLI adapter／bridge | 必须实际核对浏览器、Profile 与账号 |
| OpenCLI → 同一 ego 的 ego-browser | 可绕开 OpenCLI adapter／bridge | ego 进程与该 Profile 登录态 |
| 本机 fetch → 第三方 reader | 本机 HTTP 实现及部分网络限制 | 原站限制、第三方配额与数据外发边界 |

HTTP 403／429、网关错误或验证页只证明当前通道失败，不能据此声称内容不存在。切工具不能绕开用户授权、登录要求或账号风险限制。

## 统一结果语义

`scripts/normalize-result.py` 从 stdin 读取已捕获的信封：

```json
{
  "provider": "opencli/douyin/search",
  "exit_code": 0,
  "stdout": [],
  "stderr": "",
  "url": null,
  "access_url": null,
  "evidence_type": "metadata",
  "empty_confirmed": false,
  "truncated": false,
  "missing_fields": []
}
```

只把工具实际捕获的值写入信封，不能用丢弃 exit code/stderr 的 stdout 管道冒充完整结果。helper 按需输出 `ok / empty / partial / error`，保留 items 或 text 与证据字段；它不是调度器、登录检测器或真实性证明。归一化脚本 exit 0 只说明信封处理完成，查询成败以返回 JSON 的 `status` 为准。

`stdout_format` 可选为 `json / text / auto`；已知 `lookup/fetch` 和 `lookup/subtitles` 默认按文本处理，其他 provider 默认自动判断。明确取得的自由文本可传 `text`，避免将方括号开头的正文误当 JSON。

- `url` 用于出处；`access_url` 保留后续访问必须的完整参数，两者不可盲目互换。
- 时间、作者或互动数缺失时保持未知；已知上游占位零不能当成真实零。
- `full_text / excerpt / metadata / comments / subtitles / asr / visual` 区分证据类型；只有标题、口播或字幕不能证明画面细节。
- 已确认无匹配可标 `empty`；未经证实的空数组标 `partial`，不推断全部通道故障。`lookup/find-url` 的 JSON 书签／历史集合会分别保留 `collection`，只采信该脚本 stderr 的确认空状态；exit 3 的有界预览仍为 `partial`。
- 同一结果可支持部分结论；只有缺失部分影响判断时才继续请求。
- helper 仅使用 Python 标准库；识别完整 JSON，以及上游提示之后由本地 runner 输出的最后一行严格 JSON 错误信封；另识别 OpenCLI 严格的 YAML `error / code` 子集，不依赖 PyYAML。其他格式由调用方保留原始 stderr，helper 仅给出 `UNKNOWN` 分类，不复制可能含敏感信息的原始消息；不靠文案猜测故障类别。

## 策略台账维护

`references/providers.json` 是必要合约和任务边界资料，不保存可执行命令模板；候选按数组顺序列出，实际筛选见 [任务选路.md](任务选路.md)，不自动执行或降级。`scripts/selftest.sh` 只读取 OpenCLI 必要合约，与实时注册表比较；不证明返回内容、账号或所有平台可用。

只维护跨工具优先级、必要字段、授权／证据边界与失效作用域，不复制整个 OpenCLI 注册表。升级后检查安装版本、必要合约与受影响的最小真实场景；报告哪些未验证，不维护容易过期的固定成功率或单点统计。
