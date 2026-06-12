from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from .analysis_accumulator import BlackboxAnalysisAccumulator
from .common import (
    normalize_field as _normalize_field,
    to_float as _to_float,
)


def _parse_header_value(value: str) -> Any:
    text = value.strip().strip('"')
    if "," in text:
        parts = [part.strip() for part in text.split(",")]
        parsed = [_parse_header_value(part) for part in parts if part != ""]
        return parsed
    numeric = _to_float(text)
    if numeric is None:
        return text
    if numeric.is_integer():
        return int(numeric)
    return numeric


def _looks_like_data_header(row: list[str]) -> bool:
    normalized = [_normalize_field(value) for value in row]
    return "time" in normalized and any(value.startswith("gyroADC[") for value in normalized)


def _iter_csv_data(handle) -> tuple[dict[str, Any], list[str], Any]:
    """Return Blackbox header settings, normalized data fields, and data rows.

    Plain CSV files used in tests start directly with the data header. Decoded
    Blackbox CSVs may contain quoted header setting lines before the actual data
    header. This helper keeps both forms working.
    """
    reader = csv.reader(handle)
    settings: dict[str, Any] = {}
    raw_fields: list[str] | None = None
    for row in reader:
        if not row:
            continue
        if _looks_like_data_header(row):
            raw_fields = row
            break
        if len(row) >= 2:
            key = _normalize_field(row[0]).strip('"')
            if key:
                settings[key] = _parse_header_value(",".join(row[1:]))
    if raw_fields is None:
        return settings, [], iter(())
    fields = [_normalize_field(name) for name in raw_fields]

    def rows():
        for values in reader:
            if not values:
                continue
            if len(values) < len(fields):
                values = values + [""] * (len(fields) - len(values))
            yield dict(zip(fields, values))

    return settings, fields, rows()


def analyze_csv_log(path: str | Path, *, max_rows: int | None = None) -> dict[str, Any]:
    csv_path = Path(path)
    with csv_path.open(newline="", errors="replace") as handle:
        blackbox_settings, fields, reader = _iter_csv_data(handle)
        accumulator = BlackboxAnalysisAccumulator(csv_path=csv_path, fields=fields, blackbox_settings=blackbox_settings)
        for raw_row in reader:
            if not accumulator.process_row(raw_row, max_rows=max_rows):
                break
        return accumulator.finalize()
