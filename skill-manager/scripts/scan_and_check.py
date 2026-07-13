#!/usr/bin/env python3
"""检查更新：本地装的 vs 上游最新。

用法:
  python3 scan_and_check.py           人类可读表格
  python3 scan_and_check.py --json    原始 JSON（供其他脚本消费）

2026-07-11 重写：旧版自己实现了一套收集逻辑，与 list 各说各话，且把
「远程最新 tag」填进版本列冒充本地版本（本地明明装的是 13.10.2，却显示
13.10.3）。现在统一走 core，本地版本与上游版本严格分列，绝不混为一谈。
"""
import io
import os
import sys
import json
import concurrent.futures

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

if any(a in ("-h", "--help") for a in sys.argv[1:]):
    print(__doc__)
    sys.exit(0)

AS_JSON = "--json" in sys.argv


def remote_latest(url, tags_ok=True):
    """上游最新的发布点 → (ref, commit_sha)。

    口径必须和 update 一致：update 更新到最新 tag，check 若拿 HEAD 比，
    HEAD 永远领先 tag 几个未发版的 commit —— 更新完照样报「有新版」，
    这个黄灯永远消不掉，用户会直接无视它。
    tags_ok=False 用于插件：插件是按 commit 装的（update 也走 HEAD），拿 tag 比会误报。
    """
    if tags_ok:
        ref, sha = core.latest_tag(url)
        if ref:
            return ref, sha
    sha = core.remote_head(url)
    return ("HEAD", sha) if sha else (None, None)


def marketplace_repo(marketplace):
    src = (core.read_json(core.KNOWN_MARKETPLACES_JSON, {})
           .get(marketplace, {}).get("source", {}))
    repo = src.get("repo")
    if not repo:
        return None
    return repo if "://" in repo else f"https://github.com/{repo}"


def check_one(target):
    kind, name, url, local_hash, extra = target
    base = {**extra, "kind": kind, "name": name}
    if extra.get("frozen"):
        return {**base, "status": "frozen",
                "message": "已冻结（脱离上游，按本地版本号管）"}
    if not url:
        return {**base, "status": "local", "message": "本地 skill，无上游可比"}
    # 插件是按 commit 装的（update 也走 HEAD），拿 tag 比会永远误报「有新版」
    ref, rh = remote_latest(url, tags_ok=(kind != "plugin"))
    if not rh:
        return {**base, "status": "error", "message": f"连不上 {url}"}
    if not local_hash:
        return {**base, "remote": ref, "status": "unknown",
                "message": "本地没记 commit，无法比对"}
    if rh.startswith(local_hash[:12]):
        return {**base, "remote": ref, "status": "current", "message": f"已是最新（{ref}）"}
    return {**base, "remote": ref, "status": "outdated", "message": f"上游有新版 {ref}"}


def build_targets():
    skills = core.collect_all(all_projects=True)
    targets, seen = [], set()

    for s in skills:
        if s.source in ("github", "frozen") and s.name not in seen:
            seen.add(s.name)
            targets.append((
                "skill", s.name, s.github_url, s.github_hash,
                {"local": s.version, "enabled": s.enabled,
                 "frozen": s.source == "frozen"},
            ))

    # 插件的启用状态要从它旗下任一 skill 上取（插件本身不出现在 skill 列表里）
    plugin_enabled = {}
    for s in skills:
        if s.plugin_key:
            plugin_enabled[s.plugin_key] = plugin_enabled.get(s.plugin_key) or s.enabled

    registry = core.read_json(core.INSTALLED_PLUGINS_JSON, {}).get("plugins", {})
    for key, installs in registry.items():
        if key in seen:
            continue
        seen.add(key)
        ins = installs[0] if installs else {}
        targets.append((
            "plugin", key, marketplace_repo(key.split("@")[-1]),
            ins.get("gitCommitSha", ""),
            {"local": ins.get("version", "—"),
             "enabled": plugin_enabled.get(key, False), "frozen": False},
        ))
    return targets


ICON = {"current": "🟢", "outdated": "🟡", "frozen": "🔒",
        "local": "⚪", "error": "🔴", "unknown": "⚪"}
ORDER = {"outdated": 0, "error": 1, "unknown": 2, "current": 3, "frozen": 4, "local": 5}


def main():
    targets = build_targets()
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        results = list(ex.map(check_one, targets))

    if AS_JSON:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return

    results.sort(key=lambda r: (ORDER.get(r["status"], 9), r["name"]))
    rows = [(f"{ICON.get(r['status'], '·')} {r['name']}",
             "生效" if r["enabled"] else "未启用",
             str(r.get("local", "—")), r["message"]) for r in results]

    w_n = max(core.dw("Skill / 插件"), max(core.dw(r[0]) for r in rows))
    w_e = max(core.dw("状态"), max(core.dw(r[1]) for r in rows))
    w_l = max(core.dw("本地版本"), max(core.dw(r[2]) for r in rows))

    print("\n检查更新（本地装的 vs 上游最新）\n")
    print(f" {core.pad('Skill / 插件', w_n)} | {core.pad('状态', w_e)} | "
          f"{core.pad('本地版本', w_l)} | 上游")
    print(f" {'-' * w_n}-+-{'-' * w_e}-+-{'-' * w_l}-+-{'-' * 22}")
    for n, e, l, m in rows:
        print(f" {core.pad(n, w_n)} | {core.pad(e, w_e)} | {core.pad(l, w_l)} | {m}")

    outdated = [r for r in results if r["status"] == "outdated"]
    if outdated:
        print(f"\n🟡 {len(outdated)} 个有新版：")
        for r in outdated:
            tail = "" if r["enabled"] else "   ← 未启用，可以不管"
            print(f"   /skill-manager update {r['name']}{tail}")
    else:
        print("\n🎉 所有可追踪的 skill 都是最新")
    print()


if __name__ == "__main__":
    main()
