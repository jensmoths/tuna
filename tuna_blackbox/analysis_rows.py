from __future__ import annotations

from typing import Any

from .common import (
    ACTIVE_MOTOR_THRESHOLD,
    ACTIVE_THROTTLE_THRESHOLD,
    AXES,
    HIGH_RATE_THRESHOLD,
    MOTOR_SATURATION_THRESHOLD,
    SEGMENT_GAP_US,
    SPECTRAL_PREFIXES,
    THROTTLE_PUNCH_THRESHOLD,
    TRACKING_THRESHOLD,
    throttle_bin_label as _throttle_bin_label,
    to_float as _to_float,
    track_range as _track_range,
)

NUMERIC_PREFIXES = ("gyroADC[", "gyroUnfilt[", "setpoint[", "motor[", "axisP[", "axisI[", "axisD[", "axisF[", "rcCommand[", "debug[")
NOISE_PREFIXES = ("gyroADC[", "gyroUnfilt[", "axisD[")
PID_TERMS = ("P", "I", "D", "F")


def extract_numeric_fields(
    row: dict[str, str],
    *,
    spectral_values: dict[str, list[float]],
    motor_values: dict[str, list[float]],
    ranges: dict[str, dict[str, float]],
    previous_values: dict[str, float],
    rough_noise_acc: dict[str, dict[str, float | int]],
) -> tuple[dict[str, float], dict[str, float]]:
    numeric: dict[str, float] = {}
    deltas: dict[str, float] = {}
    for name, value_text in row.items():
        if not name.startswith(NUMERIC_PREFIXES):
            continue
        value = _to_float(value_text)
        if value is None:
            continue
        numeric[name] = value
        if name.startswith(SPECTRAL_PREFIXES):
            spectral_values.setdefault(name, []).append(value)
        if name.startswith("motor["):
            motor_values.setdefault(name, []).append(value)
        _track_range(ranges, name, value)
        _track_noise_delta(name, value, previous_values, rough_noise_acc, deltas)
    return numeric, deltas


def update_axis_overview(
    numeric: dict[str, float],
    *,
    max_abs_setpoint: dict[str, float],
    high_rate_samples: dict[str, int],
    tracking_acc: dict[str, dict[str, Any]],
) -> None:
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


def motor_saturated(numeric: dict[str, float]) -> bool:
    return any(name.startswith("motor[") and value >= MOTOR_SATURATION_THRESHOLD for name, value in numeric.items())


def update_armed_builder(
    *,
    row: dict[str, str],
    numeric: dict[str, float],
    time_value: float,
    row_count: int,
    builder: dict[str, Any] | None,
    segments: list[dict[str, Any]],
    truthy_field: Any,
) -> tuple[dict[str, Any] | None, str | None]:
    explicit_armed = _explicit_armed(row, truthy_field)
    throttle = numeric.get("rcCommand[3]")
    motor_active = any(name.startswith("motor[") and value > ACTIVE_MOTOR_THRESHOLD for name, value in numeric.items())
    throttle_active = throttle is not None and throttle > ACTIVE_THROTTLE_THRESHOLD
    active_flight = explicit_armed if explicit_armed is not None else motor_active or throttle_active
    if not active_flight:
        return builder, None
    detection_method = "explicit_armed_field" if explicit_armed is not None else "motor_or_throttle_activity"
    if builder is None or time_value - builder["last_time_us"] > SEGMENT_GAP_US:
        if builder is not None:
            segments.append(builder)
        builder = {
            "start_time_us": time_value,
            "end_time_us": time_value,
            "last_time_us": time_value,
            "start_row": row_count,
            "end_row": row_count,
            "samples": 0,
            "detection_methods": set(),
        }
    builder["end_time_us"] = time_value
    builder["last_time_us"] = time_value
    builder["end_row"] = row_count
    builder["samples"] += 1
    builder["detection_methods"].add(detection_method)
    return builder, detection_method


def update_throttle_chop_builder(
    *,
    time_value: float,
    row_count: int,
    throttle: float | None,
    numeric: dict[str, float],
    previous_throttle: float | None,
    builder: dict[str, Any] | None,
    segments: list[dict[str, Any]],
) -> dict[str, Any] | None:
    motor_outputs = [value for name, value in numeric.items() if name.startswith("motor[")]
    hang_active = throttle is not None and throttle <= 1020.0 and any(value > ACTIVE_MOTOR_THRESHOLD for value in motor_outputs)
    if not hang_active:
        if builder is not None:
            segments.append(builder)
        return None
    if builder is None or time_value - builder["last_time_us"] > SEGMENT_GAP_US:
        if builder is not None:
            segments.append(builder)
        builder = _new_throttle_chop_builder(time_value, row_count, throttle, previous_throttle)
    _update_throttle_chop_metrics(builder, time_value, row_count, throttle, motor_outputs, numeric)
    return builder


def record_throttle_bins(
    throttle: float | None,
    numeric: dict[str, float],
    *,
    heatmap_values: dict[str, dict[str, list[float]]],
    motor_throttle_bins: dict[str, dict[str, list[float]]],
) -> None:
    if throttle is None:
        return
    throttle_bin = _throttle_bin_label(throttle)
    if throttle_bin is None:
        return
    for name, value in numeric.items():
        if name.startswith(SPECTRAL_PREFIXES):
            heatmap_values.setdefault(name, {}).setdefault(throttle_bin, []).append(value)
        if name.startswith("motor["):
            motor_throttle_bins.setdefault(name, {}).setdefault(throttle_bin, []).append(value)


