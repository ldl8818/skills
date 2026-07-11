#!/usr/bin/env python3
"""skill-manager 统一数据层：所有命令共用的 skill 收集与状态判定。

2026-07-11 重构起因（实战事故）：
  list 只遍历硬盘登记表 installed_plugins.json，从不读 settings.json 的
  enabledPlugins，导致已禁用的插件（claude-mem 19 个 skill）照样显示为
  「已安装」，让人误判它们还在占用上下文。同期还发现 installed_plugins.json
  可以指向一个不存在的目录（baoyu 更新中断），项目级插件静默失效且无人察觉。

  根因是「状态散落在 6 处、每个脚本各读一套」。本模块把这 6 处归集成
  唯一事实来源，list / check / update / toggle / doctor / bump 全部走这里。

真实状态的 6 个来源：
  1. ~/.claude/skills/<name>/SKILL.md            全局直装（.disabled 后缀 = 禁用）
  2. <project>/.claude/skills/<name>/SKILL.md    项目直装
  3. ~/.claude/plugins/installed_plugins.json    插件的安装路径与版本
  4. ~/.claude/settings.json  → enabledPlugins   插件的全局启用状态
  5. <project>/.claude/settings.json → enabledPlugins  插件的项目级启用状态
  6. ~/.claude/commands/*.md                     自定义斜杠命令

版本语义（见 SKILL.md「版本规范」）：
  本地/拷贝/冻结  → 人工 semver（1.0.0），起手 1.0.0
  GitHub 有版本号 → 用上游的
  GitHub 无版本号 → 「安装日期 · 短哈希」，如 06-28 · d4e43c9
  插件            → 上游 plugin.json 的 version
  末尾 * 统一表示：内容改过了，版本号没跟上（用 bump 命令平账）
"""
import os
import re
import json
import hashlib
import subprocess
import unicodedata
from datetime import datetime, date

HOME = os.path.expanduser("~")
CLAUDE_DIR = os.path.join(HOME, ".claude")
GLOBAL_SKILLS_DIR = os.path.join(CLAUDE_DIR, "skills")
COMMANDS_DIR = os.path.join(CLAUDE_DIR, "commands")
GLOBAL_SETTINGS = os.path.join(CLAUDE_DIR, "settings.json")
INSTALLED_PLUGINS_JSON = os.path.join(CLAUDE_DIR, "plugins", "installed_plugins.json")
KNOWN_MARKETPLACES_JSON = os.path.join(CLAUDE_DIR, "plugins", "known_marketplaces.json")

SM_DIR = os.path.join(GLOBAL_SKILLS_DIR, "skill-manager")
DESCRIPTIONS_ZH = os.path.join(SM_DIR, "descriptions_zh.json")
FINGERPRINTS = os.path.join(SM_DIR, "fingerprints.json")
PROJECTS = os.path.join(SM_DIR, "projects.json")

# Claude Code 的会话记录目录：每个项目一个子目录，每跑一次会话写一份 .jsonl。
# 最新那份的 mtime = 最后一次在该项目里干活的时间 —— 这是「最近在写哪个项目」
# 唯一靠谱的信号。projects.json 的 last_seen 只记「最后一次跑过 skill-manager」，
# 跟开发活跃度无关，别拿它当活跃度用。
SESSIONS_DIR = os.path.join(CLAUDE_DIR, "projects")

# 第 7 个状态来源：skill 安装器（Waza / vercel skills CLI）留下的安装记录。
# 它权威地记着每个 skill 是从哪个仓库、哪个路径装来的。之前没读它，
# 才会把 tw93/Waza 装的 8 个 skill 误判成「本地自建」。
SKILL_LOCK = os.path.join(HOME, ".agents", ".skill-lock.json")

# 计算内容指纹时忽略的噪声（改动它们不算 skill 内容变化）
FP_IGNORE_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv"}
FP_IGNORE_FILES = {".DS_Store"}
FP_IGNORE_SUFFIX = (".pyc", ".log")

# skill-manager 的运行时数据恰好就存在它自己的 skill 目录里，
# 不排除的话，每记一次账它自己的指纹就变一次 —— 永远 dirty（自指 bug）
SM_DATA_FILES = {"fingerprints.json", "projects.json",
                 "descriptions_zh.json", "evolution.json"}

