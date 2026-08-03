# 失效域分层与候选台账

SKILL.md 只留判据（L3/L4 上 ego-browser、L1/L2 才是真没路）。本文是那条判据的推导过程和统计依据，排查通道故障、或要评估「加一条新通道值不值」时读。

## 四层模型

```
L1  ego lite 浏览器进程          ← OpenCLI 与 ego-browser 共享
L2  Profile 登录态 / 账号风控     ← OpenCLI 与 ego-browser 共享
L3  OpenCLI daemon + 扩展         ← 只有 OpenCLI 依赖
L4  OpenCLI 站点适配器逻辑        ← 只有 OpenCLI 依赖
```

**ego-browser 的依赖是 OpenCLI 依赖的真子集。**所以 L3、L4 故障时它照样能取——而这两层恰恰最容易坏：适配器跟不上平台改版、扩展断连、daemon 没起。「共享同一个浏览器所以降级无意义」是错的，只在 L1/L2 才成立。

| OpenCLI 失败形态 | ego-browser 能救 |
|---|---|
| 返回空、字段缺失、结构变了（L4） | ✅ 直接读页面 |
| `Extension: not connected`、daemon 无响应（L3） | ✅ 不走那条通道 |
| `AUTH_REQUIRED`、账号被风控（L2） | ❌ 换它也一样没登录 |
| ego lite 进程没起或崩了（L1） | ❌ 它也要这个浏览器 |

分层判据（这几行也在 SKILL.md，此处保留是为了本文自足）：探活 curl 返回非 `ok:true` 是 L3；探活通了但取数为空是 L4；平台报 `AUTH_REQUIRED` 是 L2。登录态用 `opencli auth status --site <site> --timeout 8 -f json` 有界检查。别为了分层去跑 `opencli doctor`——它会留下一个关不掉的空白窗口，见 `opencli-windows.md` 。

## 什么才算真正的独立失效域

判据是**不经 ego lite、不共享登录态**（即绕开 L1+L2），不是「换了个工具名」。同在 `ego-lite-browser` 域下的两个 provider 会被 ego lite 崩溃、Profile 损坏或账号风控同时带走，互相顶不了班。

目前只有两处真降级：

- B站搜索：`bili` 直连 ⇄ OpenCLI
- 任意网页：`fetch.sh` 本机 ⇄ Jina Reader 远端

## 集中度：单点在哪

| 事实 | 数字 |
|---|---|
| 有真降级（≥2 个不同失效域）的 action | **2 / 19（11%）** |
| 单点压在 `ego-lite-browser` 上的 action | **10 个** |

那 10 个是：X 的 search / article / thread / tweets、小红书的 search / detail / comments、Douyin search、B站 subtitle、公众号 search。公众号 search 还叠加搜狗上游失效域。

**ego lite 一挂，X、小红书、Douyin、公众号四个平台全部瘫痪，B站只剩搜索。**

X、小红书、Douyin、公众号在 L1/L2 层是客观单点，补它需要的是不走 ego lite 的独立实现——换个 OpenCLI 子命令或换 ego-browser 都不算补。

正因为存在这 10 个单点，**通道连续失败不等于该弃用它**：只有当同一 action 还有另一条失效域不同的候选时，绕开才有意义；单候选 action 上放弃等于自断退路，此时该做的是报告失败形态、请用户处理 L1/L2，而不是找替代。`AUTH_REQUIRED` 更不该计入通道故障——它是登录态问题。

## providers.json 是什么

`references/providers.json` 记录 19 个 action 的跨工具优先级、必要合约、字段裁剪、失效域归属和校验器，上面两个统计数字由它算出。

它不是执行器：运行时路由由 Agent 决定，OpenCLI 命令事实来自 `opencli list -f json`。`scripts/selftest.sh` 只读取其中 `type: opencli` 的必要合约，检查当前注册表是否仍存在对应命令、是否仍为只读、必要参数和输出字段是否还在。

维护规则：

1. OpenCLI 升级后先跑 selftest；命令签名变化由实时注册表暴露，不手改一份完整镜像。
2. 只有跨工具优先级、必要参数、必要字段、校验器或失效域变化时才改 providers.json。
3. 用户可见的选路和失败行为变化时，同步 `SKILL.md`、匹配的 routing reference 与 README。
