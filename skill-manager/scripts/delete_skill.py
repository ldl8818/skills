#!/usr/bin/env python3
"""删除 skill 或插件。

用法:
  python3 delete_skill.py <名字>              删除；插件可只写裸名（自动补 @市场名）
  python3 delete_skill.py <名字> --dry-run    只列出将删掉什么，不动手

2026-07-11 重写：
- 旧版 `shutil.rmtree` 硬删，删错了没救。现在一律**移到归档目录**
  `~/.claude/skills-archive/_deleted/<名>.<时间戳>/`，跟 update 的备份同一套思路，
  后悔了搬回去就行。真要腾空间再去手动清那个目录。
- 旧版只认 `~/.claude/skills/` 下的目录，插件删不掉。现在走 `core.resolve_target`，
  裸名字自动判断是 skill 还是插件。
- 删插件要清的不止一处：登记表、缓存目录、中文描述表、全局与项目的启用开关。
  漏一处就留下指向不存在插件的脏数据（doctor 第 1 项就是为这种残留加的）。
"""
import os
import sys
import shutil
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core

ARCHIVE_ROOT = os.path.join(core.CLAUDE_DIR, "skills-archive", "_deleted")


def archive_dir(path, label):
    """把目录移进归档区（而非 rmtree），返回归档后的路径。"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(ARCHIVE_ROOT, f"{label}.{ts}")
    os.makedirs(ARCHIVE_ROOT, exist_ok=True)
    shutil.move(path, dest)
    return dest


# ── 删直装 skill ──────────────────────────────────────────

def delete_direct_skill(name, dry_run=False):
    skill_dir = os.path.join(core.GLOBAL_SKILLS_DIR, name)
    if not os.path.isdir(skill_dir):
        print(f"❌ {name} 不在 ~/.claude/skills/ 下")
        return False

    fps = core.read_json(core.FINGERPRINTS, {})
    print(f"将删除 skill：{name}")
    print(f"   目录       {skill_dir}")
    if name in fps:
        print(f"   指纹记录   fingerprints.json → {name}")
    if dry_run:
        print("\n（--dry-run：只看不做）")
        return True

    dest = archive_dir(skill_dir, name)
    if name in fps:
        del fps[name]
        core.write_json(core.FINGERPRINTS, fps)
    print(f"\n✅ 已删除 {name}")
    print(f"📦 已归档到 {dest}（后悔了搬回 ~/.claude/skills/ 即可）")
    return True


# ── 删插件：四处登记一起清 ─────────────────────────────────

def _plugin_skill_names(install_path):
    """插件旗下的 skill 名（用于清 descriptions_zh.json）。"""
    skills_dir = os.path.join(install_path, "skills")
    if not os.path.isdir(skills_dir):
        return []
    return [d for d in os.listdir(skills_dir)
            if os.path.isfile(os.path.join(skills_dir, d, "SKILL.md"))]


def _settings_with_plugin(key):
    """哪些 settings.json 的 enabledPlugins 里提到了这个插件。"""
    hits = []
    for path in [core.GLOBAL_SETTINGS] + [
            os.path.join(p, ".claude", "settings.json") for p in core.known_projects()]:
        data = core.read_json(path, {})
        if key in data.get("enabledPlugins", {}):
            hits.append(path)
    return hits


def _plugin_data_dirs(key):
    """插件的运行时数据目录 `plugins/data/<插件名>-<市场名>/`（另有 `-inline` 变体）。

    第五处登记 —— 2026-07-11 删 imessage 时才发现漏了它，残留了个空目录。
    **删干净的定义是「所有留了它名字的地方」，不是「我想得起来的地方」。**
    """
    name, market = key.split("@")[0], key.split("@")[-1]
    root = os.path.join(core.CLAUDE_DIR, "plugins", "data")
    return [d for d in (os.path.join(root, f"{name}-{market}"),
                        os.path.join(root, f"{name}-inline"))
            if os.path.isdir(d)]


def delete_plugin(key, dry_run=False):
    registry = core.read_json(core.INSTALLED_PLUGINS_JSON, {})
    plugins = registry.get("plugins", {})
    if key not in plugins:
        print(f"❌ 插件 {key} 未安装")
        return False

    installs = plugins[key] or [{}]
    install_path = installs[0].get("installPath", "")
    # 连版本目录的父目录一起删（cache/<市场>/<插件名>/），只删版本目录会留个空壳
    plugin_cache = os.path.dirname(install_path) if install_path else ""

    zh = core.read_json(core.DESCRIPTIONS_ZH, {})
    sub_skills = [s for s in _plugin_skill_names(install_path) if s in zh]
    settings_hits = _settings_with_plugin(key)
    data_dirs = _plugin_data_dirs(key)

    print(f"将删除插件：{key}")
    if plugin_cache and os.path.isdir(plugin_cache):
        print(f"   缓存目录   {plugin_cache}")
    print(f"   登记表     installed_plugins.json → {key}")
    for s in sub_skills:
        print(f"   中文描述   descriptions_zh.json → {s}")
    for p in settings_hits:
        print(f"   启用开关   {p} → enabledPlugins.{key}")
    for d in data_dirs:
        size = "空" if not any(os.scandir(d)) else "有数据"
        print(f"   数据目录   {d}（{size}）")
    if dry_run:
        print("\n（--dry-run：只看不做）")
        return True

    dest = ""
    if plugin_cache and os.path.isdir(plugin_cache):
        dest = archive_dir(plugin_cache, key.replace("@", "_at_"))
    for d in data_dirs:
        # 有数据的一并归档（别静默丢掉用户数据）；空目录直接删
        if any(os.scandir(d)):
            archive_dir(d, os.path.basename(d) + ".data")
        else:
            os.rmdir(d)

    del plugins[key]
    core.write_json(core.INSTALLED_PLUGINS_JSON, registry)

    if sub_skills:
        for s in sub_skills:
            del zh[s]
        core.write_json(core.DESCRIPTIONS_ZH, zh)

    for path in settings_hits:
        data = core.read_json(path, {})
        del data["enabledPlugins"][key]
        core.write_json(path, data)

    print(f"\n✅ 已删除插件 {key}")
    if dest:
        print(f"📦 已归档到 {dest}（后悔了搬回 plugins/cache/ 并恢复登记表）")
    return True


if __name__ == "__main__":
    argv = sys.argv[1:]
    names = [a for a in argv if not a.startswith("-")]
    flags = {a for a in argv if a.startswith("-")}

    unknown = flags - {"--dry-run"}
    if unknown or not names:
        if unknown:
            print(f"❌ 不认识的参数: {'、'.join(sorted(unknown))}")
        print("用法: python3 delete_skill.py <名字> [--dry-run]")
        sys.exit(1)

    dry = "--dry-run" in flags
    kind, key, err = core.resolve_target(names[0])
    if err:
        print(f"❌ {err}")
        sys.exit(1)

    ok = (delete_plugin(key, dry) if kind == "plugin"
          else delete_direct_skill(key, dry))
    sys.exit(0 if ok else 1)
