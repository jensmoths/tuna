from __future__ import annotations

from typing import Any


def status_for_tool(event: dict[str, Any]) -> str:
    args = event.get("args") or {}
    text = " ".join(str(value) for value in args.values()).lower()
    if "blackbox transfer" in text or "msc_raw" in text:
        return "Transferring Blackbox Log"
    if " log import" in text:
        return "Importing Blackbox Log"
    if " analysis decode" in text or " decode-analyze" in text:
        return "Decoding Blackbox Log"
    if " analysis analyze" in text:
        return "Analyzing Blackbox Log"
    if " diagnosis record" in text:
        return "Recording Diagnosis"
    if " pending-writes" in text or " update apply" in text or "record-write-failure" in text:
        return "Writing approved Tune Update through FCS"
    if " task" in text:
        return "Waiting for Operator Task"
    if " loop" in text:
        return "Creating or resuming Loop"
    if " build" in text:
        return "Confirming Build"
    return "Inspecting Tuna state"


def trace_for_event(event: dict[str, Any], *, verbose: bool) -> str | None:
    event_type = str(event.get("type") or "event")
    if event_type == "message_update":
        return None
    if event_type == "tool_execution_update" and not verbose:
        return None
    if event_type == "message_start":
        return None
    if event_type == "message_end":
        text = message_text(event.get("message"))
        if text:
            return f"Tuning Agent message: {text[:1000]}"
        return "Tuning Agent message completed"
    if event_type == "tool_execution_start":
        args = event.get("args") or {}
        command = " ".join(str(value) for value in args.values())[:500]
        return f"tool start: {command}"
    if event_type == "tool_execution_end":
        success = event.get("success")
        return f"tool end: success={success}"
    if event_type == "agent_start":
        return "agent started responding"
    if event_type == "agent_end":
        return "agent finished responding"
    if event_type == "extension_ui_request":
        return "Tuning Agent requested Operator input"
    if event_type == "response":
        return f"Pi RPC response: command={event.get('command')} success={event.get('success')}"
    if event_type in {"extension_error", "auto_retry_end"}:
        return f"{event_type}: success={event.get('success')}"
    return f"Pi RPC event: {event_type}"


def message_text(message: Any) -> str:
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
            parts.append(item["text"].strip())
    return "\n".join(part for part in parts if part)
