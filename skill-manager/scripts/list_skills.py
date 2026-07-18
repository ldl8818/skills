#!/usr/bin/env python3
"""列出 skill，按「是否真正生效」分组。

用法:
  python3 list_skills.py               全局 + 当前目录的项目级 skill
  python3 list_skills.py <项目名|路径>  指定项目：项目 skill + 全局 skill 分开列
  python3 list_skills.py --all         全景，按最近活跃展开前 3 个项目，其余折叠
  python3 list_skills.py --all -n 10   多展开几个（-n 0 = 全部展开）

2026-07-11 重写：旧版遍历硬盘登记表，把已禁用的插件也列成「已安装」。
现在启用状态一律从 settings.json 真实读取（见 core.py）。

2026-07-11 二改（项目视图）：
  · 默认 list 会把「只在别的项目启用」的插件整块印出来（例如在 demo-a 里
    印出 creative 的 21 行）—— 根因是插件的生效范围拿全量项目算，
    算完却不筛。现在生效范围照旧全量算（否则看不见 baoyu 只在 creative 开），
    但**只展示视野内的项目**，视野外的折叠成一行摘要。项目越多，收益越大。
  · 「最近活跃」不再用 projects.json 的 last_seen（那只记「最后一次跑过
    skill-manager」），改用 Claude Code 的会话记录（见 core.session_activity）。
"""
import io
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

MAX_DESC = 40
DEFAULT_EXPAND = 3  # --all 默认展开几个项目

PLUGIN_SOURCES = ("plugin", "plugin-cmd", "codex-plugin")


def is_plugin(s):
    return s.source in PLUGIN_SOURCES


def version_cell(s):
    """版本列同时承载两个标记：* = 改了没记账，🔒 = 冻结（不跟上游更新）。"""
    return s.version + ("*" if s.dirty else "") + (" 🔒" if s.frozen else "")


def scope_projects(label):
    """从 scope_label 反解出项目名。

    直装 skill 是「项目:demo-a」；插件可能同时在多个项目启用，
    core 会拼成「项目:demo-a/demo-b」。返回 [] 表示全局。
    """
    if not label.startswith("项目:"):
        return []
    return label[len("项目:"):].split("/")


def is_global_scope(label):
    return label in ("全局", "Codex 内置") or label.endswith(" 全局") \
        or label.startswith("全局直装（")


def plugin_group_label(s):
    client = "Codex" if s.source == "codex-plugin" else "Claude"
    scope = "全局" if is_global_scope(s.scope_label) else s.scope_label
    return f"{client} 插件 · {scope}"


def print_table(skills):
    if not skills:
        return
    rows = [(s.name, core.trim(s.desc, MAX_DESC), s.kind, s.origin, version_cell(s))
            for s in skills]
    w_n = max(core.dw("Skill"), max(core.dw(r[0]) for r in rows))
    w_d = max(core.dw("描述"), max(core.dw(r[1]) for r in rows))
    w_k = max(core.dw("类型"), max(core.dw(r[2]) for r in rows))
    w_o = max(core.dw("来源"), max(core.dw(r[3]) for r in rows))
    print(f" {core.pad('Skill', w_n)} | {core.pad('描述', w_d)} | "
          f"{core.pad('类型', w_k)} | {core.pad('来源', w_o)} | 版本")
    print(f" {'-'*w_n}-+-{'-'*w_d}-+-{'-'*w_k}-+-{'-'*w_o}-+-{'-'*14}")
    for n, d, k, o, v in rows:
        print(f" {core.pad(n, w_n)} | {core.pad(d, w_d)} | {core.pad(k, w_k)} | "
              f"{core.pad(o, w_o)} | {v}")


def sort_skills(group):
    return sorted(group, key=lambda s: (is_plugin(s), s.origin, s.name))


