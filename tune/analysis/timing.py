from __future__ import annotations

import statistics
from typing import Any


def summarize_timing(sample_intervals_us: list[float], duration_seconds: float | None, row_count: int) -> dict[str, Any]:
    positive_intervals = [interval for interval in sample_intervals_us if interval > 0]
    if not positive_intervals:
        return {
            "sample_intervals": 0,
            "min_interval_us": None,
            "max_interval_us": None,
            "mean_interval_us": None,
            "nominal_interval_us": None,
            "nominal_logging_rate_hz": None,
            "effective_logging_rate_hz": None,
        }

    nominal_interval_us = statistics.median(positive_intervals)
    effective_logging_rate_hz = None
    if duration_seconds and duration_seconds > 0 and row_count > 1:
        effective_logging_rate_hz = (row_count - 1) / duration_seconds

    return {
        "sample_intervals": len(positive_intervals),
        "min_interval_us": min(positive_intervals),
        "max_interval_us": max(positive_intervals),
        "mean_interval_us": sum(positive_intervals) / len(positive_intervals),
        "nominal_interval_us": nominal_interval_us,
        "nominal_logging_rate_hz": 1_000_000.0 / nominal_interval_us if nominal_interval_us > 0 else None,
        "effective_logging_rate_hz": effective_logging_rate_hz,
    }
