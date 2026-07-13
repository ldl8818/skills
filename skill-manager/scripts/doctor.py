#!/usr/bin/env python3
"""自检：把「登记表说的」和「硬盘上真实存在的」逐项对账。

用法:
  python3 doctor.py           只报告，不改任何东西
  python3 doctor.py --fix     修掉能自动修的（删除一律走 trash，可恢复）

存在的理由（2026-07-11 实战事故）：
  installed_plugins.json 里 baoyu 的 installPath 指向一个不存在的目录
  （更新中断留下的），结果 ~/creative 里 21 个创作技能静默失效——不报错、
  就是不加载，直到有人去翻登记表才发现。这类「登记表和现实脱节」的问题
  必须有一条命令能一键查出来。

检查项:
  1. 插件登记表的 installPath 是否真实存在
  2. skills 目录里有没有断掉的软链接
  3. descriptions_zh.json 里指向已删 skill 的死条目
  4. 缺中文描述的 skill（列表里会显示英文）
  5. 来源未登记的 skill（→ trace 去溯源）
  6. 不知道装了哪一版的 GitHub skill
  7. 内容改过但版本号没跟上（带 * 的）
  8. 插件缓存里没被登记表引用的孤儿版本目录（纯占磁盘）
  9. 项目注册表里已经不存在的路径
 10. 落后主仓的 git worktree（里面的 skill 是主仓的旧副本）

铁律：--fix 只做有依据的补录（查 lock、查 GitHub API），绝不发明数据。
查不出来的就如实报出来，让人去 trace —— 编一个看起来权威的默认值最有害。
"""
import io
import os
import sys
import shutil
import subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

if any(a in ("-h", "--help") for a in sys.argv[1:]):
    print(__doc__)
    sys.exit(0)

FIX = "--fix" in sys.argv
PLUGIN_CACHE = os.path.join(core.CLAUDE_DIR, "plugins", "cache")


def dir_size(path):
    """纯 Python 算目录大小 —— 别用 `du`，Windows 上没有这个命令。"""
    total = 0
    for root, _dirs, files in os.walk(path):
        for fn in files:
            try:
                total += os.path.getsize(os.path.join(root, fn))
            except OSError:
                pass
    return total


def human_size(n):
    for unit in ("B", "K", "M", "G", "T"):
        if n < 1024:
            return f"{n:.0f}{unit}"
        n /= 1024
    return f"{n:.0f}P"


def trash(path):
    """优先用 trash（可从废纸篓恢复），没装才退回 shutil。"""
    if shutil.which("trash"):
        subprocess.run(["trash", path], check=True)
    else:
        archive = os.path.join(core.CLAUDE_DIR, "skills-archive", "_doctor_removed")
        os.makedirs(archive, exist_ok=True)
        target = os.path.join(archive, os.path.basename(path))
        if os.path.exists(target):
            target += f".{os.getpid()}"
        shutil.move(path, target)


class Report:
    def __init__(self):
        self.problems = 0
        self.fixed = 0

    def section(self, ok_msg, bad_msg, items, fixable=False, fixer=None, hint=None):
        if not items:
            print(f"  ✅ {ok_msg}")
            return
        self.problems += len(items)
        print(f"  ❌ {len(items)} {bad_msg}")
        for it in items:
            print(f"       {it}")
        if fixable and FIX and fixer:
            ok = 0
            for it in items:
                try:
                    fixer(it)
                    ok += 1
                    self.fixed += 1
                except Exception as e:
                    print(f"       ⚠ 修复失败 {it}: {e}")
            # 报实际成功数，不报条目总数 —— 失败了还说「已修复 N 项」就是谎报
            print(f"     → 已修复 {ok}/{len(items)} 项" if ok else "     → 一个都没修成")
        elif fixable:
            print("     → 加 --fix 可自动修复")
        elif hint:
            print(f"     → {hint}")


