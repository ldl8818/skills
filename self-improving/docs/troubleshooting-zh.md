# 中文排错手册

> V1.0.0 · 2026-07-12 · 适用于 self-improving 2.2.0。

先进入下载目录，再执行体检：

```bash
cd "$HOME/skills/self-improving"
python3 -m self_improving doctor
```

## `python3` 版本太低

运行：

```bash
python3 --version
```

本程序要求 Python 3.11 或更高版本。安装新版 Python 后，要确认 `python3 --version` 显示的确实是新版，不要只看安装器是否成功。

## 提示找不到 `self_improving`

你通常不在正确目录。运行：

```bash
cd "$HOME/skills/self-improving"
python3 -m self_improving --version
```

如果仓库下载在别处，把路径换成你的真实目录。

## 安装成功但 Agent 没读到记忆

1. 运行 `python3 -m self_improving doctor`，确认对应 Agent Hook 为 `✅`。
2. 完全关闭旧会话，再新开会话；旧会话不会重新触发 `SessionStart`。
3. 更新 Agent 后运行 `python3 -m self_improving upgrade`，让 Hook 重新接线。
4. 检查配置中的 `memory_root` 是否指向实际私人记忆目录。

## 明确纠错后没有进入候选箱

运行：

```bash
python3 -m self_improving persistence enable
```

再检查 `~/.config/self-improving/config.json` 中：

```json
"capture_corrections": true
```

捕获器只识别明确纠错，例如“不对”“应该是”“请记住”。普通讨论不会全部保存，避免把整段对话当成永久规则。

## 批准后仍没有生效

1. `review approve` 应输出 `imported`，并且命令必须带 `--scope global` 或 `--scope 'project:/绝对路径'`。
2. `doctor` 的“学习闭环”应显示“机器可验证”与“当前可注入”均大于 0。
3. 检查配置：

```json
"include_verified_corrections": true
```

4. 新开会话，不能只在原会话继续聊天。
5. 项目范围必须覆盖当前工作目录；项目甲的规则不会注入项目乙。
6. 如果已批准规则超过预算，按批准时间取最新 20 条；可在配置中调整 `max_verified_corrections` 和 `max_verified_chars`，但不建议无限增大。

## doctor 显示事件契约 `0/5` 或不满 `5/5`

这是一项真实性提醒，不是 Hook 接线失败。它表示当前 self-improving 版本尚未在最近 30 天记录到全部五类真实事件。新开会话、发送消息、执行一次成功和失败的 Shell 命令、结束会话后会逐步补齐。

只有“对应 Agent Hook”为 `❌` 才代表配置接线失败。

## 我不想让某条已批准纠错继续生效

使用批准时的指纹撤销：

```bash
python3 -m self_improving review revoke --fingerprint '[fp:12ab34cd56ef]'
```

看到 `revoked` 后，新会话不再注入该规则，审计记录仍保留。不要让 Agent 代跑批准或撤销命令；这些命令应由人在普通终端执行。

若要整体暂停已批准纠错注入，把配置中的 `include_verified_corrections` 改为 `false`。历史数据会保留。

## 处理隐私材料时怎样停写

当前会话使用：

```bash
SELF_IMPROVING_PERSIST=0 codex
SELF_IMPROVING_PERSIST=0 claude
```

它只关闭新内容持久化，读取现有记忆不受影响。

## 如何安全卸载

```bash
python3 -m self_improving uninstall --keep-data
```

这只移除受管 Hook 和 Skill 入口，保留私人记忆。程序不会自动删除私人数据。不要为了排错直接删 `~/.claude/settings.json` 或 `~/.codex/hooks.json`，其中可能还有其他工具的 Hook。
