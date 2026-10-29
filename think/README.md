# Think

用于价值判断、架构方案和可执行交接计划；不处理故障修复或小改。支持按任务自动触发，也可显式调用 `$think`。

## 来源

保留 [Waza 的完整 Think 原版](https://github.com/tw93/Waza/tree/b55809013be84b1f59418b557c1e8bad66380705/skills/think)：`SKILL.md` 及3份参考文档原样保留，来源 commit 及发布版本见 [Waza 来源维护说明](../skill-manager/references/冻结版本维护.md)。MIT 许可见 [LICENSE](LICENSE)。本目录增加来源及安装说明，不修改上游工作流或路由字段。

## 安装

本目录是唯一源码；共享目录与客户端目录只保留直接指向它的单跳软链。以下命令从仓库根目录执行，适用于尚无同名入口的环境；入口已存在时，先核对目标，不覆盖真目录或不同目标的软链。

```bash
skill_repo="$PWD"
mkdir -p "$HOME/.agents/skills" "$HOME/.codex/skills" "$HOME/.workbuddy-ai/skills"
ln -s "$skill_repo/think" "$HOME/.agents/skills/think"
ln -s "$skill_repo/think" "$HOME/.codex/skills/think"
ln -s "$skill_repo/think" "$HOME/.workbuddy-ai/skills/think"
```

仅使用部分客户端时，可省略相应客户端的目录和链接命令。文件及入口核验不代表模型已在真实任务中正确触发。
