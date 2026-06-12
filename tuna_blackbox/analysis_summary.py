from __future__ import annotations

from pathlib import Path
from typing import Any

from .common import AXES, GAP_MULTIPLIER, MIN_USEFUL_DURATION_SECONDS, empty_axis_metric as _empty_axis_metric


def add_timing_gaps(timing: dict[str, Any], time_intervals: list[tuple[int, int, float, float, float]], non_monotonic_time_samples: int) -> None:
    if timing["nominal_interval_us"] is not None:
        gap_threshold_us = float(timing["nominal_interval_us"]) * GAP_MULTIPLIER
        gaps = [_timing_gap(interval, float(timing["nominal_interval_us"])) for interval in time_intervals if interval[4] > gap_threshold_us]
        timing["gap_threshold_us"] = gap_threshold_us
        timing["gaps"] = gaps
        timing["gap_count"] = len(gaps)
        timing["estimated_missing_samples"] = sum(gap["estimated_missing_samples"] for gap in gaps)
    else:
        timing["gap_threshold_us"] = None
        timing["gaps"] = []
        timing["gap_count"] = 0
        timing["estimated_missing_samples"] = 0
    timing["non_monotonic_time_samples"] = non_monotonic_time_samples


def active_window(armed_segments: list[dict[str, Any]], *, row_count: int, first_time: float | None, last_time: float | None, csv_path: str | Path) -> dict[str, Any] | None:
    if not armed_segments:
        return None
    active_start = armed_segments[0]
    active_end = armed_segments[-1]
    return {
        "start_row": active_start["start_row"],
        "end_row": active_end["end_row"],
        "start_time_seconds": active_start["start_time_seconds"],
        "end_time_seconds": active_end["end_time_seconds"],
        "duration_seconds": active_end["end_time_seconds"] - active_start["start_time_seconds"],
        "leading_idle_rows": max(0, active_start["start_row"] - 1),
        "trailing_idle_rows": max(0, row_count - active_end["end_row"]),
        "leading_idle_seconds": active_start["start_time_seconds"] - (first_time / 1_000_000.0) if first_time is not None else None,
        "trailing_idle_seconds": (last_time / 1_000_000.0) - active_end["end_time_seconds"] if last_time is not None else None,
        "raw_data_ref": {
            "csv_path": str(csv_path),
            "start_row": active_start["start_row"],
            "end_row": active_end["end_row"],
            "start_time_seconds": active_start["start_time_seconds"],
            "end_time_seconds": active_end["end_time_seconds"],
        },
    }


def throttle_chop_analysis(throttle_chop_segments: list[dict[str, Any]], fields: list[str]) -> dict[str, Any]:
    analysis = {
        "available": "rcCommand[3]" in fields and any(field.startswith("motor[") for field in fields),
        "segments": throttle_chop_segments,
        "summary": {
            "segment_count": len(throttle_chop_segments),
            "max_duration_seconds": max((segment["duration_seconds"] for segment in throttle_chop_segments), default=0.0),
            "max_motor": max((segment["max_motor"] for segment in throttle_chop_segments if segment["max_motor"] is not None), default=None),
        },
        "warnings": [],
    }
    if not analysis["available"]:
        analysis["warnings"].append("Throttle-chop analysis requires rcCommand[3] and motor fields")
    elif throttle_chop_segments:
        analysis["warnings"].append("Detected throttle-min windows with motors above idle")
    return analysis


def cross_axis_flip_analysis(high_rate_segments: list[dict[str, Any]]) -> dict[str, Any]:
    roll_flip_segments = []
    for segment in high_rate_segments:
        if segment.get("axis") != "roll":
            continue
        cross_axis = segment.get("cross_axis") if isinstance(segment.get("cross_axis"), dict) else {}
        disturbance = max((axis_data.get("gyro_max_abs") or 0.0 for axis_data in cross_axis.values() if isinstance(axis_data, dict)), default=0.0)
        roll_flip_segments.append({
            "start_time_seconds": segment.get("start_time_seconds"),
            "end_time_seconds": segment.get("end_time_seconds"),
            "duration_seconds": segment.get("duration_seconds"),
            "roll_tracking": segment.get("tracking"),
            "motor_saturation_samples": segment.get("motor_saturation_samples"),
            "cross_axis": cross_axis,
            "max_cross_axis_gyro": disturbance,
            "raw_data_ref": segment.get("raw_data_ref"),
        })
    return {
        "available": bool(roll_flip_segments),
        "segments": roll_flip_segments,
        "summary": {
            "roll_flip_segment_count": len(roll_flip_segments),
            "max_cross_axis_gyro": max((segment["max_cross_axis_gyro"] for segment in roll_flip_segments), default=None),
            "motor_saturation_samples": sum(segment.get("motor_saturation_samples") or 0 for segment in roll_flip_segments),
        },
        "warnings": [] if roll_flip_segments else ["No roll high-rate segments found for cross-axis flip analysis"],
    }


def quality_warnings(base_warnings: list[str], *, duration_seconds: float | None, has_motor: bool, has_pid_terms: bool, timing: dict[str, Any], non_monotonic_time_samples: int) -> list[str]:
    warnings = list(base_warnings)
    if duration_seconds is None or duration_seconds < MIN_USEFUL_DURATION_SECONDS:
        warnings.append("Blackbox Log duration is short for tuning analysis")
    if not has_motor:
        warnings.append("No motor fields found")
    if not has_pid_terms:
        warnings.append("PID term fields are incomplete")
    if timing["gap_count"]:
        warnings.append(f"Detected {timing['gap_count']} timing gap/dropout(s); estimated {timing['estimated_missing_samples']} missing sample(s)")
    if non_monotonic_time_samples:
        warnings.append(f"Detected {non_monotonic_time_samples} non-monotonic timestamp sample(s)")
    return warnings


def tracking_summary(tracking_acc: dict[str, dict[str, Any]]) -> dict[str, Any]:
    tracking = {}
    for axis, acc in tracking_acc.items():
        if acc["samples"]:
            tracking[axis] = {
                "samples": acc["samples"],
                "mean_abs_error": acc["sum_abs_error"] / acc["samples"],
                "max_abs_error": acc["max_abs_error"],
                "samples_over_threshold": acc["samples_over_threshold"],
            }
        else:
            tracking[axis] = _empty_axis_metric()
    return tracking


def rough_noise_summary(rough_noise_acc: dict[str, dict[str, float | int]]) -> dict[str, Any]:
    rough_noise = {}
    for name, acc in rough_noise_acc.items():
        samples = int(acc["samples"])
        rough_noise[name] = {
            "samples": samples,
            "mean_abs_delta": float(acc["sum_abs_delta"]) / samples if samples else None,
            "max_abs_delta": acc["max_abs_delta"],
        }
    return rough_noise


def _timing_gap(interval: tuple[int, int, float, float, float], nominal_interval_us: float) -> dict[str, Any]:
    start_row, end_row, start_time, end_time, interval_us = interval
    return {
        "start_row": start_row,
        "end_row": end_row,
        "start_time_seconds": start_time / 1_000_000.0,
        "end_time_seconds": end_time / 1_000_000.0,
        "duration_seconds": interval_us / 1_000_000.0,
        "estimated_missing_samples": max(1, round(interval_us / nominal_interval_us) - 1),
    }

