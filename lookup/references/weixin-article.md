# 公众号取正文

`opencli weixin search` 返回的是**搜狗跳转链**（`weixin.sogou.com/link?url=...`），不是文章地址。这条链只有真实浏览器能走通，所以取正文必须过一次 ego lite。

2026-07-30 实测的三条死路，别再试：

| 试法 | 结果 |
|---|---|
| `fetch.sh <搜狗链>` | **返回 `status=ok`，内容却是搜狗反爬验证码页**（911 字节，「此验证码用于确认这些请求是您的正常行为」）——典型的假成功 |
| `curl` 直连或带浏览器 UA + Referer | 302 到 `weixin.sogou.com/antispider/` |
| `opencli weixin download --url <搜狗链>` | `status: invalid URL`，它只认 `mp.weixin.qq.com` |

## 默认走这条：一个 heredoc 打开并读回正文

搜狗链在浏览器里会 JS 跳转到 `mp.weixin.qq.com`，落地后直接取 DOM 即可。实测 2555 字正文完整。

```bash
ego-browser nodejs <<'EOF'
const task = await useOrCreateTaskSpace('<按用户目标命名>')
await openOrReuseTab('<搜狗跳转链>', { wait: true, timeout: 30 })
await new Promise(r => setTimeout(r, 4000))   // 搜狗是 JS 跳转，不等会读到中转页

const r = await js(`(() => {
  const t = document.querySelector('#activity-name')?.innerText?.trim() || '';
  const a = document.querySelector('#js_name')?.innerText?.trim() || '';
  const c = document.querySelector('#js_content')?.innerText?.trim() || '';
  return JSON.stringify({ title: t, author: a, chars: c.length, body: c });
})()`)
cliLog(r)
EOF
```

读完按纪律用独占的最后一个 heredoc 调 `completeTaskSpace(id, { keep: false })`。

`#activity-name` / `#js_name` / `#js_content` 这三个选择器是 2026-07 的页面结构，平台改版会失效；失效时先 `snapshotText()` 重新找节点，再更新这里。

## 要落盘归档时走这条

`opencli weixin download` 产出带元数据的干净 Markdown（实测 7197 字节，含标题、公众号名、发布时间、原文链接），适合存进知识库。代价是多一轮命令，且**必须先用上面的办法拿到真实 `mp.weixin.qq.com` 地址**。

```bash
opencli weixin download --url '<mp.weixin.qq.com 真实地址>' \
  --output <目录> --download-images false -f yaml --window background
```

跳转后的真实地址形如 `mp.weixin.qq.com/s?src=11&timestamp=...&signature=...`，带签名参数，`download` 接受这种形式。

只是要读内容就别用它——同样的信息量，直读少一轮命令、还不落盘。
