# skill-manager 2.10.0

本快照只分发 [skill-manager](skill-manager/SKILL.md)，标签为 `skill-manager-v2.10.0`。

来源：[完整仓库固定提交](https://github.com/ldl8818/skills/tree/eb252227245240ddb26b465c906e09f250fd9568/skill-manager)。
版本依据：SKILL.md metadata.version。

## 安装与范围

解压后使用 `skill-manager/` 目录；它包含该 Skill 的原始完整文件、脚本、参考与许可。
将该目录放在所选安装位置，按需建立指向同一目录的客户端单跳软链；已有同名入口时先核对，不覆盖。
具体环境与外部工具依赖沿用目录内的说明。独立源码快照不表示所有业务、账号、客户端或设备均已验收。

程序、原始说明及上游合并回执保持来源字节不变；本根目录的许可和分发说明只补充分发信息。
原文中从整个仓库根运行的多 Skill 安装／维护命令，需要完整仓库；单包不包含其他 Skill。

## 跨 Skill 协作

需要维护的其他 Skill 仍从实际安装位置发现；Lookup 更新由已安装 Lookup 自身的维护器执行。批量冻结安装器需要完整仓库中的冻结 Skill 集合，不能仅凭此包执行。

## 仓库外部引用

以下原文相对链接指向未随包分发的仓库文件，请使用对应固定来源链接：

| 原文件 | 原链接 | 固定来源 |
|---|---|---|
| `skill-manager/README.md` | `../lookup/references/上游更新.md#命令与范围` | [读取原文](https://github.com/ldl8818/skills/blob/eb252227245240ddb26b465c906e09f250fd9568/lookup/references/%E4%B8%8A%E6%B8%B8%E6%9B%B4%E6%96%B0.md#命令与范围) |
| `skill-manager/SKILL.md` | `../lookup/references/上游更新.md#命令与范围` | [读取原文](https://github.com/ldl8818/skills/blob/eb252227245240ddb26b465c906e09f250fd9568/lookup/references/%E4%B8%8A%E6%B8%B8%E6%9B%B4%E6%96%B0.md#命令与范围) |
| `skill-manager/references/冻结版本维护.md` | `../../think/README.md` | [读取原文](https://github.com/ldl8818/skills/blob/eb252227245240ddb26b465c906e09f250fd9568/think/README.md) |
| `skill-manager/references/升级与定制合并.md` | `../../lookup/references/上游更新.md#命令与范围` | [读取原文](https://github.com/ldl8818/skills/blob/eb252227245240ddb26b465c906e09f250fd9568/lookup/references/%E4%B8%8A%E6%B8%B8%E6%9B%B4%E6%96%B0.md#命令与范围) |
