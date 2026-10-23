#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Local scope adapter for check; not an unmodified Alibaba source file.
"""Inventory Git paths and reconcile OCR selection, without reading file bodies."""

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


class ScopeError(ValueError):
    pass


def git(repo, *args, optional=False):
    result = subprocess.run(
        ["git", "--no-optional-locks", "-C", os.fspath(repo),
         "-c", "core.quotepath=false", *args],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
    )
    if result.returncode:
        if optional:
            return None
        message = os.fsdecode(result.stderr).strip()[:500]
        raise ScopeError("git {} failed: {}".format(args[0], message))
    return result.stdout


def nul_records(raw):
    if raw and not raw.endswith(b"\0"):
        raise ScopeError("Git output is not NUL terminated")
    return [os.fsdecode(value) for value in raw.split(b"\0") if value]


def resolve_commit(repo, ref):
    if not ref or ref.startswith("-") or "\0" in ref:
        raise ScopeError("A commit reference must be nonempty and not an option")
    return git(repo, "rev-parse", "--verify", "--end-of-options",
               ref + "^{commit}").decode("ascii").strip()


def entry(layer, status, old_path, new_path):
    return {"layer": layer, "status": status, "path": new_path or old_path,
            "old_path": old_path, "new_path": new_path}


def parse_changes(raw, layer):
    fields = nul_records(raw)
    rows, offset = [], 0
    while offset < len(fields):
        status = fields[offset]
        width = 3 if status.startswith(("R", "C")) else 2
        if offset + width > len(fields):
            raise ScopeError("Truncated Git name-status record")
        first = fields[offset + 1]
        if width == 3:
            old_path, new_path = first, fields[offset + 2]
        else:
            old_path = None if status.startswith("A") else first
            new_path = None if status.startswith("D") else first
        rows.append(entry(layer, status, old_path, new_path))
        offset += width
    return rows


DIFF_FLAGS = ["--name-status", "-z", "--find-renames",
              "--no-ext-diff", "--no-textconv"]


def validate_paths(paths):
    result = []
    for path in paths:
        if not isinstance(path, str) or not path or "\0" in path:
            raise ScopeError("Paths must be nonempty strings without NUL")
        if path.startswith("/") or any(part in ("", ".", "..")
                                       for part in path.split("/")):
            raise ScopeError("Use exact repository-relative file paths")
        if path not in result:
            result.append(path)
    return result


