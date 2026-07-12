#!/usr/bin/env python3
"""给本地 skill 递增版本号，并把内容指纹重新记账（消掉 * 标记）。

用法:
  python3 bump_skill.py <名字>          1.0.0 → 1.0.1（小改，默认）
  python3 bump_skill.py <名字> minor    1.0.0 → 1.1.0（加功能）
  python3 bump_skill.py <名字> major    1.0.0 → 2.0.0（大改 / 不兼容）

没有 version 字段的（本地自建、从别人那拷来的）→ 首次定版为 1.0.0。

为什么要有这个命令：版本号靠人工维护必然会忘，所以 skill-manager 另存一份
内容指纹当「事实」。改了内容没升版本号 → 版本列打 *。bump 一下，账就平了。
GitHub 来源的 skill 不套 semver（身份是上游 commit），本命令拒绝处理。
"""
import io
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


def find_skill(name, project=None):
    wanted = os.path.abspath(project) if project else "global"
    for s in core.collect_all(all_projects=True):
        if s.name == name and s.scope == wanted and s.source in ("github", "local", "frozen"):
            return s
    return None


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    argv = sys.argv[1:]
    project = None
    if "--project" in argv:
        i = argv.index("--project")
        if i + 1 >= len(argv):
            print("❌ --project 后面要跟项目路径")
            sys.exit(1)
        project = argv[i + 1]
        del argv[i:i + 2]
    if not argv:
        print(__doc__)
        sys.exit(1)
    name = argv[0]
    level = argv[1] if len(argv) > 1 else "patch"
    if level not in ("patch", "minor", "major"):
        print(f"❌ 递增级别只能是 patch / minor / major，收到：{level}")
        sys.exit(1)

    s = find_skill(name, project)
    if not s:
        print(f"❌ 找不到直装 skill：{name}（插件的版本由上游维护，不能 bump）")
        sys.exit(1)

    if s.source == "github":
        print(f"❌ {name} 是 GitHub 来源，版本身份是上游 commit（{s.github_hash[:7]}），不套 semver")
        print("   如果你已经深度定制、要脱离上游自己管版本，先在 SKILL.md 加 update_policy: frozen")
        sys.exit(1)

    meta = core.parse_skill_md(s.md_path)
    old = str(meta.get("version", "")).strip()
    new = core.bump_semver(old, level)

    core.set_frontmatter_field(s.md_path, "version", new)
    try:
        # 重新记账：指纹和版本号对齐，* 消失
        fps = core.read_json(core.FINGERPRINTS, {})
        fps[f"{s.scope}:{name}"] = {
            "hash": core.fingerprint(s.path),
            "ident": new,
            "updated": date.today().isoformat(),
        }
        core.write_json(core.FINGERPRINTS, fps)
    except Exception:
        if old:
            core.set_frontmatter_field(s.md_path, "version", old)
        else:
            core.remove_frontmatter_field(s.md_path, "version")
        raise

    if old:
        print(f"✅ {name}  {old} → {new}（{level}）")
    else:
        print(f"✅ {name}  首次定版 → {new}")
    print(f"   已写入 {s.md_path}")


if __name__ == "__main__":
    main()
