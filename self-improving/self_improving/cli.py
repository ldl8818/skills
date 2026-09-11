"""Command-line interface for installation, Hooks, review and migration."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import shutil
import sys

from self_improving.config import default_config, load_config, resolved, with_defaults, write_config
from self_improving import __version__
from self_improving.doctor import print_report
from self_improving.hooks.common import run as run_hook
from self_improving.installer import install_hooks, install_skill_links, uninstall_hooks, uninstall_skill_links
from self_improving.indexing import sync_index
from self_improving.migration import discover_legacy, write_manifest
from self_improving.paths import PACKAGE_ROOT, default_config_path, expand_path
from self_improving.review import (
    candidate_entries,
    decide,
    import_legacy,
    lifecycle_entries,
    legacy_entries,
    list_candidates,
    list_legacy,
    list_lifecycle,
    promote,
    revoke,
)
from self_improving.storage import initialize_memory, validate_delete_target


def _agents(value: str) -> tuple[str, ...]:
    result = tuple(item.strip() for item in value.split(",") if item.strip())
    invalid = set(result) - {"claude", "codex"}
    if invalid:
        raise argparse.ArgumentTypeError(f"unsupported agents: {', '.join(sorted(invalid))}")
    return result


def command_init(args: argparse.Namespace) -> int:
    if default_config_path().exists():
        raise ValueError("self-improving is already configured; use upgrade instead of init")
    config = default_config(args.memory_root)
    enabled = set(args.agents)
    for platform in config["agents"]:
        config["agents"][platform]["enabled"] = platform in enabled
    capture_corrections = args.capture_corrections
    if capture_corrections is None:
        capture_corrections = sys.stdin.isatty() and input("自动保存明确纠错到未验证候选箱？[y/N] ").strip().lower() in {"y", "yes"}
    config["persistence"]["capture_corrections"] = capture_corrections
    config["persistence"]["capture_command_errors"] = args.capture_errors
    live = resolved(config)
    initialize_memory(Path(live["memory_root"]), PACKAGE_ROOT)
    sync_index(Path(live["memory_root"]))
    config_path = write_config(config)
    for destination, backup in install_skill_links(config):
        print(f"✅ Skill 入口：{destination}")
        if backup:
            print(f"  旧版备份：{backup}")
    for platform in enabled:
        path, backup = install_hooks(config, platform)
        print(f"✅ {platform} Hook：{path}")
        if backup:
            print(f"  备份：{backup}")
    print(f"✅ 配置：{config_path}")
    return print_report()


def command_status(_: argparse.Namespace) -> int:
    return print_report()


def command_sync(args: argparse.Namespace) -> int:
    config = resolved(load_config())
    ok, path = sync_index(Path(config["memory_root"]), check=args.check)
    if args.check:
        print(f"{'✅' if ok else '❌'} 知识索引：{path}")
        return 0 if ok else 1
    print(f"✅ 知识索引已刷新：{path}")
    return 0


def command_persistence(args: argparse.Namespace) -> int:
    marker = Path.home() / ".config/self-improving/persistence.disabled"
    marker.parent.mkdir(parents=True, exist_ok=True)
    if args.action == "disable":
        marker.touch()
        print("持久化已关闭；读取不受影响。")
    else:
        marker.unlink(missing_ok=True)
        print("持久化已启用。")
    return 0


def _interactive_review_fields(label: str, record_id: str) -> tuple[str, str, str, str, int, int]:
    print(f"{label}：{record_id}")
    try:
        correct = input("正确规则：")
        scope = input("作用范围（global、repo:/仓库绝对路径或 project:/绝对路径）：")
        promotion_target = input("正式归位目标（如 global-rules、project-rules 或 skill-docs）：")
        priority = input("优先级（normal/critical，默认 normal）：").strip() or "normal"
        review_after = input("多少天后复核（默认 30）：").strip() or "30"
        expires_after = input("多少天后停止注入（默认 90）：").strip() or "90"
    except EOFError as exc:
        raise ValueError("interactive review requires answers from a terminal") from exc
    try:
        return correct, scope, promotion_target, priority, int(review_after), int(expires_after)
    except ValueError as exc:
        raise ValueError("review and expiry days must be integers") from exc


def _review_options(args: argparse.Namespace) -> dict[str, object]:
    return {
        "priority": args.priority,
        "promotion_target": args.promotion_target,
        "review_after_days": args.review_after_days,
        "expires_after_days": args.expires_after_days,
    }


def command_review(args: argparse.Namespace) -> int:
    config = resolved(load_config())
    root = Path(config["memory_root"])
    state_root = Path(config["state_root"])
    if args.review_action == "list":
        if args.json:
            print(json.dumps(candidate_entries(root), ensure_ascii=False, indent=2))
            return 0
        rows = list_candidates(root)
        print("\n".join(rows) if rows else "没有待审核候选。")
        return 0
    if args.review_action == "legacy-list":
        rows = list_legacy(root)
        print("\n".join(rows) if rows else "没有可迁移的 active/promoted 旧流水。")
        return 0
    if args.review_action == "lifecycle-list":
        if args.json:
            print(json.dumps(lifecycle_entries(root), ensure_ascii=False, indent=2))
            return 0
        rows = list_lifecycle(root)
        print("\n".join(rows) if rows else "没有活动的 v2 纠错。")
        return 0
    if args.review_action == "revoke":
        print(revoke(root, state_root, args.fingerprint))
        return 0
    if args.review_action == "promote":
        print(promote(root, state_root, args.fingerprint))
        return 0
    if args.review_action == "approve-interactive":
        if not any(entry["fingerprint"] == args.fingerprint for entry in candidate_entries(root)):
            raise ValueError("candidate not found or already handled")
        correct, scope, target, priority, review_days, expiry_days = _interactive_review_fields("正在审核候选", args.fingerprint)
        print(decide(
            root, state_root, args.fingerprint, "approve", correct, scope,
            priority=priority, promotion_target=target,
            review_after_days=review_days, expires_after_days=expiry_days,
        ))
        return 0
    if args.review_action == "import-legacy-interactive":
        if not any(entry["legacy_id"] == args.legacy_id for entry in legacy_entries(root)):
            raise ValueError("legacy row not found; refresh review legacy-list")
        correct, scope, target, priority, review_days, expiry_days = _interactive_review_fields("正在导入旧记录", args.legacy_id)
        print(import_legacy(
            root, state_root, args.legacy_id, correct, scope,
            priority=priority, promotion_target=target,
            review_after_days=review_days, expires_after_days=expiry_days,
        ))
        return 0
    if args.review_action == "import-legacy":
        print(import_legacy(root, state_root, args.legacy_id, args.correct, args.scope, **_review_options(args)))
        return 0
    options = _review_options(args) if args.review_action == "approve" else {}
    print(decide(root, state_root, args.fingerprint, args.review_action, getattr(args, "correct", "") or "", getattr(args, "scope", "") or "", **options))
    return 0


def command_migrate(args: argparse.Namespace) -> int:
    discovery = discover_legacy()
    print("旧版记忆目录：" + str(discovery["memory_root"]))
    print(f"旧版外围脚本：{len(discovery['legacy_scripts'])} 个")
    if not args.apply:
        if default_config_path().exists():
            print("检测到已有 self-improving 配置：--apply 会拒绝覆盖；已配置环境请改用 upgrade。")
        else:
            print("当前为预览；加 --apply 才会写配置和 Hook。")
        return 0
    if default_config_path().exists():
        raise ValueError("self-improving is already configured; migrate refuses to overwrite it")
    if not discovery["memory_root"]:
        print("未找到旧版记忆目录。", file=sys.stderr)
        return 1
    config = default_config(discovery["memory_root"])
    config["persistence"]["capture_corrections"] = True
    config["persistence"]["capture_command_errors"] = False
    for platform, settings in config["agents"].items():
        key = "settings_file" if platform == "claude" else "hooks_file"
        settings["enabled"] = expand_path(settings[key]).exists()
    initialize_memory(Path(discovery["memory_root"]), PACKAGE_ROOT)
    sync_index(Path(discovery["memory_root"]))
    config_path = write_config(config)
    for platform, settings in config["agents"].items():
        key = "settings_file" if platform == "claude" else "hooks_file"
        if expand_path(settings[key]).exists():
            install_hooks(config, platform)
    install_skill_links(config)
    manifest = write_manifest(expand_path(config["state_root"]), discovery, config_path)
    print(f"迁移清单：{manifest}")
    return print_report()


def command_upgrade(_: argparse.Namespace) -> int:
    config = with_defaults(load_config())
    live = resolved(config)
    initialize_memory(Path(live["memory_root"]), PACKAGE_ROOT)
    config.pop("temp_root", None)
    config.pop("retention", None)
    config["persistence"].pop("central_error_fallback", None)
    config_path = default_config_path()
    backup_dir = Path(live["state_root"]) / "backups" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(config_path, backup_dir / "self-improving-config.json")
    write_config(config)
    for platform, settings in config["agents"].items():
        if settings.get("enabled"):
            install_hooks(config, platform)
    sync_index(Path(live["memory_root"]))
    print(f"配置与 Hook 已升级；历史记忆未改写；配置备份：{backup_dir / 'self-improving-config.json'}")
    return print_report()


def command_uninstall(args: argparse.Namespace) -> int:
    config = load_config()
    live = resolved(config)
    delete_target: Path | None = None
    if args.delete_data:
        delete_target = validate_delete_target(Path(live["memory_root"]), PACKAGE_ROOT)
        expected = str(delete_target)
        if args.confirm != expected:
            print(f"删除私人记忆需要同时传入 --confirm '{expected}'。", file=sys.stderr)
            return 2
    for platform, settings in config["agents"].items():
        if settings.get("enabled"):
            uninstall_hooks(config, platform)
            print(f"✅ 已移除 {platform} 自我进化 Hook")
    for path in uninstall_skill_links():
        print(f"✅ 已移除 Skill 入口：{path}")
    if delete_target:
        import shutil

        shutil.rmtree(delete_target)
        print("私人记忆已删除。")
    else:
        print("私人记忆和配置已保留。")
    return 0


def command_knowledge(args: argparse.Namespace) -> int:
    import json
    from self_improving import knowledge
    config = resolved(load_config())
    if args.knowledge_action == "accept":
        result = knowledge.accept(config, args.revision)
    elif args.knowledge_action == "read":
        result = knowledge.read(config, args.id, args.full)
    elif args.knowledge_action == "list" and args.all:
        result = knowledge.discover(config)
    else:
        result = knowledge.check(config)
    if getattr(args, "json", False) or args.knowledge_action == "accept":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.knowledge_action == "read":
        print(f"{result['path']} [{result['status']}] {result['revision']}\n\n{result['body']}")
    elif isinstance(result, list):
        print("\n".join(result))
    else:
        print(f"revision: {result['revision']}")
        for row in result["items"]:
            print(f"{row['id']} | {row['status']} | {row.get('title', '')} | {row['estimated_tokens']} estimated tokens" + (f" | {row['error']}" if "error" in row else ""))
        for group in result.get("exact_duplicate_groups", []):
            print("Exact duplicate wording; review scope before merging: " + ", ".join(group))
    return int(args.knowledge_action == "check" and not (result["structural_ok"] and result["reviewed"]))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="self-improving")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    knowledge = sub.add_parser("knowledge")
    actions = knowledge.add_subparsers(dest="knowledge_action", required=True)
    for name in ("check", "list", "read", "accept"):
        action = actions.add_parser(name)
        action.add_argument("--json", action="store_true")
        if name == "read":
            action.add_argument("id")
            action.add_argument("--full", action="store_true")
        if name == "list":
            action.add_argument("--all", action="store_true")
        if name == "accept":
            action.add_argument("--revision", required=True)
    knowledge.set_defaults(func=command_knowledge)
    init = sub.add_parser("init")
    init.add_argument("--agents", type=_agents, default=("claude", "codex"))
    init.add_argument("--memory-root", default="~/Documents/self-improving-memory")
    init.add_argument("--capture-corrections", action=argparse.BooleanOptionalAction, default=None)
    init.add_argument("--capture-errors", action=argparse.BooleanOptionalAction, default=False)
    init.set_defaults(func=command_init)

    for name in ("doctor", "status"):
        command = sub.add_parser(name)
        command.set_defaults(func=command_status)

    sync = sub.add_parser("sync")
    sync.add_argument("--check", action="store_true")
    sync.set_defaults(func=command_sync)

    persistence = sub.add_parser("persistence")
    persistence.add_argument("action", choices=("enable", "disable"))
    persistence.set_defaults(func=command_persistence)

    review = sub.add_parser("review")
    review_sub = review.add_subparsers(dest="review_action", required=True)
    list_action = review_sub.add_parser("list")
    list_action.add_argument("--json", action="store_true", help="machine-readable output for agent pre-review")
    review_sub.add_parser("legacy-list")
    lifecycle_list = review_sub.add_parser("lifecycle-list")
    lifecycle_list.add_argument("--json", action="store_true")
    for name in ("approve", "reject"):
        action = review_sub.add_parser(name)
        action.add_argument("--fingerprint", required=True)
        if name == "approve":
            action.add_argument("--correct", required=True)
            action.add_argument("--scope", required=True, help="global, repo:/absolute/path, or project:/absolute/path")
            action.add_argument("--priority", choices=("normal", "critical"), default="normal")
            action.add_argument("--promotion-target", required=True)
            action.add_argument("--review-after-days", type=int, default=30)
            action.add_argument("--expires-after-days", type=int, default=90)
    revoke_action = review_sub.add_parser("revoke")
    revoke_action.add_argument("--fingerprint", required=True)
    promote_action = review_sub.add_parser("promote")
    promote_action.add_argument("--fingerprint", required=True)
    interactive_approve = review_sub.add_parser("approve-interactive")
    interactive_approve.add_argument("--fingerprint", required=True)
    legacy_action = review_sub.add_parser("import-legacy")
    legacy_action.add_argument("--legacy-id", required=True, help="stable id returned by review legacy-list")
    legacy_action.add_argument("--correct", required=True)
    legacy_action.add_argument("--scope", required=True, help="global, repo:/absolute/path, or project:/absolute/path")
    legacy_action.add_argument("--priority", choices=("normal", "critical"), default="normal")
    legacy_action.add_argument("--promotion-target", required=True)
    legacy_action.add_argument("--review-after-days", type=int, default=30)
    legacy_action.add_argument("--expires-after-days", type=int, default=90)
    interactive_legacy = review_sub.add_parser("import-legacy-interactive")
    interactive_legacy.add_argument("--legacy-id", required=True, help="stable id returned by review legacy-list")
    review.set_defaults(func=command_review)

    migrate = sub.add_parser("migrate")
    migrate.add_argument("kind", choices=("legacy",))
    migrate.add_argument("--apply", action="store_true")
    migrate.set_defaults(func=command_migrate)

    upgrade = sub.add_parser("upgrade")
    upgrade.set_defaults(func=command_upgrade)

    uninstall = sub.add_parser("uninstall")
    data_action = uninstall.add_mutually_exclusive_group()
    data_action.add_argument("--keep-data", action="store_true")
    data_action.add_argument("--delete-data", action="store_true")
    uninstall.add_argument("--confirm")
    uninstall.set_defaults(func=command_uninstall)

    hook = sub.add_parser("hook")
    hook.add_argument("--platform", choices=("claude", "codex"), required=True)
    hook.add_argument("--event", required=True)
    hook.set_defaults(func=lambda args: run_hook(args.platform, args.event))
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (OSError, ValueError, KeyError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
