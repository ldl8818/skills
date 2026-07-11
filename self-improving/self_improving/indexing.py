"""Stable memory index generation and local Markdown link checks."""

from __future__ import annotations

from pathlib import Path
import re
from urllib.parse import unquote

from self_improving.paths import atomic_write


FIXED_NAMES = {
    "memory.md",
    "index.md",
    "corrections.md",
    "CORRECTIONS_INBOX.md",
    "ERRORS.md",
    "FEATURE_REQUESTS.md",
    "LEARNINGS.md",
    "README.md",
    "SKILL.md",
}
VOLATILE_PARTS = {".learnings"}
LINK = re.compile(r"(?<!!)\[[^]]*]\(([^)]+)\)")


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
        "domains": "领域",
        "projects": "项目",
        "styles": "风格",
        "archive": "冷存储",
        "设计": "设计",
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
        "> `memory.md` 每会话加载，其他文件按任务需要读取。\n\n"
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
