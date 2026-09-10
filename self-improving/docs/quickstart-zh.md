# 五分钟从零开始

> V2.2.0 · 2026-08-31 · 适用于 self-improving 3.0.0：恢复会话在规则变化时发送完整替换，撤销或归位最后一条规则时清空旧注入。
> V2.1.0 · 2026-08-31 · 适用于 self-improving 3.0.0：恢复会话只跳过未变化内容，补齐生命周期查看与正式归位。
> V2.0.0 · 2026-08-31 · 适用于 self-improving 3.0.0：默认只注入有生命周期的 v2 纠错，恢复会话跳过重复上下文。
> V1.3.0 · 2026-08-31 · 适用于 self-improving 2.6.6，区分 Claude 弹框批准与 Codex 普通终端审核。
> V1.2.1 · 2026-07-13 · 适用于 self-improving 2.5.1，术语澄清：「2.2 审核命令」改为「`review approve` 审核命令」。
> V1.2.0 · 2026-07-12 · 适用于 self-improving 2.5.0，补充预审一键批准流程。
> V1.1.0 · 2026-07-12 · 适用于 self-improving 2.2.1，补充旧流水按范围显式导入。

这份教程带你完成一次完整闭环：安装 → 自动捕获纠错 → 人工批准 → 新会话自动采用。无需安装 Obsidian，也无需懂 Python 编程。

## 1. 先准备好

你需要：

- macOS、Linux，或 Windows WSL。
- Python 3.11 或更高版本。运行 `python3 --version` 查看。
- 已经能正常打开 Claude Code、Codex，或其中一个。
- Git。运行 `git --version` 查看。

Obsidian 和私人 Git 仓库都不是必需品。

## 2. 下载程序

```bash
cd "$HOME"
git clone https://github.com/ldl8818/skills.git
cd "$HOME/skills/self-improving"
```

如果你已下载过仓库，不要重复克隆，进入原目录后执行 `git pull --ff-only`。

## 3. 选择你使用的 Agent

Claude Code 与 Codex 都使用：

```bash
python3 -m self_improving init \
  --agents claude,codex \
  --memory-root "$HOME/Documents/self-improving-memory" \
  --capture-corrections \
  --no-capture-errors
```

只使用 Claude Code，把 `--agents` 改为 `claude`；只使用 Codex，改为 `codex`。

这条命令会创建私人记忆目录、写入本机配置、合并 Hook，并给已启用 Agent 建立 Skill 入口。它不会创建 GitHub 远端，不会上传私人记忆，也不会覆盖无关 Hook。已有 Hook 配置修改前会备份；已有 self-improving 安装请使用 `upgrade`，不要用 `init` 重建配置。

看到“配置”“记忆目录”“核心记忆”和对应 Agent Hook 前面为 `✅`，说明安装接线成功。事件契约出现 `⚠️` 不等于安装失败，只表示这个版本还没有在真实新会话中触发全部五类事件。

## 4. 打开一个全新会话

完全退出并重新打开已启用的 Claude Code 或 Codex 会话。启动时，Hook 默认只读取：

- `.self-improving/verified-corrections.jsonl`：只读取 v2 审核命令写入、范围适用、仍在有效期内的正确答案；`corrections.md` 只是人类审计流水。
- `memory.md` 和其他知识文档保留给按需读取，不再默认塞进每个会话；恢复旧会话会比较该会话上次收到的内容，没变化就静默，变化时废止旧注入并发送完整新集合；撤销或归位最后一条规则会发送一次清空信号。

第一次安装还没有已批准纠错，因此第二部分为空是正常现象。

## 5. 制造第一条可验证纠错

在新会话中明确告诉 Agent：

```text
不对，应该先读取当前文件，再根据实际内容判断。请记住这条纠正。
```

Hook 应输出类似：

```text
<correction-captured result="stored"/>
```

这时内容只进入“不可信候选箱”，还没有资格影响任何 Agent。

## 6. 审核并批准

候选攒到 3 条时，结束对话会按冷却时间提醒审核；也可以随时对 Agent 说“审核一下纠错候选”。提醒不再占用每个新会话的开场上下文。

- Claude Code：你在对话里说"同意"后，Agent 代跑批准命令，客户端弹出一次权限确认框；核对命令内容后点允许即完成。
- Codex：你在对话里说"同意"后，Agent 给出一条只含候选指纹的交互命令，但不会代跑；把它复制到普通终端，再按提示输入规则正文和作用范围。Codex 的 Hook 不支持单次询问，Agent 工具里的权威写入会被直接拒绝。

下面是普通终端流程：Codex 必须使用，Claude Code 可作为备用。先回到终端，在 `self-improving` 目录运行：

```bash
python3 -m self_improving review list
```

复制输出开头的指纹，例如 `[fp:12ab34cd56ef]`，然后运行：

```bash
python3 -m self_improving review approve-interactive \
  --fingerprint '[fp:12ab34cd56ef]'
```

终端随后询问：

```text
正在审核候选：[fp:12ab34cd56ef]
正确规则：先读取当前文件，再根据实际内容判断。
作用范围（global、repo:/仓库绝对路径或 project:/绝对路径）：global
正式归位目标（如 global-rules、project-rules 或 skill-docs）：global-rules
优先级（normal/critical，默认 normal）：
多少天后复核（默认 30）：
多少天后停止注入（默认 90）：
```

