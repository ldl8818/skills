"""Installation and data health checks."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from datetime import datetime, timezone, timedelta
import json

from self_improving import __version__
from self_improving.config import load_config, resolved
from self_improving.indexing import broken_local_links, sync_index
from self_improving.installer import hook_is_installed
from self_improving.security import contains_secret
from self_improving.storage import active_corrections, load_verified_records, pending_correction_count, verified_corrections


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str
    warning: bool = False


def run_checks() -> list[Check]:
    try:
        config = resolved(load_config())
    except Exception as exc:
        return [Check("配置", False, str(exc))]
    root = Path(config["memory_root"])
    checks = [
        Check("配置", True, "schema_version=1"),
        Check("记忆目录", root.is_dir(), str(root)),
        Check("核心记忆", root.joinpath("memory.md").is_file(), str(root / "memory.md")),
        Check("纠错库", root.joinpath("corrections.md").is_file(), str(root / "corrections.md")),
    ]
    memory_path = root / "memory.md"
    if memory_path.exists():
        memory = memory_path.read_text(encoding="utf-8")
        line_count = len(memory.splitlines())
        core_chars = len(memory)
        core_limit = int(config.get("injection", {}).get("max_core_chars", 8000))
        checks.append(Check("核心记忆预算", 5 <= line_count <= 50 and core_chars <= core_limit, f"{line_count} 行、{core_chars} 字符；要求 5–50 行且不超过 {core_limit} 字符"))
        checks.append(Check("核心记忆敏感信息", not contains_secret(memory), "未发现明显凭据模式"))
    injection = config.get("injection", {})
    records, malformed = load_verified_records(root)
    approved = active_corrections(root, str(Path.cwd()))
    injectable = verified_corrections(
        root,
        int(injection.get("max_verified_corrections", 20)),
        int(injection.get("max_verified_chars", 4000)),
        str(Path.cwd()),
    )
    pending = pending_correction_count(root)
    injection_enabled = bool(injection.get("include_verified_corrections", True))
    budgets_ready = int(injection.get("max_verified_corrections", 20)) > 0 and int(injection.get("max_verified_chars", 4000)) > 0
    detail = f"待审核 {pending} 条；机器可验证 {len(records)} 条；当前目录适用 {len(approved)} 条；当前可注入 {len(injectable) if injection_enabled else 0} 条"
    if malformed:
        detail += f"；损坏记录 {malformed} 条"
    selection_ready = not approved or bool(injectable)
    ready = injection_enabled and budgets_ready and malformed == 0 and selection_ready
    if not injection_enabled:
        detail += "；已验证纠错注入已关闭"
    elif not budgets_ready:
        detail += "；注入预算为 0"
    elif approved and not injectable:
        detail += "；适用记录全部超过字符预算"
    checks.append(Check("学习闭环", ready, detail, warning=True))
    checks.append(Check("审批账本结构", malformed == 0, f"损坏记录 {malformed} 条" if malformed else "结构与时间字段有效"))
    for platform, settings in config["agents"].items():
        if settings.get("enabled"):
            checks.append(Check(f"{platform} Hook", hook_is_installed(config, platform), "配置接线"))
            schema_root = Path(config["state_root"]) / "hook-schemas"
            seen = [schema_root / f"{platform}-{event}.json" for event in ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop")]
            count = 0
            cutoff = datetime.now(timezone.utc) - timedelta(days=30)
            for path in seen:
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    observed = datetime.fromisoformat(payload["observed_at"])
                    if payload.get("package_version") == __version__ and observed >= cutoff:
                        count += 1
                except (OSError, ValueError, KeyError, json.JSONDecodeError):
                    continue
            checks.append(Check(f"{platform} 事件契约", count == len(seen), f"当前版本已验证 {count}/{len(seen)} 类", warning=True))
    if root.exists():
        index_ok, index_path = sync_index(root, check=True)
        checks.append(Check("知识索引", index_ok, str(index_path), warning=True))
        broken = broken_local_links(root)
        checks.append(Check("本地文档链接", not broken, "; ".join(broken[:5]) or "未发现断链", warning=True))
    return checks


def print_report() -> int:
    checks = run_checks()
    failures = 0
    for check in checks:
        if check.passed:
            prefix = "✅"
        elif check.warning:
            prefix = "⚠️"
        else:
            prefix = "❌"
            failures += 1
        print(f"{prefix} {check.name}：{check.detail}")
    return 1 if failures else 0
