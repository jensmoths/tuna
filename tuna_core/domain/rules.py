from __future__ import annotations

import math
from collections.abc import Mapping


def ensure_no_open_iteration(open_iteration_id: int | None) -> None:
    if open_iteration_id is not None:
        raise ValueError(f"Loop already has open Tuning Iteration {open_iteration_id}")


def ensure_rejection_reason(reason: str) -> None:
    if not reason.strip():
        raise ValueError("Rejected Tune Updates require an Operator reason")


def ensure_absolute_settings(settings: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(settings, Mapping):
        raise ValueError("Tune Update settings must be a JSON object")
    if not settings:
        raise ValueError("Tune Update settings must not be empty")
    normalized: dict[str, object] = {}
    for name, value in settings.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Tune Update setting names must be non-empty strings")
        key = name.strip()
        if value is None or isinstance(value, (dict, list, tuple, set)):
            raise ValueError(f"Tune Update setting {key} must be a scalar absolute target value")
        if isinstance(value, str) and value.strip().startswith(("+", "-")):
            raise ValueError("Tune Update settings must be absolute values, not deltas")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError(f"Tune Update setting {key} must be a finite number")
        normalized[key] = value.strip() if isinstance(value, str) else value
    return normalized
