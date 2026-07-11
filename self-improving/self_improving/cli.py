"""Command-line interface for installation, Hooks, review and migration."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from self_improving.config import default_config, load_config, resolved, write_config
from self_improving import __version__
from self_improving.doctor import print_report
from self_improving.hooks.common import run as run_hook
from self_improving.installer import install_hooks, install_skill_links, uninstall_hooks, uninstall_skill_links
from self_improving.indexing import sync_index
from self_improving.migration import discover_legacy, write_manifest
from self_improving.paths import PACKAGE_ROOT, expand_path
from self_improving.review import decide, list_candidates
from self_improving.storage import initialize_memory, validate_delete_target


def _agents(value: str) -> tuple[str, ...]:
    result = tuple(item.strip() for item in value.split(",") if item.strip())
    invalid = set(result) - {"claude", "codex"}
    if invalid:
        raise argparse.ArgumentTypeError(f"unsupported agents: {', '.join(sorted(invalid))}")
    return result


def command_init(args: argparse.Namespace) -> int:
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


def command_review(args: argparse.Namespace) -> int:
    config = resolved(load_config())
    root = Path(config["memory_root"])
    state_root = Path(config["state_root"])
    if args.review_action == "list":
        rows = list_candidates(root)
        print("\n".join(rows) if rows else "没有待审核候选。")
        return 0
    print(decide(root, state_root, args.fingerprint, args.review_action, args.correct or ""))
    return 0


def command_migrate(args: argparse.Namespace) -> int:
    discovery = discover_legacy()
    print("旧版记忆目录：" + str(discovery["memory_root"]))
    print(f"旧版外围脚本：{len(discovery['legacy_scripts'])} 个")
    if not args.apply:
        print("当前为预览；加 --apply 才会写配置和 Hook。")
        return 0
    if not discovery["memory_root"]:
        print("未找到旧版记忆目录。", file=sys.stderr)
        return 1
    config = default_config(discovery["memory_root"])
    config["persistence"]["capture_corrections"] = True
    config["persistence"]["capture_command_errors"] = True
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
    config = load_config()
    live = resolved(config)
    initialize_memory(Path(live["memory_root"]), PACKAGE_ROOT)
    config.pop("temp_root", None)
    config.pop("retention", None)
    config["persistence"].pop("central_error_fallback", None)
    write_config(config)
    for platform, settings in config["agents"].items():
        if settings.get("enabled"):
            install_hooks(config, platform)
    sync_index(Path(live["memory_root"]))
    print("配置与 Hook 已升级；私人记忆未改动。")
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="self-improving")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
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
    review_sub.add_parser("list")
    for name in ("approve", "reject"):
        action = review_sub.add_parser(name)
        action.add_argument("--fingerprint", required=True)
        if name == "approve":
            action.add_argument("--correct", required=True)
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