# 这些 frontmatter 字段是 skill-manager 自己写进去的元数据，不是用户的实质改动。
# 不剥掉的话，光是补一句 zh_description 就会把 skill 标成「改过了」。
# keep_local_description 同理：它是「别让 update 冲掉我改过的 description」这条记账声明，
# 不是内容；不剥掉的话，打个标记就会平白多出一颗 dirty 星。
MANAGED_FIELDS = ("version", "zh_description", "github_url",
                  "github_hash", "github_date", "github_path",
                  "keep_local_description")


# ── 基础 IO ──────────────────────────────────────────────

def read_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {} if default is None else default


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


# ── frontmatter 解析（免 PyYAML 依赖，任何 python3 可跑）───

def parse_frontmatter(text):
    """解析文件开头 --- 到 --- 之间的顶层 key: value（含 >/| 折叠块）。

    只吃开头的 frontmatter 块，正文里的 yaml 代码示例不会被误当成元数据。
    """
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


def parse_skill_md(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return parse_frontmatter(f.read())
    except Exception:
        return {}


def set_frontmatter_field(path, key, value):
    """在 frontmatter 里就地写入/更新一个字段，正文与其他字段一字不动。

    只认开头那个 --- 块；正文里的 yaml 代码示例不会被误改。
    """
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        raise ValueError(f"{path} 没有 frontmatter，拒绝写入")

    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        raise ValueError(f"{path} 的 frontmatter 没有闭合")

    val = f'"{value}"' if isinstance(value, str) and (":" in value or "#" in value) else value
    new_line = f"{key}: {val}"

    for i in range(1, end):
        if re.match(rf"^{re.escape(key)}:\s", lines[i]) or lines[i].strip() == f"{key}:":
            lines[i] = new_line
            break
    else:
        lines.insert(end, new_line)

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def remove_frontmatter_field(path, key):
    """删掉 frontmatter 里的一个字段。写错了要能撤销，不然只能越描越黑。"""
    with open(path, "r", encoding="utf-8") as f:
        lines = f.read().split("\n")
    if not lines or lines[0].strip() != "---":
        return False
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        return False
    kept = [l for i, l in enumerate(lines)
            if not (1 <= i < end and re.match(rf"^{re.escape(key)}:\s", l))]
    if len(kept) == len(lines):
        return False
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(kept))
    return True


def bump_semver(v, level="patch"):
    m = re.match(r"^v?(\d+)\.(\d+)\.(\d+)$", (v or "").strip())
    if not m:
        return "1.0.0"  # 没版本号或格式不认识 → 首次定版
    major, minor, patch = (int(x) for x in m.groups())
    if level == "major":
        return f"{major + 1}.0.0"
    if level == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


# ── 内容指纹 ──────────────────────────────────────────────

def strip_managed_fields(text, extra=()):
    """从 SKILL.md 里剥掉 skill-manager 自己写的 frontmatter 字段。

    指纹要反映的是「用户改没改这个 skill」，而不是「skill-manager 记没记账」。
    补一句 zh_description 就把 skill 标成「改过了」，dirty 信号就成了狼来了。

    `keep_local_description: true` 的 skill 还要额外剥掉 description：这条描述已经声明了
    「本地自己管、不跟上游」，它和上游不一致就是**预期状态**，不是异常。不剥的话
    trace 会永远判「内容对不上，可能被本地改过」，这些 skill 就永远定不了版本。

    extra 是给比对方用的：这条声明只写在本地那份文件里，上游那份没有。
    要拿两份内容做比较，剥哪些字段就必须**由本地的声明决定、对两边同时生效**，
    否则一边剥了一边没剥，口径不对称，永远比不中。
    """
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return text
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        return text
    fields = list(MANAGED_FIELDS) + list(extra)
    if str(parse_frontmatter(text).get("keep_local_description", "")).lower() == "true":
        fields.append("description")
    kept = [l for i, l in enumerate(lines)
            if not (1 <= i < end and any(
                re.match(rf"^{re.escape(k)}:\s", l) for k in fields))]
    return "\n".join(kept)


