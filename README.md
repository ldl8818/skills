# Skills

可复用的个人 Agent Skills。

| Skill | 用途 |
|---|---|
| [`neat-freak`](neat-freak/) | 项目文档与规则对齐、任务清理及交接；自管冻结版 |
| [`check`](check/) | Waza 衍生的风险分级审查；轻量直查，复杂业务审查按需使用 Alibaba OCR |
| [`health`](health/) | Agent 指令、配置、工具、验证器及 AI 协作可维护性审计 |
| [`hunt`](hunt/) | 软件故障诊断、修复与验证；按需衔接 check 审查受影响修改 |
| [`think`](think/) | 价值判断、架构方案与可执行交接计划；保留完整上游原版 |
| [`ui`](ui/) | 产品界面创建、视觉修改与真实渲染验证 |
| [`write`](write/) | 明确要求的文案起草、改写和本地化 |
| [`lookup`](lookup/) | 融合 Agent Reach 和 OpenCLI 全部能力的联网与浏览器统一入口；按需执行、配置、开发维护及更新 lookup 本体与上游 |
| [`self-improving`](self-improving/) | Claude Code 与 Codex 共用的可配置、自我进化记忆系统；公开程序与私人记忆分离 |
| [`skill-manager`](skill-manager/) | Skill 的列出、溯源、查更新、更新、启停、定版本、自检和归档删除 |
| [`download-video`](download-video/) | 按中文内容标题和发布日期下载视频，并用 `ffprobe` 验证本地文件 |
| [`luobo-ppt`](luobo-ppt/) | 生成与美化可编辑的原生 PPT；本地定制冻结版，项目以单跳软链引用 |

每个 Skill 的依赖、安装和验证命令以其目录内的 `README.md` 与 `SKILL.md` 为准。

## 独立版本下载

以下标签指向各自的独立源码快照。下载包只包含对应的 `<Skill名>/` 目录、仓库许可和分发说明，不包含其他 Skill；`main` 继续保存完整仓库。

| Skill | 版本标签 |
|---|---|
| check | [check-v6.1.0](https://github.com/ldl8818/skills/archive/refs/tags/check-v6.1.0.zip) |
| health | [health-v4.1.0](https://github.com/ldl8818/skills/archive/refs/tags/health-v4.1.0.zip) |
| hunt | [hunt-v4.3.1](https://github.com/ldl8818/skills/archive/refs/tags/hunt-v4.3.1.zip) |
| lookup | [lookup-v2.4.0](https://github.com/ldl8818/skills/archive/refs/tags/lookup-v2.4.0.zip) |
| luobo-ppt | [luobo-ppt-v1.0.1](https://github.com/ldl8818/skills/archive/refs/tags/luobo-ppt-v1.0.1.zip) |
| neat-freak | [neat-freak-v3.1.0](https://github.com/ldl8818/skills/archive/refs/tags/neat-freak-v3.1.0.zip) |
| self-improving | [self-improving-v3.1.3](https://github.com/ldl8818/skills/archive/refs/tags/self-improving-v3.1.3.zip) |
| skill-manager | [skill-manager-v2.10.0](https://github.com/ldl8818/skills/archive/refs/tags/skill-manager-v2.10.0.zip) |
| think | [think-waza-v3.40.0](https://github.com/ldl8818/skills/archive/refs/tags/think-waza-v3.40.0.zip) |
| ui | [ui-v4.1.0](https://github.com/ldl8818/skills/archive/refs/tags/ui-v4.1.0.zip) |
| write | [write-v4.2.0](https://github.com/ldl8818/skills/archive/refs/tags/write-v4.2.0.zip) |

`think` 使用已登记的 Waza 原版基线版本，不另编自身版本；`download-video` 尚无已登记版本，暂不建立数字版本标签。

独立快照中的 Skill 文件与标签说明记录的来源目录逐字一致，快照提交不带整仓父提交。跨目录文档的固定来源链接、外部工具与跨 Skill 协作前提见下载包根目录的 `README.md`；单包不包含批量冻结安装器需要的其他 Skill。解压后使用包内对应目录，保护已有安装。源码分发、隔离入口检查与真实业务／客户端验收分别判断。

已发布标签保持固定；后续内容变化时先按相应 Skill 的版本规则登记，再创建新标签。本次 `lookup-v2.3.1` 纠正了最初指向整仓提交的对象；之前下载的整仓归档应重新下载独立包。

代码审查统一使用 `check`，以 [Waza 衍生的本地 Check](check/NOTICE.md) 为主干，Alibaba OCR 作为按需工具。影响局部、预期明确的改动直接检查和验证，不要求 OCR、额外清单或整套规则；资金、权限、状态变化、共享接口及跨模块影响进入[深入审查](check/references/深入审查.md)，先核对业务预期，再沿调用关系审查、修复和验证。复杂审查按需使用 Delegate 的规则，模型工作仍由当前宿主会话完成，无需独立 API。代码、Markdown／配套文档、测试、未跟踪文件及删除影响按任务纳入，不以 OCR 筛选结果缩小范围。只有明确选择且模型通道获授权时才运行完整 OCR；命令见[接入说明](check/references/open-code-review.md)。具体故障使用 `hunt`，必要时衔接 `check`，再验证原故障路径。

## 命令

`commands/` 保存显式调用的普通命令文档，不注册为 Skill。

- [push](commands/push.md)：统一由主 Agent 直接提交并推送，不启动执行子 Agent。低风险走最低必要检查，标准档定向检查受影响部分，复用已有验证。指定范围时遵循指定；省略范围时，待提交任务全部完成则按任务分批提交，存在未完成或状态不明任务则仅处理本次任务。完成判断、最低检查及按需场景表见命令正文。
- 普通文案提交只做局部检查与 Git 结果核验，复用已有上下文和验证；无明确适用门禁时不跑全仓检查。无关 WIP 不默认触发隔离，正常 Hook 覆盖的同输入检查不手动重复。普通 push、已授权的直接合并及交付清理共用该命令的要求，不默认等待远端 CI，也不自动修复 CI；具体交付点、门禁及例外以命令正文为准。
- 本机 Claude Code 与 WorkBuddy 输入 `/push`；Codex CLI／IDE／桌面应用输入“执行push”。通过 chezmoi 将 `~/.claude/commands/push.md`、`~/.agents/commands/push.md`、`~/.workbuddy-ai/commands/push.md` 单跳链接到本仓库真身，全局规则提供 Codex 按需入口。新机器需先取得本仓库并部署对应链接／规则；执行只需当前客户端的终端能力及 Git 认证，不依赖另一模型或客户端。
- [Codex 自定义 prompts](https://developers.openai.com/codex/custom-prompts/) 已弃用，本机 CLI 0.154.0 实测不识别 `/prompts:push`，因此不将它作为可用入口。Claude Code 的 [commands Markdown 格式](https://code.claude.com/docs/en/skills#where-skills-live) 仍受支持。新装后重启客户端／新开会话加载入口。

六项 Waza 来源 Skill 为 `check`、`health`、`hunt`、`think`、`ui`、`write`。其中五项保留完整上游模式、参考资料与工具，独立维护本地定制冻结版及逐文件合并回执；`think` 保留完整上游原版。各项保留 Waza MIT 许可，`check` 另保留 Alibaba 接入材料的 Apache-2.0 许可及双来源历史。本地版本、来源基线、安装与完整上游合并流程见 [冻结版本维护](skill-manager/references/冻结版本维护.md)。本仓库按独立 Skill 分发，没有 Waza 整仓的 plugin mirror 或 Desktop bundle。
