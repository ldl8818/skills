#!/usr/bin/env python3
"""skill-manager 更新脚本。

用法:
  python3 update_skill.py                更新所有有新版的（先 check 再逐个更新）
  python3 update_skill.py --dry-run      只列出将要更新的，不动手
  python3 update_skill.py <名字>          更新单个；插件可只写裸名（自动补 @市场名）
  python3 update_skill.py lookup          总更新 lookup 本体与已安装上游
  python3 update_skill.py lookup --self-only       只更新 lookup 本体
  python3 update_skill.py lookup --upstream-only   只更新 lookup 上游
  python3 update_skill.py ego-lite        只更新 Ego，委派已安装的 lookup 维护器
  python3 update_skill.py opencli         只更新 OpenCLI；agent-reach 同理
  python3 update_skill.py lark-cli        官方更新 + 本机按需入口保护与验收

2026-07-11 增强：
- 裸名字自动解析（`core.resolve_target`，与 delete 共用）：市场名是安装来源的内部
  标识，用户没理由记得住 `codex@openai-codex` 里的后半截。裸名字先当直装 skill 找，
  找不到再去插件登记表前缀匹配，唯一命中就补全；撞名列候选让人挑（猜错 = 更新错东西）。
- 无参 = 批量更新（`update_all`）：复用 scan_and_check 的收集与比对，筛出 outdated
  逐个更新，单个失败隔离不拖累其余，末尾汇总成功/失败。

2026-07-03 重构（实战教训沉淀，事故记录见 SKILL.md「Known Fixes」）：
- 去除 PyYAML 依赖：frontmatter 用内置轻量解析，任何 python3 可直接跑
- 直装 skill 改为「整目录合并更新」：旧版只拉单个 SKILL.md，会漏掉上游新增的
  scripts/ references/ 等文件；合并规则 = 旧上游、本地、新上游三方合并；同名本地改造不直接覆盖，
  本地独有文件（config.env、site-patterns/、descriptions_zh.json 等）一律保留
- SKILL.md 更新后回注 github_url/github_hash/github_path 元数据，
  并保留本地「## User-Learned」定制段（skill-evolution-manager 维护的经验区）
- 插件更新先定位插件目录：monorepo 仓库（如 openai/codex-plugin-cc、
  claude-plugins-official）插件本体在 plugins/<name>/ 或 external_plugins/<name>/
  子目录；结构验证通过才写 installed_plugins.json，失败保留旧版运行
- frontmatter 声明 update_policy: frozen 的 skill 拒绝更新（绝版 / 深度定制）
"""
import io
import os
import re
import sys
import json
import shutil
import difflib
import tempfile
import subprocess
import urllib.request
import urllib.parse
import tarfile
import concurrent.futures
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core
from pathlib import Path
import audit_upstream
import lifecycle

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

CLAUDE_DIR = os.path.expanduser("~/.claude")
INSTALLED_PLUGINS_JSON = os.path.join(CLAUDE_DIR, "plugins", "installed_plugins.json")
KNOWN_MARKETPLACES_JSON = os.path.join(CLAUDE_DIR, "plugins", "known_marketplaces.json")
BACKUP_ROOT = os.path.join(core.ARCHIVE_DIR, "update-backups")


# ── frontmatter 轻量解析（免 PyYAML） ──────────────────────

def parse_frontmatter(text):
    return core.parse_frontmatter(text)


