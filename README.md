# Skills

可复用的个人 Agent Skills。

| Skill | 用途 |
|---|---|
| [`neat-freak`](neat-freak/) | 项目文档与规则对齐、任务清理及交接；自管冻结版 |
| [`check`](check/) | 基于 Alibaba 官方 Skill 的完整代码审查；动态覆盖文档、测试和未跟踪文件 |
| [`health`](health/) | Agent 指令、配置、工具与验证器健康审计 |
| [`hunt`](hunt/) | 软件故障诊断、修复与验证；按需衔接 check 审查受影响修改 |
| [`ui`](ui/) | 产品界面创建、视觉修改与真实渲染验证 |
| [`write`](write/) | 明确要求的文案起草、改写和本地化 |
| [`lookup`](lookup/) | 联网检索、正文读取与多来源研究综合；专用入口优先，按失效域降级并核验来源 |
| [`self-improving`](self-improving/) | Claude Code 与 Codex 共用的可配置、自我进化记忆系统；公开程序与私人记忆分离 |
| [`skill-manager`](skill-manager/) | Skill 的列出、溯源、查更新、更新、启停、定版本、自检和归档删除 |
| [`download-video`](download-video/) | 按中文内容标题和发布日期下载视频，并用 `ffprobe` 验证本地文件 |

每个 Skill 的依赖、安装和验证命令以其目录内的 `README.md` 与 `SKILL.md` 为准。

代码审查统一使用 `check`，主流程基于 [Alibaba 官方 OpenCodeReview Skill](check/NOTICE.md)，默认调用完整 `ocr review`，明确的全文或全项目审计使用 `ocr scan`。按任务动态覆盖代码、Markdown／配套文档、测试和未跟踪文件，并对 OCR 漏选或无法处理的范围补查。完整引擎需要单独安装的原生 OCR 和可用模型端点；缺少依赖时明确报告“完整 OCR 未运行”，当前 Agent 可继续已授权的补充检查、修复和验证。配置、资源预算及执行验收见 [接入说明](check/references/open-code-review.md)。排查 Bug 使用 `hunt`，必要时衔接 `check` 审查受影响修改，再验证原故障路径。

## 命令

`commands/` 保存显式调用的普通命令文档，不注册为 Skill。

- [push](commands/push.md)：统一由主 Agent 直接提交并推送，不启动执行子 Agent。低风险走最低必要检查，标准档定向检查受影响部分，复用已有验证。指定范围时遵循指定；省略范围时，待提交任务全部完成则按任务分批提交，存在未完成或状态不明任务则仅处理本次任务。完成判断、最低检查及按需场景表见命令正文。
- 普通文案提交只做局部检查与 Git 结果核验，复用已有上下文和验证；无明确适用门禁时不跑全仓检查。普通 push 不等待 CI 终态、不自动修复 CI；推送、本地检查与 CI 结果分别报告，项目明确要求的门禁仍保留。
- 本机 Claude Code 与 WorkBuddy 输入 `/push`；Codex CLI／IDE／桌面应用输入“执行push”。通过 chezmoi 将 `~/.claude/commands/push.md`、`~/.agents/commands/push.md`、`~/.workbuddy-ai/commands/push.md` 单跳链接到本仓库真身，全局规则提供 Codex 按需入口。新机器需先取得本仓库并部署对应链接／规则；执行只需当前客户端的终端能力及 Git 认证，不依赖另一模型或客户端。
- [Codex 自定义 prompts](https://developers.openai.com/codex/custom-prompts/) 已弃用，本机 CLI 0.154.0 实测不识别 `/prompts:push`，因此不将它作为可用入口。Claude Code 的 [commands Markdown 格式](https://code.claude.com/docs/en/skills#where-skills-live) 仍受支持。新装后重启客户端／新开会话加载入口。

五个定制 Skill 独立维护为本地冻结版，当前 `hunt` 为4.2.0，`check` 为5.0.0，`health` 为4.0.2，`ui`、`write` 为4.0.1，`check` 当前主体采用 Alibaba Apache-2.0 源码，保留之前 Waza 改造历史及留用材料的 MIT 许可；其余四个保留 Waza MIT 许可与来源 commit。安装、恢复和上游选择性合并见 [冻结版本维护](skill-manager/references/冻结版本维护.md)。本仓库按独立 Skill 分发，没有 Waza 整仓的 plugin mirror 或 Desktop bundle。
