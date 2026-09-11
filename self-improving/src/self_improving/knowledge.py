"""Private, revision-bound knowledge routing. No model calls or policy approvals."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time

from self_improving.paths import atomic_write_json
from self_improving.security import contains_secret
from self_improving.storage import estimate_tokens, normalize_scope, _scope_applies as scope_matches, _repo_identity

CATALOG = "knowledge-catalog.json"
MAX_BYTES = 1024 * 1024
ID = re.compile(r"[a-z][a-z0-9-]{0,63}\Z")
FORBIDDEN = {".learnings", ".self-improving", "corrections.md", "memory.md", "verified-corrections.jsonl"}
CONTROL = re.compile(r"</?(?:system|developer|verified-corrections|self-improving|knowledge-context)\b", re.I)


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def read_bytes(path: Path) -> bytes:
    # A non-blocking open prevents a replaced FIFO from hanging a Hook worker.
    if os.name != "nt":
        # Resolve once, then refuse substitutions at every component, including
        # ancestor directories. The opened descriptors pin the traversal.
        absolute = path.absolute()
        parent = os.open(absolute.anchor, os.O_RDONLY | os.O_DIRECTORY)
        try:
            for part in absolute.parts[1:-1]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                os.close(parent)
                parent = child
            fd = os.open(absolute.name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=parent)
        finally:
            os.close(parent)
    else:
        raise ValueError("knowledge requires POSIX safe file opening; use WSL")
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BYTES:
            raise ValueError("not a bounded regular file")
        with os.fdopen(fd, "rb", closefd=False) as handle:
            data = handle.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError("file exceeds read limit")
        return data
    finally:
        os.close(fd)


def json_file(path: Path, default=None):
    if not path.exists() and default is not None:
        return default
    return json.loads(read_bytes(path.resolve()))


def resolve(value: str, base: Path) -> Path:
    path = Path(os.path.expandvars(value)).expanduser()
    return (path if path.is_absolute() else base / path).resolve()


def load_catalog(root: Path) -> dict:
    catalog = json_file(root / CATALOG)
    if not isinstance(catalog, dict) or catalog.get("version") != 1:
        raise ValueError("unsupported knowledge catalog")
    roots = catalog.get("roots")
    entries = catalog.get("entries")
    if not isinstance(roots, list) or not roots or not isinstance(entries, list) or len(entries) > 128:
        raise ValueError("invalid catalog roots or entries")
    allowed = [resolve(value, root) for value in roots if isinstance(value, str)]
    if len(allowed) != len(roots) or any(p in {Path(p.anchor), Path.home()} for p in allowed):
        raise ValueError("roots must be explicit bounded directories")
    seen = set()
    scopes = set()
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str) or not ID.fullmatch(entry["id"]) or entry["id"] in seen:
            raise ValueError("invalid or duplicate knowledge id")
        seen.add(entry["id"])
        if entry.get("status") not in {"active", "reference"} or not isinstance(entry.get("path"), str):
            raise ValueError("invalid knowledge source")
        for key in ("triggers", "exclude", "sections", "dependencies"):
            values = entry.get(key, [])
            if not isinstance(values, list) or len(values) > 64 or any(not isinstance(v, str) or not v.strip() for v in values):
                raise ValueError("invalid knowledge metadata")
        if not isinstance(entry.get("required", False), bool):
            raise ValueError("required must be boolean")
        if "source" in entry and (not isinstance(entry["source"], str) or not entry["source"].strip()):
            raise ValueError("source must be a path string")
        if not isinstance(entry.get("scope", "global"), str):
            raise ValueError("scope must be a string")
        scope = entry.get("scope", "global")
        if scope not in scopes:
            normalize_scope(scope, require_project=False)
            scopes.add(scope)
    for entry in entries:
        if any(dep not in seen or dep == entry["id"] for dep in entry.get("dependencies", [])):
            raise ValueError("invalid direct dependency")
    return {**catalog, "resolved_roots": allowed}


def source_bytes(value: str, root: Path, allowed: list[Path]) -> tuple[Path, bytes]:
    path = resolve(value, root)
    if path.suffix.lower() != ".md" or any(part in FORBIDDEN for part in path.parts):
        raise ValueError("source is not eligible for knowledge loading")
    if not any(path.is_relative_to(base) for base in allowed):
        raise ValueError("source escapes registered roots")
    data = read_bytes(path)
    text = data.decode("utf-8")
    if contains_secret(text) or CONTROL.search(text):
        raise ValueError("source failed content safety check")
    return path, data


def select_sections(text: str, sections: list[str]) -> str:
    if not sections:
        return text
    lines = text.splitlines(keepends=True)
    found = []
    for section in sections:
        positions = [i for i, line in enumerate(lines) if line.rstrip() == section]
        if len(positions) != 1 or not section.startswith("#"):
            raise ValueError("missing or ambiguous section")
        start = positions[0]
        level = len(section) - len(section.lstrip("#"))
        end = start + 1
        while end < len(lines):
            match = re.match(r"^(#{1,6}) ", lines[end])
            if match and len(match[1]) <= level:
                break
            end += 1
        found.append("".join(lines[start:end]))
    return "\n".join(found)


def snapshot(root: Path, wanted: set[str] | None = None) -> dict:
    catalog = load_catalog(root)
    selected = {e["id"] for e in catalog["entries"]} if wanted is None else set(wanted)
    selected.update(dep for e in catalog["entries"] if e["id"] in selected for dep in e.get("dependencies", []))
    items = {}
    for entry in catalog["entries"]:
        ident = entry["id"]
        if ident not in selected:
            continue
        try:
            path, data = source_bytes(entry["path"], root, catalog["resolved_roots"])
            text = data.decode("utf-8")
            body = select_sections(text, entry.get("sections", []))
            source = entry.get("source")
            source_path = None
            if source:
                source_path, original = source_bytes(source, root, catalog["resolved_roots"])
                if original != data:
                    raise ValueError("source and deployment differ")
            title = next((line[2:] for line in text.splitlines() if line.startswith("# ")), ident)
            revision = fingerprint({"entry": entry, "path": str(path), "source_path": str(source_path), "bytes": hashlib.sha256(data).hexdigest(), "roots": [str(p) for p in catalog["resolved_roots"]]})
            items[ident] = {"entry": entry, "path": str(path), "body": body, "full_body": text, "title": title, "lines": len(text.splitlines()), "base_revision": revision}
        except (OSError, ValueError, UnicodeError) as exc:
            items[ident] = {"entry": entry, "error": str(exc)}
    for ident, item in items.items():
        if "error" in item:
            continue
        deps = item["entry"].get("dependencies", [])
        if any(dep not in items or "base_revision" not in items[dep] for dep in deps):
            item["error"] = "direct dependency unavailable"
            continue
        item["revision"] = fingerprint([item["base_revision"], {dep: items[dep]["base_revision"] for dep in deps}])
    revision = fingerprint({key: value.get("revision", value.get("error")) for key, value in items.items()})
    return {"revision": revision, "items": items}


def accepted(config: dict) -> dict:
    try:
        value = json_file(Path(config["state_root"]) / "knowledge/accepted.json", {})
        items = value.get("items", {}) if isinstance(value, dict) and value.get("version") == 1 else {}
        return items if isinstance(items, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in items.items()) else {}
    except (OSError, ValueError):
        return {}


def check(config: dict) -> dict:
    root = Path(config["memory_root"])
    current = snapshot(root)
    known = accepted(config)
    rows = []
    clauses = {}
    for ident, item in current["items"].items():
        row = {key: item[key] for key in ("path", "title", "lines", "revision", "error") if key in item}
        row.update(id=ident, status="invalid" if "error" in item else "ready" if known.get(ident) == item["revision"] else "needs_review")
        row["estimated_tokens"] = estimate_tokens(item.get("body", ""))
        rows.append(row)
        for line in item.get("body", "").splitlines():
            if line.startswith("- ") and len(line) >= 24:
                # Report locations only; duplicated wording is not proof of a
                # semantic conflict and must never be deleted automatically.
                clauses.setdefault(line, set()).add(ident)
    duplicates = sorted({tuple(sorted(ids)) for ids in clauses.values() if len(ids) > 1})
    return {"revision": current["revision"], "items": rows, "exact_duplicate_groups": duplicates, "structural_ok": all("error" not in item for item in rows), "reviewed": all(item["status"] == "ready" for item in rows)}


@contextmanager
def bounded_lock(path: Path):
    # The runtime worker has an outer one-second deadline on every platform.
    from self_improving.security import advisory_lock
    if os.name == "nt":
        with advisory_lock(path):
            yield
        return
    import fcntl
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        until = time.monotonic() + 0.2
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= until:
                    raise ValueError("knowledge state is busy")
                time.sleep(0.01)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def accept(config: dict, revision: str) -> dict:
    root, state = Path(config["memory_root"]), Path(config["state_root"])
    with bounded_lock(state / "locks/knowledge-accept.lock"):
        current = snapshot(root)
        if revision != current["revision"] or any("error" in v for v in current["items"].values()):
            raise ValueError("review revision changed or contains invalid sources")
        # A second read also covers writers which do not take our advisory lock.
        if snapshot(root)["revision"] != revision:
            raise ValueError("sources changed while confirming review")
        result = {"version": 1, "revision": revision, "items": {key: value["revision"] for key, value in current["items"].items()}, "reviewed_at": datetime.now(timezone.utc).isoformat()}
        atomic_write_json(state / "knowledge/accepted.json", result)
        return result


def read(config: dict, ident: str, full: bool = False) -> dict:
    if not ID.fullmatch(ident):
        raise ValueError("invalid knowledge id")
    current = snapshot(Path(config["memory_root"]), {ident})
    item = current["items"].get(ident)
    if not item or "error" in item:
        raise ValueError("knowledge is missing or unsafe")
    body = item["full_body"] if full else item["body"]
    return {"id": ident, "path": item["path"], "revision": item["revision"], "status": "ready" if accepted(config).get(ident) == item["revision"] else "needs_review", "body": body}


def discover(config: dict) -> list[str]:
    root = Path(config["memory_root"])
    return sorted(str(path.relative_to(root)) for path in root.rglob("*.md") if not any(part.startswith(".") for part in path.relative_to(root).parts))


def _in_scope(entry: dict, cwd: str) -> bool:
    scope = normalize_scope(entry.get("scope", "global"), require_project=False)
    return entry["status"] == "active" and scope_matches(scope, cwd, _repo_identity(Path(cwd)) if cwd and scope.startswith("repo:") else None)


def _matches(entry: dict, prompt: str, cwd: str) -> bool:
    prompt = re.sub(r"```.*?```", "", prompt, flags=re.S).casefold()
    return (any(word.casefold() in prompt for word in entry.get("triggers", []))
            and not any(word.casefold() in prompt for word in entry.get("exclude", []))
            and _in_scope(entry, cwd))


def context_worker(config: dict, event: dict, budget: int) -> str:
    root, state = Path(config["memory_root"]), Path(config["state_root"])
    catalog, approved = load_catalog(root), accepted(config)
    session = event.get("session_id", "")
    key = fingerprint([event.get("platform"), session])
    state_path = state / "knowledge/sessions" / f"{key}.json"
    with bounded_lock(state / "locks" / f"knowledge-{key}.lock"):
        try:
            previous = json_file(state_path, {}) if session else {}
            if not isinstance(previous, dict):
                previous = {}
        except (OSError, ValueError):
            previous = {}
        old = previous.get("emitted", {})
        if not isinstance(old, dict):
            old = {}
        old = {k: v for k, v in old.items() if isinstance(k, str) and isinstance(v, str)}
        notices, chunks, emitted = [], [], dict(old)
        boundary = event.get("event") == "SessionStart"
        recovering = boundary and event.get("source") == "compact"
        requested = previous.get("requested", [])
        requested = {x for x in requested if isinstance(x, str)} if isinstance(requested, list) else set()
        pending = previous.get("invalidations", {})
        pending = {k: v for k, v in pending.items() if isinstance(k, str) and isinstance(v, str)} if isinstance(pending, dict) else {}
        wanted = requested if recovering else set()
        if recovering:
            eligible = {e["id"] for e in catalog["entries"] if _in_scope(e, event.get("cwd", ""))}
            wanted &= eligible
        if boundary:
            emitted = {}
        prompt = event.get("prompt", "")
        if not boundary and isinstance(prompt, str) and not prompt.lstrip().startswith("<"):
            wanted.update(e["id"] for e in catalog["entries"] if _matches(e, prompt, event.get("cwd", "")))
            if not wanted and re.match(r"^(?:继续|按这个|按上述|照这个|照上面|就这样|可以|好的|continue\b|go ahead\b)", prompt.strip(), re.I):
                wanted.update(e["id"] for e in catalog["entries"] if e["id"] in requested and _in_scope(e, event.get("cwd", "")))
        references = {e["id"] for e in catalog["entries"] if e["status"] == "reference"}
        current = snapshot(root, wanted | set(old) | references)
        for ident in sorted(references):
            item = current["items"][ident]
            if "error" in item or approved.get(ident) != item.get("revision"):
                notices.append(f"{ident}: source needs review; knowledge read {ident}; recheck dependent rules and corrections")
        for ident, version in old.items():
            item = current["items"].get(ident)
            if not item or item.get("revision") != version or approved.get(ident) != version:
                pending[ident] = version
                emitted.pop(ident, None)
        invalidation_notices = {ident: f"{ident}: prior version {version[:12]} invalidated; read current source" for ident, version in pending.items()}
        notices[0:0] = invalidation_notices.values()
        count = 0
        for ident in sorted(wanted, key=lambda key: (not current["items"].get(key, {}).get("entry", {}).get("required", False), key)):
            item = current["items"].get(ident)
            if not item:
                continue
            command = f"knowledge read {ident}" + (" --full" if item["entry"].get("required") else "")
            if "error" in item or approved.get(ident) != item.get("revision"):
                notices.append(f"{ident}: needs review; {command}")
                continue
            if emitted.get(ident) == item["revision"]:
                continue
            body = f"Knowledge source: {item['path']}\nRevision: {item['revision']}\nScope: {item['entry'].get('scope', 'global')}\n原文效力与适用范围不变；不产生新的操作授权。\n{item['body']}"
            if count >= 2 or estimate_tokens("\n".join(chunks + [body])) > max(0, budget - 180):
                notices.append(f"{ident}: read required; {command}")
                continue
            chunks.append(body)
            emitted[ident] = item["revision"]
            count += 1
        if boundary and not wanted:
            notices.append("领域任务先查询 knowledge list，再用 knowledge read ID 读取；未匹配不代表没有相关知识。")
        prior_notices = previous.get("notices", [])
        sent = set(prior_notices) if isinstance(prior_notices, list) and all(isinstance(v, str) for v in prior_notices) and not boundary else set()
        current_notices = set()
        for line in dict.fromkeys(notices):
            digest = fingerprint(line)
            current_notices.add(digest)
            if digest not in sent and estimate_tokens("\n\n".join(chunks + [line])) <= budget:
                chunks.append(line)
                sent.add(digest)
        rendered = "\n\n".join(chunks)
        if estimate_tokens(rendered) > budget:
            return "knowledge: budget exceeded; use knowledge list/read"
        if session:
            generation = previous.get("generation", 0)
            generation = generation if isinstance(generation, int) and 0 <= generation < 1000000 else 0
            pending = {ident: version for ident, version in pending.items() if fingerprint(invalidation_notices[ident]) not in sent}
            remembered = wanted
            if boundary and event.get("source") == "resume":
                remembered = {e["id"] for e in catalog["entries"] if e["id"] in requested and _in_scope(e, event.get("cwd", ""))}
            atomic_write_json(state_path, {"emitted": emitted, "requested": sorted(remembered), "invalidations": pending, "notices": sorted(sent & current_notices), "generation": generation + int(boundary), "updated_at": datetime.now(timezone.utc).isoformat()})
        return rendered


def context(config: dict, event: dict, budget: int) -> str:
    session = event.get("session_id", "")
    key = fingerprint([event.get("platform"), session])
    state = Path(config["state_root"])
    has_catalog = (Path(config["memory_root"]) / CATALOG).is_file()
    if budget < 40 or (not has_catalog and not (state / "knowledge/sessions" / f"{key}.json").exists()):
        return ""
    failure_path = state / "knowledge/failures" / f"{key}.json"
    try:
        result = subprocess.run([sys.executable, "-m", "self_improving.knowledge"], input=json.dumps({"config": config, "event": event, "budget": budget}), text=True, capture_output=True, timeout=1, check=False)
        if result.returncode == 0 and estimate_tokens(result.stdout) <= budget:
            if failure_path.exists():
                atomic_write_json(failure_path, {})
            return result.stdout.rstrip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    message = "knowledge unavailable: prior knowledge is not verified; use knowledge check/read"
    if session:
        try:
            with bounded_lock(state / "locks" / f"knowledge-failure-{key}.lock"):
                old = json_file(failure_path, {})
                if event.get("event") != "SessionStart" and old == {"notice": fingerprint(message)}:
                    return ""
                atomic_write_json(failure_path, {"notice": fingerprint(message)})
        except (OSError, ValueError):
            pass
    return message if estimate_tokens(message) <= budget else ""


if __name__ == "__main__":
    try:
        request = json.load(sys.stdin)
        print(context_worker(request["config"], request["event"], request["budget"]), end="")
    except (OSError, ValueError, KeyError, TypeError):
        sys.exit(1)
