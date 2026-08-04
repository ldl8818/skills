# 中文排错手册

> V1.5.0 · 2026-08-04 · 适用于 self-improving 2.6.5，补充两端 Stop Hook 非法 JSON 报错与修复。
> V1.4.0 · 2026-07-28 · 适用于 self-improving 2.6.4，补充斜杠命令与超长提示词不捕获，新增「候选看不出为什么被捕获」。
> V1.3.0 · 2026-07-13 · 适用于 self-improving 2.6.0，补充捕获前置过滤的两种「没进候选箱」情形。

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

以下情况是有意不捕获的：

1. 以系统标签开头的消息（如 `<task-notification>` 任务通知、注入提醒）——那不是你在说话，是客户端塞进会话的机器消息（2.6.0 起）；
2. 纠错字眼只出现在 ``` 代码围栏里——你贴的报错日志、diff 里带“不对”“error”不算你在立规矩。围栏外写一句人话纠错（如“不对，应该用 utf-8”）即可正常捕获（2.6.0 起）；
3. 以斜杠命令标签开头的消息（`<command-message>`、`<command-name>`、`<command-args>`）——你敲 `/某命令 这里不对` 时客户端会把整条命令作为用户消息送进来，那是命令回显不是纠错（2.6.4 起）；
4. 超过 1500 字符的提示词——纠错是即时的短回应，长文档和客户端生成的长提示词几乎必然偶然含关键词（2.6.4 起）。正常打字的纠错远达不到这个长度；若你确实想让一段长文里的某句成为规则，单独用一句话再说一遍即可。

## 候选看不出为什么被捕获

`review list` 每条候选末尾的「命中：」显示触发捕获的关键词及其上下文（2.6.4 起，JSON 输出对应 `matched` 字段）。关键词匹配跑在完整提示词上，而候选只存前 500 字符，命中词可能落在存储文本之外——这时命中列是唯一能解释入库原因的线索。若命中的是「不对称」里的「不对」这类误伤，直接 `review reject` 即可。2.6.4 之前写入的候选没有这一列，显示为空属正常。

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

## Claude 或 Codex 显示 `invalid stop hook JSON output`

这是 2.6.4 及更早版本的待审提醒输出格式错误：候选达到 3 条后，`Stop` Hook 输出 XML，当前 Claude Code 与 Codex 都要求非空输出是合法 JSON。更新到 2.6.5 或更高版本，再运行：

```bash
python3 -m self_improving upgrade
python3 -m self_improving doctor
```

不要通过删除整个 `Stop` Hook 处理；配置中可能还有其他工具的收尾 Hook。

## 我不想让某条已批准纠错继续生效

使用批准时的指纹撤销：

```bash
python3 -m self_improving review revoke --fingerprint '[fp:12ab34cd56ef]'
```

看到 `revoked` 后，新会话不再注入该规则，审计记录仍保留。Agent 代跑批准或撤销命令时，客户端会弹出权限确认框（Claude Code 2.3.0 起、Codex 0.144+ 2.5.0 起），核对命令内容后再点允许；你也可以自己在普通终端执行，效果相同。

## Agent 写记忆文件时弹出权限确认框

这是守门机制在工作：任何对核心记忆、纠错库或审批账本的写入都需要你当场批准。看清弹框里的命令内容——是你刚同意的操作就点允许，莫名其妙的写入就点拒绝。太旧的 Codex 版本不解析这套确认协议，守门不生效，请升级 Codex。

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

## 旧流水导入提示行不存在或状态不允许

`review import-legacy` 只接受 `review legacy-list` 返回的稳定 `legacy:...` 编号。它由旧行原文生成，不会因其他行插入而漂移；如果该行内容被修改，必须重新运行 `legacy-list`。`superseded`、`obsolete`、`rejected` 都不允许复活。

导入时的 `--correct` 不是复制事故全文，而是重新写成一句仍然适用的现行规则。项目规则必须用 `project:/绝对路径`，且该目录需要真实存在。
