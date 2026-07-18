# 客户端 Skill 目录矩阵

> 核对日期：2026-07-18。客户端规范会演进；改适配器前重新打开一手文档，
> 不用搜索摘要或某台机器的现状代替官方承诺。

## 管理器实际扫描的目录

### 全局直装

1. `~/.agents/skills/`：共享入口。
2. `~/.claude/skills/`：Claude Code。
3. `~/.gemini/skills/`：Gemini CLI。
4. `~/.grok/skills/`：Grok Build。
5. `~/.gemini/config/skills/`：Antigravity 2.0 通用全局入口。
6. `~/.gemini/antigravity/skills/`：Antigravity IDE 全局入口。
7. `~/.gemini/antigravity-cli/skills/`：Antigravity CLI 全局入口。
8. `~/.codex/skills/`：Codex 客户端管理的 Skill 入口；其中 `.system/` 另列为内置、只读盘点。

### 项目级

1. `<project>/.agents/skills/`：共享标准入口。
2. `<project>/.claude/skills/`：Claude Code。
3. `<project>/.codex/skills/`：Codex 客户端兼容入口。
4. `<project>/.gemini/skills/`：Gemini CLI。
5. `<project>/.grok/skills/`：Grok Build。
6. `<project>/.agent/skills/`：Antigravity 向后兼容的旧别名；新项目应使用 `.agents/skills/`。

## 客户端承诺与边界

| 客户端 | 项目／Workspace | 用户全局 | 核对结论 |
|---|---|---|---|
| Grok Build | `.grok/skills/` | `~/.grok/skills/` | xAI 还明示支持 `~/.agents/skills/`、Claude 兼容目录和可配置额外路径；当前页面没有直接承诺项目 `.agents/skills/` |
| Claude Code | `.claude/skills/` | `~/.claude/skills/` | 官方还支持插件 Skill；当前文档没有把 `.agents/skills/` 写成 Claude Code 直接扫描目录 |
| Gemini CLI | `.gemini/skills/` 或 `.agents/skills/` | `~/.gemini/skills/` 或 `~/.agents/skills/` | 同一层级两者同名时，`.agents/skills/` 优先 |
| Google Antigravity | `.agents/skills/` | 见下方三种产品形态 | 新规范是 `.agents/skills/`，向后兼容 `.agent/skills/` |
| OpenAI Codex | `.agents/skills/` | `~/.agents/skills/` | OpenAI 当前公开文档把 `.agents/skills/` 作为仓库与用户作用域；管理器另兼容扫描项目 `.codex/skills/` 和用户 `~/.codex/skills/` |

Antigravity 的「全局目录」不能只写一个：

- Antigravity 2.0 通用文档：`~/.gemini/config/skills/`。
- Antigravity IDE：`~/.gemini/antigravity/skills/`。
- Antigravity CLI：`~/.gemini/antigravity-cli/skills/`。

## 兼容入口不等于官方推荐入口

- `<project>/.codex/skills/`：Skill Manager 会把它作为 Codex 客户端兼容入口扫描和管理；
  OpenAI 当前公开文档推荐的仓库级位置仍是 `.agents/skills/`，新建跨客户端项目应优先使用后者。
- 「Claude、Grok 都一定直接扫描项目 `.agents/skills/`」：管理器会扫这个共享目录，
  但不借此宣称每个客户端都有官方承诺。需要共用时，可为客户端专用目录建立单 Skill 软链接。

## 一手来源

- [xAI Grok Skills, Plugins & Marketplaces](https://docs.x.ai/build/features/skills-plugins-marketplaces)
- [Claude Code Skills](https://code.claude.com/docs/en/skills)
- [Gemini CLI Agent Skills](https://geminicli.com/docs/cli/skills/)
- [Google Antigravity Skills](https://antigravity.google/docs/skills)
- [Google Antigravity Skills Codelab](https://codelabs.developers.google.com/getting-started-with-antigravity-skills)
- [OpenAI Codex Skills](https://developers.openai.com/codex/concepts/customization#skills)
