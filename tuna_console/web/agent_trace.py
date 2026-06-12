from __future__ import annotations


def parse_agent_trace(trace: str | None) -> list[dict[str, str]]:
    entries = []
    for raw_line in (trace or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        timestamp = ""
        message = line
        if line.startswith("[") and "] " in line:
            timestamp, message = line[1:].split("] ", 1)
        kind, label, message = classify_trace_message(message)
        entries.append({"timestamp": timestamp, "message": message, "kind": kind, "label": label})
    return entries


def classify_trace_message(message: str) -> tuple[str, str, str]:
    if message.startswith("Tuning Agent message: "):
        return "message", "Message", message.removeprefix("Tuning Agent message: ")
    if message.startswith("tool start:") or message.startswith("tool end:"):
        return "tool", "Tool", message
    if "error" in message.lower() or "failed" in message.lower() or message.startswith("stderr:"):
        return "error", "Error", message
    if message.startswith(
        (
            "sent ",
            "starting ",
            "started ",
            "continuing ",
            "Operator Task",
            "Operator Notification",
            "no running",
            "terminated ",
        )
    ):
        return "supervisor", "Supervisor", message
    if message.startswith("Pi RPC") or message.startswith("agent ") or message.startswith("Tuning Agent requested"):
        return "rpc", "Pi RPC", message
    return "log", "Log", message