先核对终端显示的指纹与本次候选一致；每次只运行一条交互审核命令，不要用 `&&` 串联。规则正文等字段通过程序输入，不进入 Shell 命令。`global` 表示所有项目；`repo:/绝对路径` 覆盖同一 Git 仓库及其 worktree；`project:/绝对路径` 只覆盖一个目录树。归位目标说明这条临时纠错最终应写进哪份正式规则；到期后停止注入，避免永久占用上下文。

跨 Agent 只表示 Claude Code 与 Codex 共享同一条经验，不等于所有项目都该收到这条经验。

如果候选不正确，改用：

```bash
python3 -m self_improving review reject --fingerprint '[fp:12ab34cd56ef]'
```

## 7. 验证它真的学会了

先刷新索引，再运行体检：

```bash
python3 -m self_improving sync
python3 -m self_improving doctor
```

“学习闭环”应显示至少“机器可验证 1 条；全作用域活动上界 1 条；预算内可选 1 条”。然后在适用目录新开会话。继续恢复原会话且内容不变时不会重复注入；如果恢复前规则集合变化，恢复时会发送一次完整替换。`SessionStart` 会产生：

```text
<verified-corrections>
以下内容已经人工审核；当前文件和可验证证据与其冲突时，以当前证据为准。
- 先读取当前文件，再根据实际内容判断。
</verified-corrections>
```

到这里才算从“保存记录”走到了“两个 Agent 在有效期内采用”。用下面的命令查看复核期、失效期和归位目标：

```bash
python3 -m self_improving review lifecycle-list
```

稳定后，把规则写进提示的全局规则、项目规则或 Skill 并完成验证，再运行：

```bash
python3 -m self_improving review promote \
  --fingerprint '[fp:12ab34cd56ef]'
```

看到 `promoted:...` 后，这条临时纠错停止注入，审计历史仍保留。规则错误或不再适用、但没有归位时，使用 `review revoke`。

## 8. 日常只记住五条命令

```bash
python3 -m self_improving review list
python3 -m self_improving review lifecycle-list
python3 -m self_improving doctor
python3 -m self_improving sync
python3 -m self_improving upgrade
```

- `review list`：看待审核纠错。
- `review lifecycle-list`：看正在注入、待复核和已失效的临时纠错。
- `doctor`：检查接线和学习闭环。
- `sync`：刷新 Obsidian 或普通记忆目录的知识索引。
- `upgrade`：更新版本后补齐配置并重新接线。

形象地说：候选箱像学生的错题草稿，人工批准像老师批改，下一会话自动注入才是学生真正把正确解法带进考场。

## 9. 隐私任务临时停写

只关闭当前会话的记录：

```bash
SELF_IMPROVING_PERSIST=0 claude
SELF_IMPROVING_PERSIST=0 codex
```

长期关闭或恢复：

```bash
python3 -m self_improving persistence disable
python3 -m self_improving persistence enable
```

关闭持久化只是不再写新候选，不影响读取已有的有效纠错；Hook 保持静默，不额外写一条“已关闭”消息进上下文。

## 10. 更新和卸载

更新：

```bash
cd "$HOME/skills"
git pull --ff-only
cd self-improving
python3 -m self_improving upgrade
python3 -m self_improving doctor
```

卸载程序接线但保留私人记忆：

```bash
python3 -m self_improving uninstall --keep-data
```

不要手工删除私人记忆。需要排错时看 [中文排错手册](troubleshooting-zh.md)。

## 11. 旧版纠错流水怎么办

旧 `corrections.md` 和 v1 JSONL 批准记录是事故与晋升历史，不要整表自动启用：已经晋升的规则通常已在核心或领域文档中，再导入只会重复；被替代、废弃的规则更不能复活。

仍然有效、但尚未进入现行记忆的规则，应先缩成一句当前可执行规则，再明确选择范围：

```bash
python3 -m self_improving review import-legacy-interactive \
  --legacy-id 'legacy:12ab34cd56ef'
```

先运行 `python3 -m self_improving review legacy-list` 取得稳定的 `legacy:...` 编号；列表同时覆盖合格的旧 Markdown 行和活动 v1 JSONL 批准。Markdown 编号由原文生成，不会因其他行插入而漂移。运行交互命令后，程序会先验证并显示当前旧记录 ID，再提示输入重新提炼的现行规则和作用范围；同样每次只处理一条。导入命令会返回 `[fp:...]` 指纹。v1 记录成功替换为 v2 后会追加撤销事件，不会继续出现在旧记录列表。它和普通批准一样受预算、项目范围和生命周期管理。系统故意不提供“把全部 active 一键启用”，因为旧流水没有可靠范围，批量全局注入会把单个项目的特定经验带到所有无关任务里。

读取记忆文件不需要批准：常见独立 Python `read_text()` 检查已支持只读识别。若出现拒绝，先核对被拦命令是否真的写入或审核；不要因为提示就去批准某条候选。支持范围见 `hooks.md`，排查见 `troubleshooting-zh.md`。
