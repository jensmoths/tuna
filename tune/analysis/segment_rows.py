from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from .common import normalize_field as _normalize_field


def _looks_like_data_header(row: list[str]) -> bool:
    normalized = [_normalize_field(value) for value in row]
    return "time" in normalized and any(value.startswith("gyroADC[") for value in normalized)


def _iter_data_rows(handle):
    reader = csv.reader(handle)
    raw_fields = None
    for row in reader:
        if not row:
            continue
        if _looks_like_data_header(row):
            raw_fields = row
            break
    if raw_fields is None:
        return [], []
    normalized_fields = [_normalize_field(field) for field in raw_fields]
    return normalized_fields, reader


def read_segment_rows(
    csv_path: str | Path,
    *,
    start_row: int,
    end_row: int,
    fields: list[str] | None = None,
    pad_rows: int = 0,
    max_rows: int = 500,
) -> dict[str, Any]:
    if start_row < 1 or end_row < start_row:
        raise ValueError("segment row range must be 1-based and ordered")
    if pad_rows < 0:
        raise ValueError("pad_rows must be non-negative")
    if max_rows < 1:
        raise ValueError("max_rows must be positive")

    first = max(1, start_row - pad_rows)
    last = end_row + pad_rows
    selected_fields = [_normalize_field(field) for field in fields] if fields else None
    rows: list[dict[str, str]] = []
    normalized_fields: list[str] = []

    with Path(csv_path).open(newline="", errors="replace") as handle:
        normalized_fields, reader = _iter_data_rows(handle)
        for row_number, values in enumerate(reader, start=1):
            if row_number < first:
                continue
            if row_number > last or len(rows) >= max_rows:
                break
            if len(values) < len(normalized_fields):
                values = values + [""] * (len(normalized_fields) - len(values))
            normalized_row = {name: value.strip() for name, value in zip(normalized_fields, values)}
            if selected_fields is not None:
                normalized_row = {name: normalized_row.get(name, "") for name in selected_fields}
            normalized_row["_row"] = str(row_number)
            rows.append(normalized_row)

    return {
        "csv_path": str(csv_path),
        "requested_start_row": start_row,
        "requested_end_row": end_row,
        "returned_start_row": first if rows else None,
        "returned_end_row": int(rows[-1]["_row"]) if rows else None,
        "truncated": len(rows) >= max_rows and (last - first + 1) > max_rows,
        "fields": selected_fields or normalized_fields,
        "rows": rows,
    }
