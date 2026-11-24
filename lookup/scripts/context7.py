#!/usr/bin/env python3
"""Query Context7 v3 search API using Python stdlib only.

Reads CONTEXT7_API_KEY from the process environment or
${XDG_CONFIG_HOME:-$HOME/.config}/lookup/context7.env when present, and falls
back to anonymous mode when no key is configured. Never prints or echoes keys.

Exit codes: 0 ok/empty, 1 request/auth/rate-limit error, 2 invalid arguments,
3 bounded preview (truncated stdout).
Exactly one JSON status object is written to stderr after a valid invocation.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_BASE_URL = "https://context7.com"
DEFAULT_TIMEOUT_SECS = 20
DEFAULT_MAX_OUTPUT_CHARS = 40_000
MAX_RESPONSE_BYTES = 5_000_000
MAX_LIBRARIES = 4
USER_AGENT = "lookup-context7/1.0"


class Context7Error(Exception):
    def __init__(self, code: str, message: str, extra: dict | None = None):
        super().__init__(message)
        self.code = code
        self.extra = extra or {}


def default_env_file() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME", "").strip()
    base = Path(xdg) if xdg else (Path.home() / ".config")
    return base / "lookup" / "context7.env"


def validate_base_url(base_url: str) -> str:
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in base_url):
        raise Context7Error("INVALID_URL", "base URL contains control characters")
    parsed = urllib.parse.urlsplit(base_url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise Context7Error("INVALID_URL", "only HTTP(S) base URLs are supported")
    if parsed.username is not None or parsed.password is not None:
        raise Context7Error("CREDENTIAL_URL", "base URL must not contain credentials")
    return base_url.rstrip("/")


def load_api_key(env_file: Path | None, no_key: bool) -> tuple[str | None, str]:
    if no_key:
        return None, "anonymous"
    env_key = os.environ.get("CONTEXT7_API_KEY", "").strip()
    if env_key:
        return env_key, "env"
    target = env_file or default_env_file()
    if target.is_file():
        try:
            with target.open("r", encoding="utf-8") as handle:
                for raw_line in handle:
                    line = raw_line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if line.startswith("export "):
                        line = line[len("export "):].strip()
                    if "=" not in line:
                        continue
                    name, value = line.split("=", 1)
                    if name.strip() == "CONTEXT7_API_KEY":
                        cleaned = value.strip()
                        if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in ("'", '"'):
                            cleaned = cleaned[1:-1].strip()
                        if cleaned:
                            return cleaned, "env_file"
        except OSError as exc:
            raise Context7Error("ENV_FILE_UNREADABLE", "could not read context7 env file") from exc
    return None, "anonymous"


def parse_int_header(headers, name: str) -> int | None:
    raw = headers.get(name)
    if raw is None:
        return None
    try:
        return int(raw.strip())
    except ValueError:
        return None


def extract_headers_meta(headers) -> dict:
    meta: dict = {}
    if not headers:
        return meta
    quota_tier = headers.get("context7-quota-tier")
    if quota_tier:
        meta["quota_tier"] = quota_tier.strip()
    limit = parse_int_header(headers, "ratelimit-limit")
    if limit is not None:
        meta["ratelimit_limit"] = limit
    remaining = parse_int_header(headers, "ratelimit-remaining")
    if remaining is not None:
        meta["ratelimit_remaining"] = remaining
    reset = parse_int_header(headers, "ratelimit-reset")
    if reset is not None:
        meta["ratelimit_reset"] = reset
    retry_after = headers.get("retry-after")
    if retry_after:
        meta["retry_after"] = retry_after.strip()
    for header_name, field_name in (
        ("x-context7-search-status", "search_status"),
        ("x-context7-search-version", "search_version"),
        ("x-context7-search-reason", "search_reason"),
    ):
        value = headers.get(header_name)
        if value:
            meta[field_name] = value.strip()
    return meta


def extract_libraries_from_json(payload: object) -> list[str]:
    if not isinstance(payload, dict):
        return []
    seen: list[str] = []
    for bucket in ("codeSnippets", "infoSnippets"):
        items = payload.get(bucket)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            lib_id = item.get("libraryId")
            if isinstance(lib_id, str) and lib_id and lib_id not in seen:
                seen.append(lib_id)
                if len(seen) >= 8:
                    return seen
    return seen


def extract_sources_from_txt(text: str) -> list[str]:
    seen: list[str] = []
    for match in re.finditer(r"^(?:Source|Library):\s*(\S+)", text, re.M):
        value = match.group(1).strip()
        if value and value not in seen:
            seen.append(value)
            if len(seen) >= 8:
                break
    return seen


def build_request_url(
    base_url: str,
    query: str,
    libraries: list[str],
    version: str | None,
    language: str | None,
    output_format: str,
) -> str:
    params: list[tuple[str, str]] = [("query", query), ("type", output_format)]
    for lib in libraries:
        params.append(("library", lib))
    if version:
        params.append(("version", version))
    if language:
        params.append(("language", language))
    return f"{base_url}/api/v3/search?{urllib.parse.urlencode(params)}"


def emit_status(**fields) -> None:
    payload = {"provider": "lookup/context7", **fields}
    sys.stderr.write(json.dumps(payload, ensure_ascii=False) + "\n")


def positive_int(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if value < 256:
        raise argparse.ArgumentTypeError("must be at least 256")
    return value


def positive_timeout(raw: str) -> float:
    try:
        value = float(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a number") from exc
    if value <= 0 or value > 120:
        raise argparse.ArgumentTypeError("must be between 0 and 120 seconds")
    return value


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Search Context7 library documentation via /api/v3/search."
    )
    parser.add_argument("query", help="Natural-language technical question")
    parser.add_argument(
        "--library",
        action="append",
        default=[],
        help="Library name or Context7 ID (repeatable up to 4 times)",
    )
    parser.add_argument(
        "--version",
        default=None,
        help="Target library version (requires at least one --library)",
    )
    parser.add_argument(
        "--language",
        default=None,
        help="Preferred programming language for examples",
    )
    parser.add_argument(
        "--format",
        "--type",
        dest="output_format",
        choices=("txt", "json"),
        default="txt",
        help="Response format (default: txt)",
    )
    parser.add_argument(
        "--max-output-chars",
        "--max-chars",
        type=positive_int,
        default=DEFAULT_MAX_OUTPUT_CHARS,
        help="Maximum stdout characters before bounded truncation",
    )
    parser.add_argument(
        "--timeout",
        type=positive_timeout,
        default=DEFAULT_TIMEOUT_SECS,
        help="HTTP timeout in seconds (default: 20)",
    )
    parser.add_argument(
        "--env-file",
        default=None,
        help="Path to env file containing CONTEXT7_API_KEY",
    )
    parser.add_argument(
        "--no-key",
        action="store_true",
        help="Force anonymous mode without reading CONTEXT7_API_KEY",
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args(argv)

    args.query = args.query.strip()
    if not args.query:
        parser.error("query must not be empty")
    args.library = [lib.strip() for lib in args.library if lib.strip()]
    if len(args.library) > MAX_LIBRARIES:
        parser.error(f"at most {MAX_LIBRARIES} --library hints are supported")
    if args.version is not None:
        args.version = args.version.strip() or None
    if args.version and not args.library:
        parser.error("--version requires at least one --library")
    if args.language is not None:
        args.language = args.language.strip() or None
    return args


def query_context7(args: argparse.Namespace) -> int:
    auth_mode = "anonymous"
    key_source = "none"
    try:
        base_url = validate_base_url(args.base_url)
        env_path = Path(args.env_file).expanduser() if args.env_file else None
        api_key, key_source = load_api_key(env_path, args.no_key)
        auth_mode = "api_key" if api_key else "anonymous"
        request_url = build_request_url(
            base_url=base_url,
            query=args.query,
            libraries=args.library,
            version=args.version,
            language=args.language,
            output_format=args.output_format,
        )
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json" if args.output_format == "json" else "text/plain, application/json",
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        req = urllib.request.Request(request_url, headers=headers, method="GET")
        fetched_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        with urllib.request.urlopen(req, timeout=args.timeout) as resp:
            raw = resp.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise Context7Error("RESPONSE_LIMIT", "response exceeds the 5 MB safety limit")
            resp_headers = resp.headers
        text = raw.decode("utf-8", errors="replace")
        header_meta = extract_headers_meta(resp_headers)
        sources: list[str] = []
        if args.output_format == "json":
            try:
                parsed_body = json.loads(text)
            except ValueError as exc:
                raise Context7Error("INVALID_JSON", "service returned malformed JSON") from exc
            sources = extract_libraries_from_json(parsed_body)
            rendered = json.dumps(parsed_body, ensure_ascii=False, indent=2) + "\n"
        else:
            sources = extract_sources_from_txt(text)
            rendered = text if text.endswith("\n") else text + "\n"

        if not rendered.strip():
            emit_status(
                status="empty",
                auth_mode=auth_mode,
                key_source=key_source,
                format=args.output_format,
                fetched_at=fetched_at,
                truncated=False,
                **header_meta,
            )
            return 0

        truncated = len(rendered) > args.max_output_chars
        if truncated:
            if args.output_format == "json":
                # Preserve strict non-JSON warning on stderr and bounded preview on stdout.
                marker = "\n[TRUNCATED: bounded preview; rerun with larger --max-output-chars or --format txt.]\n"
            else:
                marker = "\n\n[TRUNCATED: bounded preview; increase --max-output-chars to retrieve more.]\n"
            rendered = rendered[: args.max_output_chars - len(marker)].rstrip() + marker

        status_fields = {
            "status": "partial" if truncated else "ok",
            "auth_mode": auth_mode,
            "key_source": key_source,
            "format": args.output_format,
            "fetched_at": fetched_at,
            "truncated": truncated,
            "output_chars": len(rendered),
            **header_meta,
        }
        if sources:
            status_fields["sources"] = sources
        emit_status(**status_fields)
        sys.stdout.write(rendered)
        return 3 if truncated else 0

    except urllib.error.HTTPError as exc:
        header_meta = extract_headers_meta(exc.headers)
        detail = None
        try:
            err_raw = exc.read(4096)
            err_json = json.loads(err_raw.decode("utf-8", errors="replace"))
            if isinstance(err_json, dict):
                err_msg = err_json.get("message") or err_json.get("error")
                if isinstance(err_msg, str) and err_msg.strip():
                    detail = err_msg.strip()[:200]
        except Exception:
            detail = None
        if exc.code == 404:
            emit_status(
                status="empty",
                auth_mode=auth_mode,
                key_source=key_source,
                http_status=404,
                truncated=False,
                **header_meta,
            )
            return 0
        if exc.code == 400:
            code = "INVALID_REQUEST"
            message = detail or "invalid request parameters (HTTP 400)"
        elif exc.code in (401, 403):
            code = "AUTH_ERROR"
            message = f"authentication or policy rejected (HTTP {exc.code})"
        elif exc.code == 429:
            code = "RATE_LIMITED"
            message = "Context7 rate limit or quota exceeded (HTTP 429)"
        elif exc.code == 503:
            code = "SEARCH_UNAVAILABLE"
            message = "Context7 search temporarily unavailable (HTTP 503)"
        else:
            code = "HTTP_ERROR"
            message = detail or f"Context7 returned HTTP {exc.code}"
        emit_status(
            status="error",
            auth_mode=auth_mode,
            key_source=key_source,
            http_status=exc.code,
            truncated=False,
            **header_meta,
            error={"code": code, "message": message},
        )
        return 1
    except Context7Error as exc:
        emit_status(
            status="error",
            auth_mode=auth_mode,
            key_source=key_source,
            truncated=False,
            **exc.extra,
            error={"code": exc.code, "message": str(exc)},
        )
        return 1
    except (TimeoutError, urllib.error.URLError, OSError):
        emit_status(
            status="error",
            auth_mode=auth_mode,
            key_source=key_source,
            truncated=False,
            error={"code": "REQUEST_FAILED", "message": "Context7 request failed or timed out"},
        )
        return 1


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    return query_context7(args)


if __name__ == "__main__":
    sys.exit(main())
