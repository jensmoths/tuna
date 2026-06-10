from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class BlackboxMetadata:
    parse_status: str
    metadata: dict[str, Any]
    warnings: list[str] = field(default_factory=list)
