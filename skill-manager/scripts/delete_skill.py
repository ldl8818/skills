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

2026-07-11 补漏：删「直装 skill」这条路径漏得比插件更狠——
- 中文描述表压根没清，删完就在 descriptions_zh.json 留个死条目（doctor 第 3 项擦屁股）；
- 指纹用裸名 `name` 查表，可真正的 key 是 `global:<name>`，永远查不中，等于从没清过。
**「删干净」的判定标准是「所有留了它名字的地方」，两条路径要对称，不是插件那条想周全了就完事。**
"""
import io
import os
import sys
import shutil
import copy
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ARCHIVE_ROOT = os.path.join(core.CLAUDE_DIR, "skills-archive", "_deleted")


def archive_dir(path, label):
    """把目录移进归档区（而非 rmtree），返回归档后的路径。"""
    core.safe_component(label, "归档标签")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    dest = os.path.join(ARCHIVE_ROOT, f"{label}.{ts}")
    core.contained_path(ARCHIVE_ROOT, os.path.basename(dest))
    os.makedirs(ARCHIVE_ROOT, exist_ok=True)
    shutil.move(path, dest)
    return dest


# ── 删直装 skill ──────────────────────────────────────────

def delete_direct_skill(name, dry_run=False, project=None):
    core.safe_component(name, "skill 名")
    root = os.path.join(os.path.abspath(project), ".claude", "skills") if project else core.GLOBAL_SKILLS_DIR
    skill_dir = os.path.join(root, name)
    if not os.path.isdir(skill_dir):
        print(f"❌ {name} 不在 {root} 下")
        return False

    fps = core.read_json(core.FINGERPRINTS, {})
    zh = core.read_json(core.DESCRIPTIONS_ZH, {})
    # 指纹的 key 是 core._make_direct_skill 里的 f"{scope}:{name}"，不是裸名。
    # 拿裸名去查表永远查不中，删了也清不掉——旧版就是这么漏的。
    fp_key = f"{os.path.abspath(project) if project else 'global'}:{name}"

    print(f"将删除 skill：{name}")
    print(f"   目录       {skill_dir}")
    if fp_key in fps:
        print(f"   指纹记录   fingerprints.json → {fp_key}")
    if name in zh:
        print(f"   中文描述   descriptions_zh.json → {name}")
    if dry_run:
        print("\n（--dry-run：只看不做）")
        return True

    dest = archive_dir(skill_dir, name)
    try:
        if fp_key in fps:
            del fps[fp_key]
            core.write_json(core.FINGERPRINTS, fps)
        if name in zh:
            del zh[name]
            core.write_json(core.DESCRIPTIONS_ZH, zh)
    except Exception:
        if os.path.exists(dest) and not os.path.exists(skill_dir):
            os.makedirs(os.path.dirname(skill_dir), exist_ok=True)
            shutil.move(dest, skill_dir)
        raise
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
    original_registry = copy.deepcopy(registry)
    plugins = registry.get("plugins", {})
    if key not in plugins:
        print(f"❌ 插件 {key} 未安装")
        return False

    installs = plugins[key] or [{}]
    install_path = installs[0].get("installPath", "")
    # 连版本目录的父目录一起删（cache/<市场>/<插件名>/），只删版本目录会留个空壳
    plugin_cache = os.path.dirname(install_path) if install_path else ""
    if plugin_cache:
        expected_root = os.path.join(core.CLAUDE_DIR, "plugins", "cache")
        resolved_cache = os.path.realpath(plugin_cache)
        if os.path.commonpath((os.path.realpath(expected_root), resolved_cache)) != os.path.realpath(expected_root):
            print(f"❌ 登记的 installPath 越过插件缓存边界，拒绝移动：{install_path}")
            return False
        expected_name = key.split("@")[0]
        if os.path.basename(resolved_cache) != expected_name:
            print(f"❌ 登记的 installPath 与插件名不匹配，拒绝移动：{install_path}")
            return False

    zh = core.read_json(core.DESCRIPTIONS_ZH, {})
    sub_skills = [s for s in _plugin_skill_names(install_path) if s in zh]
    settings_hits = _settings_with_plugin(key)
    original_settings = {path: core.read_json(path, {}) for path in settings_hits}
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
    moved = []
    try:
        if plugin_cache and os.path.isdir(plugin_cache):
            dest = archive_dir(plugin_cache, key.replace("@", "_at_"))
            moved.append((dest, plugin_cache))
        for d in data_dirs:
            archived = archive_dir(d, os.path.basename(d) + ".data")
            moved.append((archived, d))

        del plugins[key]
        core.write_json(core.INSTALLED_PLUGINS_JSON, registry)

        if sub_skills:
            for s in sub_skills:
                del zh[s]
            core.write_json(core.DESCRIPTIONS_ZH, zh)

        for path in settings_hits:
            data = copy.deepcopy(original_settings[path])
            del data["enabledPlugins"][key]
            core.write_json(path, data)
    except Exception:
        core.write_json(core.INSTALLED_PLUGINS_JSON, original_registry)
        for path, data in original_settings.items():
            core.write_json(path, data)
        for archived, original in reversed(moved):
            if os.path.exists(archived) and not os.path.exists(original):
                os.makedirs(os.path.dirname(original), exist_ok=True)
                shutil.move(archived, original)
        raise

    print(f"\n✅ 已删除插件 {key}")
    if dest:
        print(f"📦 已归档到 {dest}（后悔了搬回 plugins/cache/ 并恢复登记表）")
    return True


if __name__ == "__main__":
    argv = sys.argv[1:]
    if any(a in ("-h", "--help") for a in argv):
        print(__doc__)
        sys.exit(0)
    project = None
    if "--project" in argv:
        i = argv.index("--project")
        if i + 1 >= len(argv):
            print("❌ --project 后面要跟项目路径")
            sys.exit(1)
        project = argv[i + 1]
        del argv[i:i + 2]
    names = [a for a in argv if not a.startswith("-")]
    flags = {a for a in argv if a.startswith("-")}

    unknown = flags - {"--dry-run"}
    if unknown or not names:
        if unknown:
            print(f"❌ 不认识的参数: {'、'.join(sorted(unknown))}")
        print("用法: python3 delete_skill.py <名字> [--project <路径>] [--dry-run]")
        sys.exit(1)

    dry = "--dry-run" in flags
    kind, key, err = ("skill", names[0], None) if project else core.resolve_target(names[0])
    if err:
        print(f"❌ {err}")
        sys.exit(1)

    ok = (delete_plugin(key, dry) if kind == "plugin"
          else delete_direct_skill(key, dry, project))
    sys.exit(0 if ok else 1)
