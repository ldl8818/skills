#!/usr/bin/env python3
"""One bounded, real Exa keyless search; Doubao configuration only, never billed probes."""
import json
import re
import shutil
import subprocess
import sys
import time
from urllib.parse import urlsplit

EXA_URL = "https://mcp.exa.ai/mcp"


class CheckError(Exception):
    pass


def sources_from(payload):
    metadata = payload.get("_meta") if isinstance(payload, dict) else None
    if isinstance(metadata, dict) and metadata.get("ai.exa/rateLimited") is True:
        raise CheckError("EXA_RATE_LIMITED")
    if (not isinstance(payload, dict) or payload.get("isError") is True
            or payload.get("error") or payload.get("ok") is False):
        raise CheckError("SEARCH_ERROR")
    blocks = payload.get("content")
    if not isinstance(blocks, list):
        raise CheckError("SEARCH_CONTENT_INVALID")
    text = "\n".join(b.get("text", "") for b in blocks
                     if isinstance(b, dict) and b.get("type") == "text"
                     and isinstance(b.get("text"), str))
    sources = []
    for block in re.split(r"(?:^|\n)Title: ", text)[1:]:
        match = re.search(r"^URL: (https?://\S+)\s*$", block, re.M)
        if not match or not re.search(r"^Highlights:\s*\n\S", block, re.M):
            continue
        try:
            url = urlsplit(match[1])
        except ValueError:
            continue
        if (url.hostname == "modelcontextprotocol.io" and not url.username
                and not url.password and "Model Context Protocol" in block):
            title = block.splitlines()[0].strip()
            sources.append({"title": None if title == "N/A" else title, "url": match[1]})
    if not sources:
        raise CheckError("SEARCH_EVIDENCE_MISSING")
    return sources[:3]


def check():
    report = {"scope": "exa_keyless_search", "exa": {"status": "error"},
              "doubao": {"status": "not_checked", "live_query": "not_run"}}
    deadline = time.monotonic() + 45
    phase = "config"

    def call(*args, timeout=15):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise CheckError("CHECK_DEADLINE")
        return subprocess.run(["mcporter", *args], capture_output=True, text=True,
                              timeout=min(timeout, remaining), check=False)

    def data(result, code):
        if result.returncode != 0:
            raise CheckError(code)
        try:
            return json.loads(result.stdout)
        except ValueError:
            raise CheckError(code) from None

    try:
        if not shutil.which("mcporter"):
            raise CheckError("MCPORTER_UNAVAILABLE")
        config = data(call("config", "get", "exa", "--json"), "EXA_CONFIG_UNAVAILABLE")
        # A paid/keyed profile must not be silently used by the free search check.
        headers = config.get("headers", {}) if isinstance(config, dict) else {}
        if (not isinstance(config, dict) or config.get("transport") != "http"
                or config.get("baseUrl") != EXA_URL or not isinstance(headers, dict)
                or any(k.lower() != "accept" or v != "application/json, text/event-stream"
                       for k, v in headers.items())
                or config.get("auth") or config.get("env")):
            raise CheckError("EXA_KEYLESS_CONFIG_REQUIRED")
        doubao = call("config", "get", "huashu-doubao-search", "--json")
        report["doubao"]["status"] = ("configured_not_tested" if doubao.returncode == 0
                                       else "configuration_unavailable")
        phase = "discovery"
        listing = data(call("list", "exa", "--schema", "--json", "--no-oauth",
                            "--timeout", "15000"), "EXA_DISCOVERY_FAILED")
        if not isinstance(listing, dict) or listing.get("status") != "ok":
            raise CheckError("EXA_DISCOVERY_FAILED")
        tools = listing.get("tools", []) if isinstance(listing, dict) else []
        tool = next((t for t in tools if isinstance(t, dict)
                     and t.get("name") == "web_search_exa"), {})
        schema = tool.get("inputSchema", {})
        required = schema.get("required", [])
        arguments = {"query": "Model Context Protocol official specification",
                     "objective": "Find the official Model Context Protocol specification; "
                                  "return original modelcontextprotocol.io sources and their content.",
                     "numResults": 3}
        if (not isinstance(schema, dict) or not isinstance(required, list)
                or not {"query", "objective", "numResults"}.issubset(schema.get("properties", {}))
                or not set(required).issubset(arguments)):
            raise CheckError("EXA_SCHEMA_CHANGED")
        phase = "search"
        result = data(call("call", "exa.web_search_exa", "--args", json.dumps(arguments),
                           "--no-oauth", "--timeout", "30000", "--output", "json", timeout=30),
                      "EXA_SEARCH_FAILED")
        report["exa"] = {"status": "ok", "sources": sources_from(result),
                         "verification": "nonempty_related_content_and_original_urls"}
        report["status"] = "ok"
        return report, 0
    except subprocess.TimeoutExpired:
        code = "SEARCH_OUTCOME_UNKNOWN" if phase == "search" else "CHECK_TIMEOUT"
    except OSError:
        code = "MCPORTER_START_FAILED"
    except CheckError as error:
        code = str(error)
    except (TypeError, AttributeError):
        code = "EXA_SCHEMA_CHANGED"
    report["status"] = "error"
    report["phase"] = phase
    report["exa"]["error"] = code
    report["exa"]["outcome_unknown"] = code == "SEARCH_OUTCOME_UNKNOWN"
    return report, 1


if __name__ == "__main__":
    if sys.argv[1:]:
        print("Usage: python3 scripts/search-check.py (performs one real free search)", file=sys.stderr)
        sys.exit(2)
    result, exit_code = check()
    print(json.dumps(result, ensure_ascii=False))
    sys.exit(exit_code)
