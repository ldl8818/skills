# lookup 2.4.0

本快照只分发 [lookup](lookup/SKILL.md)，标签为 `lookup-v2.4.0`。

来源：[完整仓库固定提交](https://github.com/ldl8818/skills/tree/f43c74e3fa841504aab9bd5c81ce32349e072ace/lookup)。
版本依据：SKILL.md metadata.version。

## 安装与范围

解压后使用 `lookup/` 目录；它包含该 Skill 的原始完整文件、脚本、参考与许可。
将该目录放在所选安装位置，按需建立指向同一目录的客户端单跳软链；已有同名入口时先核对，不覆盖。
具体环境与外部工具依赖沿用目录内的说明。独立源码快照不表示所有业务、账号、客户端或设备均已验收。

程序、原始说明及上游合并回执保持来源字节不变；本根目录的许可和分发说明只补充分发信息。
原文中从整个仓库根运行的多 Skill 安装／维护命令，需要完整仓库；单包不包含其他 Skill。

## 跨 Skill 协作

普通检索入口可独立加载；修改上游 Skill 路由字段的定制合并校验需要已安装的 skill-manager，缺少时沿现有门禁拒绝，不隐式安装。

## 仓库外部引用

以下原文相对链接指向未随包分发的仓库文件，请使用对应固定来源链接：

| 原文件 | 原链接 | 固定来源 |
|---|---|---|
| `lookup/README.md` | `../ROADMAP.md` | [读取原文](https://github.com/ldl8818/skills/blob/f43c74e3fa841504aab9bd5c81ce32349e072ace/ROADMAP.md) |
| `lookup/references/上游更新.md` | `../../skill-manager/references/升级与定制合并.md` | [读取原文](https://github.com/ldl8818/skills/blob/f43c74e3fa841504aab9bd5c81ce32349e072ace/skill-manager/references/%E5%8D%87%E7%BA%A7%E4%B8%8E%E5%AE%9A%E5%88%B6%E5%90%88%E5%B9%B6.md) |
