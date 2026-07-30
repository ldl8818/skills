# OpenCLI 的容器窗口为什么关不掉

SKILL.md 只留结论和探活命令。本文是机制细节，用户抱怨「又多了空白窗口」、或你想找个办法关掉它们时读——**结论是关不掉，别再找了，只能靠不触发。**

## 它绕过了 Space 机制

OpenCLI 是标准 Chrome 扩展，用 tabs/windows API 开普通窗口，不受 ego 的 Space 隔离约束。所以 `completeTaskSpace()` 回收不到它——那个只管 ego 的 task space。把 OpenCLI 留下的窗口误判成「task space 没收尾」会导致你反复检查错的地方。

扩展按 role 维护两个「容器窗口」（`ownedContainers`，`chrome.windows.create` 建 1280x900 普通窗口），role 由命令的 surface 决定：

| 容器 role | 谁触发 | 默认焦点 | 橙色「OpenCLI Browser」标签组 | 注册表丢失后 |
|---|---|---|---|---|
| `automation` | 适配器命令（六平台 search 等） | background | 无 | **无法再识别，下条命令新建 → 孤儿累积** |
| `interactive` | `opencli browser ...`、`opencli doctor` | **foreground（抢焦点弹窗）** | 有 | 能按标签组标题全局找回，有限自愈 |

`automation` 那一列的「孤儿累积」是窗口越堆越多的真正来源：注册表一丢，已存在的窗口再也认不出来，下条命令又建一个新的。

## 为什么没有关闭路径

扩展在 `releaseLease()` 里把最后一个标签导航回 `about:blank` 当可复用占位符，**全文件没有一处 `chrome.windows.remove`**。实测 `opencli browser <sess> close` 和 `opencli browser tab close` 都只释放 lease，窗口不动；那个占位标签在 `tab list` 里根本不出现，所以你也看不到它。

`--window background` 只管抢不抢焦点，**消不掉窗口本身**。

## 探活别用 doctor

`opencli doctor` 硬编码 `surface: 'browser'` 且没有 `--window` 选项，每跑一次就在用户面前弹一个前台空白窗口并永久留下。

确实需要 doctor 的详细诊断时，前面加 `OPENCLI_WINDOW=background`（`sendCommandRaw` 读这个环境变量）压掉抢焦点——但窗口仍会创建并留下，这只是让它不打断用户。

零窗口的替代见 SKILL.md 的探活 curl。另外 `opencli profile list` 和 `opencli daemon status` 也零窗口，但它们只读 daemon 记忆里的连接状态、不做端到端往返，只能用来看「daemon 起没起」。
