#!/usr/bin/env python3
"""Clean local VTT/SRT cues; preserve timing and meaningful repeated speech."""
import argparse
import json
import re
import sys
from html import unescape
from pathlib import Path

MAX_INPUT_BYTES = 5 * 1024 * 1024
TIMESTAMP = r"(?:\d{2,}:)?[0-5]\d:[0-5]\d[.,]\d{3}"
TIMING = re.compile(rf"^({TIMESTAMP})\s+-->\s+({TIMESTAMP})(?:\s+.*)?$")
INLINE_TIME = re.compile(rf"<{TIMESTAMP}>")

# Remove only known VTT/SRT presentation tags. Technical literals such as
# vector<T> and <stdio.h> must survive; decode entities exactly once afterwards.
FORMAT_TAG = re.compile(
    r"</?(?:b|i|u|ruby|rt|c(?:\.[^\s<>/]+)?|v|lang|font)(?:[ \t]+[^<>]*)?\s*/?>", re.I
)
BREAK_TAG = re.compile(r"<br\s*/?>", re.I)

def milliseconds(value):
    parts = value.replace(",", ".").split(":")
    seconds, fraction = parts[-1].split(".")
    minutes = int(parts[-2])
    hours = int(parts[-3]) if len(parts) == 3 else 0
    return ((hours * 60 + minutes) * 60 + int(seconds)) * 1000 + int(fraction)

def timestamp(value):
    seconds, fraction = divmod(value, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}.{fraction:03}"

def parse_cues(source):
    cues, malformed = [], 0
    source = source.replace("\r\n", "\n").replace("\r", "\n")
    for block in re.split(r"\n[ \t]*\n", source.strip()):
        lines = block.splitlines()
        if not lines:
            continue
        if re.match(r"^(NOTE(?:\s|$)|STYLE$|REGION$)", lines[0]):
            continue
        timing_lines = [index for index, line in enumerate(lines) if "-->" in line]
        if not timing_lines:
            if not re.match(r"^WEBVTT(?:[ \t]|$)", lines[0]):
                malformed += 1
            continue
        if len(timing_lines) != 1:
            malformed += 1
            continue
        index = timing_lines[0]
        match = TIMING.fullmatch(lines[index].strip())
        if not match:
            malformed += 1
            continue
        start, end = map(milliseconds, match.groups())
        if end <= start:
            malformed += 1
            continue
        raw_text = "\n".join(lines[index + 1:])
        literal = INLINE_TIME.sub("", raw_text)
        literal = FORMAT_TAG.sub("", BREAK_TAG.sub(" ", literal))
        text = " ".join(unescape(literal).split())
        if not text:
            malformed += 1
            continue
        cues.append({"start": start, "end": end, "text": text,
                     "rolling": bool(INLINE_TIME.search(raw_text))})
    return cues, malformed

def clean_cues(cues):
    """Remove only adjacent rolling overlap; ordinary repeated cues survive."""
    output, previous = [], None
    for cue in cues:
        text = cue["text"]
        if previous is not None:
            same_interval = (cue["start"], cue["end"]) == (previous["start"], previous["end"])
            adjacent_rolling = (
                (cue["rolling"] or previous["rolling"])
                and previous["start"] <= cue["start"] <= previous["end"] + 250
            )
            if same_interval and text == previous["text"]:
                text = ""
            elif adjacent_rolling:
                old_words, new_words = previous["text"].split(), text.split()
                if len(old_words) > 1 or len(new_words) > 1:
                    for overlap in range(min(len(old_words), len(new_words)), 0, -1):
                        if old_words[-overlap:] == new_words[:overlap]:
                            text = " ".join(new_words[overlap:])
                            break
                elif len(previous["text"]) >= 2 and text.startswith(previous["text"]):
                    text = text[len(previous["text"]):].strip()
        if text:
            output.append({**cue, "text": text})
        previous = cue
    return output

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", help="Actual local VTT/SRT file; no network requests")
    parser.add_argument("--max-output-chars", type=int, default=40000)
    args = parser.parse_args(argv)
    if not 64 <= args.max_output_chars <= MAX_INPUT_BYTES:
        parser.error("--max-output-chars must be between 64 and 5242880")
    try:
        with Path(args.path).open("rb") as handle:
            raw = handle.read(MAX_INPUT_BYTES + 1)
        if len(raw) > MAX_INPUT_BYTES:
            raise ValueError("subtitle input exceeds 5 MiB")
        cues, malformed = parse_cues(raw.decode("utf-8-sig"))
        cleaned = clean_cues(cues)
        if not cleaned:
            raise ValueError("no usable timed subtitle cues")
        lines, size, limited = [], 0, False
        for cue in cleaned:
            line = f"[{timestamp(cue['start'])}] {cue['text']}"
            remaining = args.max_output_chars - size - 1
            if len(line) > remaining:
                if remaining > 20:
                    lines.append(line[:remaining])
                limited = True
                break
            lines.append(line)
            size += len(line) + 1
        if not lines:
            raise ValueError("output budget cannot retain a subtitle cue")
        partial = limited or malformed > 0
        print("\n".join(lines))
        print(json.dumps({
            "status": "partial" if partial else "ok",
            "evidence_type": "subtitles",
            "cue_count": len(cues),
            "emitted_cues": len(lines),
            "malformed_cues": malformed,
            "truncated": limited,
        }), file=sys.stderr)
        return 3 if partial else 0
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        print(json.dumps({"status": "error", "error": {
            "code": "SUBTITLE_INPUT", "message": str(exc)
        }}), file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
