# Skills

可复用的个人 Agent Skills。

| Skill | 用途 |
|---|---|
| [`neat-freak`](neat-freak/) | 项目文档与规则对齐、任务清理及交接；自管冻结版 |
| [`check`](check/) | 明确的代码审查、项目审计与发布验收 |
| [`health`](health/) | Agent 指令、配置、工具与验证器健康审计 |
| [`hunt`](hunt/) | 可观察的软件故障诊断与修复验证 |
| [`ui`](ui/) | 产品界面创建、视觉修改与真实渲染验证 |
| [`write`](write/) | 明确要求的文案起草、改写和本地化 |
| [`lookup`](lookup/) | 联网检索、正文读取与多来源研究综合；专用入口优先，按失效域降级并核验来源 |
| [`self-improving`](self-improving/) | Claude Code 与 Codex 共用的可配置、自我进化记忆系统；公开程序与私人记忆分离 |
| [`skill-manager`](skill-manager/) | Skill 的列出、溯源、查更新、更新、启停、定版本、自检和归档删除 |
| [`download-video`](download-video/) | 按中文内容标题和发布日期下载视频，并用 `ffprobe` 验证本地文件 |

每个 Skill 的依赖、安装和验证命令以其目录内的 `README.md` 与 `SKILL.md` 为准。

## 命令

`commands/` 保存显式调用的普通命令文档，不注册为 Skill。

- [push](commands/push.md)：使用 GPT-5.6 Luna（medium）提交并推送当前任务，主 Agent 核对范围、检查及远端结果。默认仅当前任务，明确“全部”才按主题处理全部已确认改动。
- 本机 Claude Code 输入 `/push`；Codex CLI／IDE／桌面应用输入“执行push”。通过 chezmoi 将 `~/.claude/commands/push.md`、`~/.agents/commands/push.md` 单跳链接到本仓库真身，全局规则提供 Codex 按需入口。新机器需先取得本仓库并部署对应链接／规则，Claude Code 调用 Luna 还需已登录的 Codex CLI。
- [Codex 自定义 prompts](https://developers.openai.com/codex/custom-prompts/) 已弃用，本机 CLI 0.154.0 实测不识别 `/prompts:push`，因此不将它作为可用入口。Claude Code 的 [commands Markdown 格式](https://code.claude.com/docs/en/skills#where-skills-live) 仍受支持。新装后重启客户端／新开会话加载入口。

五个 Waza 衍生 Skill 独立维护为本地4.0.0冻结版，保留原作者 MIT 许可与来源 commit。安装、恢复和上游选择性合并见 [冻结版本维护](skill-manager/references/冻结版本维护.md)。本仓库按独立 Skill 分发，没有 Waza 整仓的 plugin mirror 或 Desktop bundle。
