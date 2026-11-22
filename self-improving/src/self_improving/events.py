"""Normalize multi-agent Hook payloads into one event shape."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


SUPPORTED_EVENTS = frozenset(
    {"SessionStart", "UserPromptSubmit", "PreInvocation", "PreToolUse", "PostToolUse", "Stop"}
)


@dataclass(frozen=True)
class HookEvent:
    platform: str
    event: str
    session_id: str = ""
    source: str = ""
    cwd: str = ""
    prompt: str = ""
    tool_name: str = ""
    tool_input: dict[str, Any] = field(default_factory=dict)
    tool_output: str = ""
    exit_status: int | None = None
    failed: bool = False
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


def _prompt_text(platform: str, payload: dict[str, Any]) -> str:
    prompt = payload.get("prompt")
    if isinstance(prompt, list):
        parts = [
            str(part.get("text") or "")
            for part in prompt
            if isinstance(part, dict) and part.get("type") == "text" and part.get("text")
        ]
        return "\n".join(parts)
    if isinstance(prompt, str):
        return prompt
    if platform == "claude" and isinstance(payload.get("user_prompt"), str):
        return payload["user_prompt"]
    if platform == "antigravity" and isinstance(payload.get("lastUserInput"), str):
        return payload["lastUserInput"]
    return ""


def _tool_fields(platform: str, payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if platform == "antigravity" and isinstance(payload.get("toolCall"), dict):
        call = payload["toolCall"]
        raw_args = call.get("args")
        tool_input = dict(raw_args) if isinstance(raw_args, dict) else {}
        if "command" not in tool_input and isinstance(tool_input.get("CommandLine"), str):
            tool_input["command"] = tool_input["CommandLine"]
        if "file_path" not in tool_input:
            for key in ("Path", "TargetFile", "path", "target_file"):
                if isinstance(tool_input.get(key), str) and tool_input[key]:
                    tool_input["file_path"] = tool_input[key]
                    break
        return str(call.get("name") or ""), tool_input
    raw_input = payload.get("tool_input")
    if raw_input is None:
        raw_input = payload.get("toolInput")
    if raw_input is None:
        raw_input = payload.get("tool")
    tool_input = dict(raw_input) if isinstance(raw_input, dict) else {}
    tool_name = str(payload.get("tool_name") or payload.get("toolName") or payload.get("tool") or "")
    return tool_name, tool_input


def normalize(platform: str, declared_event: str, payload: dict[str, Any]) -> HookEvent:
    if declared_event not in SUPPORTED_EVENTS:
        raise ValueError(f"unsupported Hook event: {declared_event}")
    event = "UserPromptSubmit" if (platform == "antigravity" and declared_event == "PreInvocation") else declared_event
    session_id = str(
        payload.get("session_id")
        or (payload.get("conversationId") if platform == "antigravity" else "")
        or payload.get("sessionId")
        or ""
    )
    cwd = str(payload.get("cwd") or "")
    if not cwd and platform == "antigravity":
        workspaces = payload.get("workspacePaths")
        if isinstance(workspaces, list) and workspaces and isinstance(workspaces[0], str):
            cwd = workspaces[0]
    prompt = _prompt_text(platform, payload)
    tool_name, tool_input = _tool_fields(platform, payload)
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
    structured_failure = bool(payload.get("is_error") or payload.get("interrupted"))
    if isinstance(response, dict):
        structured_failure = structured_failure or bool(
            response.get("isError") or response.get("is_error") or response.get("interrupted")
        )
        # Some clients put an error object/string next to otherwise missing exit status.
        structured_failure = structured_failure or (
            exit_status is None and response.get("error") not in (None, "", False)
        )
    return HookEvent(
        platform=platform,
        event=event,
        session_id=session_id,
        source=str(payload.get("source") or ""),
        cwd=cwd,
        prompt=prompt,
        tool_name=tool_name,
        tool_input=tool_input,
        tool_output=_output_text(response),
        exit_status=exit_status,
        failed=(exit_status not in (None, 0)) or structured_failure,
    )
