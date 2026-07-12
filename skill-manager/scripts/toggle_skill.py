#!/usr/bin/env python3
"""启用 / 禁用 skill 或插件。

用法:
  python3 toggle_skill.py enable  <名字> [--project <路径>]
  python3 toggle_skill.py disable <名字> [--project <路径>]

两种目标的机制完全不同：
  直装 skill → 重命名 SKILL.md ↔ SKILL.md.disabled
  插件       → 改 settings.json 的 enabledPlugins（全局或项目级）

--project 只对插件有意义：把插件启用在某个项目而非全局
（baoyu 就是这么用的：全局关、~/creative 开）。
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


def resolve_plugin_key(name):
    """支持简写：baoyu-skills → baoyu-skills@baoyu-skills。歧义则报错让用户写全。"""
    registry = core.read_json(core.INSTALLED_PLUGINS_JSON, {}).get("plugins", {})
    if name in registry:
        return name
    hits = [k for k in registry if k.split("@")[0] == name]
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        print(f"❌ {name} 有多个匹配，请写全：{', '.join(hits)}")
        sys.exit(1)
    return None


def toggle_plugin(key, enable, project):
    settings_path = (os.path.join(os.path.abspath(project), ".claude", "settings.json")
                     if project else core.GLOBAL_SETTINGS)
    where = f"项目 {os.path.basename(os.path.abspath(project))} " if project else "全局"

    data = core.read_json(settings_path, {})
    plugins = data.setdefault("enabledPlugins", {})
    if plugins.get(key) is enable:
        print(f"ℹ️  {key} 在{where}已经是{'启用' if enable else '禁用'}状态，无需改动")
        return
    plugins[key] = enable
    core.write_json(settings_path, data)
    print(f"✅ {key} 已在{where}{'启用' if enable else '禁用'}")
    print(f"   写入 {settings_path}")
    print("   重启 Claude Code 会话后生效")


def toggle_direct(name, enable, project=None):
    """在全局和所有已登记项目里找这个 skill。"""
    core.safe_component(name, "skill 名")
    roots = ([(os.path.join(os.path.abspath(project), ".claude", "skills"),
               f"项目 {os.path.basename(os.path.abspath(project))}")] if project else
             [(core.GLOBAL_SKILLS_DIR, "全局")] + [
                 (os.path.join(p, ".claude", "skills"), f"项目 {os.path.basename(p)}")
                 for p in core.load_projects()])

    for root, where in roots:
        d = os.path.join(root, name)
        if not os.path.isdir(d):
            continue
        md = os.path.join(d, "SKILL.md")
        md_dis = os.path.join(d, "SKILL.md.disabled")
        if enable:
            if os.path.exists(md):
                print(f"ℹ️  {name}（{where}）已经是启用状态")
                return True
            if os.path.exists(md_dis):
                os.rename(md_dis, md)
                print(f"✅ {name}（{where}）已启用")
                print("   重启 Claude Code 会话后生效")
                return True
        else:
            if os.path.exists(md_dis):
                print(f"ℹ️  {name}（{where}）已经是禁用状态")
                return True
            if os.path.exists(md):
                os.rename(md, md_dis)
                print(f"✅ {name}（{where}）已禁用")
                print("   重启 Claude Code 会话后生效")
                return True
    return False


def main():
    if len(sys.argv) < 3 or sys.argv[1] not in ("enable", "disable"):
        print(__doc__)
        sys.exit(1)

    action, name = sys.argv[1], sys.argv[2]
    try:
        if "@" not in name:
            core.safe_component(name, "skill 名")
    except ValueError as exc:
        print(f"❌ {exc}")
        sys.exit(1)
    enable = action == "enable"
    project = None
    if "--project" in sys.argv:
        i = sys.argv.index("--project")
        if i + 1 >= len(sys.argv):
            print("❌ --project 后面要跟项目路径")
            sys.exit(1)
        project = sys.argv[i + 1]
        if not os.path.isdir(project):
            print(f"❌ 项目路径不存在：{project}")
            sys.exit(1)

    project_direct = (project and os.path.isdir(os.path.join(
        os.path.abspath(project), ".claude", "skills", name)))
    key = None if project_direct else resolve_plugin_key(name)
    if key:
        toggle_plugin(key, enable, project)
        return

    if not toggle_direct(name, enable, project):
        print(f"❌ 找不到 skill 或插件：{name}")
        print("   用 /skill-manager list 查看全部名字")
        sys.exit(1)


if __name__ == "__main__":
    main()
