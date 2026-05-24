from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class IterationStatus(str, Enum):
    OPEN = "open"
    COMPLETED = "completed"
    FAILED = "failed"


class TuneUpdateStatus(str, Enum):
    PROPOSED = "proposed"
    APPROVED_PENDING_WRITE = "approved_pending_write"
    WRITE_FAILED = "write_failed"
    APPLIED = "applied"
    REJECTED = "rejected"


@dataclass(frozen=True)
class Build:
    id: int
    name: str
    fc_snapshot: dict[str, Any]
    operator_notes: str


@dataclass(frozen=True)
class Loop:
    id: int
    build_id: int
    tune_goal: str
    status: str


@dataclass(frozen=True)
class ImportedLog:
    id: int
    build_id: int
    sha256: str
    managed_path: str
    parse_status: str
    metadata: dict[str, Any]
