#!/usr/bin/env python3
"""Fetch HTTP(S) text locally without forwarding the URL to another reader.

HTML uses readability-lxml + html2text when available, otherwise stdlib.
Plain text and Markdown are preserved as text. JavaScript is not executed.
Exit codes: 0 complete output, 1 failure, 2 invalid arguments, 3 bounded preview.
Exactly one JSON status object is written to stderr after a valid invocation.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from email.message import Message
from html.parser import HTMLParser
from itertools import groupby
import json
import re
import sys
from typing import NamedTuple
import urllib.error
import urllib.request
from urllib.parse import urlsplit


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 12_0) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
)
FETCH_TIMEOUT_SECS = 20
MAX_RESPONSE_BYTES = 5_000_000
DEFAULT_MAX_OUTPUT_CHARS = 40_000
HTML_TYPES = {"text/html", "application/xhtml+xml"}
TEXT_TYPES = {"text/plain", "text/markdown"}


class FetchedPage(NamedTuple):
    text: str
    media_type: str
    final_url: str


class ExtractedContent(NamedTuple):
    text: str
    title: str = ""


class FetchFailure(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def validate_url(url: str) -> None:
    if any(ord(char) < 32 or ord(char) == 127 for char in url):
        raise FetchFailure("INVALID_URL", "URL contains control characters")
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise FetchFailure("INVALID_URL", "only HTTP(S) URLs are supported")
    if parsed.username is not None or parsed.password is not None:
        raise FetchFailure("CREDENTIAL_URL", "URLs containing credentials are not supported")


class SourceRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_page(url: str) -> FetchedPage:
    validate_url(url)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    opener = urllib.request.build_opener(SourceRedirectHandler())
    with opener.open(req, timeout=FETCH_TIMEOUT_SECS) as resp:
        content_type = Message()
        content_type["Content-Type"] = resp.headers.get("Content-Type", "")
        media_type = content_type.get_content_type().lower()
        if not resp.headers.get("Content-Type") or media_type not in HTML_TYPES | TEXT_TYPES:
            raise FetchFailure("UNSUPPORTED_CONTENT_TYPE", "response is not a supported text type")
        raw = resp.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise FetchFailure("RESPONSE_LIMIT", "response exceeds the 5 MB extraction limit")
        final_url = resp.geturl()
        validate_url(final_url)
    charset = content_type.get_content_charset()
    if not charset and media_type in HTML_TYPES:
        # HTML often declares its encoding in a meta tag instead of the header.
        match = re.search(rb"<meta\b[^>]*\bcharset\s*=\s*[\"']?\s*([\w-]+)", raw[:4096], re.I)
        if match:
            charset = match.group(1).decode("ascii")
    charset = charset or "utf-8"
    if charset.lower().replace("_", "-") in ("utf-8", "utf8"):
        charset = "utf-8-sig"
    try:
        text = raw.decode(charset)
    except (LookupError, UnicodeDecodeError) as exc:
        raise FetchFailure("DECODING_FAILED", "response encoding could not be decoded") from exc
    return FetchedPage(text, media_type, final_url)


def fetch_html(url: str) -> str:
    """Compatibility helper for callers that only need the fetched text."""
    return fetch_page(url).text


def extract_with_readability(html: str, url: str) -> ExtractedContent | None:
    try:
        from readability import Document  # type: ignore
        import html2text  # type: ignore
    except ImportError:
        return None
    doc = Document(html, url=url)
    cleaned_html = doc.summary(html_partial=True)
    converter = html2text.HTML2Text()
    converter.body_width = 0
    converter.baseurl = url
    converter.unicode_snob = True
    converter.ignore_links = False
    converter.ignore_images = False
    body = converter.handle(cleaned_html).strip()
    if not body:
        return None
    return ExtractedContent(body, " ".join((doc.short_title() or "").split()))


class _StdlibStripper(HTMLParser):
    """Simple deterministic HTML text fallback; no scripts or network access."""

    DROP_TAGS = {"script", "style", "nav", "footer", "aside", "noscript", "form"}
    BLOCK_TAGS = {
        "p", "div", "section", "article", "li", "ul", "ol",
        "h1", "h2", "h3", "h4", "h5", "h6", "br", "tr", "td", "th",
    }

    def __init__(self) -> None:
        super().__init__()
        self._buf: list[tuple[bool, str]] = []
        self._drop_depth = 0
        self._title = ""
        self._in_title = False
        self._in_pre = False

    def _append(self, text: str) -> None:
        self._buf.append((self._in_pre, text))

    def handle_starttag(self, tag, attrs):
        if tag in self.DROP_TAGS:
            self._drop_depth += 1
        elif tag == "title":
            self._in_title = True
        elif tag == "pre" and not self._drop_depth:
            self._append("\n")
            self._in_pre = True
        elif tag in self.BLOCK_TAGS and not self._drop_depth:
            self._append("\n")

    def handle_endtag(self, tag):
        if tag in self.DROP_TAGS:
            self._drop_depth = max(0, self._drop_depth - 1)
        elif tag == "title":
            self._in_title = False
        elif tag == "pre" and not self._drop_depth:
            self._in_pre = False
            self._append("\n")
        elif tag in self.BLOCK_TAGS and not self._drop_depth:
            self._append("\n")

    def handle_data(self, data):
        if self._drop_depth:
            return
        if self._in_title:
            self._title += data
        else:
            self._append(data)

    def text(self) -> str:
        segments = []
        for preserve, group in groupby(self._buf, key=lambda part: part[0]):
            text = "".join(part[1] for part in group)
            if not preserve:
                lines = [line.strip() for line in text.splitlines()]
                text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
            if text:
                segments.append(text)
        return "\n\n".join(segments)


def extract_with_stdlib(html: str, url: str) -> ExtractedContent:
    parser = _StdlibStripper()
    parser.feed(html)
    parser.close()
    return ExtractedContent(parser.text(), " ".join(parser._title.split()))


def extract_page(page: FetchedPage, prefer: str) -> tuple[ExtractedContent, str]:
    if page.media_type in TEXT_TYPES:
        return ExtractedContent(page.text.strip()), "text"
    if prefer in ("auto", "readability"):
        try:
            result = extract_with_readability(page.text, page.final_url)
        except Exception as exc:
            if prefer == "readability":
                raise FetchFailure("EXTRACTION_FAILED", "readability could not extract this page") from exc
            result = None
        if result is not None:
            return result, "readability"
        if prefer == "readability":
            raise FetchFailure("EXTRACTOR_UNAVAILABLE", "readability dependencies or usable content are unavailable")
    return extract_with_stdlib(page.text, page.final_url), "stdlib"


def output_budget(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("output budget must be an integer") from exc
    if not 256 <= number <= MAX_RESPONSE_BYTES:
        raise argparse.ArgumentTypeError("output budget must be between 256 and 5000000 characters")
    return number


def status(**fields) -> None:
    print(json.dumps({"provider": "lookup/fetch", **fields}, ensure_ascii=False), file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="HTTP(S) URL to fetch")
    parser.add_argument("--prefer", choices=("auto", "readability", "stdlib"), default="auto")
    parser.add_argument("--max-output-chars", "--max-chars", type=output_budget,
                        default=DEFAULT_MAX_OUTPUT_CHARS, help="stdout budget, including source and truncation marker")
    args = parser.parse_args()
    try:
        page = fetch_page(args.url)
        fetched_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        content, used = extract_page(page, args.prefer)
        if not content.text.strip():
            raise FetchFailure("EMPTY_CONTENT", "no text content was extracted")
        header = f"# {content.title}\n\n" if content.title else ""
        rendered = f"{header}> Source: {page.final_url}\n\n{content.text}\n"
        truncated = len(rendered) > args.max_output_chars
        if truncated:
            marker = "\n\n[TRUNCATED: bounded preview; increase --max-output-chars to retrieve more.]\n"
            rendered = rendered[:args.max_output_chars - len(marker)].rstrip() + marker
        status(status="partial" if truncated else "ok", extractor=used,
               media_type=page.media_type, redirected=page.final_url != args.url,
               requested_url=args.url, final_url=page.final_url, fetched_at=fetched_at,
               truncated=truncated, content_chars=len(content.text), output_chars=len(rendered))
        sys.stdout.write(rendered)
        return 3 if truncated else 0
    except Exception as exc:
        if isinstance(exc, FetchFailure):
            code, message = exc.code, str(exc)
        elif isinstance(exc, urllib.error.HTTPError):
            code, message = "HTTP_ERROR", f"source returned HTTP {exc.code}"
        elif isinstance(exc, (TimeoutError, urllib.error.URLError, OSError)):
            code, message = "FETCH_FAILED", "source request failed or timed out"
        else:
            code, message = "EXTRACTION_FAILED", "local extraction failed"
        # Do not log exception strings: urllib errors can include signed URLs.
        status(status="error", truncated=False, error={"code": code, "message": message})
        return 1


if __name__ == "__main__":
    sys.exit(main())
