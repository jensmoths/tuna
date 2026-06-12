from __future__ import annotations

import json
import sys
from typing import Any


def row_to_dict(row: Any) -> dict[str, Any]:
    return dict(row) if row is not None else {}


def loads_json_object(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def emit(payload: dict[str, Any], json_output: bool) -> None:
    if json_output:
        print_json(payload)
    else:
        print(next(iter(payload.values())))


def command_error_payload(exc: BaseException) -> dict[str, Any]:
    return {"error": {"kind": exc.__class__.__name__, "message": str(exc), "retryable": False}}


def emit_command_error(exc: BaseException, json_output: bool) -> None:
    if json_output:
        print_json(command_error_payload(exc))
    else:
        print(str(exc), file=sys.stderr)


def require_row(row: Any, label: str, row_id: int) -> Any:
    if row is None:
        raise ValueError(f"{label} {row_id} does not exist")
    return row
