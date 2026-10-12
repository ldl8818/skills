# OpenCLI 诊断与窗口版本差异

仅在诊断连接、窗口残留或升级兼容性时读。先记录安装版本与实际实现，历史问题不能直接套用到新版本。

## doctor 的当前依据

旧文档把 `opencli doctor` 一律描述成会创建无法关闭的前台窗口，已不适用于核对过的新实现。

2026-10-12 检查的 OpenCLI main `b06ab7780e73d3021e12e0f170086c2d55675776` 中，[`checkConnectivity()`](https://github.com/jackwener/opencli/blob/b06ab7780e73d3021e12e0f170086c2d55675776/src/doctor.ts#L81-L99) 使用 `cookies` 探针与 `opencli-probe.invalid`，不通过新标签页测试连通性。它仍可能按需启动 daemon；不创建测试页不等于整个命令没有本地副作用。

日常查询用 `scripts/opencli-health.sh` 检查 Lookup 选定 bridge/Profile；用户明确排障时可在理解安装版本的情况下运行 doctor。不要为遵守旧禁令而放弃有效诊断，也不要只用版本号推定目标内容可读。

## 平台动作与窗口归属

OpenCLI adapter、OpenCLI 通用 browser 和宿主浏览器可能使用不同的标签／容器管理机制。依据当前工具公开接口判断哪些资源属于本任务，不把所有窗口都当 ego task space。

- `--window background` 控制焦点，不承诺无窗口。
- bridge/Profile 健康只说明连接，不能代替平台登录态和业务结果验收。
- OpenCLI bridge 故障时 `opencli browser` 通常仍共享该依赖，不能作为独立 fallback；换当前宿主合适浏览器，再考虑 ego-browser。
- 窗口或任务空间回收按实际创建者的正式接口和归属处理。没有归属证据时只报告，不跨会话关闭标签、不杀共享浏览器或 daemon。
- ego 正式 Skill 的版本化接口见 [ego-space-hooks.md](ego-space-hooks.md)，这里不复制 API。

## 更新兼容层

`opencli-run.mjs` 只做选定 Profile、异步入口兼容与有界等待，不替代上游平台逻辑。`LOOKUP_OPENCLI_PROFILE` 默认 `ego-lite`；继承的另一个 `OPENCLI_PROFILE` 不得把任务切到别的账号。

当前 helper 对非空 `OPENCLI_CDP_ENDPOINT` 拒绝执行，避免未声明地换到另一浏览器 transport。需要 CDP 环境时应明确核对支持并补充独立验证，不能靠环境变量偷偷跳过 Profile 门禁。

入口加载默认 15 秒，由 `OPENCLI_RUN_IMPORT_TIMEOUT_MS` 控制；整个调用的等待预算默认 90 秒，由 `LOOKUP_OPENCLI_TIMEOUT_MS` 控制，包含加载阶段。业务超时不证明服务端未执行，不能自动重派。

当前兼容补丁只覆盖已核对的 `@jackwener/opencli` 1.8.6–1.8.8，且必须识别到磁盘入口仍调用同步 `runCli().parse()`。版本、包归属或入口特征变化时退出 78／`COMPAT_UNVERIFIED`，不盲目继续 patch；按新安装源码重新验证，若上游已正确等待 `parseAsync` 就移除补丁。具体平台逻辑继续由上游维护。

`OPENCLI_CONFIG_DIR` 可指定已配置的 OpenCLI 目录，`OPENCLI_DAEMON_PORT` 可指定 daemon 端口；health 与 runner 必须使用同一环境。不要把改端口或 Profile 当作绕过失败依赖的证明。
