from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

AXES = {0: "roll", 1: "pitch", 2: "yaw"}
TRACKING_THRESHOLD = 50.0
HIGH_RATE_THRESHOLD = 200.0
MOTOR_SATURATION_THRESHOLD = 1990.0
MIN_USEFUL_DURATION_SECONDS = 5.0
SEGMENT_GAP_US = 200_000.0
MIN_SEGMENT_DURATION_US = 100_000.0
THROTTLE_PUNCH_THRESHOLD = 1700.0



def _to_float(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_field(name: str) -> str:
    name = name.strip()
    if " (" in name:
        name = name.split(" (", 1)[0]
    return name


def _track_range(ranges: dict[str, dict[str, float]], name: str, value: float) -> None:
    current = ranges.setdefault(name, {"min": value, "max": value})
    current["min"] = min(current["min"], value)
    current["max"] = max(current["max"], value)


def _empty_axis_metric() -> dict[str, float | int | None]:
    return {"samples": 0, "mean_abs_error": None, "max_abs_error": None, "samples_over_threshold": 0}


def analyze_csv_log(path: str | Path, *, max_rows: int | None = None) -> dict[str, Any]:
    csv_path = Path(path)
    warnings: list[str] = []
    ranges: dict[str, dict[str, float]] = {}
    first_time: float | None = None
    last_time: float | None = None
    row_count = 0
    high_rate_samples = {axis: 0 for axis in AXES.values()}
    max_abs_setpoint = {axis: 0.0 for axis in AXES.values()}
    motor_saturation_samples = 0
    tracking_acc = {axis: {"samples": 0, "sum_abs_error": 0.0, "max_abs_error": 0.0, "samples_over_threshold": 0} for axis in AXES.values()}
    previous_values: dict[str, float] = {}
    rough_noise_acc: dict[str, dict[str, float | int]] = {}
    high_rate_builders = {axis: None for axis in AXES.values()}
    high_rate_segments = []
    throttle_builder = None
    throttle_segments = []

    with csv_path.open(newline="", errors="replace") as handle:
        reader = csv.DictReader(handle)
        raw_fields = reader.fieldnames or []
        fields = [_normalize_field(name) for name in raw_fields]
        for raw_row in reader:
            row_count += 1
            if max_rows is not None and row_count > max_rows:
                warnings.append(f"Stopped after max_rows={max_rows}")
                row_count -= 1
                break

            row = {_normalize_field(name): value for name, value in raw_row.items()}
            time_value = _to_float(row.get("time", ""))
            if time_value is not None:
                first_time = time_value if first_time is None else first_time
                last_time = time_value

            numeric: dict[str, float] = {}
            for name, value_text in row.items():
                if not name.startswith(("gyroADC[", "gyroUnfilt[", "setpoint[", "motor[", "axisP[", "axisI[", "axisD[", "axisF[", "rcCommand[")):
                    continue
                value = _to_float(value_text)
                if value is None:
                    continue
                numeric[name] = value
                _track_range(ranges, name, value)
                if name.startswith(("gyroADC[", "gyroUnfilt[", "axisD[")):
                    previous = previous_values.get(name)
                    if previous is not None:
                        acc = rough_noise_acc.setdefault(name, {"samples": 0, "sum_abs_delta": 0.0, "max_abs_delta": 0.0})
                        delta = abs(value - previous)
                        acc["samples"] += 1
                        acc["sum_abs_delta"] += delta
                        acc["max_abs_delta"] = max(float(acc["max_abs_delta"]), delta)
                    previous_values[name] = value

            saturated_this_row = False
            for index, axis in AXES.items():
                setpoint = numeric.get(f"setpoint[{index}]")
                gyro = numeric.get(f"gyroADC[{index}]")
                if setpoint is not None:
                    abs_setpoint = abs(setpoint)
                    max_abs_setpoint[axis] = max(max_abs_setpoint[axis], abs_setpoint)
                    if abs_setpoint >= HIGH_RATE_THRESHOLD:
                        high_rate_samples[axis] += 1
                if setpoint is not None and gyro is not None:
                    error = abs(setpoint - gyro)
                    acc = tracking_acc[axis]
                    acc["samples"] += 1
                    acc["sum_abs_error"] += error
                    acc["max_abs_error"] = max(acc["max_abs_error"], error)
                    if error >= TRACKING_THRESHOLD:
                        acc["samples_over_threshold"] += 1

            for name, value in numeric.items():
                if name.startswith("motor[") and value >= MOTOR_SATURATION_THRESHOLD:
                    saturated_this_row = True
            if saturated_this_row:
                motor_saturation_samples += 1

            if time_value is not None:
                for index, axis in AXES.items():
                    setpoint = numeric.get(f"setpoint[{index}]")
                    gyro = numeric.get(f"gyroADC[{index}]")
                    active = setpoint is not None and abs(setpoint) >= HIGH_RATE_THRESHOLD
                    builder = high_rate_builders[axis]
                    if active:
                        if builder is None or time_value - builder["last_time_us"] > SEGMENT_GAP_US:
                            if builder is not None:
                                high_rate_segments.append(builder)
                            builder = {
                                "axis": axis,
                                "start_time_us": time_value,
                                "end_time_us": time_value,
                                "last_time_us": time_value,
                                "samples": 0,
                                "max_abs_setpoint": 0.0,
                                "max_abs_gyro": 0.0,
                                "motor_saturation_samples": 0,
                            }
                        builder["end_time_us"] = time_value
                        builder["last_time_us"] = time_value
                        builder["samples"] += 1
                        builder["max_abs_setpoint"] = max(builder["max_abs_setpoint"], abs(setpoint))
                        if gyro is not None:
                            builder["max_abs_gyro"] = max(builder["max_abs_gyro"], abs(gyro))
                        if saturated_this_row:
                            builder["motor_saturation_samples"] += 1
                        high_rate_builders[axis] = builder

                throttle = numeric.get("rcCommand[3]")
                throttle_active = throttle is not None and throttle >= THROTTLE_PUNCH_THRESHOLD
                if throttle_active:
                    if throttle_builder is None or time_value - throttle_builder["last_time_us"] > SEGMENT_GAP_US:
                        if throttle_builder is not None:
                            throttle_segments.append(throttle_builder)
                        throttle_builder = {
                            "start_time_us": time_value,
                            "end_time_us": time_value,
                            "last_time_us": time_value,
                            "samples": 0,
                            "throttle_start": throttle,
                            "throttle_peak": throttle,
                            "motor_saturation_samples": 0,
                        }
                    throttle_builder["end_time_us"] = time_value
                    throttle_builder["last_time_us"] = time_value
                    throttle_builder["samples"] += 1
                    throttle_builder["throttle_peak"] = max(throttle_builder["throttle_peak"], throttle)
                    if saturated_this_row:
                        throttle_builder["motor_saturation_samples"] += 1

    for builder in high_rate_builders.values():
        if builder is not None:
            high_rate_segments.append(builder)
    if throttle_builder is not None:
        throttle_segments.append(throttle_builder)

    def finish_segments(segments):
        finished = []
        for segment in segments:
            duration_us = segment["end_time_us"] - segment["start_time_us"]
            if duration_us < MIN_SEGMENT_DURATION_US:
                continue
            item = {k: v for k, v in segment.items() if k != "last_time_us"}
            item["start_time_seconds"] = item.pop("start_time_us") / 1_000_000.0
            item["end_time_seconds"] = item.pop("end_time_us") / 1_000_000.0
            item["duration_seconds"] = duration_us / 1_000_000.0
            finished.append(item)
        return finished

    high_rate_segments = finish_segments(high_rate_segments)
    throttle_segments = finish_segments(throttle_segments)

    required = ["time", "gyroADC[0]", "gyroADC[1]", "gyroADC[2]", "setpoint[0]", "setpoint[1]", "setpoint[2]"]
    missing = [name for name in required if name not in fields]
    if missing:
        warnings.append("Missing expected fields: " + ", ".join(missing))

    duration_seconds = None
    if first_time is not None and last_time is not None and last_time >= first_time:
        duration_seconds = (last_time - first_time) / 1_000_000.0

    has_motor = any(field.startswith("motor[") for field in fields)
    has_pid_terms = all(any(field.startswith(prefix) for field in fields) for prefix in ("axisP[", "axisI[", "axisD["))
    quality_warnings = list(warnings)
    if duration_seconds is None or duration_seconds < MIN_USEFUL_DURATION_SECONDS:
        quality_warnings.append("Blackbox Log duration is short for tuning analysis")
    if not has_motor:
        quality_warnings.append("No motor fields found")
    if not has_pid_terms:
        quality_warnings.append("PID term fields are incomplete")

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

    rough_noise = {}
    for name, acc in rough_noise_acc.items():
        samples = int(acc["samples"])
        rough_noise[name] = {
            "samples": samples,
            "mean_abs_delta": float(acc["sum_abs_delta"]) / samples if samples else None,
            "max_abs_delta": acc["max_abs_delta"],
        }

    return {
        "csv_path": str(csv_path),
        "row_count": row_count,
        "fields": fields,
        "field_count": len(fields),
        "duration_seconds": duration_seconds,
        "ranges": ranges,
        "quality": {
            "usable": not quality_warnings,
            "duration_ok": duration_seconds is not None and duration_seconds >= MIN_USEFUL_DURATION_SECONDS,
            "has_gyro": all(f"gyroADC[{i}]" in fields for i in AXES),
            "has_setpoint": all(f"setpoint[{i}]" in fields for i in AXES),
            "has_motor": has_motor,
            "has_pid_terms": has_pid_terms,
            "warnings": quality_warnings,
        },
        "activity": {
            "max_abs_setpoint": max_abs_setpoint,
            "high_rate_samples": high_rate_samples,
            "motor_saturation_samples": motor_saturation_samples,
            "throttle_range": ranges.get("rcCommand[3]"),
        },
        "tracking": tracking,
        "rough_noise": rough_noise,
        "segments": {
            "high_rate": high_rate_segments,
            "throttle_punch": throttle_segments,
        },
        "warnings": warnings,
    }
