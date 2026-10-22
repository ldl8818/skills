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

## 浏览器接口与资源

选路确定使用 OpenCLI Browser 后，直接读取安装包匹配的执行文档：

```bash
node scripts/opencli-run.mjs skills read opencli-browser -f plain
node scripts/opencli-run.mjs browser <command> --help -f json
```

不为读取执行文档再安装一个自动触发的通用路由 Skill。页面会话、frame、等待、截图与动作参数以上述当前文档为准；Lookup 不复制另一份 API 手册。

接口返回空列表或执行回执时，仍按 [动态页面读取](动态页面读取.md) 与 [媒体读取](媒体读取.md) 核对目标；工具声明支持 frame、点击或视频不等于当前页面已通过这些能力的验证。

一次任务使用自己的 `--session`，只操作明确归属的页面。多步浏览器任务结束时执行该 session 的 `browser close`；一次性 adapter 使用帮助支持的 `--site-session ephemeral --keep-tab false`，由 runner 开启原生 owned tab 清理。`--window background` 只控制焦点。

清理必须有上游回执；警告或未知结果单独核对。旧扩展可能拒绝清理；不要把已取得业务结果重派，也不要强关未知页面或停止共享 daemon。bound 用户页面按原生解绑规则保留。

## 连接诊断

`bash scripts/opencli-health.sh` 委托原生 `doctor`，仅将报告转换为门禁结果，不探测固定端口、读取 Profile 内部文件、启动或杀死 daemon。doctor 可以按需启动 daemon，并用专用探针验证 bridge；不发目标站点业务查询。

正常读取不强制先做全环境体检；有连接疑点或执行 selftest 时再调用。必须同时核对 `daemonRunning`、`extensionConnected`、`connectivity.ok` 及 stale／flaky 状态，doctor 的退出0与外层 `ok:true` 只说明报告生成成功。通过仍不证明站点登录、动作能力或正文完整。

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
