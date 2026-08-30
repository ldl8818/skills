"""Stable memory index generation and local Markdown link checks."""

from __future__ import annotations

from pathlib import Path
import re
from urllib.parse import unquote
from datetime import date, datetime
from zoneinfo import ZoneInfo

from self_improving.paths import atomic_write


VOLATILE_PARTS = {".learnings"}
AUDIT_ONLY_FILES = {"corrections.md"}
ARCHIVE_PARTS = {"archive", "归档"}
LINK = re.compile(r"(?<!!)\[[^]]*]\(([^)]+)\)")
BACKTICK_PATH = re.compile(r"`([^`]+\.md(?:#[^`]*)?)`")
EXPIRY = re.compile(r"至\s*(20\d{2}-\d{2}-\d{2})")


def _title(path: Path) -> str:
    try:
        first = next((line for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("# ")), "")
    except (OSError, UnicodeError):
        return path.stem
    return first[2:].strip() or path.stem


def _category(relative: Path) -> str:
    if relative.name in {"memory.md", "corrections.md"} or len(relative.parts) == 1:
        return "核心 / 架构"
    return {
        "domains": "领域知识",
        "projects": "项目",
        "styles": "创作风格",
        "archive": "归档",
        "领域知识": "领域知识",
        "项目": "项目",
        "创作风格": "创作风格",
        "归档": "归档",
        "草稿": "草稿",
        "设计": "设计",
        "方案": "方案",
        ".learnings": "候选学习",
    }.get(relative.parts[0], "其他")


def render_index(root: Path) -> str:
    rows: list[str] = []
    for path in sorted(root.rglob("*.md"), key=lambda item: item.relative_to(root).as_posix().casefold()):
        relative = path.relative_to(root)
        if relative.name == "index.md":
            continue
        href = relative.as_posix().replace(" ", "%20")
        if any(part in VOLATILE_PARTS for part in relative.parts):
            metrics = "—"
        else:
            metrics = str(len(path.read_text(encoding="utf-8").splitlines()))
        rows.append(
            f"| {_category(relative)} | [`{relative.as_posix()}`]({href}) | {_title(path).replace('|', '¦')} | {metrics} |"
        )
    return (
        "# Memory Index\n\n"
        "> 本文件由 `python3 -m self_improving sync` 生成；禁止手工修改表格。\n"
        "> `memory.md` 仅在配置开启核心注入时加载，其他文件按任务需要读取。\n\n"
        "| 类别 | 文件 | 标题 | 行数 |\n"
        "|---|---|---|---:|\n"
        + "\n".join(rows)
        + "\n"
    )


def sync_index(root: Path, check: bool = False) -> tuple[bool, Path]:
    path = root / "index.md"
    expected = render_index(root)
    current = path.read_text(encoding="utf-8") if path.exists() else ""
    if check:
        return current == expected, path
    if current != expected:
        atomic_write(path, expected)
    return True, path


def broken_local_links(root: Path) -> list[str]:
    broken: list[str] = []
    for source in root.rglob("*.md"):
        relative = source.relative_to(root)
        # 自动捕获的候选/日志（.learnings/）不是文档，其中的不可信文本不做断链检查。
        if (
            any(part in VOLATILE_PARTS or part in ARCHIVE_PARTS for part in relative.parts)
            or relative.name in AUDIT_ONLY_FILES
        ):
            continue
        text = source.read_text(encoding="utf-8")
        for raw in LINK.findall(text):
            target = raw.strip().strip("<>").split("#", 1)[0]
            if not target or "://" in target or target.startswith(("mailto:", "#")):
                continue
            destination = (source.parent / unquote(target)).resolve()
            try:
                destination.relative_to(root.resolve())
            except ValueError:
                continue
            if not destination.exists():
                broken.append(f"{source.relative_to(root)} -> {target}")
    return sorted(set(broken))


def broken_local_references(root: Path) -> list[str]:
    """Check backticked Markdown paths that ordinary link validation cannot see."""
    broken: list[str] = []
    for source in root.rglob("*.md"):
        relative = source.relative_to(root)
        if (
            any(part in VOLATILE_PARTS or part in ARCHIVE_PARTS for part in relative.parts)
            or relative.name in AUDIT_ONLY_FILES
        ):
            continue
        text = source.read_text(encoding="utf-8")
        for raw in BACKTICK_PATH.findall(text):
            target = raw.split("#", 1)[0]
            if target.startswith(("http://", "https://")):
                continue
            if not (
                target.startswith(("~/", "$HOME/", "./", "../", "/"))
                or "/" in target
            ):
                # A bare `name.md` is often a label or example rather than a
                # resolvable path. Only references with an explicit root or
                # directory component have a deterministic base to validate.
                continue
            if target.startswith("~/"):
                destination = Path(target).expanduser()
            elif target.startswith("$HOME/"):
                destination = Path.home() / target.removeprefix("$HOME/")
            elif Path(target).is_absolute():
                destination = Path(target)
            else:
                destination = source.parent / target
            if not destination.exists():
                broken.append(f"{relative.as_posix()} -> {target}")
    return sorted(set(broken))


def expired_notices(root: Path, *, today: date | None = None) -> list[str]:
    """Find explicit until-dates in the always-on core; archives are intentionally ignored."""
    core = root / "memory.md"
    if not core.exists():
        return []
    current = today or datetime.now(ZoneInfo("Asia/Shanghai")).date()
    expired = {
        value
        for value in EXPIRY.findall(core.read_text(encoding="utf-8"))
        if date.fromisoformat(value) < current
    }
    return [f"memory.md -> {value}" for value in sorted(expired)]
