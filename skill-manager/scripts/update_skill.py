#!/usr/bin/env python3
"""skill-manager 更新脚本。

用法:
  python3 update_skill.py                更新所有有新版的（先 check 再逐个更新）
  python3 update_skill.py --dry-run      只列出将要更新的，不动手
  python3 update_skill.py <名字>          更新单个；插件可只写裸名（自动补 @市场名）

2026-07-11 增强：
- 裸名字自动解析（`core.resolve_target`，与 delete 共用）：市场名是安装来源的内部
  标识，用户没理由记得住 `codex@openai-codex` 里的后半截。裸名字先当直装 skill 找，
  找不到再去插件登记表前缀匹配，唯一命中就补全；撞名列候选让人挑（猜错 = 更新错东西）。
- 无参 = 批量更新（`update_all`）：复用 scan_and_check 的收集与比对，筛出 outdated
  逐个更新，单个失败隔离不拖累其余，末尾汇总成功/失败。

2026-07-03 重构（实战教训沉淀，事故记录见 SKILL.md「Known Fixes」）：
- 去除 PyYAML 依赖：frontmatter 用内置轻量解析，任何 python3 可直接跑
- 直装 skill 改为「整目录合并更新」：旧版只拉单个 SKILL.md，会漏掉上游新增的
  scripts/ references/ 等文件；合并规则 = 上游文件覆盖同名本地文件，
  本地独有文件（config.env、site-patterns/、descriptions_zh.json 等）一律保留
- SKILL.md 更新后回注 github_url/github_hash/github_path 元数据，
  并保留本地「## User-Learned」定制段（skill-evolution-manager 维护的经验区）
- 插件更新先定位「插件真身」：monorepo 仓库（如 openai/codex-plugin-cc、
  claude-plugins-official）插件本体在 plugins/<name>/ 或 external_plugins/<name>/
  子目录；结构验证通过才写 installed_plugins.json，失败保留旧版运行
- frontmatter 声明 update_policy: frozen 的 skill 拒绝更新（绝版 / 深度定制）
"""
import os
import re
import sys
import json
import shutil
import tempfile
import subprocess
import urllib.request
import concurrent.futures
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core

CLAUDE_DIR = os.path.expanduser("~/.claude")
SKILLS_DIR = os.path.join(CLAUDE_DIR, "skills")
INSTALLED_PLUGINS_JSON = os.path.join(CLAUDE_DIR, "plugins", "installed_plugins.json")
KNOWN_MARKETPLACES_JSON = os.path.join(CLAUDE_DIR, "plugins", "known_marketplaces.json")
BACKUP_ROOT = os.path.join(CLAUDE_DIR, "skills-archive", "_update_backups")

# 只认纯语义化 tag（v3.31.2 / 1.5.16）。聚合仓库常给每个 skill 单独打 tag
# （如 neat-freak-v1.0.2），按「数字最大」去挑会挑到别的 skill 的 tag 上 ——
# 认不出来就老实回退 HEAD，别乱猜。
SEMVER_TAG = re.compile(r"^v?\d+\.\d+\.\d+$")


# ── frontmatter 轻量解析（免 PyYAML） ──────────────────────

def parse_frontmatter(text):
    """解析顶层 key: value（含 >/| 折叠块），返回 dict（值均为 str）。"""
    meta = {}
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return meta
    i = 1
    while i < len(lines):
        line = lines[i]
        if line.strip() == "---":
            break
        m = re.match(r"^([A-Za-z_][\w.-]*):\s*(.*)$", line)
        if m:
            key, val = m.group(1), m.group(2).strip()
            if val in (">", "|", ">-", "|-", ""):
                block = []
                j = i + 1
                while j < len(lines) and lines[j].strip() != "---" and (
                        lines[j].startswith((" ", "\t")) or not lines[j].strip()):
                    if lines[j].strip():
                        block.append(lines[j].strip())
                    j += 1
                if block:
                    meta[key] = " ".join(block)
                    i = j - 1
                else:
                    meta[key] = val
            else:
                if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
                    val = val[1:-1]
                meta[key] = val
        i += 1
    return meta


def set_frontmatter_field(content, key, value):
    """在 frontmatter 中设置/替换一个字段（保持其余内容原样）。"""
    lines = content.split("\n")
    if not lines or lines[0].strip() != "---":
        return content
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return content
    for i in range(1, end):
        if lines[i].startswith(f"{key}:"):
            lines[i] = f"{key}: {value}"
            return "\n".join(lines)
    lines.insert(end, f"{key}: {value}")
    return "\n".join(lines)