def print_disabled_plugins(skills):
    """未启用的插件按插件聚合 —— 19 个 claude-mem skill 各印一行毫无意义。"""
    groups = {}
    for s in skills:
        groups.setdefault(s.plugin_key, []).append(s)
    if not groups:
        return
    total = sum(len(v) for v in groups.values())
    print(f"\n○ 未启用的插件（{len(groups)} 个插件，含 {total} 个 skill，不占用上下文）\n")
    rows = []
    for key, group in sorted(groups.items()):
        command = ("在 ~/.codex/config.toml 启用" if group[0].source == "codex-plugin"
                   else f"/skill-manager enable {key}")
        rows.append((key, str(len(group)), command))
    w_k = max(core.dw("插件"), max(core.dw(r[0]) for r in rows))
    w_c = max(core.dw("skill 数"), max(core.dw(r[1]) for r in rows))
    print(f" {core.pad('插件', w_k)} | {core.pad('skill 数', w_c)} | 启用方式")
    print(f" {'-'*w_k}-+-{'-'*w_c}-+-{'-'*40}")
    for k, c, cmd in rows:
        print(f" {core.pad(k, w_k)} | {core.pad(c, w_c)} | {cmd}")


def print_folded(folded, acts, paths_by_name, title):
    """视野外的项目：一个项目一行，不把它们的 skill 表整块印出来。"""
    if not folded:
        return
    per_project = {}
    for s in folded:
        for name in scope_projects(s.scope_label):
            per_project.setdefault(name, []).append(s)
    if not per_project:
        return
    print(f"\n○ {title}（{len(per_project)} 个项目，{len(folded)} 个 skill）\n")

    def when(name):
        p = paths_by_name.get(name)
        ts = acts.get(p) if p else None
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d") if ts else "—"

    rows = [(n, str(len(v)), when(n), f"/skill-manager list {n}")
            for n, v in sorted(per_project.items(),
                               key=lambda kv: -len(kv[1]))]
    w_n = max(core.dw("项目"), max(core.dw(r[0]) for r in rows))
    w_c = max(core.dw("skill 数"), max(core.dw(r[1]) for r in rows))
    w_t = max(core.dw("最近活跃"), max(core.dw(r[2]) for r in rows))
    print(f" {core.pad('项目', w_n)} | {core.pad('skill 数', w_c)} | "
          f"{core.pad('最近活跃', w_t)} | 查看")
    print(f" {'-'*w_n}-+-{'-'*w_c}-+-{'-'*w_t}-+-{'-'*30}")
    for n, c, t, cmd in rows:
        print(f" {core.pad(n, w_n)} | {core.pad(c, w_c)} | {core.pad(t, w_t)} | {cmd}")


def print_warnings(skills, live):
    # 健康提示：细节交给 doctor，这里只提醒有没有账要平。
    # 口径必须和 doctor 一致——只看生效中的，否则两个命令会给出互相矛盾的数字
    no_zh = [s for s in live if not s.desc_zh and s.source != "codex-system"]
    dirty = [s for s in skills if s.dirty]
    undef = [s for s in live if s.version == "未定版"]
    warn = []
    if no_zh:
        warn.append(f"{len(no_zh)} 个缺中文描述")
    if dirty:
        warn.append(f"{len(dirty)} 个改过但版本号没跟上（带 *）")
    if undef:
        warn.append(f"{len(undef)} 个还没定版本号")
    if warn:
        print(f"\n⚠  {' · '.join(warn)} → /skill-manager doctor 查看并修复")


def render_project(path, skills):
    """单项目视图：直装 Skill 与插件分开，范围仍按项目／全局统计。"""
    live = [s for s in skills if s.enabled]
    name = os.path.basename(path)
    mine = sort_skills([s for s in live if name in scope_projects(s.scope_label)])
    glob = sort_skills([s for s in live if is_global_scope(s.scope_label)])

    print(f"\n📦 {name}   {path}")
    print(f"   项目 {len(mine)} · 全局 {len(glob)} · "
          f"合计 {len(mine) + len(glob)} 个在此生效")

    sections = [
        ("项目级 Skill", [s for s in mine if not is_plugin(s)]),
        ("项目启用的插件", [s for s in mine if is_plugin(s)]),
        ("全局直装", [s for s in glob if not is_plugin(s) and s.source != "codex-system"]),
        ("Codex 内置", [s for s in glob if s.source == "codex-system"]),
        ("全局启用的插件", [s for s in glob if is_plugin(s)]),
    ]
    for title, group in sections:
        if group:
            print(f"\n● {title}（{len(group)}）\n")
            print_table(group)

    dead_direct = [s for s in skills if not s.enabled and not is_plugin(s)]
    if dead_direct:
        print(f"\n○ 已禁用的 skill（{len(dead_direct)}）\n")
        print_table(sort_skills(dead_direct))
        print("\n  启用：/skill-manager enable <名字>")
    print_disabled_plugins([s for s in skills if not s.enabled and is_plugin(s)])
    print_warnings(skills, live)
    print()


