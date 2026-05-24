from __future__ import annotations

from pathlib import Path

from .metadata import BlackboxMetadata

_HEADER_LIMIT = 256 * 1024


def _parse_csv_ints(value: str) -> list[int] | None:
    try:
        return [int(part.strip()) for part in value.split(",") if part.strip()]
    except ValueError:
        return None


def parse_blackbox_metadata(path: str | Path) -> BlackboxMetadata:
    data = Path(path).read_bytes()[:_HEADER_LIMIT]
    text = data.decode("latin1", errors="replace")
    headers: dict[str, str] = {}
    warnings: list[str] = []

    for line in text.splitlines():
        if not line.startswith("H "):
            if headers:
                break
            continue
        body = line[2:]
        if ":" not in body:
            warnings.append(f"Malformed header line: {body[:80]}")
            continue
        key, value = body.split(":", 1)
        headers[key.strip()] = value.strip()

    if not headers:
        return BlackboxMetadata("unreadable", {}, ["No Blackbox header lines found"])

    metadata: dict[str, object] = {
        "headers": headers,
        "product": headers.get("Product"),
        "data_version": headers.get("Data version"),
        "firmware_type": headers.get("Firmware type"),
        "firmware_revision": headers.get("Firmware revision"),
        "firmware_date": headers.get("Firmware date"),
        "craft_name": headers.get("Craft name"),
        "looptime": headers.get("looptime"),
        "fields": {},
        "pids": {},
    }

    for field_name in ("I", "P", "S", "G"):
        key = f"Field {field_name} name"
        if key in headers:
            metadata["fields"][field_name] = [part.strip() for part in headers[key].split(",")]

    pid_keys = {
        "rollPID": "roll",
        "pitchPID": "pitch",
        "yawPID": "yaw",
        "levelPID": "level",
    }
    for header_key, axis in pid_keys.items():
        values = _parse_csv_ints(headers.get(header_key, ""))
        if values is not None:
            metadata["pids"][axis] = values

    if not metadata["pids"]:
        warnings.append("No PID headers found")

    return BlackboxMetadata("readable", metadata, warnings)
