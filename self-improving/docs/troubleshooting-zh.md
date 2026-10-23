# 中文排错手册

> V2.1.4 · 2026-09-11 · 对齐 self-improving 3.1.3的恢复条件、只读检查和审批账本保护。版本历史见 [CHANGELOG](../CHANGELOG.md)。

先进入下载目录，再执行体检：

```bash
cd "$HOME/skills/self-improving/src"
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
cd "$HOME/skills/self-improving/src"
python3 -m self_improving --version
```

如果仓库下载在别处，把路径换成你的真实目录。3.1.3起，Python 源码位于 `src/`；旧版升级后还需在此目录执行 `python3 -m self_improving upgrade`，刷新仍指向上一级的 Hook。

## 安装成功但 Agent 没读到记忆

1. 运行 `python3 -m self_improving doctor`，确认对应 Agent Hook 为 `✅`。
2. 完全关闭旧会话，再新开会话；没有知识目录时默认 `resume_mode=skip`，恢复旧会话只跳过未变化内容，新批准规则会在下一次恢复时补注一次。
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

1. `review approve-interactive --fingerprint ...` 应先显示当前指纹，再询问规则、作用范围、归位目标和生命周期；作用域可用 `global`、`repo:/仓库绝对路径` 或 `project:/绝对路径`。多条候选必须逐条运行。
2. `doctor` 的“学习闭环”应显示“机器可验证”“全作用域活动上界”和“预算内可选”均大于0；后两者是保守上界，实际注入仍须核对会话目录与预算。
3. 检查配置：

```json
{
  "include_verified_corrections": true,
  "min_verified_version": 2,
  "max_total_tokens": 1200
}
```

4. 新开会话，或恢复同一个有 `session_id` 的会话；没有知识目录时，恢复时只有内容发生变化才会发送一次完整替换。撤销或归位最后一条规则后，下一次恢复会发送清空信号。无知识目录时，`resume_mode=always` 会在每次恢复重复注入；有目录时不论该设置如何，都重置知识去重并补发基础上下文。
5. 作用范围必须覆盖当前目录；`repo` 作用域会覆盖同仓库 linked worktree，`project` 只覆盖一个目录树。
6. v1 旧批准默认只保留审计，不注入；应把稳定内容归位正式规则，确需临时中转时重新审核为 v2。
7. `<self-improving-receipt>` 中 `omitted` 表示总 token、数量或字符预算淘汰，`expired` 表示已失效，`due` 表示到复核期，`legacy_ignored` 表示旧版忽略，`malformed` 表示账本损坏。不要靠无限增大预算掩盖这些状态。

用 `python3 -m self_improving review lifecycle-list` 查看每条 v2 规则的状态、日期、范围和归位目标。无知识目录时，如果恢复会话没有 `session_id`，系统无法安全比较同一会话的摘要，默认保持静默；有目录时则重复提供安全输出。新开会话仍按配置注入。

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

看到 `revoked` 后，新会话不再注入该规则，审计记录仍保留。Claude Code 可让 Agent 代跑，再在客户端权限框确认；Codex 必须把精确命令复制到普通终端执行，Agent 工具中的撤销命令会被守门拒绝。

如果规则不是错误，而是已经写进正式目标并验证完成，应改用：

```bash
python3 -m self_improving review promote --fingerprint '[fp:12ab34cd56ef]'
```

看到 `promoted:目标` 后同样停止注入，但审计语义明确记录为“已正式归位”，不是“撤销”。

## Claude 弹权限框，Codex 却直接拒绝写记忆

先区分操作对象：`memory.md` 与 `corrections.md` 自3.1.2起按普通授权维护，修改和归档不再触发额外守门。旧 `corrections.md` 为可选历史资料，已有标记目录归档后不会由初始化重建，体检也不要求它存在。

审批账本写入及变更审核命令仍受保护：Claude Code 返回 `ask` 请求单次确认；Codex 返回 `deny`。纠错审核时，Codex 用户在普通终端运行含指纹的交互命令，再输入规则、范围和生命周期；普通文件操作不能靠批准无关候选解锁。

若被拦的是只读检查，先核对完整命令。独立 Python `-c`、带引号 heredoc 的受限 AST 支持 `read_text()`、`startswith()` 和负数下标；简单 Shell 命令分别匹配解释器与引用，管道保留输入关联。未知代码和复杂展开仍可能被保守拦截。`[authority-guard]` 只表示命中检测，不证明已经写入或正在审批。完整边界见 [hooks.md](hooks.md)。

五类自我进化 Hook 的执行上限是 10 秒。若仍看到接近 600 秒的卡顿，先运行 `python3 -m self_improving upgrade` 重新接线，再用 `doctor` 检查 Hook；600 秒是 Codex 在未配置超时时的默认值，不是本系统的期望配置。

若要整体暂停已批准纠错注入，把配置中的 `include_verified_corrections` 改为 `false`。历史数据会保留。

## 成功命令被误记成错误

3.0.0 起只依据退出码和客户端结构化失败标志。成功输出里出现 `error`、`failed`、`exception` 等词不会落入错误库。当前 Claude Code 的普通 `Bash` 结果可能只有 `interrupted` 而没有退出码；这不足以证明普通命令失败，`doctor` 会显示错误捕获契约降级，不会用输出文字猜测。若仍误记，先运行 `upgrade`，再用 `doctor` 检查 Hook；`ERRORS.md` 默认最多保留 200 条，可用 `max_error_entries` 调整。

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

`review import-legacy` 只接受 `review legacy-list` 返回的稳定 `legacy:...` 编号。列表包含合格的旧 Markdown 行和活动 v1 JSONL 批准；Markdown 编号由旧行原文生成，不会因其他行插入而漂移，如果该行内容被修改，必须重新运行 `legacy-list`。v1 替换成功后会追加撤销事件，不再重复列出。`superseded`、`obsolete`、`rejected` 都不允许复活。

运行 `review import-legacy-interactive --legacy-id ...` 后，正确规则不是复制事故全文，而是重新写成一句仍然适用的现行规则，并填写正式归位目标、复核期和失效期。项目或仓库范围必须使用存在的绝对路径。

## 知识没有自动提供或提示待复核

先运行 `knowledge check --json`。`invalid` 检查路径、章节、敏感模式及源／部署；`needs_review` 表示版本未复核，不代表内容错误。已授权维护中核验当前来源及直接依赖后再 accept，不能反复确认旧 digest。

没有命中时用 `knowledge list` 和 `knowledge read ID`；必读长文使用 `--full`。出现 unavailable 时核对 worker 超时、锁、损坏状态或运行目录；候选捕获关闭不会停用知识读取。目录存在时 resume 保守补发基础入口，这不是重复注入故障。详见 [知识边界](knowledge.md)。

## Exact hook trust after changes

Codex requires review and trust of the current hook definition after matcher or command changes. Use the normal `/hooks` interface to inspect the changed self-improving hook and enable that exact definition. Do not use bypass flags. Configuration wiring alone does not prove trust or execution; check a real next model request after startup, resume, clear or compact. Official contract: https://learn.chatgpt.com/docs/hooks .
