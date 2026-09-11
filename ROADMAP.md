# ROADMAP

仓库导航见 `README.md`，开发规范见 `CLAUDE.md`。本文只记真实进度：当前阶段、待办、阻塞、最近验证。已完成的工作以 git 历史和 PR 为档案，不在本文重复列举。

## 当前阶段

四个 Skill 已纳入仓库：`lookup` 1.9.0、`self-improving` 3.1.2、`skill-manager` 2.6.5，以及尚未定版的 `download-video`。前三个已有本机运行记录；`download-video` 已完成脚本级基础验证，实际站点下载待用户提供链接后验证。

## 最近完成

- 2026-09-11 13:34：只读 Hook 误拦修复按独立补丁交付；增加前缀判断与负数下标识别，按独立命令匹配解释器引用，管道输入保持关联。保留现行普通 Markdown 维护及审批账本保护。

- 2026-09-10 19:48：旧 `corrections.md` 支持归档且不在已有标记目录重新初始化时重建；普通 Markdown 修改和移动放行，审批账本与审核命令继续受保护；版本3.1.2及受众文档已同步。

- 2026-09-10 16:56：修复 Python 只读检查因提及受保护文件名被误拦截；使用完整命令及受限 AST 识别，未知代码、Shell 拼接、真实写入与审核继续沿用保护。同步 Hook、架构、教程和排错说明，未变更审批记录。

## 待办

### lookup · OpenCLI doctor 零窗口修复后复核版本分界

**触发条件**：上游 PR `jackwener/OpenCLI#2206` 合并、`@jackwener/opencli` 发布含该修复的版本、且本机已升级到该版本。三条同时满足才启动。

**要做的事**：

1. 改写 `lookup/references/opencli-windows.md` 的「探活别用 doctor」一节，标明版本分界——`opencli doctor` 弹前台空白窗口并永久留下的描述只适用于 1.8.6 及以前，修复版本起 `checkConnectivity()` 改用无窗口 cookies 探针，不再创建容器窗口。
2. 复核 `lookup/SKILL.md` 的「不用 `opencli doctor` 做日常探活」是否仍需保留。当前判断是保留：`scripts/selftest.sh` 另外覆盖本地依赖、OpenCLI 注册表合约和有界登录态，doctor 修好也替代不了。动手前重新确认这条理由是否还成立。

**不受影响的结论**：PR #2206 只修 doctor 一条路径，扩展的 `releaseLease()` 仍无 `chrome.windows.remove`，`automation` 容器注册表丢失后仍无法找回。因此 `opencli-windows.md` 的核心判断「容器窗口关不掉，只能靠不触发」不变，`scripts/selftest.sh` 的零窗口探针不需要改动——它与 PR 采用同一个 `cookies` 动作，且不依赖 opencli 版本。

## 阻塞

- 上游 issue `jackwener/OpenCLI#2202` 与 PR `#2206` 自 2026-07-31 起无维护者响应：零 review、零评论、CI 未运行、无 assignee。上述待办在上游合并前无法启动。

## 最近验证

- 2026-09-11 13:34：仅含本次补丁的隔离快照87项测试通过；原误拦4处红灯、管道回归1处红灯均先复现再修复。未纳入知识治理改动，安装包只读识别 smoke 通过；远端 CI 以对应提交运行结果为准。

- 2026-09-10 19:48：隔离提交运行 `python3 -m unittest discover -s tests`，84项通过；`compileall`、公开隐私词扫描和 `git diff --check` 通过。

- 2026-09-10 17:05：提交前隔离验证只读守卫；补充排序与 JSON 回调的动态执行边界，回归先复现后修复。另一知识治理任务的代码、版本和文档变更不纳入本次提交。

- 2026-09-10 16:56：新增只读保护回归测试先复现4处失败，修复后本版本81项通过；与 knowledge-governance 快照组合102项通过。实际 Codex Hook 放行 Python 只读检查，写入／删除／改名／动态执行／审批保护由测试验证。`git diff --check` 通过。`sync --check` 发现现有知识索引差异，doctor 另报旧引用、核心记忆时效和错误库体积告警；留给并行知识治理任务，本次未重写私人索引。

- 2026-09-10 00:37：新增 `download-video` Skill，已通过 Python 编译检查和合成参数／核心函数 smoke；未进行实际站点下载验证。
- 2026-09-10 00:37：同步仓库导航与 Skill 当前版本快照；`lookup` 的 OpenCLI 版本分界说明保留为上游 PR #2206 合并及本机升级后的待复核事项，当前状态未作实时上游确认。
- 2026-09-10 00:25：修复 skill-manager 保留本地描述时遗留上游多行正文的问题；新增回归测试先复现失败，修复后全套53项通过。已安装 neat-freak 的 YAML 解析通过，中文描述与正文保持不变；客户端重新加载待确认。
- 2026-09-10 00:25：对已登记的全局、项目、内置和插件 Skill 做 YAML 及必需字段检查，141个独立文件中139个通过；t、ts 的描述行混入作者字段，仍有2个格式问题，本轮仅报告。
- 2026-08-07：核对 `@jackwener/opencli` 本机安装版本与 npm 最新版本均为 1.8.6；PR #2206 状态 OPEN，`mergedAt` 为空。
