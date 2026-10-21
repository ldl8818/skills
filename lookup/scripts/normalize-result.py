#!/usr/bin/env python3
"""Normalize a captured read result from stdin; never execute or retry tools.

Input: provider, exit_code, stdout, stderr; optional stdout_format=json|text|auto,
url, access_url, source, author, published_at, fetched_at, evidence_type,
empty_confirmed, truncated, missing_fields, outcome_unknown.
The result describes capture/shape quality. The Agent still verifies relevance,
authorship, freshness and whether the evidence answers the user's question.
"""
import argparse
import json
import re
import sys

MAX_INPUT_BYTES = 5 * 1024 * 1024
EVIDENCE = {"full_text", "excerpt", "metadata", "comments", "subtitles", "asr", "visual"}
CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")

def no_constant(value):
    raise ValueError(f"non-finite JSON number: {value}")

def loads(value):
    return json.loads(value, parse_constant=no_constant)

def encoded(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))

def error_metadata(stderr):
    if isinstance(stderr, dict):
        return stderr
    if not isinstance(stderr, str) or not stderr.strip():
        return {}
    try:
        value = loads(stderr)
        return value if isinstance(value, dict) else {}
    except (ValueError, RecursionError):
        pass
    # The local runner may emit its own error after an upstream stderr banner.
    # Accept only its final, fully structured envelope; keep other text unknown.
    try:
        tail = loads(stderr.strip().splitlines()[-1])
        error = tail.get("error") if isinstance(tail, dict) else None
        if (isinstance(error, dict)
                and isinstance(error.get("original_code"), str)
                and error["original_code"].startswith("OPENCLI_")
                and tail.get("phase") in {"entry", "action"}
                and isinstance(tail.get("outcome_unknown"), bool)
                and tail.get("retryable") is False):
            return tail
    except (ValueError, RecursionError):
        pass
    # Only read the exact flat error.code field in OpenCLI's emitted envelope.
    # This is not a general YAML parser. Complex/ambiguous YAML stays unknown.
    lines = [line for line in stderr.splitlines()
             if line.strip() and not line.lstrip().startswith("#")]
    if not lines or lines[0] != "error:":
        return {}
    values = []
    for line in lines[1:]:
        if not line.startswith(" "):
            return {}
        if line.startswith("  code:"):
            match = re.fullmatch(r"  code: (?:(?:([A-Z][A-Z0-9_]{0,63}))|'([A-Z][A-Z0-9_]{0,63})'|\"([A-Z][A-Z0-9_]{0,63})\")", line)
            if not match:
                return {}
            values.append(next(value for value in match.groups() if value))
        elif re.match(r"^  (?:<<:|[&*!])", line):
            return {}
    return {"error": {"code": values[0]}} if len(values) == 1 else {}

def bounded(value, budget):
    """Retain valid JSON, marking every output reduction explicitly."""
    if len(encoded(value)) <= budget:
        return value, False
    if isinstance(value, str):
        low, high = 0, len(value)
        while low < high:
            middle = (low + high + 1) // 2
            if len(encoded(value[:middle])) <= budget:
                low = middle
            else:
                high = middle - 1
        return value[:low], True
    if isinstance(value, list):
        result, used = [], 2
        for child in value:
            available = budget - used - bool(result)
            if available < 4:
                break
            item, cut = bounded(child, available)
            result.append(item)
            used += len(encoded(item)) + (1 if len(result) > 1 else 0)
            if cut:
                break
        return result, True
    if isinstance(value, dict):
        result, used = {}, 2
        for key, child in value.items():
            overhead = len(encoded(key)) + 1 + bool(result)
            available = budget - used - overhead
            if available < 4:
                break
            item, cut = bounded(child, available)
            result[key] = item
            used += overhead + len(encoded(item))
            if cut:
                break
        return result, True
    return None, True

def decode_output(capture, provider):
    output = capture["stdout"]
    default_format = "text" if provider in {"lookup/fetch", "lookup/subtitles"} else "auto"
    output_format = capture.get("stdout_format", default_format)
    if output_format not in {"json", "text", "auto"}:
        raise ValueError("stdout_format must be json, text or auto")
    if isinstance(output, str) and output.strip() and output_format != "text":
        try:
            return loads(output), False
        except (ValueError, RecursionError):
            return output, output_format == "json" or output.lstrip().startswith(("[", "{"))
    return output, False