def record_axis_samples(
    *,
    time_value: float,
    throttle: float | None,
    numeric: dict[str, float],
    step_response_samples: dict[str, list[tuple[float, float, float]]],
    pid_samples: dict[str, list[dict[str, float | None]]],
) -> None:
    for index, axis in AXES.items():
        setpoint = numeric.get(f"setpoint[{index}]")
        gyro = numeric.get(f"gyroADC[{index}]")
        if setpoint is not None and gyro is not None:
            step_response_samples[axis].append((time_value, setpoint, gyro))
        pid_sample = {
            "time_us": time_value,
            "setpoint": setpoint,
            "throttle": throttle,
            "P": numeric.get(f"axisP[{index}]"),
            "I": numeric.get(f"axisI[{index}]"),
            "D": numeric.get(f"axisD[{index}]"),
            "F": numeric.get(f"axisF[{index}]"),
        }
        if any(pid_sample[term] is not None for term in PID_TERMS):
            pid_samples[axis].append(pid_sample)


def chirp_row(row_count: int, time_value: float, numeric: dict[str, float], saturated_this_row: bool) -> dict[str, float | int] | None:
    item: dict[str, float | int] = {"_row": row_count, "time": time_value, "motor_saturated": int(saturated_this_row)}
    for field in (
        "debug[0]", "debug[1]", "debug[2]", "debug[3]",
        "setpoint[0]", "setpoint[1]", "setpoint[2]",
        "gyroADC[0]", "gyroADC[1]", "gyroADC[2]",
    ):
        value = numeric.get(field)
        if value is None:
            return None
        item[field] = value
    return item


def update_throttle_punch_builder(
    *,
    time_value: float,
    row_count: int,
    throttle: float | None,
    saturated_this_row: bool,
    builder: dict[str, Any] | None,
    segments: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if throttle is None or throttle < THROTTLE_PUNCH_THRESHOLD:
        return builder
    if builder is None or time_value - builder["last_time_us"] > SEGMENT_GAP_US:
        if builder is not None:
            segments.append(builder)
        builder = {
            "start_time_us": time_value,
            "end_time_us": time_value,
            "last_time_us": time_value,
            "samples": 0,
            "start_row": row_count,
            "end_row": row_count,
            "throttle_start": throttle,
            "throttle_peak": throttle,
            "motor_saturation_samples": 0,
        }
    builder["end_time_us"] = time_value
    builder["last_time_us"] = time_value
    builder["end_row"] = row_count
    builder["samples"] += 1
    builder["throttle_peak"] = max(builder["throttle_peak"], throttle)
    if saturated_this_row:
        builder["motor_saturation_samples"] += 1
    return builder


def _explicit_armed(row: dict[str, str], truthy_field: Any) -> bool | None:
    for armed_field in ("armed", "isArmed", "armState"):
        if armed_field in row:
            explicit = truthy_field(row.get(armed_field))
            if explicit is not None:
                return explicit
    return None


def _new_throttle_chop_builder(time_value: float, row_count: int, throttle: float, previous_throttle: float | None) -> dict[str, Any]:
    return {
        "start_time_us": time_value,
        "end_time_us": time_value,
        "last_time_us": time_value,
        "start_row": row_count,
        "end_row": row_count,
        "samples": 0,
        "throttle_before_drop": previous_throttle,
        "throttle_min": throttle,
        "max_motor": None,
        "motor_sum_above_idle": 0.0,
        "motor_samples_above_idle": 0,
        "pid_abs_sums": {axis: {term: 0.0 for term in PID_TERMS} for axis in AXES.values()},
        "pid_abs_max": {axis: {term: 0.0 for term in PID_TERMS} for axis in AXES.values()},
        "pid_samples": {axis: 0 for axis in AXES.values()},
    }


def _update_throttle_chop_metrics(builder: dict[str, Any], time_value: float, row_count: int, throttle: float, motor_outputs: list[float], numeric: dict[str, float]) -> None:
    builder["end_time_us"] = time_value
    builder["last_time_us"] = time_value
    builder["end_row"] = row_count
    builder["samples"] += 1
    builder["throttle_min"] = min(builder["throttle_min"], throttle)
    if motor_outputs:
        row_max_motor = max(motor_outputs)
        builder["max_motor"] = row_max_motor if builder["max_motor"] is None else max(builder["max_motor"], row_max_motor)
        above_idle = [value for value in motor_outputs if value > ACTIVE_MOTOR_THRESHOLD]
        builder["motor_sum_above_idle"] += sum(above_idle)
        builder["motor_samples_above_idle"] += len(above_idle)
    for index, axis in AXES.items():
        saw_pid = False
        for term, field in (("P", f"axisP[{index}]"), ("I", f"axisI[{index}]"), ("D", f"axisD[{index}]"), ("F", f"axisF[{index}]")):
            value = numeric.get(field)
            if value is None:
                continue
            saw_pid = True
            abs_value = abs(value)
            builder["pid_abs_sums"][axis][term] += abs_value
            builder["pid_abs_max"][axis][term] = max(builder["pid_abs_max"][axis][term], abs_value)
        if saw_pid:
            builder["pid_samples"][axis] += 1


def _track_noise_delta(
    name: str,
    value: float,
    previous_values: dict[str, float],
    rough_noise_acc: dict[str, dict[str, float | int]],
    deltas: dict[str, float],
) -> None:
    if not name.startswith(NOISE_PREFIXES):
        return
    previous = previous_values.get(name)
    if previous is not None:
        acc = rough_noise_acc.setdefault(name, {"samples": 0, "sum_abs_delta": 0.0, "max_abs_delta": 0.0})
        delta = abs(value - previous)
        deltas[name] = delta
        acc["samples"] += 1
        acc["sum_abs_delta"] += delta
        acc["max_abs_delta"] = max(float(acc["max_abs_delta"]), delta)
    previous_values[name] = value