def set_frontmatter_field(content, key, value):
    fd, path = tempfile.mkstemp(prefix="skill-frontmatter-", text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        core.set_frontmatter_field(path, key, value)
        with open(path, encoding="utf-8") as f:
            return f.read()
    finally:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass


# ── 远端与下载 ────────────────────────────────────────────

def get_remote_hash(url):
    # 判定单源：ls-remote 的实现（含「没装 git」的人话报错）统一在 core
    return core.remote_head(url)


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


def resolve_update_target(url, meta, ref_arg=None):
    """决定这次更新拉哪个提交 → (显示用 ref, commit sha, 跟随通道)。

    通道只有两种，对应 check 的两种比对口径，二者必须一致，否则更新完还报「有新版」：
      ""      跟 release tag（默认）
      "main"  跟主分支 HEAD（上游把改进压在未发版提交里时用）

    通道有粘性：装过 main 的 skill，后续无参 update 继续跟 main。不粘的话，
    一次 update 就把它悄悄退回 tag，用户以为还在跟 main，实际早掉队了。
    显式 `--ref release` 是退回 tag 的唯一方式。
    """
    channel = (ref_arg or meta.get("github_ref") or "").strip()
    if channel == "release":
        channel = ""
    if channel and channel != "main":
        raise ValueError("--ref 只接受 main 或 release")
    if channel == "main":
        sha = get_remote_hash(url)
        return ("main", sha, "main") if sha else (None, None, "main")
    ref, sha = latest_release(url)
    return ref, sha, ""


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
    parsed = urllib.parse.urlsplit(github_url)
    if (parsed.scheme != "https" or parsed.hostname != "github.com"
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ValueError("github_url 只允许无认证信息的 https://github.com/<owner>/<repo>")
    parts = [p for p in parsed.path.strip("/").removesuffix(".git").split("/") if p]
    if len(parts) != 2 or any(not re.fullmatch(r"[A-Za-z0-9_.-]+", p) for p in parts):
        raise ValueError("github_url 的 owner/repo 格式不合法")
    if not re.fullmatch(r"[0-9a-fA-F]{40}|v?\d+\.\d+\.\d+|HEAD", ref or ""):
        raise ValueError("下载 ref 不是允许的 commit/tag")
    tar_url = f"https://github.com/{parts[0]}/{parts[1]}/archive/{ref}.tar.gz"
    os.makedirs(dest_dir, exist_ok=True)
    archive = os.path.join(dest_dir, ".download.tar.gz")
    with urllib.request.urlopen(
            urllib.request.Request(tar_url, headers={"User-Agent": "skill-manager"}),
            timeout=120) as response, open(archive, "wb") as out:
        shutil.copyfileobj(response, out)
    with tarfile.open(archive, "r:gz") as tf:
        members = tf.getmembers()
        links = []
        root = os.path.realpath(dest_dir)
        for member in members:
            stripped = member.name.split("/", 1)[1] if "/" in member.name else ""
            if not stripped:
                continue
            target = os.path.realpath(os.path.join(dest_dir, stripped))
            if os.path.commonpath((root, target)) != root:
                raise ValueError("上游归档包含路径逃逸")
            if member.issym() or member.islnk():
                links.append((member, stripped))
                continue
            if not (member.isfile() or member.isdir()):
                raise ValueError("上游归档包含不安全的设备文件")
            if member.isdir():
                os.makedirs(target, exist_ok=True)
            else:
                os.makedirs(os.path.dirname(target), exist_ok=True)
                source = tf.extractfile(member)
                if source is None:
                    raise ValueError("上游归档中的普通文件无法读取")
                with source, open(target, "wb") as out:
                    shutil.copyfileobj(source, out)
                os.chmod(target, member.mode & 0o777)
        for member, stripped in links:
            if member.issym():
                linked = os.path.join(os.path.dirname(stripped), member.linkname)
            else:
                linked = member.linkname.split("/", 1)[1] if "/" in member.linkname else ""
            linked_target = os.path.realpath(os.path.join(dest_dir, linked))
            target = os.path.realpath(os.path.join(dest_dir, stripped))
            if (not linked or os.path.commonpath((root, linked_target)) != root
                    or not os.path.isfile(linked_target)):
                raise ValueError("上游归档包含不安全的链接或设备文件")
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(linked_target, "rb") as source, open(target, "wb") as out:
                shutil.copyfileobj(source, out)
            os.chmod(target, os.stat(linked_target).st_mode & 0o777)
    os.unlink(archive)
    return bool(os.listdir(dest_dir))


# ── 直装 skill：整目录合并更新 ─────────────────────────────

def find_skill_source(extract_root, skill_name, github_path=None):
    """在解压的仓库里定位 skill 源目录（含 SKILL.md）。"""
    candidates = []
    if github_path:
        if os.path.isabs(github_path) or ".." in github_path.split(os.sep):
            raise ValueError("github_path 不得是绝对路径或包含 ..")
        candidates.append(core.contained_path(extract_root, github_path))
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
PRESERVE_FIELDS = ("zh_description", "update_policy")


def merge_skill_md(upstream_content, old_content, meta_fields):
    """上游 SKILL.md + 回注元数据 + 保留本地定制。

    `description` 保留完整上游原文；中文展示由 `zh_description` 独立维护。
    旧 `keep_local_description` 标记不能绕过上游字段完整性要求。
    """
    new = upstream_content
    old_meta = parse_frontmatter(old_content or "")
    fields = list(PRESERVE_FIELDS)
    for k in fields:
        if old_meta.get(k):
            new = set_frontmatter_field(new, k, old_meta[k])
    for k, v in meta_fields.items():
        new = set_frontmatter_field(new, k, v)
    old_sec = USER_SECTION_RE.search(old_content or "")
    if old_sec and "User-Learned Best Practices" not in new:
        new = new.rstrip("\n") + "\n\n" + old_sec.group(0).rstrip("\n") + "\n"
    return new


def validate_skill_md(content):
    """落盘后自检：合并有没有把 frontmatter 搞坏。返回缺失的必需字段列表（空 = 通过）。"""
    meta = parse_frontmatter(content or "")
    return [k for k in ("name", "description") if not meta.get(k)]


def copy_frontmatter_field(content, reference, key):
    """Copy the original YAML field block, including folded/literal semantics."""
    def span(lines):
        if not lines or lines[0].strip() != '---':
            raise ValueError('SKILL.md has no frontmatter')
        end = next((i for i in range(1, len(lines)) if lines[i].strip() == '---'), None)
        if end is None:
            raise ValueError('SKILL.md frontmatter is not closed')
        start = next((i for i in range(1, end) if lines[i].startswith(key + ':')), end)
        stop = start + 1 if start < end else end
        while stop < end and (not lines[stop].strip() or lines[stop].startswith((' ', '\t'))):
            stop += 1
        return start, stop

    source = reference.splitlines(keepends=True)
    start, stop = span(source)
    if start == stop:
        raise ValueError('upstream SKILL.md is missing ' + key)
    target = content.splitlines(keepends=True)
    a, b = span(target)
    target[a:b] = source[start:stop]
    return ''.join(target)


def copy_description(content, reference):
    return copy_frontmatter_field(content, reference, 'description')


HEADER_RE = re.compile(r"^##\s+(.+?)\s*$", re.M)


def summarize_change(old_content, new_content):
    """粗粒度总结这次更新改了什么，供 update 后打印——不做静默换血。

    只挑用户/agent 关心的两类信号：description 变了（决定 Claude 选不选它的
    那句话）、章节增减（功能新增/废弃的直接信号）。逐行 diff 太啰嗦，不展开。
    """
    old_meta = parse_frontmatter(old_content or "")
    new_meta = parse_frontmatter(new_content or "")
    lines = []
    if old_meta.get("description", "") != new_meta.get("description", ""):
        lines.append("⚠️  description 变了（决定 Claude 选不选它的那句话），建议看一眼还准不准")
    added = set(HEADER_RE.findall(new_content or "")) - set(HEADER_RE.findall(old_content or ""))
    removed = set(HEADER_RE.findall(old_content or "")) - set(HEADER_RE.findall(new_content or ""))
    if added:
        lines.append(f"新增章节：{'、'.join(sorted(added))}")
    if removed:
        lines.append(f"移除章节：{'、'.join(sorted(removed))}（可能是废弃了对应用法）")
    if not lines:
        diff = list(difflib.unified_diff(
            (old_content or "").splitlines(), (new_content or "").splitlines(), lineterm=""))
        changed = sum(1 for l in diff if l[:1] in "+-" and l[:3] not in ("+++", "---"))
        if changed:
            lines.append(f"内容有改动（{changed} 行），未检测到 description/章节层面的明显差异")
    return lines


def merge_bytes(local, base, upstream, name):
    if local is None or local == upstream:
        return upstream
    if base is None:
        raise ValueError(f"missing verified baseline for local differences: {name}")
    if local == base:
        return upstream
    if upstream == base:
        return local
    if b"\x00" in local + base + upstream:
        raise ValueError(f"binary merge conflict: {name}")
    with tempfile.TemporaryDirectory(prefix="skill-merge-") as temp:
        paths = [Path(temp) / label for label in ('local', 'base', 'upstream')]
        for path, data in zip(paths, (local, base, upstream)):
            path.write_bytes(data)
        result = subprocess.run(['git', 'merge-file', '-p', *map(str, paths)],
                                capture_output=True, timeout=30)
        if result.returncode:
            raise ValueError(f"three-way merge conflict: {name}; reconcile in isolation before updating")
        return result.stdout


def merge_skill_dir(src, dst, meta_fields, md_name="SKILL.md", baseline=None):
    """Merge verified base, local customization and complete upstream in staging."""
    source = audit_upstream.local_files(Path(src))
    current = audit_upstream.local_files(Path(dst))
    original = audit_upstream.local_files(Path(baseline)) if baseline else {}
    old_md = (Path(dst) / md_name).read_text() if (Path(dst) / md_name).exists() else ''
    operations = {}
    for name, upstream in source.items():
        local = current.get(name)
        base = original.get(name)
        if name == 'SKILL.md':
            def normalized(data):
                if data is None:
                    return None
                text = USER_SECTION_RE.sub('', data.decode('utf-8'))
                return core.strip_managed_fields(text, extra=('update_policy', 'description')).encode()
            merged = merge_bytes(normalized(local), normalized(base), normalized(upstream), name)
            old_section = USER_SECTION_RE.search(old_md)
            upstream_section = USER_SECTION_RE.search(upstream.decode('utf-8'))
            if old_section and upstream_section and old_section.group() != upstream_section.group():
                raise ValueError('three-way merge conflict: User-Learned Best Practices')
            if upstream_section and not old_section:
                merged += b'\n' + upstream_section.group().encode()
            merged = merge_skill_md(merged.decode('utf-8'), old_md, meta_fields)
            merged = copy_description(merged, upstream.decode('utf-8'))
            errors = audit_upstream.routing_field_errors(merged,
                audit_upstream.routing_field_blocks(upstream.decode('utf-8')))
            if errors:
                raise ValueError('; '.join(errors))
            merged = merged.encode()
        else:
            merged = merge_bytes(local, base, upstream, name)
        operations[name] = merged
    for name, base in original.items():
        if name not in source and name in current:
            if current[name] != base:
                raise ValueError(f'upstream deletion conflicts with local customization: {name}')
            operations[name] = None
    # Do not touch staging until every collision has been resolved.
    for name, data in operations.items():
        path = Path(dst) / (md_name if name == 'SKILL.md' else name)
        if data is None:
            path.unlink()
        else:
            path.parent.mkdir(exist_ok=True, parents=True)
            path.write_bytes(data)
            path.chmod((Path(src) / name).stat().st_mode & 0o777)
    return old_md, operations.get('SKILL.md', b'').decode('utf-8')


def live_snapshot(directory, files=None):
    """Transaction identity includes the real entry name and ordinary modes."""
    root = Path(directory)
    files = audit_upstream.local_files(root) if files is None else dict(files)
    entry = 'SKILL.md' if (root / 'SKILL.md').is_file() else 'SKILL.md.disabled'
    if not (root / entry).is_file():
        raise ValueError('incomplete live Skill entry')
    receipt = root / audit_upstream.RECEIPT
    if receipt.is_symlink():
        raise ValueError('redirected merge receipt')
    if receipt.is_file():
        files[audit_upstream.RECEIPT] = receipt.read_bytes()
    return {'entry': entry, 'files': {
        name: {'sha256': audit_upstream.digest(data),
               'mode': (root / (entry if name == 'SKILL.md' else name)).stat().st_mode & 0o777}
        for name, data in files.items()}}


def recover_direct(skill_dir):
    """Reconcile only the paths and complete snapshots owned by this journal."""
    live = Path(skill_dir)
    journal = Path(core.direct_state_dir(live)) / 'transaction.json'
    if not journal.exists():
        return
    record = core.read_json(str(journal))
    if not isinstance(record, dict) or record.get('live') != str(live):
        raise ValueError(f'invalid update recovery record: {journal}')
    stage = Path(record.get('stage', ''))
    old = Path(record.get('old', ''))
    prefix = f'.{live.name}.stage-'
    suffix = stage.name[len(prefix):]
    if (stage.parent != live.parent or not stage.name.startswith(prefix) or not suffix
            or old != live.with_name(live.name + '.old-' + suffix)
            or any(path.is_symlink() for path in (live, stage, old))):
        raise ValueError(f'invalid update recovery paths: {journal}')
    before, after = record.get('before'), record.get('after')
    for path, expected in ((old, before), (stage, after)):
        if path.exists() and live_snapshot(path) != expected:
            raise ValueError(f'recovery material changed; inspect {journal}')
    if live.exists():
        if live_snapshot(live) not in (before, after):
            raise ValueError(f'live Skill changed; inspect {journal}')
    elif old.exists():
        os.rename(old, live)
    else:
        raise ValueError(f'live and previous Skill absent; inspect {journal}')
    for path in (old, stage):
        if path.exists():
            shutil.rmtree(path)
    journal.unlink()


def update_direct_skill(skill_name, project=None, ref_arg=None, self_only=False,
                        upstream_only=False, target_path=None):
    core.safe_component(skill_name, "skill 名")
    resolved, error = ((target_path, None) if target_path else
                       core.resolve_direct_path(skill_name, project))
    if error:
        print(f"❌ {error}")
        return False
    if not resolved:
        print(f"❌ {skill_name} 不存在")
        return False
    skill_dir = os.path.realpath(resolved)
    with core.maintenance_lock(core.direct_state_dir(skill_dir)) as acquired:
        if not acquired:
            print(f"❌ {skill_name} 正在维护，请稍后重试")
            return False
        with core.maintenance_signals():
            try:
                recover_direct(skill_dir)
            except (OSError, ValueError) as error:
                print(f"❌ {skill_name} 待恢复：{error}")
                return False
            return _update_direct_skill(skill_name, skill_dir, ref_arg, self_only, upstream_only)


def _update_direct_skill(skill_name, skill_dir, ref_arg, self_only, upstream_only):
    # 禁用的 skill 入口叫 SKILL.md.disabled。不认它的话，冷藏起来的 skill
    # 就永远停在禁用那天的版本，想更新还得先启用一次——那正是用户要避开的中间态。
    md_name = "SKILL.md"
    skill_md = os.path.join(skill_dir, md_name)
    if not os.path.exists(skill_md):
        md_name = "SKILL.md.disabled"
        skill_md = os.path.join(skill_dir, md_name)
    if not os.path.exists(skill_md):
        print(f"❌ {skill_name} 不存在")
        return False
    if md_name.endswith(".disabled"):
        print(f"💤 {skill_name} 当前是禁用状态，更新后仍保持禁用")

    owner = lifecycle.lookup_root(skill_dir)
    if owner:
        if ref_arg:
            print('❌ lookup 的本体通道由其维护入口管理，不通过通用 --ref 切换。')
            return False
        return lifecycle.update(owner, self_only, upstream_only)
    if upstream_only:
        print('❌ 该 Skill 没有已接入的上游依赖维护入口。')
        return False

    initial_snapshot = live_snapshot(skill_dir)
    with open(skill_md, encoding="utf-8") as f:
        content = f.read()
    meta = parse_frontmatter(content)

    if meta.get("update_policy") == "frozen":
        print(f"🧊 {skill_name} 已声明 update_policy: frozen（绝版或深度定制），按策略不更新。"
              f"保留冻结标记，按 references/冻结版本维护.md 在隔离目录完整合并上游与本地差异；"
              f"必须通过 audit_upstream.py 的源快照覆盖验收，不能以升版或测试通过代替。")
        return False

    github_url = meta.get("github_url")
    if not github_url:
        print(f"❌ {skill_name} 没有 github_url，无法更新（可在 frontmatter 登记来源后重试）")
        return False

    print(f"🔍 检查 {skill_name} 更新...")
    try:
        target_ref, remote_hash, channel = resolve_update_target(
            github_url, meta, ref_arg)
    except ValueError as e:
        print(f"❌ {e}")
        return False
    if not remote_hash:
        print(f"❌ 无法连接到 {github_url}")
        return False
    if channel == "main":
        print("🌿 跟随上游主分支（未发版提交），后续 update 默认继续跟 main；"
              "回到发布版用 --ref release")

    local_hash = meta.get("github_hash", "")
    if local_hash and (remote_hash.startswith(local_hash) or local_hash.startswith(remote_hash[:12])):
        try:
            receipt = json.loads(Path(skill_dir, audit_upstream.RECEIPT).read_text())
            if not audit_upstream.verify(Path(skill_dir), receipt):
                print(f"✅ {skill_name} 上游提交相同，合并回执与现存全部文件一致（{target_ref}）")
                return True
        except (OSError, ValueError, KeyError, TypeError):
            pass
        print('登记 commit 相同，但缺少有效内容验收；继续核对完整源快照。')
    print(f"📥 目标版本：{target_ref}（{remote_hash[:8]}）")

    # 整目录备份（回滚入口，删除请手动清理 _update_backups）
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_dir = os.path.join(BACKUP_ROOT, f"{skill_name}.{ts}")
    os.makedirs(BACKUP_ROOT, exist_ok=True)
    shutil.copytree(skill_dir, backup_dir, symlinks=True)
    print(f"📦 已整目录备份到 {backup_dir}")

    tmp = tempfile.mkdtemp(prefix="skillupd_")
    baseline_tmp = tempfile.mkdtemp(prefix="skillbase_")
    stage = tempfile.mkdtemp(prefix=f".{Path(skill_dir).name}.stage-", dir=os.path.dirname(skill_dir))
    journal = Path(core.direct_state_dir(skill_dir)) / 'transaction.json'
    try:
        print(f"📥 下载 {remote_hash[:8]} ...")
        if not download_repo(github_url, remote_hash, tmp):
            print("❌ 下载失败，本地未改动")
            return False
        src = find_skill_source(tmp, skill_name, meta.get("github_path"))
        if not src:
            print(f"❌ 仓库里找不到 {skill_name} 的 SKILL.md（可在 frontmatter 用 github_path 指明子目录），本地未改动")
            return False
        incoming_meta = core.parse_skill_md(os.path.join(src, 'SKILL.md'))
        if incoming_meta.get('name') != meta.get('name'):
            raise ValueError('upstream Skill identity differs from the installed Skill; reconcile a rename explicitly')
        baseline_src = None
        if re.fullmatch(r'[0-9a-fA-F]{40}', local_hash):
            if not download_repo(github_url, local_hash, baseline_tmp):
                raise ValueError('registered upstream baseline cannot be downloaded')
            baseline_src = find_skill_source(baseline_tmp, skill_name, meta.get('github_path'))
            if not baseline_src:
                raise ValueError('registered upstream baseline has no matching Skill')
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
        if channel == "main":
            # 主分支上 VERSION 文件通常还停在上一个 tag（作者发版时才 bump）。
            # 照抄就成了「版本号说 3.32.0、内容是 3.32.0 之后的未发版提交」——
            # 正是本文件反复防的那种撒谎。加 +main 让它自曝领先发布版。
            fields["github_ref"] = "main"
            # 上游没给版本号时不编一个："main" 不是版本号。留空让版本列回退到
            # 「日期 · 短哈希」，那才说得清装的是哪一版；通道信息由 github_ref 承担。
            if upstream_version:
                upstream_version = f"{upstream_version}+main"
        elif meta.get("github_ref"):
            # 只有从 main 退回来时才写空值清标记。无条件写会给每个跟 release 的
            # skill 平白留一行 github_ref: ""，元数据只记真实状态，不记默认值。
            fields["github_ref"] = ""
        if upstream_version:
            fields["version"] = upstream_version
        # 两边都要 realpath：find_skill_source 走 core.contained_path 时返回的是
        # 解析过软链的路径（macOS 上 /var → /private/var），拿它跟未解析的 tmp
        # 算相对路径，会得到一串 ../ 直通临时目录，并被当成 github_path 写进
        # frontmatter —— 下次更新就再也找不到源目录了。
        rel = os.path.relpath(os.path.realpath(src), os.path.realpath(tmp))
        if rel != "." and not rel.startswith(".."):
            fields["github_path"] = rel
        shutil.rmtree(stage)
        shutil.copytree(skill_dir, stage, symlinks=True)
        old_md, new_md = merge_skill_dir(src, stage, fields, md_name, baseline=baseline_src)

        missing = validate_skill_md(new_md)
        if missing:
            print(f"❌ 合并后 SKILL.md 缺少必需字段 {missing}，本地未改动")
            return False
        source_files = audit_upstream.local_files(Path(src))
        staged_files = audit_upstream.local_files(Path(stage))
        adaptations = {name: ['Three-way merge from the registered upstream baseline, preserving local customization and managed metadata.']
                       for name, data in source_files.items()
                       if staged_files.get(name) != data}
        receipt = audit_upstream.make_receipt(Path(stage), source_files,
            dict(repository=github_url, commit=remote_hash, source_path=fields.get('github_path', meta.get('github_path', '.'))), adaptations)
        core.write_json(str(Path(stage) / audit_upstream.RECEIPT), receipt)
        errors = audit_upstream.verify(Path(stage), receipt, source_files)
        if errors:
            raise ValueError('upstream merge coverage failed: ' + '; '.join(errors))
        if live_snapshot(skill_dir) != initial_snapshot:
            raise ValueError('live Skill changed during update; preserve concurrent work and retry after reconciliation')

        suffix = Path(stage).name[len(f'.{Path(skill_dir).name}.stage-'):]
        old_live = f"{skill_dir}.old-{suffix}"
        core.write_json(str(journal), {'live': skill_dir, 'old': old_live, 'stage': stage,
            'before': initial_snapshot, 'after': live_snapshot(stage, staged_files)})
        try:
            os.rename(skill_dir, old_live)
            os.rename(stage, skill_dir)
        except BaseException:
            try:
                recover_direct(skill_dir)
            except BaseException as recovery_error:
                print(f"❌ 目录切换待恢复：{journal}；{recovery_error}")
            raise
        recover_direct(skill_dir)

        for line in summarize_change(old_md, new_md):
            print(f"   {line}")
        print(f"✅ {skill_name} 已三方合并到 {remote_hash[:8]}，完整核对{len(source_files)}个上游文件并保留本地差异；回执：{audit_upstream.RECEIPT}")
        return True
    except Exception as e:
        state = f"目录切换待恢复：{journal}" if journal.exists() else "请核对现存目录"
        print(f"❌ 更新失败: {e}（{state}；备份: {backup_dir}）")
        return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(baseline_tmp, ignore_errors=True)
        if not journal.exists():
            shutil.rmtree(stage, ignore_errors=True)


# ── 插件更新：monorepo 定位 + 验证后提交 ───────────────────

def is_valid_plugin_root(d):
    """插件根目录判定：标准结构或 baoyu 式 marketplace 结构。"""
    cp = os.path.join(d, ".claude-plugin")
    if os.path.isfile(os.path.join(cp, "plugin.json")):
        return True
    return (os.path.isfile(os.path.join(cp, "marketplace.json"))
            and os.path.isdir(os.path.join(d, "skills")))


def locate_plugin_root(extract_root, plugin_name):
    """在解压仓库里定位插件目录（支持 monorepo）。"""
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

    registry_snapshot = Path(INSTALLED_PLUGINS_JSON).read_bytes()
    registry = json.loads(registry_snapshot)
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

    installs = registry["plugins"][plugin_key]
    if not installs or not isinstance(installs[0], dict):
        print(f"❌ 插件 {plugin_key} 的登记结构损坏，拒绝更新")
        return False
    install = installs[0]
    local_hash = install.get("gitCommitSha", "")
    # A cache registration cannot prove that its files still match that commit.
    try:
        if not re.fullmatch(r'[0-9a-fA-F]{40}', local_hash):
            raise ValueError('plugin baseline is unknown; trace the installed source before updating')
        with tempfile.TemporaryDirectory(prefix='pluginbase_') as baseline:
            if not download_repo(github_url, local_hash, baseline):
                raise ValueError('plugin baseline cannot be downloaded')
            baseline_root = locate_plugin_root(baseline, plugin_name)
            installed_root = Path(install.get('installPath', ''))
            if not baseline_root or not installed_root.is_dir():
                raise ValueError('plugin baseline or installed files are unavailable')
            installed_files = audit_upstream.local_files(installed_root)
            if installed_files != audit_upstream.local_files(Path(baseline_root)):
                raise ValueError('plugin has local differences; reconcile the full baseline/local/upstream snapshots in isolation, preserving local-only files')
    except (OSError, ValueError) as error:
        print(f'❌ {error}（插件与登记表保持原状，未完成更新）')
        return False
    if local_hash and (remote_hash.startswith(local_hash) or local_hash.startswith(remote_hash[:12])):
        print(f"✅ {plugin_key} 上游提交相同且安装内容已逐文件核对 ({remote_hash[:8]})")
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

        candidate_files = audit_upstream.local_files(Path(plugin_root))

        version = plugin_version_of(plugin_root, remote_hash[:12])
        cache_dir = os.path.join(CLAUDE_DIR, "plugins", "cache", marketplace, plugin_name)
        core.safe_component(marketplace, "marketplace 名")
        core.safe_component(plugin_name, "plugin 名")
        new_dir = core.contained_path(
            cache_dir, f"{remote_hash[:12]}-{datetime.now().strftime('%Y%m%d%H%M%S%f')}")
        if os.path.abspath(new_dir) == os.path.abspath(install.get("installPath", "")):
            new_dir = os.path.join(cache_dir, remote_hash[:12])
        os.makedirs(cache_dir, exist_ok=True)
        shutil.move(plugin_root, new_dir)

        if not is_valid_plugin_root(new_dir):
            shutil.rmtree(new_dir, ignore_errors=True)
            print("❌ 落盘后结构验证失败，保留旧版本")
            return False
        if audit_upstream.local_files(Path(new_dir)) != candidate_files:
            raise ValueError('plugin candidate content differs after staging')
        if audit_upstream.local_files(installed_root) != installed_files:
            raise ValueError('installed plugin changed during update; preserve concurrent changes')

        if Path(INSTALLED_PLUGINS_JSON).read_bytes() != registry_snapshot:
            raise ValueError('plugin registry changed during update; preserve concurrent registration changes')
        registry["plugins"][plugin_key][0].update({
            "installPath": new_dir,
            "version": version,
            "lastUpdated": datetime.now().isoformat(),
            "gitCommitSha": remote_hash,
        })
        core.write_json(INSTALLED_PLUGINS_JSON, registry)

        old_path = install.get("installPath", "")
        print(f"✅ {plugin_key} 已更新到 v{version} ({remote_hash[:8]})")
        if old_path and os.path.isdir(old_path) and os.path.abspath(old_path) != os.path.abspath(new_dir):
            print(f"🗑  旧版本目录可手动清理: {old_path}")
        return True
    except Exception as e:
        candidate = locals().get("new_dir")
        if candidate and os.path.isdir(candidate):
            cache_root = os.path.realpath(os.path.join(CLAUDE_DIR, "plugins", "cache"))
            if os.path.commonpath((cache_root, os.path.realpath(candidate))) == cache_root:
                shutil.rmtree(candidate, ignore_errors=True)
        print(f"❌ 更新失败: {e}（登记表未改动，旧版本继续可用）")
        return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ── 单个更新（名字解析走 core.resolve_target，update / delete 共用） ──

def update_one(name, project=None, ref_arg=None, self_only=False, upstream_only=False):
    if name in lifecycle.TOOL_NAMES:
        if project or ref_arg or self_only or upstream_only:
            print('❌ 工具更新不接受 Skill 作用域或通道参数；保持所属维护器的安装来源。')
            return False
        payload, code = lifecycle.invoke_tool(name)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return code == 0
    if project:
        return update_direct_skill(name, project, ref_arg, self_only, upstream_only)
    kind, key, err = core.resolve_target(name)
    if err:
        print(f"❌ {err}")
        return False
    if kind == "plugin":
        if self_only or upstream_only:
            print('❌ 插件不支持 lookup 的本体／上游范围参数。')
            return False
        if ref_arg:
            print("❌ --ref 只对直装 skill 有效：插件按 commit 装，本来就跟 HEAD")
            return False
        return update_plugin(key)
    return update_direct_skill(key, None, ref_arg, self_only, upstream_only)


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

    outdated = sorted((r for r in results if r["status"] == "outdated" or r.get('needs_merge_verification')
                       or r.get('managed_update')),
                      key=lambda r: r["name"])
    errors = [r for r in results if r["status"] == "error" and not r.get('managed_update')]
    unresolved = [r for r in results if r['status'] == 'unknown' or (
        r['status'] == 'frozen' and r.get('has_upstream') and r.get('merge_coverage') != 'verified')]

    if errors:
        print(f"⚠️  {len(errors)} 个连不上上游，本轮跳过：" +
              "、".join(r["name"] for r in errors) + "\n")
    if unresolved:
        print('⚠️  来源或完整合并仍待核验：' + '、'.join(r['name'] for r in unresolved))

    if not outdated:
        print('没有待执行的自动更新；冻结项未在本轮联网比较，不能据此认定全部最新版已合并。')
        return not errors and not unresolved

    print(f"🟡 {len(outdated)} 个待更新或待完整内容核验：")
    for r in outdated:
        tail = "" if r["enabled"] else "（未启用）"
        print(f"   {chk.target_label(r)}  {r.get('local', '—')} → {r.get('remote', '本体与上游分项维护')}{tail}")
    print()

    if dry_run:
        print("（--dry-run：只看不做，去掉该参数即开始更新）")
        return True

    done, failed = [], []
    for i, r in enumerate(outdated, 1):
        print(f"── [{i}/{len(outdated)}] {chk.target_label(r)} " + "─" * 30)
        try:
            location = {key: r[key] for key in ('project', 'target_path') if key in r}
            ok = (update_plugin(r["name"]) if r["kind"] == "plugin"
                  else update_direct_skill(r["name"], **location))
        except Exception as e:          # 单个炸了不能中断整批
            print(f"❌ 更新失败: {e}")
            ok = False
        (done if ok else failed).append(chk.target_label(r))
        print()

    print("═" * 46)
    print(f"✅ 成功 {len(done)}：" + "、".join(done) if done else "✅ 成功 0")
    if failed:
        print(f"❌ 未全部完成 {len(failed)}：" + "、".join(failed) +
              f"\n   （逐项核对实际结果；普通 Skill 备份在 {BACKUP_ROOT}/，lookup 另有维护回执。）")
    return not failed and not errors and not unresolved


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
    ref_arg = None
    if "--ref" in argv:
        i = argv.index("--ref")
        if i + 1 >= len(argv):
            print("❌ --ref 后面要跟 main 或 release")
            sys.exit(1)
        ref_arg = argv[i + 1]
        del argv[i:i + 2]
    names = [a for a in argv if not a.startswith("-")]
    flags = {a for a in argv if a.startswith("-")}
    if len(names) > 1:
        print('❌ 单项更新只接受一个 Skill 名称；不能忽略多余对象扩大更新范围。')
        sys.exit(1)

    unknown = flags - {"--dry-run", "--self-only", "--upstream-only"}
    if unknown:
        print(f"❌ 不认识的参数: {'、'.join(sorted(unknown))}")
        print("用法: python3 update_skill.py [名字] [--project <路径>] "
              "[--ref main|release] [--dry-run]")
        print("      不给名字 = 检查并更新所有有新版的")
        print("      --ref main    = 跟上游主分支的未发版提交（通道有粘性）")
        print("      --ref release = 退回最新发布 tag")
        sys.exit(1)

    if ref_arg and not names:
        print("❌ --ref 要指定 skill 名：批量更新不整体切换跟随通道")
        sys.exit(1)

    if ('--self-only' in flags and '--upstream-only' in flags) or (
            not names and flags & {'--self-only', '--upstream-only'}):
        print('❌ 本体／上游范围参数须指定单个 Skill，且不能同时使用。')
        sys.exit(1)

    if not names:
        if project:
            print("❌ --project 只能用于更新单个项目级 skill")
            sys.exit(1)
        sys.exit(0 if update_all(dry_run="--dry-run" in flags) else 1)

    if "--dry-run" in flags:
        if names[0] in lifecycle.TOOL_NAMES:
            if project or ref_arg or flags & {'--self-only', '--upstream-only'}:
                print('❌ 工具更新不接受 Skill 作用域或通道参数。')
                sys.exit(1)
            payload, code = lifecycle.invoke_tool(names[0], dry_run=True)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            sys.exit(code)
        # 只解析目标，不联网查新版（批量 dry-run 才做真实比对）——如实说清，别让人
        # 把「将更新」误读成「确认有新版」
        kind, key, err = ("skill", names[0], None) if project else core.resolve_target(names[0])
        if not err and kind == 'skill':
            path, resolution_error = core.resolve_direct_path(key, project)
            owner = lifecycle.lookup_root(path) if path and not resolution_error else None
            if owner:
                if ref_arg:
                    print('❌ lookup 不通过通用 --ref 切换通道。')
                    sys.exit(1)
                payload, code = lifecycle.invoke(owner, self_only='--self-only' in flags,
                    upstream_only='--upstream-only' in flags, dry_run=True)
                print(json.dumps(payload, ensure_ascii=False, indent=2))
                sys.exit(code)
        print(f"❌ {err}" if err else
              f"（--dry-run）目标解析为{'插件' if kind == 'plugin' else 'skill'}：{key}"
              f"（是否有新版以实际执行时的比对为准）")
        sys.exit(1 if err else 0)

    sys.exit(0 if update_one(names[0], project, ref_arg, '--self-only' in flags,
                            '--upstream-only' in flags) else 1)