def inventory(repo, mode="workspace", from_ref=None, to_ref=None,
              commit_ref=None, paths=()):
    repo = Path(os.fsdecode(git(repo, "rev-parse", "--show-toplevel"))
                .removesuffix("\n"))
    paths = validate_paths(paths)
    scope = {"immutable": mode in ("range", "commit"), "ocr_args": []}
    if mode == "range":
        start = resolve_commit(repo, from_ref)
        head = resolve_commit(repo, to_ref)
        bases = git(repo, "merge-base", "--all", start, head).decode().split()
        if len(bases) != 1:
            raise ScopeError("Range requires one unambiguous merge base")
        base = bases[0]
        scope.update(base=base, head=head, resolved_from=start,
                     exact_range=base + ".." + head,
                     ocr_args=["--from", base, "--to", head])
        rows = parse_changes(git(repo, "diff", *DIFF_FLAGS,
                                 base, head, "--"), "range")
    elif mode == "commit":
        head = resolve_commit(repo, commit_ref)
        parents = git(repo, "rev-list", "--parents", "-n", "1",
                      "--end-of-options", head).decode().split()[1:]
        base = parents[0] if parents else None
        scope.update(base=base, head=head,
                     exact_range=base + ".." + head if base else None,
                     ocr_args=["--commit", head])
        if base:
            raw = git(repo, "diff", *DIFF_FLAGS, base, head, "--")
        else:
            raw = git(repo, "diff-tree", "--root", "-r", "--no-commit-id",
                      *DIFF_FLAGS, head, "--")
        rows = parse_changes(raw, "commit")
    elif mode in ("workspace", "scan"):
        head = git(repo, "rev-parse", "--verify", "--quiet",
                   "HEAD^{commit}", optional=True)
        scope.update(base=head.decode().strip() if head else None,
                     head=None, exact_range=None)
        if mode == "workspace":
            rows = parse_changes(git(repo, "diff", "--cached", *DIFF_FLAGS,
                                     "--"), "staged")
            rows += parse_changes(git(repo, "diff", *DIFF_FLAGS, "--"),
                                  "unstaged")
        else:
            rows = []
            for path in dict.fromkeys(nul_records(git(repo, "ls-files", "-z"))):
                exists = os.path.lexists(repo / path)
                rows.append(entry("tracked", "tracked" if exists else "D",
                                  path, path if exists else None))
        rows += [entry("untracked", "?", None, path) for path in
                 nul_records(git(repo, "ls-files", "-z", "--others",
                                 "--exclude-standard"))]
        scope["snapshot_note"] = (
            "Mutable, non-atomic path/status inventory. File contents are not "
            "read or fingerprinted; equal inventories do not prove equal content. "
            "Recheck content identity before reusing a preview or review."
        )
    else:
        raise ScopeError("Unknown inventory mode")
    total = len(rows)
    if paths:
        wanted = set(paths)
        rows = [row for row in rows
                if row["old_path"] in wanted or row["new_path"] in wanted]
    found = {path for row in rows
             for path in (row["old_path"], row["new_path"]) if path is not None}
    identity = json.dumps([mode, scope, paths, rows],
                          sort_keys=True, separators=(",", ":")).encode()
    return {
        "schema_version": "1", "repository": str(repo), "mode": mode,
        "scope": scope, "inventory_id": hashlib.sha256(identity).hexdigest(),
        "identity_kind": "paths-status-refs-only", "requested_paths": paths,
        "unmatched_paths": [path for path in paths if path not in found],
        "counts": {"entries": len(rows), "paths": len({r["path"] for r in rows}),
                   "unfiltered_entries": total,
                   "layers": dict(Counter(r["layer"] for r in rows))},
        "entries": rows,
    }


