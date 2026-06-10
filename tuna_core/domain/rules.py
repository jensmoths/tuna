from __future__ import annotations


def ensure_no_open_iteration(open_iteration_id: int | None) -> None:
    if open_iteration_id is not None:
        raise ValueError(f"Loop already has open Tuning Iteration {open_iteration_id}")


def ensure_rejection_reason(reason: str) -> None:
    if not reason.strip():
        raise ValueError("Rejected Tune Updates require an Operator reason")


def ensure_absolute_settings(settings: dict[str, object]) -> None:
    if not settings:
        raise ValueError("Tune Update settings must not be empty")
    for name, value in settings.items():
        if not name or not isinstance(name, str):
            raise ValueError("Tune Update setting names must be non-empty strings")
        if isinstance(value, str) and value.strip().startswith(("+", "-")):
            raise ValueError("Tune Update settings must be absolute values, not deltas")
