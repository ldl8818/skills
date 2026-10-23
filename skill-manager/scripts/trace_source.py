#!/usr/bin/env python3
"""溯源：查出一个 skill 到底从哪来、装的是哪一版，然后登记进 frontmatter。

用法:
  python3 trace_source.py <名字>                    溯源单个
  python3 trace_source.py --all                     溯源所有来源未登记的
  python3 trace_source.py <名字> --repo <仓库URL>   直接指定仓库
  python3 trace_source.py <名字> --path <子目录>    指定 skill 在仓库里的路径
  加 --write 才真正写入 frontmatter，默认只报告

设计前提（2026-07-11 事故教训）：
  「来源没登记」不等于「没有来源」——绝大多数 skill 都是从 GitHub 装的，
  信息不是不存在，是没去找。旧版把没有 github_url 的一律判成「本地自建」，
  还给它们编了 version 1.0.0；实际上其中 8 个是 tw93/Waza v3.31.1 装的。
  所以顺序是：先查安装器记录 → 再联网搜 GitHub → 下载逐版比对内容 → 确认后才写。
  找不到才承认 unknown。

三级溯源：
  1. 安装器的 lock 记录（~/.agents/.skill-lock.json）—— 最权威，直接给出仓库和路径
  2. GitHub 仓库搜索 —— 按 skill 名搜，列候选
  3. 内容比对定版 —— 下载候选仓库各个 tag，用内容指纹逐一比对，
     只有完全一致才认定版本。绝不靠「上游最新版」倒推本地版本。
"""
import io
import os
import re
import sys
import json
import shutil
import tempfile
import subprocess
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

WRITE = "--write" in sys.argv
MAX_TAGS = 12  # 往回比对多少个版本；再老就不值得等了


def api(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "skill-manager"})
        with urllib.request.urlopen(req, timeout=12) as r:
            return json.loads(r.read())
    except Exception:
        return None


def repo_slug(url):
    m = re.search(r"github\.com[/:]([^/]+/[^/]+?)(?:\.git)?/?$", url or "")
    return m.group(1) if m else None


# ── 第 1 级：安装器的 lock 记录 ────────────────────────────

def from_lock(name):
    rec = core.load_skill_lock().get(name)
    if not rec:
        return None
    url = (rec.get("sourceUrl") or "").removesuffix(".git")
    sp = rec.get("skillPath", "")
    path = sp[: -len("/SKILL.md")] if sp.endswith("/SKILL.md") else ""
    return {"url": url, "path": path, "via": "安装器记录"} if url else None


# ── 第 2 级：GitHub 搜索 ──────────────────────────────────

def search_github(name):
    """按 skill 名搜 GitHub，返回候选仓库（不认证，60 次/小时够用）。"""
    out = []
    for q in (f"{name}+skill+in:name", f"{name}+in:name+claude"):
        d = api(f"https://api.github.com/search/repositories?q={q}&per_page=5")
        for it in (d or {}).get("items", []):
            if it["html_url"] not in [c["url"] for c in out]:
                out.append({"url": it["html_url"], "stars": it["stargazers_count"],
                            "desc": (it.get("description") or "")[:60]})
    return out[:8]


# ── 第 3 级：下载各版本，用内容指纹定位真实版本 ──────────────

def list_tags(slug):
    try:
        r = subprocess.run(["git", "ls-remote", "--tags",
                            f"https://github.com/{slug}"],
                           capture_output=True, text=True, timeout=25)
        tags = [l.split("refs/tags/")[-1] for l in r.stdout.splitlines()
                if "refs/tags/" in l and not l.endswith("^{}")
                and core.SEMVER_TAG.match(l.split("refs/tags/")[-1])]

        def key(t):
            nums = re.findall(r"\d+", t)
            return [int(n) for n in nums] or [0]

        return sorted(set(tags), key=key, reverse=True)[:MAX_TAGS]
    except Exception:
        return []


def fetch_at(slug, ref, dest):
    from update_skill import download_repo
    return download_repo(f"https://github.com/{slug}", ref, dest)


def find_skill_dir(root, name, hint=""):
    if hint and os.path.isfile(os.path.join(root, hint, "SKILL.md")):
        return os.path.join(root, hint)
    # 单 skill 仓库：仓库根就是 skill 本体。解压后的临时目录名是随机的，
    # 不能靠「目录名 == skill 名」认出它，要看 frontmatter 里的 name。
    root_md = os.path.join(root, "SKILL.md")
    if os.path.isfile(root_md):
        try:
            if core.parse_skill_md(root_md).get("name") == name:
                return root
        except Exception:
            pass
    for base in (root, os.path.join(root, "skills"), os.path.join(root, name)):
        if os.path.isfile(os.path.join(base, name, "SKILL.md")):
            return os.path.join(base, name)
        if os.path.isfile(os.path.join(base, "SKILL.md")) and os.path.basename(base) == name:
            return base
    for dirpath, dirnames, files in os.walk(root):
        if dirpath[len(root):].count(os.sep) > 6:
            dirnames[:] = []
            continue
        if os.path.basename(dirpath) == name and "SKILL.md" in files:
            return dirpath
    return None


