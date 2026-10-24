# OpenCLI 2.0.2互动指标补丁

本目录提供两个站点 override 使用的 helper。它们与[完整指标补丁](../opencli-2.0.2-engagement.patch)配套，不能只复制 helper 或只改一个读取命令。上游源码摘录与差异沿用 [OpenCLI Apache-2.0 许可](../../upstream/LICENSE-opencli)。

## 应用

1. 核对实际 OpenCLI 版本、trace 指向的 adapter 路径及本地差异；只对已授权的站点 override 施工，保留既有改动。首次创建使用原生 `adapter eject`，已有 override 不重复导出覆盖。
2. 本补丁基于2.0.2及既有[小红书搜索导航](../opencli-2.0.2-xiaohongshu-search.patch)、[搜索指标基础](../opencli-2.0.2-xiaohongshu-search-metrics.patch)、[X 单帖媒体](../opencli-2.0.2-twitter-download.patch)补丁。先比较并补齐适用的前置差异；禁止将其他版本的源码强行套入补丁。
3. 将 `xiaohongshu-engagement.js` 复制为小红书 override 中的 `engagement.js`，将 `twitter-engagement.js` 复制为 X override 中的 `engagement.js`。如果目标已有同名文件，先比较合并，不覆盖未知内容。
4. 在包含 `xiaohongshu/`、`twitter/` 的 override 根目录，对完整补丁运行 `patch --dry-run -p1 -F 0 < <补丁绝对路径>`；无冲突后去掉 `--dry-run` 应用。只有一个平台在维护范围内时，提取该平台的差异并单独核对，不改变另一站点。
5. 运行 `adapter check xiaohongshu`、`adapter check twitter` 和受影响的只读动作。原生 `adapter check` 不接受 `-f`；从每个动作的当前帮助核对其格式参数。

完整补丁修改小红书的搜索、详情、feed、用户笔记、收藏／点赞、评论及创作者列表／摘要读取；X 的搜索、详情、作者推文、时间线、列表、收藏／收藏夹、点赞、通知订阅读取和引用对象共用 helper。保留动作参数、对象 ID、文本、媒体和嵌套回执结构。

## 验证

从 `lookup/` 执行：

```bash
python3 -m unittest discover -s tests -p test_result_helpers.py
```

上述命令验证结果归一化，不连接账号，也不证明站点指标映射正确。补丁应用后，分别核对搜索排序、目标详情、引用对象、真实0与缺失值，并将点赞、评论和收藏字段与对应的站点数据逐一比较。真实站点、登录状态与私人集合的可访问性另验；不能用定义检查或合成测试替代。

指标含义与未知值约定统一见[执行参考](../../references/opencli-windows.md#小红书与-x-的互动指标)。后续上游升级先比较新版是否已包含修复；只保留仍需要的本地差异，不自动覆盖或重新应用。
