"""Installation and data health checks."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from datetime import datetime, timezone, timedelta
import json

from self_improving import __version__
from self_improving.config import load_config, resolved
from self_improving.indexing import broken_local_links, broken_local_references, expired_notices, sync_index
from self_improving.installer import hook_is_installed
from self_improving.security import contains_secret
from self_improving.storage import (
    RECEIPT_RESERVE_TOKENS,
    SESSION_UPDATE_RESERVE_TOKENS,
    VERIFIED_WRAPPER_TOKENS,
    correction_selection,
    estimate_tokens,
    load_verified_records,
    pending_correction_count,
)


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
    injection = config.get("injection", {})
    checks = [
        Check("配置", True, "schema_version=1"),
        Check("记忆目录", root.is_dir(), str(root)),
        Check("核心记忆", root.joinpath("memory.md").is_file(), str(root / "memory.md")),
        Check("旧纠错档案（可选）", True,
              str(root / "corrections.md") if root.joinpath("corrections.md").is_file()
              else "未启用或已归档；不影响候选收集和新版审批"),
    ]
    memory_path = root / "memory.md"
    remaining_tokens = max(
        0,
        int(injection.get("max_total_tokens", 1200))
        - RECEIPT_RESERVE_TOKENS
        - SESSION_UPDATE_RESERVE_TOKENS,
    )
    if memory_path.exists():
        memory = memory_path.read_text(encoding="utf-8")
        line_count = len(memory.splitlines())
        core_chars = len(memory)
        core_limit = int(config.get("injection", {}).get("max_core_chars", 8000))
        core_enabled = bool(injection.get("include_core_memory", False))
        valid_title = bool(memory.splitlines()) and memory.splitlines()[0].startswith(("# Memory ·", "# Memory "))
        core_cost = estimate_tokens(f"<self-improving-memory>\n{memory.rstrip()}\n</self-improving-memory>")
        core_fits = core_cost <= remaining_tokens
        core_ready = (
            5 <= line_count <= 50
            and core_chars <= core_limit
            and valid_title
            and not contains_secret(memory)
            and core_fits
        )
        detail = (
            f"{line_count} 行、{core_chars} 字符、预计 {core_cost} token；"
            f"可用 {remaining_tokens} token；注入{'开启' if core_enabled else '关闭'}"
        )
        checks.append(Check("核心记忆预算", core_ready if core_enabled else True, detail, warning=core_enabled))
        checks.append(Check("核心记忆敏感信息", not contains_secret(memory), "未发现明显凭据模式"))
        if core_enabled and core_ready:
            remaining_tokens -= core_cost
    records, malformed = load_verified_records(root)
    selection = correction_selection(
        root,
        int(injection.get("max_verified_corrections", 20)),
        int(injection.get("max_verified_chars", 4000)),
        max(0, remaining_tokens - VERIFIED_WRAPPER_TOKENS),
        str(Path.cwd()),
        min_version=int(injection.get("min_verified_version", 2)),
        all_scopes=True,
    )
    pending = pending_correction_count(root)
    injection_enabled = bool(injection.get("include_verified_corrections", True))
    budgets_ready = (
        int(injection.get("max_verified_corrections", 20)) > 0
        and int(injection.get("max_verified_chars", 4000)) > 0
        and int(injection.get("max_total_tokens", 1200)) > 0
    )
    detail = (
        f"待审核 {pending} 条；机器可验证 {len(records)} 条；全作用域活动上界 {selection.applicable} 条；"
        f"预算内可选 {len(selection.answers) if injection_enabled else 0} 条；"
        f"预算遗漏 {selection.omitted} 条；旧版忽略 {selection.legacy_ignored} 条；"
        f"已过期 {selection.expired} 条；待复核 {selection.due} 条"
    )
    if malformed:
        detail += f"；损坏记录 {malformed} 条"
    selection_ready = not selection.applicable or bool(selection.answers)
    ready = injection_enabled and budgets_ready and malformed == 0 and selection_ready
    if not injection_enabled:
        detail += "；已验证纠错注入已关闭"
    elif not budgets_ready:
        detail += "；注入预算为 0"
    elif selection.applicable and not selection.answers:
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
            if config.get("persistence", {}).get("capture_command_errors"):
                post_path = schema_root / f"{platform}-PostToolUse.json"
                try:
                    post_schema = json.loads(post_path.read_text(encoding="utf-8"))
                    shape = post_schema.get("shape", {})
                    response_shape = shape.get("tool_response")
                except (OSError, ValueError, json.JSONDecodeError):
                    shape = {}
                    response_shape = None
                structured_failure = (
                    any(key in shape for key in ("exit_status", "is_error"))
                    or isinstance(response_shape, dict)
                    and any(
                        key in response_shape
                        for key in ("exit_code", "isError", "is_error", "error")
                    )
                )
                checks.append(Check(
                    f"{platform} 错误捕获契约",
                    structured_failure,
                    "最近的 PostToolUse 暴露结构化失败字段"
                    if structured_failure
                    else "最近的 PostToolUse 未暴露结构化失败字段；为避免误报，本端不会从输出文字猜失败",
                    warning=True,
                ))
    if root.exists():
        index_ok, index_path = sync_index(root, check=True)
        checks.append(Check("知识索引", index_ok, str(index_path), warning=True))
        broken = broken_local_links(root)
        checks.append(Check("本地文档链接", not broken, "; ".join(broken[:5]) or "未发现断链", warning=True))
        references = broken_local_references(root)
        checks.append(Check("反引号文档路径", not references, "; ".join(references[:5]) or "未发现断链", warning=True))
        expired = expired_notices(root)
        checks.append(Check("核心记忆有效期", not expired, "; ".join(expired[:5]) or "未发现过期日期", warning=True))
        errors = root / ".learnings/ERRORS.md"
        error_count = sum(1 for line in errors.read_text(encoding="utf-8").splitlines() if line.startswith("| 20")) if errors.exists() else 0
        error_limit = int(config.get("persistence", {}).get("max_error_entries", 200))
        checks.append(Check("错误库体积", error_count <= error_limit, f"{error_count}/{error_limit} 条", warning=True))
    from self_improving.knowledge import CATALOG, check as knowledge_check
    if (root / CATALOG).exists():
        try:
            knowledge = knowledge_check(config)
            pending_ids = [item["id"] for item in knowledge["items"] if item["status"] != "ready"]
            checks.append(Check("知识目录与版本", knowledge["structural_ok"] and knowledge["reviewed"],
                                "待核对：" + ", ".join(pending_ids) if pending_ids else "登记来源及直接依赖版本一致", warning=True))
        except (OSError, ValueError) as exc:
            checks.append(Check("知识目录与版本", False, str(exc), warning=True))
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
