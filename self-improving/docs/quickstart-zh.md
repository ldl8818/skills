# 五分钟从零开始

> V1.0.0 · 2026-07-12 · 适用于 self-improving 2.2.0。

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

完全退出并重新打开已启用的 Claude Code 或 Codex 会话。启动时，Hook 会读取：

- `memory.md`：精简的长期核心记忆。
- `.self-improving/verified-corrections.jsonl`：只读取 2.2 审核命令写入、且范围适用于当前目录的正确答案；`corrections.md` 只是人类审计流水。

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

回到终端，在 `self-improving` 目录运行：

```bash
python3 -m self_improving review list
```

复制输出开头的指纹，例如 `[fp:12ab34cd56ef]`，然后运行：

```bash
python3 -m self_improving review approve \
  --fingerprint '[fp:12ab34cd56ef]' \
  --correct '先读取当前文件，再根据实际内容判断。' \
  --scope global
```

看到 `imported` 表示批准完成。`--correct` 后面的内容才是未来会话采用的规则；请写完整、准确、适用范围清楚的句子，不要直接复制含糊的抱怨。

`--scope global` 表示所有项目都适用。只适用于一个项目时必须写绝对路径，例如：

```bash
--scope 'project:/Users/你的名字/dev/某项目'
```

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

“学习闭环”应显示至少“机器可验证 1 条；当前目录适用 1 条；当前可注入 1 条”。然后再次在适用目录新开 Claude Code 或 Codex 会话。`SessionStart` 会产生：

```text
<verified-corrections>
以下内容已经人工审核；当前文件和可验证证据与其冲突时，以当前证据为准。
- 先读取当前文件，再根据实际内容判断。
</verified-corrections>
```

到这里才算从“保存了一条记录”走到了“两个 Agent 下次都会采用”。

## 8. 日常只记住四条命令

```bash
python3 -m self_improving review list
python3 -m self_improving doctor
python3 -m self_improving sync
python3 -m self_improving upgrade
```

- `review list`：看待审核纠错。
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

关闭持久化只是不再写新候选，不影响读取已有核心记忆和已批准纠错。

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
