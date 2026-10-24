# ego-browser 入口与空间归属

仅在选用 ego lite、空间收尾或旧 hook 兼容时读。普通 API／CLI 读取不加载本文件。

## 按需读取正式执行指南

lookup 选中 Ego 后，先执行 `ego-browser skill` 读取当前应用随包的完整执行指南，使用它声明的启动、任务空间、快照、执行、接管和收尾接口。若 CLI 不可用，可显式读取已保留在自动发现目录之外的原始指南，并核对应用版本；不得为了读取指南重新注册自动触发入口。普通业务错误的 finally 收尾按下文执行；控制权或权限错误必须停止。本文件不复制浏览器 API，也不维护旧 heredoc 片段。

- 浏览器选择统一遵循 [浏览器选路.md](浏览器选路.md)。除本地 Web UI 调试可用 Agent 真正内置的浏览器外，浏览器任务只用 ego-lite；不可用时报告阻塞，不切其他浏览器。
- 只操作本任务实际创建或明确接管的页面／空间。追问可复用同一目标的资源，页面变化后重新观察。
- 用户接管后停止自动操作；不重新夺回控制。
- 收尾依据正式 Skill 与实际资源归属。不能凭 `ownership=agent`、全局闲置时间或另一个客户端的日志批量关闭空间。
- 恢复和收尾只使用创建回执中的编号；`taskSpace(name)` 可能在原空间消失后创建新空间，不用于查存在性或证明关闭。列表为空或编号不存在只能证明当前未发现该空间，不能补造 `finish` 回执。
- 无法取得当前正式执行指南或必需接口时，报告该候选不可用，并继续其他独立路径；自动发现清单中没有 ego-browser 不表示接口不可用。不要用旧 API 猜测或运行整库自制脚本。

## 随包辅助脚本

`scripts/ego-spaces.mjs` 是可选的兼容检查工具，不承担浏览器路由，也不替代正式 Skill。`list` 只做有界诊断，未知会话归属标记为 `cleanupEligible: false`；`close / keep / unkeep` 退出 78，并指向原任务空间的正式收尾接口。

旧 `hook-stop / hook-session-start` 静默成功，不调用浏览器、不写状态，也不阻断客户端；保留旧配置不会触发批量清理。普通安装不自动写入 hook。

当前会话无法证明某个空间归属时只报告，不自动回收。全局 `last-touch` 超过阈值不能证明空间已无人使用，尤其不能推断其他 Agent 会话的资源已过期。

升级旧配置时移除依赖全局闲置时间批量回收的假设；保留用户有意留下的页面与并行会话。不要在此文档复制用户设置、真实会话或 transcript。

## 本任务生命周期入口

整轮只读浏览器脚本通过 `scripts/ego-run.mjs` 执行。为每个用户目标指定独立的 lease 文件和任务标签；同一 lease 同时只允许一个执行者。工作文件导出 `async function(task)`，只通过传入的 TaskSpace 操作页面，不自行创建其他空间。

```js
// work.mjs
export default async function(task) {
  const page = task.page('p1');
  await page.goto('https://example.com', {timeout: 15000});
  return {title: await page.title()};
}
```

```bash
node scripts/ego-run.mjs run /absolute/task/lease.json "Read example" /absolute/task/work.mjs
node scripts/ego-run.mjs finish /absolute/task/lease.json
node tests/test_ego_task.mjs
```

`run` 在创建前记录随机唯一名字，创建后记录编号；成功、页面错误及导航超时都进入 finally。`finish` 只读取指定 lease，逐一核对精确名字、编号、创建者和当前控制权，再调用一次原生 `finish`；等待回执与有界列表读回确认。用户创建或未知来源标签由浏览器原生保护，不逐页强关。

多轮交互在 ego 的 Node runtime 动态导入安装目录的 `scripts/ego-task.mjs`。首轮调用 `openOwnedTask({taskSpace, listTaskSpaces}, {leasePath, label})`，以后仅复用该记录的编号；目标结束调用 `finishOwnedTask`。需要用户操作时按正式 Skill 交接并停止，不能因为页面还在就继续控制。显式指定浏览器 Profile 时，可向首轮传入已核实的 `profileId`。

为 CLI 辅助人工登录时，先按 [登录准备与恢复](opencli-windows.md#登录准备与恢复) 核对原绑定环境。等待用户期间使用正式交接机制并保留 lease，不用会在成功返回后自动收尾的整轮 `run` 承载等待；交回后按登录流程恢复原 CLI，再核对可收尾的本任务资源。

CLI 等待上限为60秒，超时不证明浏览器执行已取消。进程被杀或创建回执丢失时保留 lease；后续 `finish` 仅核对该记录，不扫描其他空间。`run` 遇到未结束的记录只做该记录的恢复收尾，本轮不开始新业务；若确认关闭，下一轮可重新执行。收尾已发出但回执丢失时不得重复调用 `finish`。

`user_control`、`denied`、`protected_tabs` 和 `uncertain` 均保留记录并暂停自动操作，不以新空间绕过。维护者须核对实际空间及原操作是否结束；只有用户明确恢复控制，或原空间已确认消失且没有迟到操作，才可归档旧 lease 并开始新目标。不得仅按标题、域名、`ownership=agent` 或闲置时长猜测归属。

整轮脚本的收尾只覆盖本入口实际创建的空间；旧空间没有 lease 时须由原任务的创建记录证明归属，再按正式接口单独收尾。没有关闭回执和列表确认时，交付说明必须写明空间尚未确认释放。
