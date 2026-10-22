# 公众号正文与跳转

已知公众号原文链接时先使用合适的专用读取能力。OpenCLI `weixin/search` 有时返回 `weixin.sogou.com/link?url=...` 中转链；它不是文章正文地址，可能需要浏览器执行跳转。

## 核对目标与正文

1. 保留搜索结果的原始链接、标题、公众号名和可用时间，判断是中转链还是 `mp.weixin.qq.com` 原文。
2. 中转链需要浏览器时按 [浏览器选路.md](浏览器选路.md) 选择；本机日常外部网页默认 ego-browser 执行接口，选中后通过 `ego-browser skill` 读取当前指南并保留用户指定环境。
3. 等待真实跳转完成，观察落地 URL 与当前页面；按页面状态等待，不固定 sleep 后盲读。验证页、登录页和中转页不能交付为正文。
4. 定向提取标题、作者、发布时间和正文。历史页面常见选择器为 `#activity-name`、`#js_name`、`#js_content`；节点不存在时重新观察 DOM，不因旧选择器失效就声称文章不存在。
5. 正文是否完整按文章与任务判断，不设统一千字门槛。完整短文可交付；长文片段明确标部分，缺口影响问题时再补充。
6. 按正式浏览器 Skill 收尾本任务资源，不调用旧 API 或回收其他会话页面。

过去曾观察到中转链经普通 HTTP 返回验证码页、下载命令只接受原文 URL；这些是带版本与环境条件的经验，不是所有未来实现都无效的证明。当前调用仍以 URL、内容与错误状态验收，避免反复尝试同一已失败中转路径。

## 显式归档

仅在用户需要保存时才选择 OpenCLI `weixin/download`。先从当前注册表和帮助确认 `access`、输出目录和图片选项，再传真实原文 URL：

```bash
node scripts/opencli-run.mjs weixin download --url "<mp.weixin.qq.com 原文URL>" \
  --output "<指定目录>" --download-images false -f json --window background
```

[已核对实现](https://github.com/jackwener/opencli/blob/b06ab7780e73d3021e12e0f170086c2d55675776/clis/weixin/download.js#L342-L352) 遇验证页会返回含 `title: Error` 和失败 `status` 的非空结果行；exit 0 或非空数组仍不能证明归档成功，应核对实际状态、正文与生成文件。

真实可访问 URL 可能含签名或跳转参数；保留在 `access_url`，不要为了去重或美化覆盖它。只阅读时不为了拿同一内容重复归档；保存操作遵循用户现有授权、范围与文件保留规则。