def reconcile(report, preview):
    """Attach selection evidence. No selection outcome means reviewed/passed."""
    if isinstance(preview, dict) and "files" not in preview:
        # Delegate v1 has separate selected/excluded arrays, not full-engine files.
        selected = preview.get("reviewable_files")
        excluded = preview.get("excluded_files")
        if (preview.get("schema_version") != "1"
                or not isinstance(selected, list) or not isinstance(excluded, list)):
            raise ScopeError("Expected Delegate v1 or full-engine preview JSON")
        files = []
        for rows, will_review in ((selected, True), (excluded, False)):
            for item in rows:
                if not isinstance(item, dict):
                    raise ScopeError("Malformed Delegate preview entry")
                if "will_review" in item:
                    raise ScopeError("Unexpected Delegate selection flag")
                files.append({**item, "will_review": will_review})
        preview = {**preview, "files": files}
    if not isinstance(preview, dict) or not isinstance(preview.get("files"), list):
        raise ScopeError("Expected OCR preview JSON")
    by_path = {}
    for item in preview["files"]:
        if (not isinstance(item, dict) or not isinstance(item.get("path"), str)
                or not isinstance(item.get("status"), str)
                or type(item.get("will_review")) is not bool
                or not isinstance(item.get("exclude_reason", ""), str)):
            raise ScopeError("Malformed OCR preview entry")
        by_path.setdefault(item["path"], []).append(item)
    layers = {}
    for row in report["entries"]:
        layers.setdefault(row["path"], set()).add(row["layer"])
    dispositions = Counter()
    for row in report["entries"]:
        matches = by_path.get(row["path"], [])
        deleted = row["new_path"] is None
        same_side = [item for item in matches
                     if (item["status"] == "deleted") == deleted]
        selection = [{"status": item["status"], "will_review": item["will_review"],
                      "reason": item.get("exclude_reason", "")}
                     for item in same_side]
        if deleted:
            disposition, reason = "deleted", "deletion_requires_impact_review"
        elif (report["mode"] == "workspace" and len(layers[row["path"]]) > 1):
            disposition, reason = "manual_layer_gap", "workspace_layers_may_be_collapsed"
        elif len(same_side) > 1 or (matches and not same_side):
            disposition, reason = "manual_layer_gap", "ambiguous_or_other_layer_preview"
        elif not same_side:
            disposition, reason = "provider_missing", "absent_from_preview_cause_unknown"
        elif same_side[0]["will_review"]:
            disposition, reason = "selected", "selection_only_not_review_success"
        else:
            disposition, reason = "excluded", same_side[0].get("exclude_reason", "unknown")
        row["preview"] = {"disposition": disposition, "reason": reason,
                          "selection": selection}
        dispositions[disposition] += 1
    own_paths = {row["path"] for row in report["entries"]}
    outside = [{"path": item["path"], "status": item["status"],
                "will_review": item["will_review"]}
               for item in preview["files"] if item["path"] not in own_paths]
    report["preview"] = {
        "selection_only": True,
        "identity_verified": False,
        "identity_note": "OCR preview has no sealed content identity; the caller must "
                         "match repository, mode, refs, rules, limits and content.",
        "dispositions": dict(dispositions), "outside_inventory": outside,
        "selected_outside_inventory": sum(item["will_review"] for item in outside),
    }
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--mode", choices=("workspace", "range", "commit", "scan"),
                        default="workspace")
    parser.add_argument("--from", dest="from_ref")
    parser.add_argument("--to", dest="to_ref")
    parser.add_argument("--commit", dest="commit_ref")
    parser.add_argument("--path", action="append", default=[],
                        help="Exact repository-relative file path; repeat as needed")
    parser.add_argument("--paths-file", help="JSON array of exact file paths")
    parser.add_argument("--preview", help="OCR review/scan preview JSON to reconcile")
    parser.add_argument("--output", help="Create a JSON report file; stdout then shows counts only")
    args = parser.parse_args(argv)
    try:
        if args.mode != "range" and (args.from_ref or args.to_ref):
            raise ScopeError("--from/--to require --mode range")
        if args.mode != "commit" and args.commit_ref:
            raise ScopeError("--commit requires --mode commit")
        paths = args.path
        if args.paths_file:
            extra = json.loads(Path(args.paths_file).read_text(encoding="utf-8"))
            if not isinstance(extra, list):
                raise ScopeError("--paths-file must contain a JSON array")
            paths += extra
        report = inventory(args.repo, args.mode, args.from_ref, args.to_ref,
                           args.commit_ref, paths)
        if args.preview:
            reconcile(report, json.loads(Path(args.preview).read_text(encoding="utf-8")))
        encoded = json.dumps(report, separators=(",", ":")) + "\n"
        if args.output and args.output != "-":
            with open(args.output, "x", encoding="utf-8") as output:
                output.write(encoded)
            summary = {"output": str(Path(args.output).absolute()),
                       "inventory_id": report["inventory_id"], **report["counts"],
                       "unmatched_paths": len(report["unmatched_paths"])}
            if "preview" in report:
                summary["preview"] = report["preview"]["dispositions"]
                summary["selected_outside_inventory"] = report["preview"]["selected_outside_inventory"]
            print(json.dumps(summary, separators=(",", ":")))
        else:
            sys.stdout.write(encoded)
        return 0
    except (ScopeError, json.JSONDecodeError, OSError, UnicodeError,
            subprocess.SubprocessError) as error:
        print(json.dumps({"error": str(error)}, separators=(",", ":")), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
