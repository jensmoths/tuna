from __future__ import annotations

from pathlib import Path
from typing import Any

from .common import MIN_SEGMENT_DURATION_US


def finish_segments(segments: list[dict[str, Any]], csv_path: str | Path) -> list[dict[str, Any]]:
    finished = []
    for segment in segments:
        duration_us = segment["end_time_us"] - segment["start_time_us"]
        if duration_us < MIN_SEGMENT_DURATION_US:
            continue
        item = {k: v for k, v in segment.items() if k != "last_time_us"}
        item["start_time_seconds"] = item.pop("start_time_us") / 1_000_000.0
        item["end_time_seconds"] = item.pop("end_time_us") / 1_000_000.0
        item["duration_seconds"] = duration_us / 1_000_000.0
        item["raw_data_ref"] = _raw_ref(csv_path, item)
        if "tracking_sum_abs_error" in item:
            _finish_high_rate_metrics(item)
        finished.append(item)
    return finished


def finish_throttle_chop_segments(segments: list[dict[str, Any]], csv_path: str | Path) -> list[dict[str, Any]]:
    finished = []
    for segment in segments:
        duration_us = segment["end_time_us"] - segment["start_time_us"]
        if duration_us < 20_000.0:
            continue
        motor_samples = segment["motor_samples_above_idle"]
        start_time_seconds = segment["start_time_us"] / 1_000_000.0
        end_time_seconds = segment["end_time_us"] / 1_000_000.0
        item = {
            "start_row": segment["start_row"],
            "end_row": segment["end_row"],
            "samples": segment["samples"],
            "start_time_seconds": start_time_seconds,
            "end_time_seconds": end_time_seconds,
            "duration_seconds": duration_us / 1_000_000.0,
            "throttle_before_drop": segment["throttle_before_drop"],
            "throttle_min": segment["throttle_min"],
            "max_motor": segment["max_motor"],
            "mean_motor_above_idle": segment["motor_sum_above_idle"] / motor_samples if motor_samples else None,
            "motor_samples_above_idle": motor_samples,
            "pid_terms": _finish_pid_terms(segment),
            "raw_data_ref": _raw_ref(csv_path, {"start_row": segment["start_row"], "end_row": segment["end_row"], "start_time_seconds": start_time_seconds, "end_time_seconds": end_time_seconds}),
        }
        finished.append(item)
    return finished


def finish_armed_segments(segments: list[dict[str, Any]], csv_path: str | Path) -> list[dict[str, Any]]:
    finished = []
    for segment in segments:
        start_time_seconds = segment["start_time_us"] / 1_000_000.0
        end_time_seconds = segment["end_time_us"] / 1_000_000.0
        item = {
            "start_row": segment["start_row"],
            "end_row": segment["end_row"],
            "samples": segment["samples"],
            "start_time_seconds": start_time_seconds,
            "end_time_seconds": end_time_seconds,
            "duration_seconds": (segment["end_time_us"] - segment["start_time_us"]) / 1_000_000.0,
            "detection_methods": sorted(segment["detection_methods"]),
            "raw_data_ref": _raw_ref(csv_path, {"start_row": segment["start_row"], "end_row": segment["end_row"], "start_time_seconds": start_time_seconds, "end_time_seconds": end_time_seconds}),
        }
        finished.append(item)
    return finished


def _raw_ref(csv_path: str | Path, item: dict[str, Any]) -> dict[str, Any]:
    return {
        "csv_path": str(csv_path),
        "start_row": item.get("start_row"),
        "end_row": item.get("end_row"),
        "start_time_seconds": item["start_time_seconds"],
        "end_time_seconds": item["end_time_seconds"],
    }


def _finish_high_rate_metrics(item: dict[str, Any]) -> None:
    samples = item.pop("samples")
    item["samples"] = samples
    item["tracking"] = {
        "mean_abs_error": item.pop("tracking_sum_abs_error") / samples if samples else None,
        "max_abs_error": item.pop("tracking_max_abs_error"),
        "samples_over_threshold": item.pop("tracking_samples_over_threshold"),
    }
    gyro_delta_samples = item.pop("gyro_delta_samples")
    item["rough_noise"] = {
        "gyro_mean_abs_delta": item.pop("gyro_sum_abs_delta") / gyro_delta_samples if gyro_delta_samples else None,
        "gyro_max_abs_delta": item.pop("gyro_max_abs_delta"),
        "gyro_delta_samples": gyro_delta_samples,
    }
    dterm_delta_samples = item.pop("dterm_delta_samples")
    item["rough_noise"].update({
        "dterm_mean_abs_delta": item.pop("dterm_sum_abs_delta") / dterm_delta_samples if dterm_delta_samples else None,
        "dterm_max_abs_delta": item.pop("dterm_max_abs_delta"),
        "dterm_delta_samples": dterm_delta_samples,
    })
    _finish_cross_axis(item)


def _finish_cross_axis(item: dict[str, Any]) -> None:
    cross_axis = item.pop("cross_axis", {})
    item["cross_axis"] = {}
    for other_axis, cross in cross_axis.items():
        cross_samples = cross["samples"]
        item["cross_axis"][other_axis] = {
            "samples": cross_samples,
            "gyro_mean_abs": cross["gyro_sum_abs"] / cross_samples if cross_samples else None,
            "gyro_max_abs": cross["gyro_max_abs"] if cross_samples else None,
            "setpoint_max_abs": cross["setpoint_max_abs"] if cross_samples else None,
            "pid_terms": {
                term: {
                    "mean_abs": cross["pid_abs_sums"][term] / cross_samples if cross_samples else None,
                    "max_abs": cross["pid_abs_max"][term] if cross_samples else None,
                }
                for term in ("P", "I", "D", "F")
            },
        }


def _finish_pid_terms(segment: dict[str, Any]) -> dict[str, Any]:
    pid_terms = {}
    for axis, samples in segment["pid_samples"].items():
        pid_terms[axis] = {
            term: {
                "mean_abs": segment["pid_abs_sums"][axis][term] / samples if samples else None,
                "max_abs": segment["pid_abs_max"][axis][term] if samples else None,
            }
            for term in ("P", "I", "D", "F")
        }
    return pid_terms

