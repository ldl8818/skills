# dev/skills — 多 Skill 公开仓库

公开发布在 `github.com/ldl8818/skills`。每个一级目录是一个独立 Skill；仓库导航见 `README.md`。

## 红线

- 公开仓库，**禁止出现**：真实 `memory.md` / `corrections.md` / `.learnings/` 内容、用户名绝对路径、令牌、真实会话或 transcript。示例一律用合成值。
- 私人记忆真身在 `~/Documents/obsidian/self-improving-memory`（配置指向，见 `~/.config/self-improving/config.json`），绝不复制进本仓库。

## self-improving 开发纪律

- 系统正式名称：**Doraemon 跨 Agent 自我进化记忆系统**（2026-07-12 定）。对外文档、发布说明统一用此名；程序包名、命令、目录仍为 `self-improving`，不改代码标识符。
- 测试：`cd self-improving && python3 -m unittest discover -s tests`（本机未装 pytest）。
- 升版本必须同步四处：`self_improving/__init__.py`、`pyproject.toml`、`SKILL.md` frontmatter、`CHANGELOG.md` 新条目。测试断言动态引用 `__version__`，不用改。
- 升版本后 doctor 的「事件契约」会降为 ⚠（旧版本验证记录按设计作废），由下次真实 Claude/Codex 新会话自动补齐；不得用历史记录冒充当前版本已验证。
- 行为变更（用户可感知）按受众清单**全量**同步，缺一不发。逐份点名：
  1. `docs/architecture-zh.md` —— 架构、Hook 事件、审核流程或安全边界变了就改，实质修改递增版本头 VX.Y.Z；
  2. `docs/hooks.md`；
  3. `README.md`；
  4. `SKILL.md`；
  5. `docs/quickstart-zh.md` —— 新手中文教程，2.5.0 时曾漏、最易漏；
  6. `docs/troubleshooting-zh.md`。
  发布前自查：对以上 6 份逐一回答「本次变更影响它吗」，答不上来就打开文件核对，不允许凭印象跳过。私人记忆库自 2026-07-12 起不再承担架构同步（架构真身已入仓）；仅本机部署方式变化时才更新私人库 `方案/本机部署与验证档案.md`。
- 改完运行：`python3 -m self_improving sync && python3 -m self_improving doctor`。

## 文档去向（新增或移动文档前先分类，2026-07-12 定）

- `self-improving/docs/` 只放**现在为真**的现役文档：教程、排错、参考、架构。平铺存放，英文文件名（面向中文读者的加 `-zh` 后缀）；文件数超过 12 份前**不建子目录**。
- 已完成的改造计划、实施记录、验收记录是历史档案：**不进公开仓库**（git 历史与 PR 就是公开档案），全文放私人记忆库 `归档/`；其中值得公开的设计决策蒸馏进 `docs/architecture-zh.md` 的「设计取舍」章节，不整篇照搬。
- 含真实纠错内容、legacy 指纹或用户绝对路径的工作单**永不公开**（见红线），现役的放私人库 `方案/`，完结后移入 `归档/`。
- 新增公开文档前跑红线扫描，两段拼起来查：公共模式 `grep -nE '/Users/|dylan' <文件>`，再加本机私有词表（`~/Documents/obsidian/self-improving-memory/方案/公开仓库红线词表.md`）中的模式；任一命中即不得提交。项目代号等违禁词只写进私有词表——写进公开规则或 CI 等于自我暴露（2026-07-13 定）。

## 已知坑

- 本仓库的 Hook 守门对整条 Bash 命令做文本扫描：命令文字（含 git 提交信息）同时出现 `>` 与 `memory.md` 字样会命中守门。命中后弹权限框请用户批准（Claude Code 2.3.0 起，Codex 0.144+ 2.5.0 起），误伤时点拒绝换措辞即可。
