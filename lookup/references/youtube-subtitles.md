# YouTube 字幕

要「这个视频讲了什么」时走这条。B站字幕不走这里，用 `opencli bilibili subtitle <BV号>`——**不要用 yt-dlp 抓 B站**。

## 三步

```bash
# 1) 下载
yt-dlp --write-auto-sub --sub-lang "en,zh-Hans" --skip-download --sub-format vtt -o "$HOME/tmp/%(id)s" "<URL>"

# 2) 清洗后再读，别直接读 .vtt
sed -e '/-->/d' -e '/^WEBVTT/d' -e '/^Kind:/d' -e '/^Language:/d' -e 's/<[^>]*>//g' \
    "$HOME/tmp/<id>.en.vtt" | awk 'NF' | awk '!seen[$0]++'

# 3) 读完删掉，别留在 ~/tmp
trash "$HOME/tmp/<id>".*.vtt
```

**第 2 步不是可选的。**自动字幕带内联时间码和滚动重复（`We're<00:00:19.039><c> no</c>` 这种），实测 14807 字节清洗后只剩 1224 字节，**省 92%**。直接读原始 VTT 是在烧上下文。

## 两条不用管的输出

`Error solving N challenge requests using "node" provider` 和 `Access to this API has been restricted` 这两条 WARNING **每次都会出现，且不影响字幕**——沙箱开、关两种情况实测都照常拿到中英文 VTT。它们只影响需要签名求解的视频流格式，纯下字幕用不到。**不要为它关沙箱，也不要去查 YouTube 侧**，那是白费一轮。

输出 `There are no subtitles for the requested languages` 是正常结果不是故障：这个视频就是没字幕。别据此判定通道不通，换个视频即可。
