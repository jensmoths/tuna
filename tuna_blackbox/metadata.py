from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class BlackboxMetadata:
    parse_status: str
    metadata: dict[str, Any]
    warnings: list[str] = field(default_factory=list)


def metadata_summary(metadata: dict[str, Any]) -> dict[str, Any]:
    fields = metadata.get("fields") if isinstance(metadata.get("fields"), dict) else {}
    return {
        "firmware_type": metadata.get("firmware_type"),
        "firmware_revision": metadata.get("firmware_revision"),
        "firmware_date": metadata.get("firmware_date"),
        "craft_name": metadata.get("craft_name"),
        "data_version": metadata.get("data_version"),
        "pids": metadata.get("pids"),
        "field_counts": {key: len(value) for key, value in fields.items() if isinstance(value, list)},
    }
