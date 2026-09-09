#!/usr/bin/env python3
"""Download one or more videos with Chinese content titles and dated filenames."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


BEIJING = ZoneInfo("Asia/Shanghai")
VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}
URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
INVALID_FILENAME_RE = re.compile(r"[\\/:*?\"<>|\x00-\x1f]")
DESTINATION_LOCK = threading.Lock()


@dataclass(frozen=True)
class DownloadSpec:
    index: int
    url: str
    name_override: str | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="批量下载视频，并按中文内容标题和发布日期命名。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  download_video.py 'https://example.com/video'\n"
            "  download_video.py URL1 URL2 --jobs 2 --output-dir ~/Downloads\n"
            "  download_video.py URL --name '客服接待量堪比996'\n"
        ),
    )
    parser.add_argument("urls", nargs="*", help="一个或多个视频页面 URL")
    parser.add_argument("--input-file", type=Path, help="一行一个 URL 的 UTF-8 文本文件")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path.home() / "Downloads",
        help="保存目录，默认 ~/Downloads",
    )
    parser.add_argument("--name", help="单条下载使用的中文内容标题")
    parser.add_argument(
        "--name-map",
        type=Path,
        help='批量中文标题 JSON，格式为 {"URL": "中文标题"}',
    )
    parser.add_argument("--date", help="单条下载覆盖日期，格式 YYYY-MM-DD")
    parser.add_argument("--jobs", type=int, default=3, help="并行视频数，默认 3")
    parser.add_argument(
        "--concurrent-fragments",
        type=int,
        default=4,
        help="每条 HLS/DASH 视频的并行分片数，默认 4",
    )
    parser.add_argument("--cookies-from-browser", help="按需读取 yt-dlp 支持的浏览器登录态")
    parser.add_argument("--proxy", help="按需传给 yt-dlp 的代理 URL")
    parser.add_argument("--inspect", action="store_true", help="只读取元数据和计划文件名，不下载")
    parser.add_argument("--deep-verify", action="store_true", help="下载后完整解码一遍，适合高可靠性任务")
    return parser.parse_args()


def fail(message: str, code: int = 2) -> None:
    print(json.dumps({"status": "error", "error": message}, ensure_ascii=False))
    raise SystemExit(code)


def load_urls(args: argparse.Namespace) -> list[str]:
    urls = list(args.urls)
    if args.input_file:
        try:
            lines = args.input_file.expanduser().read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            fail(f"无法读取 URL 文件：{exc}")
        urls.extend(line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#"))

    unique: list[str] = []
    seen: set[str] = set()
    for url in urls:
        if not re.match(r"^https?://", url, re.IGNORECASE):
            fail(f"不是有效的 HTTP(S) URL：{url}")
        if url not in seen:
            seen.add(url)
            unique.append(url)
    if not unique:
        fail("至少提供一个视频 URL，或使用 --input-file。")
    return unique


def load_name_map(path: Path | None) -> dict[str, str]:
    if not path:
        return {}
    try:
        data = json.loads(path.expanduser().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"无法读取 --name-map：{exc}")
    if not isinstance(data, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in data.items()):
        fail("--name-map 必须是 URL 到中文标题的 JSON 对象。")
    return data


def require_commands() -> None:
    required = ["yt-dlp", "ffmpeg", "ffprobe"]
    missing = [name for name in required if not shutil.which(name)]
    if missing:
        fail(f"缺少依赖：{', '.join(missing)}。未自动安装。")


def tool_options(args: argparse.Namespace) -> list[str]:
    options: list[str] = []
    if args.cookies_from_browser:
        options.extend(["--cookies-from-browser", args.cookies_from_browser])
    if args.proxy:
        options.extend(["--proxy", args.proxy])
    return options


def run_command(command: list[str], timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, text=True, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("读取视频元数据超时") from exc


def compact_error(stderr: str, stdout: str = "") -> str:
    lines = [line.strip() for line in (stderr + "\n" + stdout).splitlines() if line.strip()]
    return (lines[-1] if lines else "命令执行失败")[:500]


def fetch_metadata(url: str, args: argparse.Namespace) -> dict[str, Any]:
    command = [
        "yt-dlp",
        "--simulate",
        "--dump-single-json",
        "--no-warnings",
        "--no-playlist",
        *tool_options(args),
        url,
    ]
    result = run_command(command, timeout=90)
    if result.returncode != 0:
        raise RuntimeError(compact_error(result.stderr, result.stdout))
    try:
        metadata = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("yt-dlp 返回了无效的元数据 JSON") from exc
    if not isinstance(metadata, dict):
        raise RuntimeError("yt-dlp 未返回单条视频元数据")
    return metadata


def first_line(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return next((line.strip() for line in value.splitlines() if line.strip()), "")


def clean_title(value: str) -> str:
    title = unicodedata.normalize("NFC", value)
    if title.lstrip().startswith("@") and " - " in title:
        title = title.split(" - ", 1)[1]
    title = URL_RE.sub("", title)
    title = "".join(
        char
        for char in title
        if unicodedata.category(char) not in {"So", "Cs", "Cf"}
    )
    title = INVALID_FILENAME_RE.sub(" ", title)
    title = re.sub(r"\s+", " ", title).strip(" ._-—，。!！?？")
    return title[:48].rstrip(" ._-—，。!！?？")


def content_title(metadata: dict[str, Any], override: str | None) -> str:
    if override:
        return clean_title(override)
    title = first_line(metadata.get("title"))
    description = first_line(metadata.get("description"))
    cleaned = clean_title(title)
    if not CJK_RE.search(cleaned) and CJK_RE.search(description):
        cleaned = clean_title(description)
    return cleaned


def normalize_date(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    digits = re.sub(r"\D", "", value)
    if len(digits) == 8:
        try:
            parsed = datetime.strptime(digits, "%Y%m%d")
        except ValueError:
            return None
        return parsed.strftime("%Y-%m-%d")
    return None


def content_date(metadata: dict[str, Any], override: str | None) -> tuple[str, str]:
    if override:
        normalized = normalize_date(override)
        if not normalized:
            raise RuntimeError("--date 必须是有效的 YYYY-MM-DD")
        return normalized, "override"
    for key in ("upload_date", "release_date"):
        normalized = normalize_date(metadata.get(key))
        if normalized:
            return normalized, key
    for key in ("timestamp", "release_timestamp"):
        value = metadata.get(key)
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=BEIJING).strftime("%Y-%m-%d"), key
    return datetime.now(BEIJING).strftime("%Y-%m-%d"), "download_date"


def probe_video(path: Path) -> dict[str, Any]:
    result = run_command(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration,size:stream=codec_type,codec_name,width,height",
            "-of",
            "json",
            str(path),
        ],
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe 验证失败：{compact_error(result.stderr)}")
    try:
        data = json.loads(result.stdout)
        duration = float(data.get("format", {}).get("duration", 0))
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise RuntimeError("ffprobe 返回了无效结果") from exc
    streams = data.get("streams", [])
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    if not video or duration <= 0 or path.stat().st_size <= 0:
        raise RuntimeError("文件缺少有效视频流、时长或内容")
    return {
        "duration_seconds": round(duration, 3),
        "size_bytes": path.stat().st_size,
        "video_codec": video.get("codec_name"),
        "width": video.get("width"),
        "height": video.get("height"),
        "has_audio": any(stream.get("codec_type") == "audio" for stream in streams),
    }


def deep_verify(path: Path) -> None:
    result = run_command(["ffmpeg", "-v", "error", "-i", str(path), "-f", "null", "-"])
    if result.returncode != 0:
        raise RuntimeError(f"完整解码失败：{compact_error(result.stderr)}")


def find_existing(output_dir: Path, stem: str) -> Path | None:
    for path in sorted(output_dir.glob(f"{stem}.*")):
        if path.is_file() and path.suffix.lower() in VIDEO_SUFFIXES:
            try:
                probe_video(path)
            except RuntimeError:
                continue
            return path
    return None


def safe_destination(output_dir: Path, stem: str, suffix: str) -> Path:
    candidate = output_dir / f"{stem}{suffix}"
    counter = 2
    while candidate.exists():
        candidate = output_dir / f"{stem}_{counter}{suffix}"
        counter += 1
    return candidate


def download_media(url: str, output_dir: Path, stem: str, args: argparse.Namespace) -> tuple[Path, dict[str, Any]]:
    temp_root = Path.home() / "tmp"
    temp_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="download-video-", dir=temp_root) as temp_name:
        template = str(Path(temp_name) / "source.%(ext)s")
        command = [
            "yt-dlp",
            "--no-playlist",
            "--no-warnings",
            "--no-progress",
            "--no-simulate",
            "--no-overwrites",
            "-f",
            "bv*+ba/b",
            "-S",
            "res,br",
            "--merge-output-format",
            "mp4",
            "--remux-video",
            "mp4",
            "--concurrent-fragments",
            str(args.concurrent_fragments),
            "--print",
            "after_move:filepath",
            "-o",
            template,
            *tool_options(args),
            url,
        ]
        result = run_command(command)
        if result.returncode != 0:
            raise RuntimeError(compact_error(result.stderr, result.stdout))
        printed_paths = [Path(line.strip()) for line in result.stdout.splitlines() if line.strip()]
        source = next((path for path in reversed(printed_paths) if path.is_file()), None)
        if source is None:
            source = next((path for path in Path(temp_name).iterdir() if path.is_file()), None)
        if source is None:
            raise RuntimeError("下载命令成功，但未找到输出文件")
        with DESTINATION_LOCK:
            destination = safe_destination(output_dir, stem, source.suffix.lower() or ".mp4")
            shutil.move(str(source), destination)
    details = probe_video(destination)
    if args.deep_verify:
        deep_verify(destination)
        details["deep_verified"] = True
    else:
        details["deep_verified"] = False
    return destination, details


def process_one(spec: DownloadSpec, args: argparse.Namespace) -> dict[str, Any]:
    base: dict[str, Any] = {"index": spec.index, "url": spec.url}
    try:
        metadata = fetch_metadata(spec.url, args)
        title = content_title(metadata, spec.name_override)
        date, date_source = content_date(metadata, args.date if len(args._all_urls) == 1 else None)
        source_title = first_line(metadata.get("title"))
        description = clean_title(first_line(metadata.get("description")))
        if not title or not CJK_RE.search(title):
            return {
                **base,
                "status": "needs_chinese_name",
                "source_title": source_title[:200],
                "description": description[:200],
                "hint": "使用 --name 传入内容相关的中文标题后重试",
            }
        stem = f"{title}_{date}"
        planned = str(args.output_dir / f"{stem}.mp4")
        if args.inspect:
            return {
                **base,
                "status": "inspected",
                "source_title": source_title[:200],
                "planned_path": planned,
                "date_source": date_source,
            }
        existing = find_existing(args.output_dir, stem)
        if existing:
            return {
                **base,
                "status": "existing",
                "path": str(existing.resolve()),
                "date_source": date_source,
                **probe_video(existing),
            }
        path, details = download_media(spec.url, args.output_dir, stem, args)
        return {
            **base,
            "status": "downloaded",
            "path": str(path.resolve()),
            "date_source": date_source,
            **details,
        }
    except Exception as exc:  # Convert per-URL failures into stable batch results.
        return {**base, "status": "failed", "error": str(exc)[:500]}


def main() -> int:
    args = parse_args()
    require_commands()
    urls = load_urls(args)
    args._all_urls = urls
    if args.jobs < 1 or args.jobs > 8:
        fail("--jobs 必须在 1 到 8 之间。")
    if args.concurrent_fragments < 1 or args.concurrent_fragments > 16:
        fail("--concurrent-fragments 必须在 1 到 16 之间。")
    if (args.name or args.date) and len(urls) != 1:
        fail("--name 和 --date 只适用于单条 URL；批量中文标题请使用 --name-map。")
    name_map = load_name_map(args.name_map)
    args.output_dir = args.output_dir.expanduser().resolve()
    if not args.inspect:
        args.output_dir.mkdir(parents=True, exist_ok=True)

    specs = [
        DownloadSpec(index=index, url=url, name_override=args.name if len(urls) == 1 else name_map.get(url))
        for index, url in enumerate(urls, start=1)
    ]
    workers = min(args.jobs, len(specs))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        results = list(executor.map(lambda spec: process_one(spec, args), specs))
    results.sort(key=lambda item: item["index"])
    for result in results:
        print(json.dumps(result, ensure_ascii=False))
    summary = {
        "status": "summary",
        "total": len(results),
        "downloaded": sum(item["status"] == "downloaded" for item in results),
        "existing": sum(item["status"] == "existing" for item in results),
        "needs_chinese_name": sum(item["status"] == "needs_chinese_name" for item in results),
        "failed": sum(item["status"] == "failed" for item in results),
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary["needs_chinese_name"] == 0 and summary["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