def render_overview(skills, view_paths, all_mode, hidden_projects):
    """默认视图 / --all 视图：直装 Skill 与插件分开，再标明各自作用域。"""
    live = [s for s in skills if s.enabled]
    dead_direct = [s for s in skills if not s.enabled and not is_plugin(s)]
    dead_plugin = [s for s in skills if not s.enabled and is_plugin(s)]
    view_names = {os.path.basename(p) for p in view_paths}
    acts = core.session_activity()
    paths_by_name = {os.path.basename(p): p for p in core.known_projects()}

    def in_view(s):
        names = scope_projects(s.scope_label)
        return not names or bool(view_names.intersection(names))

    shown = [s for s in live if in_view(s)]
    folded = [s for s in live if not in_view(s)]

    print(f"\n共 {len(skills)} 个 skill · 生效 {len(live)} · "
          f"未启用 {len(dead_direct) + len(dead_plugin)}")
    if all_mode:
        total = len(view_paths) + hidden_projects
        print(f"（全部 {total} 个项目，按最近活跃展开前 {len(view_paths)} 个"
              f"{' · 全部展开：-n 0' if hidden_projects else ''}）")
    else:
        here = "、".join(sorted(view_names)) if view_names else "无"
        print(f"（范围：全局 + 当前项目 {here} · "
              f"看别的项目：/skill-manager list <项目名>）")

    by_scope = {}
    for s in shown:
        if is_plugin(s):
            continue
        by_scope.setdefault(s.scope_label, []).append(s)
    for label in sorted(by_scope, key=lambda x: (not is_global_scope(x), x)):
        group = sort_skills(by_scope[label])
        print(f"\n● {label}生效（{len(group)}）\n" if is_global_scope(label)
              else f"\n● {label}（{len(group)}）\n")
        print_table(group)

    by_plugin_scope = {}
    for s in shown:
        if is_plugin(s):
            by_plugin_scope.setdefault(plugin_group_label(s), []).append(s)
    for label in sorted(by_plugin_scope):
        group = sort_skills(by_plugin_scope[label])
        print(f"\n● {label}（{len(group)}）\n")
        print_table(group)

    if dead_direct:
        print(f"\n○ 已禁用的 skill（{len(dead_direct)}）\n")
        print_table(sort_skills(dead_direct))
        print("\n  启用：/skill-manager enable <名字>")

    print_disabled_plugins(dead_plugin)
    print_folded(folded, acts, paths_by_name,
                 "未展开的项目" if all_mode else "只在其他项目生效")
    print_warnings(skills, live)
    print()


def main():
    argv = sys.argv[1:]
    if any(a in ("-h", "--help") for a in argv):
        print(__doc__)
        return 0
    all_mode = "--all" in argv
    expand = DEFAULT_EXPAND
    if "-n" in argv:
        i = argv.index("-n")
        if i + 1 < len(argv) and argv[i + 1].lstrip("-").isdigit():
            expand = int(argv[i + 1])
            del argv[i:i + 2]
    token = next((a for a in argv if not a.startswith("-")), None)

    if token:
        path, cands = core.resolve_project(token)
        if not path:
            if not cands:
                print(f"\n找不到项目「{token}」。已知项目：")
                for p in core.rank_projects():
                    print(f"  {os.path.basename(p):<20} {p}")
                print("\n（项目要有已支持的 Skill 目录，或 .claude/settings.json 才算数）\n")
                return 1
            print(f"\n「{token}」匹配到 {len(cands)} 个项目，指定完整路径再来一次："
                  "\n（同名撞车不替你猜）\n")
            for p in cands:
                print(f"  /skill-manager list {p}")
            print()
            return 1
        render_project(path, core.collect_all(projects=[path]))
        return 0

    if all_mode:
        skills = core.collect_all(all_projects=True)
        ranked = core.rank_projects()
        view = ranked if expand <= 0 else ranked[:expand]
        render_overview(skills, view, True, len(ranked) - len(view))
    else:
        skills = core.collect_all()
        cwd = os.path.abspath(os.getcwd())
        view = [cwd] if core.is_project_dir(cwd) else []
        render_overview(skills, view, False, 0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