def pin_version(slug, name, local_dir, hint=""):
    """逐个版本下载比对，找出与本地内容一致的那一版。

    绝不假设「本地 == 上游最新」：本地 Waza 8 个 skill 装于 07-05，
    上游最新是 v3.31.2（07-10 发布），实际本地是 v3.31.1。猜就会猜错。

    比对是方向性的（core.content_matches_upstream）：上游文件逐一比对，
    本地自生成的运行时文件不参与——否则一个 config.env 就让所有版本永远比不中。
    """
    refs = list_tags(slug) or ["HEAD"]
    print(f"    比对 {len(refs)} 个版本 …", flush=True)
    for ref in refs:
        tmp = tempfile.mkdtemp()
        try:
            if not fetch_at(slug, ref, tmp):
                continue
            sd = find_skill_dir(tmp, name, hint)
            if not sd:
                continue
            if core.content_matches_upstream(local_dir, sd):
                rel = os.path.relpath(sd, tmp)
                ver = ""
                vf = os.path.join(tmp, "VERSION")
                if os.path.isfile(vf):
                    with open(vf, encoding="utf-8") as f:
                        ver = f.read().strip()
                if not ver and ref != "HEAD":
                    ver = ref.lstrip("v")
                return {"ref": ref, "path": rel, "version": ver}
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return None


def commit_of(slug, ref):
    d = api(f"https://api.github.com/repos/{slug}/commits/{ref}")
    if not d:
        return "", ""
    return d["sha"], d["commit"]["committer"]["date"][5:10]


# ── 主流程 ────────────────────────────────────────────────

def trace(s, repo=None, path_hint=""):
    print(f"\n🔍 {s.name}（{s.scope_label}）")

    # 来源优先级与 --all 批量路径一致：手动指定 > 已登记的 github_url > 安装器 lock
    hit = ({"url": repo, "path": path_hint, "via": "手动指定"} if repo
           else {"url": s.github_url, "path": getattr(s, "github_path", "") or "",
                 "via": "frontmatter 登记"} if s.github_url
           else from_lock(s.name))

    if not hit:
        print("    安装器没有记录 → 联网搜 GitHub")
        cands = search_github(s.name)
        if not cands:
            print("    ❌ GitHub 上也没搜到 → 确实来源不明")
            print(f"       确认是自己写的，请在 SKILL.md metadata 下登记 source: local")
            return None
        print("    候选仓库：")
        for c in cands:
            print(f"       {c['url']}  ★{c['stars']}  {c['desc']}")
        print(f"    → 挑一个后跑：/skill-manager trace {s.name} --repo <URL>")
        return None

    slug = repo_slug(hit["url"])
    print(f"    来源（{hit['via']}）：{hit['url']}")
    if not slug:
        print("    ❌ 不是 GitHub 地址，无法比对")
        return None

    pinned = pin_version(slug, s.name, s.path, hit.get("path", ""))
    if not pinned:
        print(f"    ⚠ 近 {MAX_TAGS} 个版本都对不上本地内容")
        print("       → 你可能改过它，或者装的是更老的版本；来源仍按上面登记")
        fields = {"github_url": hit["url"]}
        if hit.get("path"):
            fields["github_path"] = hit["path"]
    else:
        sha, date = commit_of(slug, pinned["ref"])
        print(f"    ✅ 本地内容 = {pinned['ref']}"
              + (f"（版本 {pinned['version']}）" if pinned["version"] else ""))
        fields = {"github_url": hit["url"], "github_path": pinned["path"]}
        if sha:
            fields["github_hash"] = sha
        if date:
            fields["github_date"] = date
        if pinned["version"]:
            fields["version"] = pinned["version"]

    if not WRITE:
        print(f"    （预览，未写入。加 --write 生效）{fields}")
        return fields

    # 之前编造的 version 1.0.0 必须先清掉，否则会盖住真实版本
    if "version" in fields:
        core.set_frontmatter_field(s.md_path, "version", fields.pop("version"))
    for k, v in fields.items():
        core.set_frontmatter_field(s.md_path, k, v)
    print(f"    ✍️  已写入 {s.md_path}")
    return fields