# ── 远端与下载 ────────────────────────────────────────────

def get_remote_hash(url):
    try:
        result = subprocess.run(
            ["git", "ls-remote", url, "HEAD"],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0:
            parts = result.stdout.split()
            return parts[0] if parts else None
    except Exception:
        pass
    return None


def latest_release(url):
    """更新目标 = 最新语义化 tag（没有 tag 才回退 HEAD）。

    HEAD 往往领先最新 tag 若干个未发版的 commit：Waza 的 HEAD 比 v3.31.2 多几个
    commit，但 VERSION 文件还写着 3.31.2。装 HEAD 就变成「内容是 3.31.2+n、
    版本号却标 3.31.2」—— 又一次撒谎。
    tag → commit sha 的解析（annotated tag 的坑）统一走 core.remote_tags。
    """
    ref, sha = core.latest_tag(url)
    if ref:
        return ref, sha
    return "HEAD", get_remote_hash(url)


def get_commit_date(github_url, sha):
    """取该 commit 的提交日期（MM-DD）。

    上游作者大多不给 skill 写版本号，只剩一串裸哈希。列表里显示
    「06-28 · d4e43c9」比 「d4e43c9」有用得多——你至少知道装的是哪天那一版。
    装的时候记进 frontmatter，list 平时就不用联网了。
    """
    m = re.search(r"github\.com/([^/]+/[^/]+?)(?:\.git)?/?$", github_url)
    if not m:
        return None
    try:
        url = f"https://api.github.com/repos/{m.group(1)}/commits/{sha}"
        req = urllib.request.Request(url, headers={"User-Agent": "skill-manager"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
        return data["commit"]["committer"]["date"][5:10]  # 2026-06-28T... → 06-28
    except Exception:
        return None


def download_repo(github_url, ref, dest_dir):
    """下载仓库某个提交的 tarball 并解压到 dest_dir（去掉顶层目录）。"""
    url = github_url.rstrip("/")
    tar_url = f"{url}/archive/{ref}.tar.gz"
    os.makedirs(dest_dir, exist_ok=True)
    proc = subprocess.run(
        f'curl -fsSL "{tar_url}" | tar -xz -C "{dest_dir}" --strip-components=1',
        shell=True, timeout=120
    )
    return proc.returncode == 0 and os.listdir(dest_dir)


# ── 直装 skill：整目录合并更新 ─────────────────────────────

def find_skill_source(extract_root, skill_name, github_path=None):
    """在解压的仓库里定位 skill 源目录（含 SKILL.md）。"""
    candidates = []
    if github_path:
        candidates.append(os.path.join(extract_root, github_path))
    candidates += [
        extract_root,                                       # 单 skill 仓库
        os.path.join(extract_root, "skills", skill_name),   # 常见聚合布局
        os.path.join(extract_root, skill_name),
    ]
    for c in candidates:
        if os.path.isfile(os.path.join(c, "SKILL.md")):
            return c
    # 兜底：全仓库浅层扫描同名目录
    for root, dirs, files in os.walk(extract_root):
        depth = root[len(extract_root):].count(os.sep)
        if depth > 4:
            dirs[:] = []
            continue
        if os.path.basename(root) == skill_name and "SKILL.md" in files:
            return root
    return None


USER_SECTION_RE = re.compile(r"^## User-Learned Best Practices.*", re.M | re.S)

# 本地定制的 frontmatter 字段：上游更新时必须原样保下来，否则每更新一次就丢一次
PRESERVE_FIELDS = ("zh_description", "update_policy", "keep_local_description")


def merge_skill_md(upstream_content, old_content, meta_fields):
    """上游 SKILL.md + 回注元数据 + 保留本地定制。

    `description` 默认跟随上游——它是上游的东西，本来就该更新。
    但它同时是**决定 Claude 选不选这个 skill 的那句话**（注入模型的 skill 清单
    用的就是它，不是 zh_description）。所以有人把它改写得更好触发之后，
    update 会把这份优化悄悄冲回上游那版——没有任何提示，只在下次选错 skill 时才显形。

    `keep_local_description: true` = 「这条描述我调过，别动」。显式声明才生效，
    不做「本地和上游不一样就自动保留」的推断——那样上游改进的描述会永远拿不到，
    而且用户根本不知道自己的描述被锁住了。
    """
    new = upstream_content
    old_meta = parse_frontmatter(old_content or "")
    fields = list(PRESERVE_FIELDS)
    if str(old_meta.get("keep_local_description", "")).lower() == "true":
        fields.append("description")
    for k in fields:
        if old_meta.get(k):
            new = set_frontmatter_field(new, k, old_meta[k])
    for k, v in meta_fields.items():
        new = set_frontmatter_field(new, k, v)
    old_sec = USER_SECTION_RE.search(old_content or "")
    if old_sec and "User-Learned Best Practices" not in new:
        new = new.rstrip("\n") + "\n\n" + old_sec.group(0).rstrip("\n") + "\n"
    return new


def merge_skill_dir(src, dst, meta_fields):
    """上游目录合并进本地：覆盖同名文件，保留本地独有文件。"""
    old_md = ""
    dst_md = os.path.join(dst, "SKILL.md")
    if os.path.isfile(dst_md):
        with open(dst_md, encoding="utf-8") as f:
            old_md = f.read()
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d != ".git"]
        rel = os.path.relpath(root, src)
        target_root = dst if rel == "." else os.path.join(dst, rel)
        os.makedirs(target_root, exist_ok=True)
        for fn in files:
            if fn == ".DS_Store":
                continue
            s, t = os.path.join(root, fn), os.path.join(target_root, fn)
            if rel == "." and fn == "SKILL.md":
                with open(s, encoding="utf-8") as f:
                    upstream = f.read()
                with open(t, "w", encoding="utf-8") as f:
                    f.write(merge_skill_md(upstream, old_md, meta_fields))
            else:
                shutil.copy2(s, t)


def update_direct_skill(skill_name):
    skill_dir = os.path.join(SKILLS_DIR, skill_name)
    skill_md = os.path.join(skill_dir, "SKILL.md")
    if not os.path.exists(skill_md):
        print(f"❌ {skill_name} 不存在")
        return False

    with open(skill_md, encoding="utf-8") as f:
        content = f.read()
    meta = parse_frontmatter(content)

    if meta.get("update_policy") == "frozen":
        print(f"🧊 {skill_name} 已声明 update_policy: frozen（绝版或深度定制），按策略不更新。"
              f"确需更新请先移除该标记并人工评估合并。")
        return False

    github_url = meta.get("github_url")
    if not github_url:
        print(f"❌ {skill_name} 没有 github_url，无法更新（可在 frontmatter 登记来源后重试）")
        return False

    print(f"🔍 检查 {skill_name} 更新...")
    target_ref, remote_hash = latest_release(github_url)
    if not remote_hash:
        print(f"❌ 无法连接到 {github_url}")
        return False

    local_hash = meta.get("github_hash", "")
    if local_hash and (remote_hash.startswith(local_hash) or local_hash.startswith(remote_hash[:12])):
        print(f"✅ {skill_name} 已是最新版本（{target_ref}）")
        return True
    print(f"📥 目标版本：{target_ref}（{remote_hash[:8]}）")

    # 整目录备份（回滚入口，删除请手动清理 _update_backups）
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = os.path.join(BACKUP_ROOT, f"{skill_name}.{ts}")
    os.makedirs(BACKUP_ROOT, exist_ok=True)
    shutil.copytree(skill_dir, backup_dir, symlinks=True)
    print(f"📦 已整目录备份到 skills-archive/_update_backups/{os.path.basename(backup_dir)}")

    tmp = tempfile.mkdtemp(prefix="skillupd_")
    try:
        print(f"📥 下载 {remote_hash[:8]} ...")
        if not download_repo(github_url, remote_hash, tmp):
            print("❌ 下载失败，本地未改动")
            return False
        src = find_skill_source(tmp, skill_name, meta.get("github_path"))
        if not src:
            print(f"❌ 仓库里找不到 {skill_name} 的 SKILL.md（可在 frontmatter 用 github_path 指明子目录），本地未改动")
            return False
        fields = {"github_url": github_url, "github_hash": remote_hash}
        commit_date = get_commit_date(github_url, remote_hash)
        if commit_date:
            fields["github_date"] = commit_date
        # 版本号取值优先级：VERSION 文件 > semver tag 名 > 不写（退回「日期 · 哈希」）。
        # 不同步版本号的话，更新完内容是 3.31.2、版本列还写 3.31.1 —— 又是一次撒谎；
        # 而 tag 名本身就是上游给的版本号（v1.5.16），不用白不用。
        upstream_version = ""
        version_file = os.path.join(tmp, "VERSION")
        if os.path.isfile(version_file):
            with open(version_file, encoding="utf-8") as vf:
                upstream_version = vf.read().strip()
        if not upstream_version and core.SEMVER_TAG.match(target_ref):
            upstream_version = target_ref.lstrip("v")
        if upstream_version:
            fields["version"] = upstream_version
        rel = os.path.relpath(src, tmp)
        if rel != ".":
            fields["github_path"] = rel
        merge_skill_dir(src, skill_dir, fields)
        print(f"✅ {skill_name} 已合并更新到 {remote_hash[:8]}（本地独有文件与 User-Learned 段已保留）")
        return True
    except Exception as e:
        print(f"❌ 更新失败: {e}（可从备份恢复: {backup_dir}）")
        return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ── 插件更新：monorepo 定位 + 验证后提交 ───────────────────

def is_valid_plugin_root(d):
    """插件根目录判定：标准结构或 baoyu 式 marketplace 结构。"""
    cp = os.path.join(d, ".claude-plugin")
    if os.path.isfile(os.path.join(cp, "plugin.json")):
        return True
    return (os.path.isfile(os.path.join(cp, "marketplace.json"))
            and os.path.isdir(os.path.join(d, "skills")))


def locate_plugin_root(extract_root, plugin_name):
    """在解压仓库里定位插件真身（monorepo 支持）。"""
    candidates = [
        extract_root,
        os.path.join(extract_root, "plugins", plugin_name),
        os.path.join(extract_root, "external_plugins", plugin_name),
    ]
    for c in candidates:
        if os.path.isdir(c) and is_valid_plugin_root(c):
            return c
    for root, dirs, _files in os.walk(extract_root):
        depth = root[len(extract_root):].count(os.sep)
        if depth > 3:
            dirs[:] = []
            continue
        if os.path.basename(root) == plugin_name and is_valid_plugin_root(root):
            return root
    return None


def plugin_version_of(plugin_root, fallback):
    pj = os.path.join(plugin_root, ".claude-plugin", "plugin.json")
    try:
        with open(pj, encoding="utf-8") as f:
            v = json.load(f).get("version")
        return v or fallback
    except Exception:
        return fallback


def update_plugin(plugin_key):
    print(f"🔍 检查插件 {plugin_key} 更新...")

    with open(INSTALLED_PLUGINS_JSON, encoding="utf-8") as f:
        registry = json.load(f)
    if plugin_key not in registry.get("plugins", {}):
        print(f"❌ 插件 {plugin_key} 未安装")
        return False

    plugin_name = plugin_key.split("@")[0]
    marketplace = plugin_key.split("@")[-1] if "@" in plugin_key else plugin_key
    if not os.path.exists(KNOWN_MARKETPLACES_JSON):
        print("❌ 找不到 marketplace 配置")
        return False
    with open(KNOWN_MARKETPLACES_JSON, encoding="utf-8") as f:
        marketplaces = json.load(f)
    repo = marketplaces.get(marketplace, {}).get("source", {}).get("repo")
    if not repo:
        print(f"❌ 找不到 {marketplace} 的仓库信息")
        return False

    github_url = f"https://github.com/{repo}"
    remote_hash = get_remote_hash(github_url)
    if not remote_hash:
        print(f"❌ 无法连接到 {github_url}")
        return False

    install = registry["plugins"][plugin_key][0]
    local_hash = install.get("gitCommitSha", "")
    if local_hash and (remote_hash.startswith(local_hash) or local_hash.startswith(remote_hash[:12])):
        print(f"✅ {plugin_key} 已是最新版本 ({remote_hash[:8]})")
        return True

    print(f"📥 下载最新版本 {remote_hash[:8]}...")
    tmp = tempfile.mkdtemp(prefix="pluginupd_")
    try:
        if not download_repo(github_url, remote_hash, tmp):
            print("❌ 下载失败，保留旧版本")
            return False

        plugin_root = locate_plugin_root(tmp, plugin_name)
        if not plugin_root:
            print(f"❌ 仓库里定位不到插件 {plugin_name} 的有效结构"
                  f"（需 .claude-plugin/plugin.json 或 marketplace.json + skills/），保留旧版本")
            return False

        version = plugin_version_of(plugin_root, remote_hash[:12])
        cache_dir = os.path.join(CLAUDE_DIR, "plugins", "cache", marketplace, plugin_name)
        new_dir = os.path.join(cache_dir, version)
        if os.path.abspath(new_dir) == os.path.abspath(install.get("installPath", "")):
            new_dir = os.path.join(cache_dir, remote_hash[:12])
        if os.path.exists(new_dir):
            shutil.rmtree(new_dir)
        os.makedirs(cache_dir, exist_ok=True)
        shutil.move(plugin_root, new_dir)

        if not is_valid_plugin_root(new_dir):
            shutil.rmtree(new_dir, ignore_errors=True)
            print("❌ 落盘后结构验证失败，保留旧版本")
            return False

        registry["plugins"][plugin_key][0].update({
            "installPath": new_dir,
            "version": version,
            "lastUpdated": datetime.now().isoformat(),
            "gitCommitSha": remote_hash,
        })
        with open(INSTALLED_PLUGINS_JSON, "w", encoding="utf-8") as f:
            json.dump(registry, f, indent=4)

        old_path = install.get("installPath", "")
        print(f"✅ {plugin_key} 已更新到 v{version} ({remote_hash[:8]})")
        if old_path and os.path.isdir(old_path) and os.path.abspath(old_path) != os.path.abspath(new_dir):
            print(f"🗑  旧版本目录可手动清理: {old_path}")
        return True
    except Exception as e:
        print(f"❌ 更新失败: {e}（登记表未改动，旧版本继续可用）")
        return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ── 单个更新（名字解析走 core.resolve_target，update / delete 共用） ──

def update_one(name):
    kind, key, err = core.resolve_target(name)
    if err:
        print(f"❌ {err}")
        return False
    return update_plugin(key) if kind == "plugin" else update_direct_skill(key)


# ── 批量更新：不给名字就把有新版的全更了 ───────────────────

def update_all(dry_run=False):
    """无参更新 = 先 check 找出有新版的，再逐个更新。

    复用 scan_and_check 的收集与比对（SKILL.md 状态模型：收集逻辑只此一家，
    另起一套就是历史事故的复现）。逐个更新互相隔离，一个失败不拖累其余。
    """
    import scan_and_check as chk

    print("🔍 检查所有 skill 与插件的更新...\n")
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        results = list(ex.map(chk.check_one, chk.build_targets()))

    outdated = sorted((r for r in results if r["status"] == "outdated"),
                      key=lambda r: r["name"])
    errors = [r for r in results if r["status"] == "error"]

    if errors:
        print(f"⚠️  {len(errors)} 个连不上上游，本轮跳过：" +
              "、".join(r["name"] for r in errors) + "\n")

    if not outdated:
        print("🎉 所有可追踪的 skill 都是最新，无需更新")
        return True

    print(f"🟡 {len(outdated)} 个有新版：")
    for r in outdated:
        tail = "" if r["enabled"] else "（未启用）"
        print(f"   {r['name']}  {r.get('local', '—')} → {r['remote']}{tail}")
    print()

    if dry_run:
        print("（--dry-run：只看不做，去掉该参数即开始更新）")
        return True

    done, failed = [], []
    for i, r in enumerate(outdated, 1):
        print(f"── [{i}/{len(outdated)}] {r['name']} " + "─" * 30)
        try:
            ok = update_plugin(r["name"]) if r["kind"] == "plugin" \
                else update_direct_skill(r["name"])
        except Exception as e:          # 单个炸了不能中断整批
            print(f"❌ 更新失败: {e}")
            ok = False
        (done if ok else failed).append(r["name"])
        print()

    print("═" * 46)
    print(f"✅ 成功 {len(done)}：" + "、".join(done) if done else "✅ 成功 0")
    if failed:
        print(f"❌ 失败 {len(failed)}：" + "、".join(failed) +
              "\n   （失败的都未改动本地，备份在 skills-archive/_update_backups/）")
    return not failed


if __name__ == "__main__":
    argv = sys.argv[1:]
    names = [a for a in argv if not a.startswith("-")]
    flags = {a for a in argv if a.startswith("-")}

    unknown = flags - {"--dry-run"}
    if unknown:
        print(f"❌ 不认识的参数: {'、'.join(sorted(unknown))}")
        print("用法: python3 update_skill.py [名字] [--dry-run]")
        print("      不给名字 = 检查并更新所有有新版的")
        sys.exit(1)

    if not names:
        sys.exit(0 if update_all(dry_run="--dry-run" in flags) else 1)

    if "--dry-run" in flags:
        kind, key, err = core.resolve_target(names[0])
        print(f"❌ {err}" if err else f"（--dry-run）将更新{'插件' if kind == 'plugin' else 'skill'}：{key}")
        sys.exit(1 if err else 0)

    sys.exit(0 if update_one(names[0]) else 1)