def main():
    print("\n🩺 skill-manager 自检" + ("（--fix 模式，会动文件）" if FIX else "（只读）"))
    print(f"   数据目录：{core.DATA_DIR}")
    r = Report()
    skills = core.collect_all(all_projects=True)

    # 1. 插件登记表指向的目录是否真实存在
    print("\n[1] 插件登记表")
    registry = core.read_json(core.INSTALLED_PLUGINS_JSON, {})
    broken = []
    live_paths = set()
    for key, installs in registry.get("plugins", {}).items():
        for ins in installs:
            p = ins.get("installPath", "")
            if os.path.isdir(p):
                live_paths.add(os.path.abspath(p))
            else:
                broken.append(f"{key} → {p}")
    r.section("登记表指向的目录都存在", "个插件登记的目录已不存在（插件会静默失效）", broken,
              hint="跑 /skill-manager update <插件名> 重装即可修复")

    # 2. 断掉的软链接
    print("\n[2] 软链接完整性")
    dangling = []
    for root in [core.GLOBAL_SKILLS_DIR] + [
            os.path.join(p, ".claude", "skills") for p in core.load_projects()]:
        if not os.path.isdir(root):
            continue
        for n in sorted(os.listdir(root)):
            f = os.path.join(root, n)
            if os.path.islink(f) and not os.path.exists(f):
                dangling.append(f"{f} → {os.readlink(f)}")
    r.section("没有断掉的软链接", "个软链接已断（指向的真身没了）", dangling, fixable=True,
              fixer=lambda it: os.unlink(it.split(" → ")[0]))

    # 3 & 4. 中文描述
    print("\n[3] 中文描述表")
    zh_map = core.read_json(core.DESCRIPTIONS_ZH, {})
    known = {s.name for s in skills}
    dead_entries = [k for k in zh_map if k not in known]

    def drop_entry(k):
        m = core.read_json(core.DESCRIPTIONS_ZH, {})
        m.pop(k, None)
        core.write_json(core.DESCRIPTIONS_ZH, m)

    r.section("descriptions_zh.json 没有死条目",
              "条中文描述指向已删除的 skill", dead_entries,
              fixable=True, fixer=drop_entry)

    print("\n[4] 描述可读性")
    # 只要求生效中的 skill 有中文描述：未启用的不占上下文，也就不会被看到
    no_zh = [f"{s.name}（{s.scope_label}）" for s in skills if s.enabled and not s.desc_zh]
    r.section("生效中的 skill 都有中文描述", "个生效中的 skill 还是英文描述", no_zh,
              hint="让 Claude 读 SKILL.md 后补 zh_description 字段（插件类补进 descriptions_zh.json）")

    # 5. 来源与版本
    #
    # 这里曾经有一个 fixer：把没登记来源的 skill 一律填成 version 1.0.0。
    # 它把 tw93/Waza v3.31.1 装的 8 个 skill 编成了「本地自建 1.0.0」。
    # 凭空造出一个看起来权威的版本号，比老实说「不知道」有害得多 —— 已删除。
    # 现在的规矩：doctor --fix 只做有依据的补录（从 lock、从 GitHub API），
    # 绝不发明数据。查不出来的，报出来让人去 trace。
    print("\n[5] 来源登记")
    unknown = [s for s in skills if s.enabled and s.source == "unknown"]
    r.section("所有 skill 的来源都已登记",
              "个 skill 来源不明（既没登记 github_url，安装器也没记录）",
              [f"{s.name}（{s.scope_label}）" for s in unknown],
              hint="跑 /skill-manager trace --all 自动溯源（查安装记录 → 搜 GitHub → 下载比对定版）")

    print("\n[6] 版本号")
    no_ver = [s for s in skills
              if s.enabled and s.source == "github" and not s.github_hash]
    r.section("GitHub skill 都定了版本",
              "个 GitHub skill 不知道装的是哪一版",
              [f"{s.name}（{s.scope_label}）" for s in no_ver],
              hint="跑 /skill-manager trace <名字> —— 会下载各版本逐一比对内容来定版")

    undef = [s for s in skills
             if s.enabled and s.source in ("local", "frozen") and s.version == "未定版"]
    r.section("本地 skill 都有版本号", "个本地 skill 还没定版本号",
              [f"{s.name}（{s.scope_label}）" for s in undef],
              hint="确认是自己写的就跑 /skill-manager bump <名字> 定版 1.0.0")

    # GitHub 来源没记安装日期 → 版本列只剩一串裸哈希，人读不懂
    no_date = [s for s in skills
               if s.source == "github" and s.github_hash and not s.github_date]

    def fill_date(s):
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from update_skill import get_commit_date
        d = get_commit_date(s.github_url, s.github_hash)
        if not d:
            raise RuntimeError("GitHub API 没取到该 commit 的日期")
        core.set_frontmatter_field(s.md_path, "github_date", d)

    r.section("GitHub skill 都记了安装日期",
              "个 GitHub skill 只有裸哈希、没有日期（需联网补）",
              [f"{s.name}（{s.github_hash[:7]}）" for s in no_date],
              fixable=True,
              fixer=lambda it: fill_date(next(s for s in no_date
                                              if f"{s.name}（{s.github_hash[:7]}）" == it)))

    # 7. 改了没记账
    print("\n[7] 版本号与内容是否对得上")
    dirty = [f"{s.name}（{s.scope_label}）· 当前 {s.version}" for s in skills if s.dirty]
    r.section("版本号和内容对得上", "个 skill 改过内容但版本号没跟上（列表里带 *）", dirty,
              hint="确认改动无误后跑 /skill-manager bump <名字> 平账")

    # 8. 孤儿缓存
    print("\n[8] 插件缓存")
    orphans = []
    if os.path.isdir(PLUGIN_CACHE):
        for mkt in sorted(os.listdir(PLUGIN_CACHE)):
            mp = os.path.join(PLUGIN_CACHE, mkt)
            if not os.path.isdir(mp):
                continue
            for plug in sorted(os.listdir(mp)):
                pp = os.path.join(mp, plug)
                if not os.path.isdir(pp):
                    continue
                for ver in sorted(os.listdir(pp)):
                    vp = os.path.abspath(os.path.join(pp, ver))
                    if os.path.isdir(vp) and vp not in live_paths:
                        orphans.append(f"{vp}  ({human_size(dir_size(vp))})")
    r.section("缓存里没有无人引用的旧版本", "个孤儿版本目录（无人引用，纯占磁盘）",
              orphans, fixable=True, fixer=lambda it: trash(it.split("  (")[0]))

    # 9. 项目注册表
    print("\n[9] 项目注册表")
    projects = core.load_projects()
    gone = [p for p in projects if not os.path.isdir(p)]

    def drop_project(p):
        data = core.read_json(core.PROJECTS, {})
        data.get("projects", {}).pop(p, None)
        core.write_json(core.PROJECTS, data)

    r.section("注册的项目都还在", "个已登记项目的目录不存在了", gone,
              fixable=True, fixer=drop_project)
    if projects:
        print(f"     已登记 {len(projects)} 个项目：" +
              "、".join(os.path.basename(p) for p in projects if os.path.isdir(p)))

    # 10. worktree
    #
    # 它们已从项目列表里归并掉（同一批 skill 不重复数），但**必须报出来**：
    # 排除是为了不重复计数，不是为了假装它不存在。落后主分支的 worktree
    # 里躺着一份旧 skill，你在主分支修好的东西它一概没有——不说清楚，
    # 人就会盯着一份旧副本反复怀疑「我明明修过了怎么还报」。
    print("\n[10] Git worktree")
    worktrees = core.detected_worktrees()
    stale = []
    for wt, main in worktrees.items():
        behind = core.worktree_behind(wt, main)
        if behind:
            stale.append(f"{os.path.basename(wt)} 落后 {os.path.basename(main)} "
                         f"{behind} 个提交 · {wt}")
    r.section(f"没有落后的 worktree（共 {len(worktrees)} 个，已归并到主仓）"
              if worktrees else "没有 worktree",
              "个 worktree 落后主仓（里面的 skill 是旧副本，别拿它当准）", stale,
              hint="进去 git merge <主分支> 同步；用不上了就 git worktree remove")

    print(f"\n{'─' * 50}")
    if r.problems == 0:
        print("🎉 一切正常")
    elif FIX:
        print(f"发现 {r.problems} 个问题，自动修复了 {r.fixed} 个")
        if r.problems > r.fixed:
            print(f"剩下 {r.problems - r.fixed} 个需要人工判断（见上方 → 提示）")
    else:
        print(f"发现 {r.problems} 个问题 · 加 --fix 自动修可修的部分")
    print()


if __name__ == "__main__":
    main()