def fingerprint(skill_dir, extra_strip=()):
    """整目录内容哈希。任一文件内容变化 → 指纹变化（忽略噪声与自管元数据）。

    extra_strip 传给 strip_managed_fields —— 比对本地与上游时，用本地的声明
    统一两边的口径（见 strip_managed_fields 的 extra 说明）。
    """
    is_self = os.path.abspath(skill_dir) == SM_DIR
    h = hashlib.sha256()
    for root, dirs, files in os.walk(skill_dir):
        dirs[:] = sorted(d for d in dirs if d not in FP_IGNORE_DIRS)
        for fn in sorted(files):
            if fn in FP_IGNORE_FILES or fn.endswith(FP_IGNORE_SUFFIX):
                continue
            if is_self and fn in SM_DATA_FILES:
                continue
            fp = os.path.join(root, fn)
            rel = os.path.relpath(fp, skill_dir)
            h.update(rel.encode("utf-8"))
            h.update(b"\0")
            try:
                if fn in ("SKILL.md", "SKILL.md.disabled"):
                    with open(fp, "r", encoding="utf-8") as f:
                        h.update(strip_managed_fields(
                            f.read(), extra_strip).encode("utf-8"))
                else:
                    with open(fp, "rb") as f:
                        while chunk := f.read(65536):
                            h.update(chunk)
            except Exception:
                pass
    return h.hexdigest()[:16]


# ── 中文描述 ──────────────────────────────────────────────

SHORT_DESC = 80  # 超过这个长度的，基本是 skill 作者写的原始英文文档而非整理过的短描述


def is_chinese(s):
    """描述读起来是不是中文的（判断依据是长度 + 中英占比）。

    两类描述要区别对待，只用一条规则必然误判：
      · 短描述（≤80 字）—— 有人整理过的一句话用途。设计类 skill 天然中英混排
        （「杂志感长文, 含 masthead、hero、pull quote」），术语保留英文反而更好懂，
        有中文就算合格。硬按占比判会把它们全标成「待翻译」。
      · 长描述（>80 字）—— skill 作者写的原始文档，末尾常挂一串中文触发词
        （neat-freak、self-improving 都是）。只看「含不含中文」会被触发词骗过去，
        必须按占比判。
    """
    s = (s or "").strip()
    if not s:
        return False
    cjk = sum(1 for c in s if "一" <= c <= "鿿")
    if len(s) <= SHORT_DESC:
        return cjk >= 2
    ascii_alpha = sum(1 for c in s if c.isascii() and c.isalpha())
    return cjk > 0 and cjk * 2 >= ascii_alpha


def resolve_desc(name, meta, zh_map):
    """中文描述查找顺序：SKILL.md 的 zh_description > 外挂表 > 原始 description。

    zh_description 写在 skill 自己的 frontmatter 里，搬家/拷贝时跟着走；
    插件 skill 的 SKILL.md 会被上游更新覆盖，只能走外挂表 descriptions_zh.json。
    """
    zh = (meta.get("zh_description") or "").strip()
    if zh:
        return zh, True
    if name in zh_map:
        return zh_map[name], True
    raw = (meta.get("description") or "—").replace("\n", " ").strip()
    return raw, is_chinese(raw)


# ── 项目注册表 ────────────────────────────────────────────

def load_projects():
    return read_json(PROJECTS, {}).get("projects", {})


def is_project_dir(path):
    """有项目级 skill 或项目级插件配置，才算一个「有 skill 的项目」。

    HOME 和 ~/.claude 必须排除：~/.claude/skills 就是全局 skill 目录，
    把 HOME 当成项目会让 27 个全局 skill 又被当作「项目:dylan」重列一遍。
    以前靠注册表里碰巧没有 HOME 才没暴露；现在项目会从会话记录自动发现，
    这个坑就在路上了，堵在源头。
    """
    path = os.path.abspath(path)
    if path in (HOME, CLAUDE_DIR):
        return False
    return (os.path.isdir(os.path.join(path, ".claude", "skills"))
            or os.path.isfile(os.path.join(path, ".claude", "settings.json")))


def register_project(path):
    """在某项目里跑过 list，就自动登记，之后 `list --all` 能跨项目看全。"""
    path = os.path.abspath(path)
    if not is_project_dir(path):
        return False
    data = read_json(PROJECTS, {})
    projects = data.setdefault("projects", {})
    today = date.today().isoformat()
    if path in projects:
        projects[path]["last_seen"] = today
    else:
        projects[path] = {"registered": today, "last_seen": today}
    write_json(PROJECTS, data)
    return path not in projects


