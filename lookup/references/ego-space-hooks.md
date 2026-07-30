# ego task space 自动收尾机制

## 问题

ego lite 的每个 agent task space 底层是一个独立浏览器窗口。收尾靠 Agent 在最后一轮主动调 `completeTaskSpace(id, { keep: false })`——会话被打断、上下文压缩、任务没走完，这一步就丢，窗口永久残留。靠提示词约束「必须做的最后动作」不可靠，需要机制兜底。

## 两层机制

执行器统一是 `scripts/ego-spaces.mjs`（零依赖，Node ≥ 18）。

| 层 | 触发点 | 行为 |
|---|---|---|
| **Stop 门禁**（主防线） | Claude Code Stop hook，Agent 每次结束回复时 | 本会话 transcript 里出现过 `ego-browser nodejs` 且仍有 agent 持有的 space → 阻断收尾，把 space 清单塞回给模型：close、keep 或声明「属并行会话」。此刻上下文还在，模型自己知道哪个该关 |
| **闲置回收**（兜底） | Claude Code SessionStart hook | 全局最近一次 ego-browser 使用（`last-touch`）距今超过 2 小时 → 现存 agent space 判定为孤儿，全部 `completeTaskSpace(keep:false)`，接住崩溃/强杀的会话 |

防误伤设计：

- **只动 `ownership === 'agent'` 的 space**；用户持有和已交接（`agentDelegatedToUser`）的一概不碰。
- **每会话每 space 只提醒一次**（`acks/` 记账，先记后提醒），加上 `stop_hook_active` 守卫，不可能形成阻断循环。
- **`keep <id> --note` 标记有意保留**，两层机制都跳过；space 消失后标记自动清理。
- **ego lite 没运行则两层都直接退出**——绝不因为清理把浏览器拉起来。
- **门禁自身出错一律放行**（exit 0），不卡用户会话。
- 首次安装时 `last-touch` 不存在 → 只建基线不回收，因为此刻无法区分孤儿和在用。

已知限制：`listTaskSpaces()` 不返回创建/活跃时间，闲置判定只能用全局 `last-touch` 单时间戳近似；Codex 会话使用 ego 不会刷新它（Codex 无对应 hook），极端情况下一个闲置 2 小时以上的 Codex ego 会话的 space 可能被新 Claude 会话误回收。阈值可用环境变量 `EGO_SPACES_IDLE_HOURS` 调整。

## 安装（Claude Code）

在 `~/.claude/settings.json` 的 `hooks` 里加三条（与已有 hook 并存，追加即可）：

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "INPUT=$(cat); case \"$INPUT\" in *\"ego-browser\"*) mkdir -p \"$HOME/.agents/data/ego-spaces\"; date +%s > \"$HOME/.agents/data/ego-spaces/last-touch\";; esac"
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "PATH=\"$HOME/.local/bin:/opt/homebrew/bin:$PATH\" node \"$HOME/.agents/skills/lookup/scripts/ego-spaces.mjs\" hook-stop",
            "statusMessage": "检查 ego task space 收尾"
          }
        ]
      }
    ],
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "PATH=\"$HOME/.local/bin:/opt/homebrew/bin:$PATH\" node \"$HOME/.agents/skills/lookup/scripts/ego-spaces.mjs\" hook-session-start",
            "statusMessage": "回收孤儿 ego space"
          }
        ]
      }
    ]
  }
}
```

PostToolUse 用纯 shell 写时间戳（不起 node，每条 Bash 命令的开销可忽略）；匹配到含 `ego-browser` 的命令才动笔，误匹配（如编辑提到 ego-browser 的文档）只是多刷新一次时间戳，无害。

新会话生效；改完 hooks 需重开会话或 `/hooks` 确认加载。

## 手动运维

```bash
node ~/.agents/skills/lookup/scripts/ego-spaces.mjs list        # 列出 agent 持有的 space
node ~/.agents/skills/lookup/scripts/ego-spaces.mjs close 3 5   # 关闭指定 space
node ~/.agents/skills/lookup/scripts/ego-spaces.mjs keep 4 --note "用户要看这页"
node ~/.agents/skills/lookup/scripts/ego-spaces.mjs unkeep 4
```

状态目录 `~/.agents/data/ego-spaces/`：`last-touch`（epoch 秒）、`keep.json`、`acks/<session>.json`。全删无副作用，等价于重新初始化。
