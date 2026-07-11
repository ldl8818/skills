"""Normalize Claude Code and Codex Hook payloads into one event shape."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


SUPPORTED_EVENTS = frozenset({"SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"})


@dataclass(frozen=True)
class HookEvent:
    platform: str
    event: str
    session_id: str = ""
    cwd: str = ""
    prompt: str = ""
    tool_name: str = ""
    tool_input: dict[str, Any] = field(default_factory=dict)
    tool_output: str = ""
    exit_status: int | None = None
    trust_level: str = "untrusted"


def _output_text(response: object) -> str:
    if isinstance(response, str):
        return response
    if not isinstance(response, dict):
        return ""
    parts: list[str] = []
    for key in ("stderr", "stdout", "output", "content"):
        value = response.get(key)
        if value:
            parts.append(str(value))
    if response.get("interrupted"):
        parts.append("interrupted")
    return "\n".join(parts)


def normalize(platform: str, declared_event: str, payload: dict[str, Any]) -> HookEvent:
    if declared_event not in SUPPORTED_EVENTS:
        raise ValueError(f"unsupported Hook event: {declared_event}")
    event = declared_event
    prompt = payload.get("prompt")
    if not isinstance(prompt, str) and platform == "claude":
        prompt = payload.get("user_prompt")
    if not isinstance(prompt, str):
        prompt = ""
    tool_input = payload.get("tool_input") or payload.get("tool") or {}
    if not isinstance(tool_input, dict):
        tool_input = {}
    response = payload.get("tool_response")
    if response is None:
        response = payload.get("tool_output")
    status = payload.get("exit_status")
    if status is None and isinstance(response, dict):
        status = response.get("exit_code")
    try:
        exit_status = int(status) if status is not None else None
    except (TypeError, ValueError):
        exit_status = None
    return HookEvent(
        platform=platform,
        event=event,
        session_id=str(payload.get("session_id") or ""),
        cwd=str(payload.get("cwd") or ""),
        prompt=prompt,
        tool_name=str(payload.get("tool_name") or payload.get("tool") or ""),
        tool_input=tool_input,
        tool_output=_output_text(response),
        exit_status=exit_status,
    )