# ── 项目活跃度（真实开发信号）────────────────────────────

def _session_cwd(jsonl, max_lines=200):
    """从会话 .jsonl 里读出权威的项目路径。

    会话目录名是把 `/` 换成 `-` 编码的，反解有歧义 ——
    `-Users-dylan-dev-caipiao-feature` 既可能是 dev/caipiao-feature
    也可能是 dev/caipiao/feature，光看名字分不出来。文件内的 cwd 字段是
    权威路径，读它就没歧义。cwd 不一定在第一行，扫前若干行即可。
    """
    try:
        with open(jsonl, encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                if i >= max_lines:
                    return None
                if '"cwd"' not in line:
                    continue
                try:
                    cwd = json.loads(line).get("cwd")
                except (ValueError, AttributeError):
                    continue
                if cwd:
                    return os.path.abspath(cwd)
    except OSError:
        pass
    return None


def session_activity():
    """{项目绝对路径: 最近一次 Claude Code 会话的时间戳}。已删除的目录不返回。"""
    out = {}
    if not os.path.isdir(SESSIONS_DIR):
        return out
    for name in os.listdir(SESSIONS_DIR):
        d = os.path.join(SESSIONS_DIR, name)
        if not os.path.isdir(d):
            continue
        newest, ts = None, 0.0
        for fn in os.listdir(d):
            if not fn.endswith(".jsonl"):
                continue
            try:
                m = os.path.getmtime(os.path.join(d, fn))
            except OSError:
                continue
            if m > ts:
                newest, ts = os.path.join(d, fn), m
        if not newest:
            continue
        cwd = _session_cwd(newest)
        if cwd and os.path.isdir(cwd):
            out[cwd] = max(out.get(cwd, 0.0), ts)
    return out


def known_projects():
    """所有「有 skill 的项目」= 注册表 ∪ 有过会话记录的目录。

    光靠注册表不够：只有在项目里跑过 skill-manager 才会登记，
    你天天开发但没跑过它的项目就永远看不见。会话记录能自动发现它们。
    """
    pool = {p for p in load_projects() if os.path.isdir(p)}
    pool |= {p for p in session_activity() if is_project_dir(p)}
    return sorted(pool)


def rank_projects(paths=None):
    """按最近活跃度排序（最近的在前）。没有会话记录的排后面，退回 last_seen。"""
    acts = session_activity()
    known = load_projects()
    pool = list(paths) if paths is not None else known_projects()
    hot = sorted((p for p in pool if p in acts), key=lambda p: -acts[p])
    cold = sorted((p for p in pool if p not in acts),
                  key=lambda p: known.get(p, {}).get("last_seen", ""), reverse=True)
    return hot + cold


def resolve_project(token):
    """把用户给的项目名或路径解析成绝对路径。

    返回 (路径, 候选列表)。同名项目撞车时返回 (None, [候选...]) ——
    列出来让用户挑，绝不替他猜一个。
    """
    direct = os.path.abspath(os.path.expanduser(token))
    if os.path.isdir(direct):
        return direct, []
    pool = known_projects()
    exact = [p for p in pool if os.path.basename(p) == token]
    if len(exact) == 1:
        return exact[0], []
    if exact:
        return None, rank_projects(exact)
    fuzzy = [p for p in pool if token.lower() in os.path.basename(p).lower()]
    if len(fuzzy) == 1:
        return fuzzy[0], []
    return None, rank_projects(fuzzy)


# ── 插件启用状态 ──────────────────────────────────────────

def enabled_plugins_of(settings_path):
    return read_json(settings_path, {}).get("enabledPlugins", {})


def plugin_scopes(plugin_key, project_paths):
    """算出一个插件在哪些范围下真正生效。

    Claude Code 的行为：项目 settings.json 的 enabledPlugins 覆盖全局同名项，
    项目没写则继承全局。所以 baoyu（全局 false + creative true）= 只在 creative 生效。
    返回 (全局是否启用, [启用它的项目名])
    """
    global_on = bool(enabled_plugins_of(GLOBAL_SETTINGS).get(plugin_key, False))
    proj_on = []
    for p in project_paths:
        val = enabled_plugins_of(os.path.join(p, ".claude", "settings.json")).get(plugin_key)
        if val is True or (val is None and global_on):
            proj_on.append(os.path.basename(p))
    return global_on, proj_on


# ── Skill 记录 ────────────────────────────────────────────

class Skill(dict):
    """用 dict 子类而非 dataclass：各脚本要 json.dumps 输出，省一层转换。"""

    def __getattr__(self, k):
        try:
            return self[k]
        except KeyError:
            raise AttributeError(k)


def load_skill_lock():
    """安装器的 lock 记录：skill 名 → {source, sourceUrl, skillPath}。"""
    return read_json(SKILL_LOCK, {}).get("skills", {})


def repo_slug(url):
    """https://github.com/tw93/Waza(.git) → tw93/Waza"""
    m = re.search(r"github\.com[/:]([^/]+/[^/]+?)(?:\.git)?/?$", url or "")
    return m.group(1) if m else ""


# 只认纯语义化 tag（v3.31.2 / 1.5.16）。聚合仓库常给每个 skill 单独打 tag
# （neat-freak-v1.0.2），按「数字最大」去挑会挑到别的 skill 的 tag 上——
# 认不出来就老实回退 HEAD，别乱猜。
SEMVER_TAG = re.compile(r"^v?\d+\.\d+\.\d+$")


def remote_tags(url):
    """列出上游的语义化 tag → 它指向的 **commit** sha。

    坑：`git ls-remote --tags` 对 annotated tag（带说明的 tag）返回的是
    **tag 对象自己的 sha**，不是它指向的 commit。真正的 commit sha 在 `^{}` 那一行。
    过滤掉 `^{}` 就会把 tag 对象 sha 当成 commit 记进 github_hash ——
    然后 GitHub API 查这个 sha 会直接报「No commit found」（vercel-labs/skills 就是）。
    Waza 用的是 lightweight tag（直接指向 commit），所以碰巧没暴露这个 bug。
    """
    try:
        r = subprocess.run(["git", "ls-remote", "--tags", url],
                           capture_output=True, text=True, timeout=25)
    except Exception:
        return {}
    raw, peeled = {}, {}
    for line in r.stdout.splitlines():
        if "refs/tags/" not in line:
            continue
        sha, ref = line.split()[0], line.split("refs/tags/")[-1]
        if ref.endswith("^{}"):
            peeled[ref[:-3]] = sha       # annotated tag 真正指向的 commit
        else:
            raw[ref] = sha
    return {ref: peeled.get(ref, sha)    # 有 peeled 用 peeled，否则是 lightweight tag
            for ref, sha in raw.items() if SEMVER_TAG.match(ref)}


def latest_tag(url):
    """最新的语义化 tag → (ref, commit_sha)。没有就 (None, None)。"""
    tags = remote_tags(url)
    if not tags:
        return None, None
    newest = max(tags, key=lambda t: [int(n) for n in re.findall(r"\d+", t)])
    return newest, tags[newest]


def remote_head(url):
    try:
        r = subprocess.run(["git", "ls-remote", url, "HEAD"],
                           capture_output=True, text=True, timeout=20)
        if r.returncode == 0 and r.stdout.split():
            return r.stdout.split()[0]
    except Exception:
        pass
    return None


def marketplace_repo(marketplace):
    src = (read_json(KNOWN_MARKETPLACES_JSON, {})
           .get(marketplace, {}).get("source", {}))
    return src.get("repo", "") if isinstance(src, dict) else ""


# ── 名字解析：用户只写裸名，市场名由这里补 ──────────────────

def resolve_target(name, quiet=False):
    """用户给的名字 → (kind, 真实 key, 错误说明)。kind ∈ {"skill", "plugin"}。

    插件的真实 key 是 `插件名@市场名`（codex@openai-codex），但市场名是安装来源的
    内部标识，用户没理由记得住。这里替他补全：裸名字在登记表里唯一命中就直接补。
    撞名（同名插件装在两个市场）时列候选让人挑 —— 猜一个的代价是操作错对象。

    update / delete 共用此解析，别再各写一份（收集逻辑单源，见 SKILL.md 状态模型）。
    """
    registry = read_json(INSTALLED_PLUGINS_JSON, {}).get("plugins", {})

    if "@" in name:
        return "plugin", name, None

    if os.path.isfile(os.path.join(GLOBAL_SKILLS_DIR, name, "SKILL.md")):
        return "skill", name, None

    matches = [k for k in registry if k.split("@")[0] == name]
    if len(matches) == 1:
        if not quiet:
            print(f"🔗 {name} 是插件，已补全为 {matches[0]}")
        return "plugin", matches[0], None
    if len(matches) > 1:
        cand = "\n".join(f"   {k}" for k in sorted(matches))
        return None, None, f"插件 {name} 装在多个市场，请指明是哪个：\n{cand}"

    return None, None, (f"找不到 {name}（既不是 ~/.claude/skills/ 下的 skill，"
                        f"也不是已安装的插件）。跑 /skill-manager list 看看有哪些。")


# ── 三个正交维度：类型 / 来源 / 更新策略 ──────────────────
#
# 旧版把它们塞进同一列（GitHub / 本地 / 冻结 / 插件@xxx），怎么归类都别扭：
#   「冻结」是更新策略，不是来源（skill-manager 冻结了，来源仍是 GitHub）
#   「插件」是装载形态，不是来源（baoyu 插件也是从 GitHub 装的）
#   「聚合仓库」根本不是一类 —— 它就是 GitHub，只是一个仓库里放了多个 skill
# 而「GitHub」这个词本身几乎零信息量（除本地自建外基本全是 GitHub），
# 真正有用的是「哪个仓库」。所以：类型一列，来源直接写仓库名，冻结标在版本上。

KIND_SKILL, KIND_PLUGIN, KIND_COMMAND = "技能", "插件", "命令"


def _origin_of(source, github_url, marketplace=""):
    if source in ("plugin", "plugin-cmd"):
        return marketplace_repo(marketplace) or marketplace
    if source == "unknown":
        return "未登记 ❓"
    slug = repo_slug(github_url)
    if slug:
        return slug
    return "本地"


def _version_of(meta, source, github_date, github_hash):
    """按来源决定版本怎么显示（规则见模块 docstring）。"""
    v = str(meta.get("version", "")).strip()
    if source == "unknown":
        return "来源未登记"  # 绝不用 1.0.0 之类的默认值糊上去
    if source in ("local", "frozen"):
        return v or "未定版"
    if source == "github":
        if v:
            return v
        if github_hash:
            short = github_hash[:7]
            return f"{github_date} · {short}" if github_date else short
        return "版本未知"  # 来源登记了，但不知道装的是哪个 commit
    return v or "—"


def _source_of(meta):
    """判定来源。

    铁律：「没登记来源」≠「本地自建」。
    旧版把「没有 github_url」直接判成 local，然后 doctor --fix 给它们编了
    version 1.0.0 —— 而它们其实是 tw93/Waza v3.31.2 装的。凭空捏造出一个
    看起来权威的版本号，比老实说「不知道」有害得多。
    不知道就是 unknown，交给 doctor 报警、让人去登记。
    """
    if meta.get("update_policy") == "frozen":
        return "frozen"
    if meta.get("github_url"):
        return "github"
    if meta.get("source") == "local":  # 必须显式声明，不靠推断
        return "local"
    return "unknown"


def _apply_lock(name, meta, lock):
    """frontmatter 没登记来源时，用安装器的 lock 记录补上。

    lock 是安装器写的，比 frontmatter 更权威也更不容易丢（上游更新会重写
    SKILL.md，把我们加的字段冲掉，但 lock 会被同步更新）。
    """
    rec = lock.get(name)
    if not rec or meta.get("github_url"):
        return meta
    url = (rec.get("sourceUrl") or "").removesuffix(".git")
    if not url:
        return meta
    meta = dict(meta)
    meta["github_url"] = url
    sp = rec.get("skillPath", "")
    if sp.endswith("/SKILL.md"):
        meta.setdefault("github_path", sp[: -len("/SKILL.md")])
    return meta


def _make_direct_skill(name, skill_dir, md_path, enabled, scope, scope_label,
                       zh_map, fps, touched, lock):
    meta = _apply_lock(name, parse_skill_md(md_path), lock)
    source = _source_of(meta)
    desc, desc_zh = resolve_desc(name, meta, zh_map)

    github_hash = meta.get("github_hash", "")
    github_date = meta.get("github_date", "")
    version = _version_of(meta, source, github_date, github_hash)

    # 指纹对账：内容变了但版本号没跟上 → dirty（版本列打 *）
    #
    # 例外：有些 skill 设计上就会改写自己（self-improving 的 hook 每次会话都把
    # 学到的经验写回自己的 SKILL.md）。它们会永远 dirty，那颗星就成了噪声，
    # 真正该报的改动反而被淹没。声明 self_mutating: true 即豁免，只记账不报警。
    key = f"{scope}:{name}"
    cur_hash = fingerprint(skill_dir)
    ident = str(meta.get("version", "")) or github_hash
    self_mutating = str(meta.get("self_mutating", "")).lower() == "true"
    rec = fps.get(key)
    dirty = False
    if rec is None or rec.get("hash") != cur_hash:
        if rec is not None and rec.get("ident") == ident and not self_mutating:
            dirty = True  # 内容动了、身份没动 = 改了没记账
        else:
            fps[key] = {"hash": cur_hash, "ident": ident,
                        "updated": date.today().isoformat()}
            touched.append(key)

    return Skill(
        name=name, desc=desc, desc_zh=desc_zh, source=source,
        kind=KIND_SKILL, origin=_origin_of(source, meta.get("github_url", "")),
        frozen=(source == "frozen"),
        scope=scope, scope_label=scope_label, enabled=enabled,
        version=version, dirty=dirty, path=skill_dir,
        github_url=meta.get("github_url", ""), github_hash=github_hash,
        github_date=github_date, github_path=meta.get("github_path", ""),
        update_policy=meta.get("update_policy", ""),
        plugin_key="", marketplace="", md_path=md_path,
    )


def collect_direct(skills_root, scope, scope_label, zh_map, fps, touched, lock):
    out = []
    if not os.path.isdir(skills_root):
        return out
    for name in sorted(os.listdir(skills_root)):
        d = os.path.join(skills_root, name)
        if not os.path.isdir(d):
            continue
        md, md_dis = os.path.join(d, "SKILL.md"), os.path.join(d, "SKILL.md.disabled")
        if os.path.exists(md):
            out.append(_make_direct_skill(name, d, md, True, scope, scope_label,
                                          zh_map, fps, touched, lock))
        elif os.path.exists(md_dis):
            out.append(_make_direct_skill(name, d, md_dis, False, scope, scope_label,
                                          zh_map, fps, touched, lock))
    return out


def collect_plugins(zh_map, project_paths):
    """插件能力：启用状态从 settings.json 真实读取，不再假设「装了 = 在用」。

    插件既可以带 skills/，也可以只带 commands/（claude-hud 就没有 skills 目录，
    能力全在 commands/ 里；只扫 skills/ 会让它整个从列表消失）。两处都要收。
    """
    out = []
    registry = read_json(INSTALLED_PLUGINS_JSON, {}).get("plugins", {})
    for plugin_key, installs in registry.items():
        marketplace = plugin_key.split("@")[-1] if "@" in plugin_key else plugin_key
        plugin_name = plugin_key.split("@")[0]
        global_on, proj_on = plugin_scopes(plugin_key, project_paths)

        if global_on:
            scope_label, enabled = "全局", True
        elif proj_on:
            scope_label, enabled = "项目:" + "/".join(proj_on), True
        else:
            scope_label, enabled = "—", False

        def mk(name, path, md_path, src):
            meta = parse_skill_md(md_path) if os.path.exists(md_path) else {}
            desc, desc_zh = resolve_desc(name, meta, zh_map)
            return Skill(
                name=name, desc=desc, desc_zh=desc_zh, source=src,
                kind=KIND_PLUGIN if src == "plugin" else KIND_COMMAND,
                origin=_origin_of(src, "", marketplace), frozen=False,
                scope="plugin", scope_label=scope_label, enabled=enabled,
                version=version, dirty=False, path=path,
                github_url="", github_hash="", github_date="", github_path="",
                update_policy="", plugin_key=plugin_key, marketplace=marketplace,
                md_path=md_path,
            )

        for install in installs:
            path = install.get("installPath", "")
            version = install.get("version", "—")

            skills_dir = os.path.join(path, "skills")
            if os.path.isdir(skills_dir):  # 路径失效交给 doctor 报，list 不静默吞
                for n in sorted(os.listdir(skills_dir)):
                    sd = os.path.join(skills_dir, n)
                    if os.path.isdir(sd):
                        out.append(mk(n, sd, os.path.join(sd, "SKILL.md"), "plugin"))

            cmds_dir = os.path.join(path, "commands")
            if os.path.isdir(cmds_dir):
                for fn in sorted(os.listdir(cmds_dir)):
                    if not fn.endswith(".md"):
                        continue
                    cp = os.path.join(cmds_dir, fn)
                    out.append(mk(f"{plugin_name}:{fn[:-3]}", cp, cp, "plugin-cmd"))
    return out


def collect_commands(zh_map):
    out = []
    if not os.path.isdir(COMMANDS_DIR):
        return out
    for fname in sorted(os.listdir(COMMANDS_DIR)):
        if not fname.endswith(".md"):
            continue
        name = fname[:-3]
        fpath = os.path.join(COMMANDS_DIR, fname)
        meta = {}
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()
            meta = parse_frontmatter(content)
            if "description" not in meta:
                for line in content.splitlines():
                    line = line.strip().lstrip("#").strip()
                    if line:
                        meta["description"] = line
                        break
        except Exception:
            pass
        desc, desc_zh = resolve_desc(name, meta, zh_map)
        out.append(Skill(
            name=name, desc=desc, desc_zh=desc_zh, source="command",
            kind=KIND_COMMAND, origin="本地", frozen=False,
            scope="global", scope_label="全局", enabled=True,
            version="—", dirty=False, path=fpath,
            github_url="", github_hash="", github_date="", github_path="",
            update_policy="", plugin_key="", marketplace="", md_path=fpath,
        ))
    return out


# ── 对外主入口 ────────────────────────────────────────────

def collect_all(cwd=None, all_projects=False, projects=None):
    """收集全部 skill 的真实状态。

    cwd          当前目录（有 .claude/ 就一并扫，并自动登记进项目注册表）
    all_projects True 则把所有已知项目一起扫出来（`list --all`）
    projects     显式指定要扫哪些项目（`list <项目名>`）；给了就以它为准

    注意「扫哪些项目」和「插件在哪些项目生效」是两回事：前者决定列什么，
    后者永远要看全量项目，否则 baoyu 只在 creative 启用这件事就看不见了。
    """
    zh_map = read_json(DESCRIPTIONS_ZH, {})
    fps = read_json(FINGERPRINTS, {})
    lock = load_skill_lock()
    touched = []

    cwd = os.path.abspath(cwd or os.getcwd())
    if is_project_dir(cwd):
        register_project(cwd)

    if projects is not None:
        project_paths = [os.path.abspath(p) for p in projects if os.path.isdir(p)]
    elif all_projects:
        project_paths = rank_projects()
    elif is_project_dir(cwd):
        project_paths = [cwd]
    else:
        project_paths = []

    skills = collect_direct(GLOBAL_SKILLS_DIR, "global", "全局",
                            zh_map, fps, touched, lock)
    for p in project_paths:
        label = "项目:" + os.path.basename(p)
        skills += collect_direct(os.path.join(p, ".claude", "skills"),
                                 p, label, zh_map, fps, touched, lock)

    skills += collect_plugins(zh_map, known_projects() or project_paths)
    skills += collect_commands(zh_map)

    if touched:
        write_json(FINGERPRINTS, fps)
    return skills


# ── 表格显示辅助（CJK 宽度对齐）────────────────────────────

def dw(s):
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in s)


def pad(s, width):
    return s + " " * max(0, width - dw(s))


def trim(s, maxw):
    if dw(s) <= maxw:
        return s
    out, cur = "", 0
    for c in s:
        cw = 2 if unicodedata.east_asian_width(c) in ("W", "F") else 1
        if cur + cw > maxw - 1:
            return out + "…"
        out += c
        cur += cw
    return out