def normalize(capture, budget=40000):
    if not isinstance(capture, dict):
        raise ValueError("capture must be a JSON object")
    provider = capture.get("provider")
    if not isinstance(provider, str) or not provider or len(provider) > 200:
        raise ValueError("provider must be a nonempty string of at most 200 characters")
    if "exit_code" not in capture or "stdout" not in capture:
        raise ValueError("capture must include actual exit_code and stdout")
    exit_code = capture["exit_code"]
    if exit_code is not None and (isinstance(exit_code, bool) or not isinstance(exit_code, int)):
        raise ValueError("exit_code must be an integer or null for an unknown outcome")
    evidence = capture.get("evidence_type", "metadata")
    if evidence not in EVIDENCE:
        raise ValueError("unsupported evidence_type")
    for key in ("empty_confirmed", "truncated", "outcome_unknown"):
        if key in capture and not isinstance(capture[key], bool):
            raise ValueError(f"{key} must be a boolean")
    missing = capture.get("missing_fields", [])
    if not isinstance(missing, list) or any(not isinstance(item, str) for item in missing):
        raise ValueError("missing_fields must be a string array")
    if len(missing) > 100 or any(len(item) > 200 for item in missing):
        raise ValueError("missing_fields exceeds the bounded metadata limit")
    for key in ("url", "access_url", "source", "author", "published_at", "fetched_at"):
        value = capture.get(key)
        limit = 8192 if key in {"url", "access_url"} else 1000
        if value is not None and (not isinstance(value, str) or len(value) > limit):
            raise ValueError(f"{key} must be null or a bounded string")
    metadata = error_metadata(capture.get("stderr", ""))
    result = {
        "status": "error", "provider": provider, "exit_code": exit_code,
        "evidence_type": evidence, "verification_scope": "capture_and_shape",
        **{key: capture.get(key) for key in
           ("url", "access_url", "source", "author", "published_at", "fetched_at")},
        "truncated": bool(capture.get("truncated") or metadata.get("truncated") is True),
        "missing_fields": list(dict.fromkeys(missing)), "error": None,
    }
    if provider == "lookup/fetch":
        for key, fallback in (("url", "final_url"), ("access_url", "requested_url"), ("fetched_at", "fetched_at")):
            value = metadata.get(fallback)
            if result[key] is None and isinstance(value, str) and len(value) <= (1000 if key == "fetched_at" else 8192):
                result[key] = value
    output, parse_failed = decode_output(capture, provider)
    error = metadata.get("error", {})
    code = error.get("code", "UNKNOWN") if isinstance(error, dict) else "UNKNOWN"
    code = code if isinstance(code, str) and CODE.fullmatch(code) else "UNKNOWN"
    opencli_envelope = provider.startswith("opencli/") and isinstance(output, dict) and "ok" in output
    envelope_failed = opencli_envelope and (
        output.get("ok") is not True or bool(output.get("error")) or output.get("status") == "error"
    )
    if opencli_envelope and not envelope_failed:
        if "data" in output:
            output = output["data"]
        else:
            parse_failed = True
    upstream_error = output.get("error") if isinstance(output, dict) else None
    upstream_failed = bool(upstream_error) or (isinstance(output, dict) and output.get("status") == "error")
    upstream_failed = upstream_failed or envelope_failed
    if code == "UNKNOWN" and isinstance(upstream_error, dict):
        upstream_code = upstream_error.get("code")
        if isinstance(upstream_code, str) and CODE.fullmatch(upstream_code):
            code = upstream_code
    unknown = exit_code is None or capture.get("outcome_unknown") is True or metadata.get("outcome_unknown") is True
    unknown = unknown or code in {"TIMEOUT", "COMMAND_TIMEOUT", "OUTCOME_UNKNOWN"}
    unknown = unknown or (isinstance(upstream_error, dict) and upstream_error.get("outcome") == "unknown")
    local_partial = (
        provider in {"lookup/fetch", "lookup/subtitles", "lookup/find-url"}
        and exit_code == 3 and metadata.get("status") == "partial"
        and bool(capture["stdout"])
    )
    if unknown or (exit_code != 0 and not local_partial) or error or upstream_failed or metadata.get("status") == "error":
        if not unknown and not result["truncated"] and code == "EMPTY_RESULT" and capture.get("empty_confirmed") is True:
            result.update(status="empty", items=[], empty_confirmed=True)
            return result
        scope = ("transport_profile" if code == "BROWSER_CONNECT" else
                 "site_profile" if code in {"AUTH_REQUIRED", "SECURITY_BLOCK"} else "site_action")
        result["error"] = {"code": "OUTCOME_UNKNOWN" if unknown else code,
                           "scope": scope, "outcome_unknown": unknown}
        return result
    if parse_failed:
        result["error"] = {"code": "PARSE", "scope": "site_action",
                           "outcome_unknown": False}
        return result
    if isinstance(output, dict):
        result["truncated"] = result["truncated"] or output.get("truncated") is True
        local_partial = local_partial or output.get("status") == "partial"
    confirmed_empty = capture.get("empty_confirmed") is True
    if provider == "lookup/find-url":
        if (not isinstance(output, dict)
                or not all(isinstance(output.get(key), list) for key in ("bookmarks", "history"))
                or not isinstance(output.get("more_available"), bool)
                or not isinstance(output.get("profile"), str)
                or any(not isinstance(row, dict) for key in ("bookmarks", "history") for row in output[key])):
            result["error"] = {"code": "PARSE", "scope": "site_action",
                               "outcome_unknown": False}
            return result
        result["profile"] = output["profile"]
        result["more_available"] = output["more_available"]
        if metadata.get("provider") == provider:
            confirmed_empty = confirmed_empty or (
                metadata.get("status") == "empty"
                and metadata.get("empty_confirmed") is True
            )
            local_partial = local_partial or metadata.get("status") == "partial"
        output = [{**row, "collection": key}
                  for key in ("bookmarks", "history") for row in output[key]]
    if isinstance(output, dict) and isinstance(output.get("items"), list):
        output = output["items"]
    if provider == "opencli/douyin/search" and isinstance(output, list):
        normalized = []
        for row in output:
            if isinstance(row, dict):
                row = dict(row)
                for field in ("plays", "comments", "shares"):
                    if row.get(field) == 0:
                        row[field] = None
                        if field not in result["missing_fields"]:
                            result["missing_fields"].append(field)
            normalized.append(row)
        output = normalized
    empty = output is None or output == [] or output == {} or (isinstance(output, str) and not output.strip())
    if empty:
        confirmed = confirmed_empty
        result.update(status="empty" if confirmed and not result["truncated"] and not local_partial else "partial", items=[],
                      empty_confirmed=confirmed)
        if not confirmed:
            result["missing_fields"].append("empty_confirmation")
        return result
    if isinstance(output, (bool, int, float)):
        result.update(status="partial", items=[])
        result["missing_fields"].append("content")
        return result
    if isinstance(output, dict):
        output = [output]
    output, reduced = bounded(output, budget)
    result["truncated"] = result["truncated"] or reduced
    key = "text" if isinstance(output, str) else "items"
    result[key] = output if key == "text" or isinstance(output, list) else [output]
    result["status"] = "partial" if (local_partial or result["truncated"] or result["missing_fields"]) else "ok"
    return result

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-output-chars", type=int, default=40000,
                        help="JSON content budget; envelope metadata is additional")
    args = parser.parse_args(argv)
    if not 64 <= args.max_output_chars <= MAX_INPUT_BYTES:
        parser.error("--max-output-chars must be between 64 and 5242880")
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        if len(raw) > MAX_INPUT_BYTES:
            raise ValueError("capture exceeds 5 MiB")
        result = normalize(loads(raw), args.max_output_chars)
        print(encoded(result))
        return 0
    except (ValueError, UnicodeError, TypeError, RecursionError) as exc:
        print(encoded({"status": "error", "error": {"code": "NORMALIZER_INPUT",
                      "message": str(exc)}}))
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
