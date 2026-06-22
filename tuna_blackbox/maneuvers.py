from __future__ import annotations

from pathlib import Path
from typing import Any

from .common import AXES

PROPWASH_LOW_THROTTLE = 1300.0
PROPWASH_RECOVERY_THROTTLE = 1500.0
PROPWASH_THROTTLE_DELTA = 200.0
PROPWASH_WINDOW_US = 500_000.0
PROPWASH_MIN_SAMPLES = 4
PROPWASH_GYRO_DELTA_WARNING = 60.0
PROPWASH_TRACKING_WARNING = 120.0


def summarize_propwash_analysis(samples: list[dict[str, Any]], fields: list[str], csv_path: str | Path) -> dict[str, Any]:
    if "rcCommand[3]" not in fields:
        return {
            "available": False,
            "reason": "missing_throttle",
            "segments": [],
            "summary": {"segment_count": 0},
            "warnings": ["Propwash recovery analysis requires rcCommand[3]"],
        }

    segments = []
    last_event_time = -PROPWASH_WINDOW_US
    for index in range(1, len(samples)):
        previous = samples[index - 1]
        current = samples[index]
        previous_throttle = previous.get("throttle")
        throttle = current.get("throttle")
        if previous_throttle is None or throttle is None:
            continue
        if current["time_us"] - last_event_time < PROPWASH_WINDOW_US:
            continue
        if previous_throttle > PROPWASH_LOW_THROTTLE or throttle < PROPWASH_RECOVERY_THROTTLE:
            continue
        if throttle - previous_throttle < PROPWASH_THROTTLE_DELTA:
            continue
        window = [sample for sample in samples[index:] if sample["time_us"] <= current["time_us"] + PROPWASH_WINDOW_US]
        if len(window) < PROPWASH_MIN_SAMPLES:
            continue
        segment = _summarize_recovery_window(window, csv_path, previous_throttle, throttle)
        segments.append(segment)
        last_event_time = current["time_us"]

    warnings = []
    if not segments:
        warnings.append("No throttle-recovery propwash segments found")
    elif any(segment.get("flags") for segment in segments):
        warnings.append("Propwash recovery segments have tracking/noise flags")

    return {
        "available": True,
        "segments": segments,
        "summary": {
            "segment_count": len(segments),
            "max_gyro_mean_abs_delta": max((segment["summary"].get("max_gyro_mean_abs_delta") or 0.0 for segment in segments), default=None),
            "max_tracking_error": max((segment["summary"].get("max_tracking_error") or 0.0 for segment in segments), default=None),
            "motor_saturation_segments": sum(1 for segment in segments if segment.get("motor_saturation_samples")),
        },
        "warnings": warnings,
    }


def _summarize_recovery_window(window: list[dict[str, Any]], csv_path: str | Path, previous_throttle: float, throttle: float) -> dict[str, Any]:
    axes = {}
    flags = set()
    for axis in AXES.values():
        gyro_values = [sample["gyro"].get(axis) for sample in window if sample.get("gyro", {}).get(axis) is not None]
        setpoint_gyro_pairs = [
            (sample["setpoint"].get(axis), sample["gyro"].get(axis))
            for sample in window
            if sample.get("setpoint", {}).get(axis) is not None and sample.get("gyro", {}).get(axis) is not None
        ]
        d_values = [sample["D"].get(axis) for sample in window if sample.get("D", {}).get(axis) is not None]
        gyro_deltas = [abs(float(gyro_values[i]) - float(gyro_values[i - 1])) for i in range(1, len(gyro_values))]
        d_deltas = [abs(float(d_values[i]) - float(d_values[i - 1])) for i in range(1, len(d_values))]
        errors = [abs(float(setpoint) - float(gyro)) for setpoint, gyro in setpoint_gyro_pairs]
        gyro_mean_abs_delta = sum(gyro_deltas) / len(gyro_deltas) if gyro_deltas else None
        max_tracking_error = max(errors) if errors else None
        axis_flags = []
        if gyro_mean_abs_delta is not None and gyro_mean_abs_delta >= PROPWASH_GYRO_DELTA_WARNING:
            axis_flags.append("high_gyro_activity_after_throttle_recovery")
        if max_tracking_error is not None and max_tracking_error >= PROPWASH_TRACKING_WARNING:
            axis_flags.append("high_tracking_error_after_throttle_recovery")
        flags.update(axis_flags)
        axes[axis] = {
            "samples": len(window),
            "gyro_mean_abs_delta": gyro_mean_abs_delta,
            "gyro_max_abs_delta": max(gyro_deltas) if gyro_deltas else None,
            "dterm_mean_abs_delta": sum(d_deltas) / len(d_deltas) if d_deltas else None,
            "dterm_max_abs_delta": max(d_deltas) if d_deltas else None,
            "max_tracking_error": max_tracking_error,
            "mean_tracking_error": sum(errors) / len(errors) if errors else None,
            "flags": axis_flags,
        }

    if any(sample.get("motor_saturated") for sample in window):
        flags.add("motor_saturation")

    start = window[0]
    end = window[-1]
    max_gyro_mean_abs_delta = max((axis_data.get("gyro_mean_abs_delta") or 0.0 for axis_data in axes.values()), default=None)
    max_tracking_error = max((axis_data.get("max_tracking_error") or 0.0 for axis_data in axes.values()), default=None)
    return {
        "start_row": start["row"],
        "end_row": end["row"],
        "samples": len(window),
        "start_time_seconds": start["time_us"] / 1_000_000.0,
        "end_time_seconds": end["time_us"] / 1_000_000.0,
        "duration_seconds": (end["time_us"] - start["time_us"]) / 1_000_000.0,
        "throttle_before_recovery": previous_throttle,
        "throttle_recovery_start": throttle,
        "motor_saturation_samples": sum(1 for sample in window if sample.get("motor_saturated")),
        "axes": axes,
        "summary": {
            "max_gyro_mean_abs_delta": max_gyro_mean_abs_delta,
            "max_tracking_error": max_tracking_error,
        },
        "flags": sorted(flags),
        "raw_data_ref": {
            "csv_path": str(csv_path),
            "start_row": start["row"],
            "end_row": end["row"],
            "start_time_seconds": start["time_us"] / 1_000_000.0,
            "end_time_seconds": end["time_us"] / 1_000_000.0,
        },
    }