def trace_batch(slug, group, path_hint=""):
    """同一仓库下的一批 skill 共用一次下载。

    逐个 trace 会把同一个仓库反复下 N×M 次（creative 那 74 个 × 12 个版本
    = 888 次），慢到根本跑不完。所以按仓库分组：每个 tag 只下载一次，
    一次比对该仓库下所有待溯源的 skill。
    """
    url = f"https://github.com/{slug}"
    pending = {s.name: s for s in group}
    refs = list_tags(slug) or ["HEAD"]
    print(f"\n📦 {slug} —— {len(group)} 个 skill，比对 {len(refs)} 个版本")

    resolved = {}
    for ref in refs:
        if not pending:
            break
        tmp = tempfile.mkdtemp()
        try:
            if not fetch_at(slug, ref, tmp):
                continue
            ver = ""
            vf = os.path.join(tmp, "VERSION")
            if os.path.isfile(vf):
                with open(vf, encoding="utf-8") as f:
                    ver = f.read().strip()
            if not ver and ref != "HEAD":
                ver = ref.lstrip("v")
            sha = date = ""
            for name in list(pending):
                sd = find_skill_dir(tmp, name, path_hint)
                if sd and core.content_matches_upstream(pending[name].path, sd):
                    if not sha:
                        sha, date = commit_of(slug, ref)
                    resolved[name] = {"github_url": url,
                                      "github_path": os.path.relpath(sd, tmp),
                                      "github_hash": sha, "github_date": date,
                                      "version": ver}
                    print(f"    ✅ {name:26} = {ref}" + (f"（{ver}）" if ver else ""))
                    pending.pop(name)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    for name in pending:
        print(f"    ⚠ {name:26} 近 {len(refs)} 个版本都对不上（可能被本地改过）")
        resolved[name] = {"github_url": url}
        if path_hint:
            resolved[name]["github_path"] = path_hint

    if not WRITE:
        print("    （预览，未写入。加 --write 生效）")
        return

    by_name = {s.name: s for s in group}
    for name, fields in resolved.items():
        for k, v in fields.items():
            if v:
                core.set_frontmatter_field(by_name[name].md_path, k, v)
    print(f"    ✍️  已写入 {len(resolved)} 个 SKILL.md")


def main():
    if any(a in ("-h", "--help") for a in sys.argv[1:]):
        print(__doc__)
        sys.exit(0)
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    repo = path_hint = None
    if "--repo" in sys.argv:
        repo = sys.argv[sys.argv.index("--repo") + 1]
    if "--path" in sys.argv:
        path_hint = sys.argv[sys.argv.index("--path") + 1]

    skills = core.collect_all(all_projects=True)

    if "--all" in sys.argv:
        # 两类都要溯源：来源不明的，以及来源知道但不知道装的是哪一版的
        targets = [s for s in skills
                   if s.source == "unknown"
                   or (s.source == "github" and not s.github_hash)]
        if not targets:
            print("🎉 所有 skill 的来源和版本都已登记")
            return
        print(f"待溯源：{len(targets)} 个"
              f"（来源不明 {sum(1 for s in targets if s.source == 'unknown')}，"
              f"版本未定 {sum(1 for s in targets if s.source == 'github')}）")

        # 先按仓库分组（repo 由命令行指定，或从 lock / frontmatter 拿）
        groups, orphans = {}, []
        for s in targets:
            hit = {"url": repo} if repo else (
                {"url": s.github_url} if s.github_url else from_lock(s.name))
            slug = repo_slug(hit["url"]) if hit else None
            if slug:
                groups.setdefault(slug, []).append(s)
            else:
                orphans.append(s)

        for slug, group in groups.items():
            trace_batch(slug, group, path_hint or "")

        if orphans:
            print(f"\n❓ 还有 {len(orphans)} 个查不到仓库："
                  f"{'、'.join(s.name for s in orphans[:6])}"
                  f"{' …' if len(orphans) > 6 else ''}")
            print("   知道出处就直接指定（同仓库的会一次性批量溯源）：")
            print("     /skill-manager trace <名字> --repo <仓库URL>")
            print("   不知道出处就让它联网搜候选：")
            print("     /skill-manager trace <名字>")
        return

    if not args:
        print(__doc__)
        sys.exit(1)

    name = args[0]
    hits = [s for s in skills if s.name == name and s.source != "plugin"]
    if not hits:
        print(f"❌ 找不到 skill：{name}")
        sys.exit(1)
    trace(hits[0], repo, path_hint or "")


if __name__ == "__main__":
    main()
