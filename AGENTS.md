# Skills 仓库开发规则

本仓库公开发布在 `github.com/ldl8818/skills`，按独立 Skill 分发。本文只补充项目约定；通用授权、Git 和协作规则沿用全局配置。

## 工作入口

- [README.md](README.md)：Skill 清单与用途；各 Skill 的 `SKILL.md`、`README.md` 提供模块约定、安装和验证入口，按任务读取。
- `commands/`：显式调用的普通命令文档，与独立 Skills 分开维护，不加入 Skill 自动发现。
- [ROADMAP.md](ROADMAP.md)：施工与接力状态，不在本文记录版本现状、待办或验证历史。
- 根 `AGENTS.md` 是规则真身，`CLAUDE.md` 保持指向它的单跳相对软链；修改子目录时同时遵循适用的 `AGENTS.md`。
- 本地冻结的 Waza 衍生 Skills：更新、恢复或选择性合并前读 [冻结版本维护](skill-manager/references/冻结版本维护.md)，保留许可与来源信息。
- 新机引导位于 `self-improving/mac-environment-migration/`，范围与检查入口见该目录的 [AGENTS.md](self-improving/mac-environment-migration/AGENTS.md)。

## 公开内容边界

- 禁止写入真实记忆、纠错及 `.learnings/` 内容、用户名绝对路径、凭据、真实会话或 transcript；示例和测试数据使用合成值。
- 私人记忆位置以 `~/.config/self-improving/config.json` 的 `memory_root` 为准，绝不复制进本仓库。
- 新增或修改公开文档时，扫描本次新增内容中的本机用户路径、身份词及凭据，并应用私人记忆库 `方案/公开仓库红线词表.md` 的模式；命中即不得提交，无法读取词表须说明缺失验证。私人词表、身份词和项目代号不得写进公开规则或 CI。

## Skill 修改与验证

- `description` 是实际路由上下文，写简短用途与中文触发条件；仅易混淆时增加排除条件。`zh_description` 只用于展示。
- 修改授权、路由、执行或验收行为时，核对直接引用并做定向场景验证；Markdown 文件同样适用。
- 普通代码改动运行相关测试；纯措辞、排版和链接修改检查受影响内容与引用。文档执行命令改变时验证对应步骤。
- 安装、迁移或首次使用的实际执行路径改变时，除相关自动测试外，在干净 HOME／环境按文档实跑受影响流程；失败须修正代码或文档。隔离或模拟验证不替代真实客户端、新机或业务验收。

## self-improving 开发

对外名称统一为 **Doraemon 跨 Agent 自我进化记忆系统**；程序包名、命令和目录仍使用 `self-improving`。

- Python 源码：`self-improving/src/self_improving/`。源码 CLI 从 `self-improving/src/` 执行；Skill 入口、模板和示例留在 Skill 根目录。
- 完整测试入口（从仓库根目录执行）；局部改动按影响选择相关测试：

  ```bash
  cd self-improving
  PYTHONPATH=src python3 -m unittest discover -s tests
  ```

- 升版本同步 Skill 根目录下的 `src/self_improving/__init__.py`、`pyproject.toml`、`SKILL.md` frontmatter 和 `CHANGELOG.md`；测试动态引用 `__version__`。
- 升版本会使旧版事件契约验证记录失效；由真实 Claude／Codex 新会话补齐，不用历史记录证明当前版本已验证。
- 知识索引输入变化时运行 `python3 -m self_improving sync`；安装、配置或 Hook 接线变化时运行 `python3 -m self_improving doctor`。两者均从 `self-improving/src/` 执行；只读审计不运行 `sync`，独立子工具不自动刷新私人记忆状态。
- Hook 拒绝先核对原始命令，不凭拒绝提示推断发生了记忆审批；只读识别范围与受保护操作见 [hooks.md](self-improving/docs/hooks.md)。

### 文档同步

按实际影响同步下列文档；无法判断时读取相应章节，不要求无关文档一起修改。

| 变更 | 核对入口 |
|---|---|
| 架构、Hook、审核或安全边界 | [architecture-zh.md](self-improving/docs/architecture-zh.md)、[hooks.md](self-improving/docs/hooks.md)、受影响的 [troubleshooting-zh.md](self-improving/docs/troubleshooting-zh.md)；架构文档实质修改递增版本头 `VX.Y.Z` |
| 安装、命令、路由或新手流程 | [README.md](self-improving/README.md)、[SKILL.md](self-improving/SKILL.md)、[quickstart-zh.md](self-improving/docs/quickstart-zh.md) |
| 仓库导航 | 根 [README.md](README.md) |
| 新机引导 | `self-improving/mac-environment-migration/` 内文档；记忆系统接口或上层导航受影响时才同步上层说明 |

私人库不维护架构副本；本机部署方式变化时才更新私人库 `方案/本机部署与验证档案.md`。

### 文档归属

- `self-improving/docs/` 只放现役教程、排错、参考和架构文档。新文档使用中文文件名，产品名和工具约定入口保持原名；沿用平铺结构，确有导航需要时再调整，不按文件数量机械建目录。
- 完成的计划、实施与验收记录不新增到公开仓库；公开历史使用 Git／PR，全文档案放私人库 `归档/`。值得公开的设计决策提炼进架构文档的「设计取舍」，不整篇复制。
- 含真实纠错、legacy 指纹或用户绝对路径的工作单只留私人库：现役放 `方案/`，完结归档；移动或归档仍遵循用户授权边界。
