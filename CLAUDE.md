# dev/skills — 多 Skill 公开仓库

公开发布在 `github.com/ldl8818/skills`。每个一级目录是一个独立 Skill；仓库导航见 `README.md`。

## 红线

- 公开仓库，**禁止出现**：真实 `memory.md` / `corrections.md` / `.learnings/` 内容、用户名绝对路径、令牌、真实会话或 transcript。示例一律用合成值。
- 私人记忆真身在 `~/Documents/obsidian/self-improving-memory`（配置指向，见 `~/.config/self-improving/config.json`），绝不复制进本仓库。

## self-improving 开发纪律

- 测试：`cd self-improving && python3 -m unittest discover -s tests`（本机未装 pytest）。
- 升版本必须同步四处：`self_improving/__init__.py`、`pyproject.toml`、`SKILL.md` frontmatter、`CHANGELOG.md` 新条目。测试断言动态引用 `__version__`，不用改。
- 升版本后 doctor 的「事件契约」会降为 ⚠（旧版本验证记录按设计作废），由下次真实 Claude/Codex 新会话自动补齐；不得用历史记录冒充当前版本已验证。
- 行为变更（用户可感知）需同步 `docs/` 相应文件与私人记忆库中的架构文档（`Doraemon跨Agent记忆系统架构.md`，改动时按版本头约定递增 VX.Y.Z）。
- 改完运行：`python3 -m self_improving sync && python3 -m self_improving doctor`。

## 已知坑

- 本仓库的 Hook 守门对整条 Bash 命令做文本扫描：命令文字（含 git 提交信息）同时出现 `>` 与 `memory.md` 字样会命中守门。命中后弹权限框请用户批准（Claude Code 2.3.0 起，Codex 0.144+ 2.5.0 起），误伤时点拒绝换措辞即可。
