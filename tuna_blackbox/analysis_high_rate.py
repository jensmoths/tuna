from __future__ import annotations

from typing import Any

from .common import AXES, HIGH_RATE_THRESHOLD, SEGMENT_GAP_US, TRACKING_THRESHOLD


def update_high_rate_segments(
    *,
    high_rate_builders: dict[str, dict[str, Any] | None],
    high_rate_segments: list[dict[str, Any]],
    row_count: int,
    time_value: float,
    numeric: dict[str, float],
    deltas: dict[str, float],
    saturated_this_row: bool,
) -> None:
    for index, axis in AXES.items():
        setpoint = numeric.get(f"setpoint[{index}]")
        gyro = numeric.get(f"gyroADC[{index}]")
        active = setpoint is not None and abs(setpoint) >= HIGH_RATE_THRESHOLD
        builder = high_rate_builders[axis]
        if not active:
            continue
        if builder is None or time_value - builder["last_time_us"] > SEGMENT_GAP_US:
            if builder is not None:
                high_rate_segments.append(builder)
            builder = _new_high_rate_builder(axis, time_value, row_count)
        _update_high_rate_builder(
            builder,
            index=index,
            axis=axis,
            setpoint=setpoint,
            gyro=gyro,
            numeric=numeric,
            deltas=deltas,
            time_value=time_value,
            row_count=row_count,
            saturated_this_row=saturated_this_row,
        )
        high_rate_builders[axis] = builder


def _new_high_rate_builder(axis: str, time_value: float, row_count: int) -> dict[str, Any]:
    return {
        "axis": axis,
        "start_time_us": time_value,
        "end_time_us": time_value,
        "last_time_us": time_value,
        "samples": 0,
        "start_row": row_count,
        "end_row": row_count,
        "max_abs_setpoint": 0.0,
        "max_abs_gyro": 0.0,
        "motor_saturation_samples": 0,
        "tracking_sum_abs_error": 0.0,
        "tracking_max_abs_error": 0.0,
        "tracking_samples_over_threshold": 0,
        "gyro_sum_abs_delta": 0.0,
        "gyro_max_abs_delta": 0.0,
        "gyro_delta_samples": 0,
        "dterm_sum_abs_delta": 0.0,
        "dterm_max_abs_delta": 0.0,
        "dterm_delta_samples": 0,
        "cross_axis": {
            other_axis: {
                "samples": 0,
                "gyro_sum_abs": 0.0,
                "gyro_max_abs": 0.0,
                "setpoint_max_abs": 0.0,
                "pid_abs_sums": {term: 0.0 for term in ("P", "I", "D", "F")},
                "pid_abs_max": {term: 0.0 for term in ("P", "I", "D", "F")},
            }
            for other_axis in AXES.values()
            if other_axis != axis
        },
    }


def _update_high_rate_builder(
    builder: dict[str, Any],
    *,
    index: int,
    axis: str,
    setpoint: float,
    gyro: float | None,
    numeric: dict[str, float],
    deltas: dict[str, float],
    time_value: float,
    row_count: int,
    saturated_this_row: bool,
) -> None:
    builder["end_time_us"] = time_value
    builder["last_time_us"] = time_value
    builder["end_row"] = row_count
    builder["samples"] += 1
    builder["max_abs_setpoint"] = max(builder["max_abs_setpoint"], abs(setpoint))
    if gyro is not None:
        builder["max_abs_gyro"] = max(builder["max_abs_gyro"], abs(gyro))
        error = abs(setpoint - gyro)
        builder["tracking_sum_abs_error"] += error
        builder["tracking_max_abs_error"] = max(builder["tracking_max_abs_error"], error)
        if error >= TRACKING_THRESHOLD:
            builder["tracking_samples_over_threshold"] += 1
    _record_builder_delta(builder, deltas, f"gyroADC[{index}]", sum_key="gyro_sum_abs_delta", max_key="gyro_max_abs_delta", count_key="gyro_delta_samples")
    _record_builder_delta(builder, deltas, f"axisD[{index}]", sum_key="dterm_sum_abs_delta", max_key="dterm_max_abs_delta", count_key="dterm_delta_samples")
    if saturated_this_row:
        builder["motor_saturation_samples"] += 1
    _record_cross_axis(builder, axis, numeric)


def _record_builder_delta(builder: dict[str, Any], deltas: dict[str, float], field_name: str, *, sum_key: str, max_key: str, count_key: str) -> None:
    delta = deltas.get(field_name)
    if delta is None:
        return
    builder[sum_key] += delta
    builder[max_key] = max(builder[max_key], delta)
    builder[count_key] += 1


def _record_cross_axis(builder: dict[str, Any], axis: str, numeric: dict[str, float]) -> None:
    for other_index, other_axis in AXES.items():
        if other_axis == axis:
            continue
        other_setpoint = numeric.get(f"setpoint[{other_index}]")
        other_gyro = numeric.get(f"gyroADC[{other_index}]")
        if other_setpoint is None or other_gyro is None or abs(other_setpoint) > 50.0:
            continue
        cross = builder["cross_axis"][other_axis]
        cross["samples"] += 1
        cross["gyro_sum_abs"] += abs(other_gyro)
        cross["gyro_max_abs"] = max(cross["gyro_max_abs"], abs(other_gyro))
        cross["setpoint_max_abs"] = max(cross["setpoint_max_abs"], abs(other_setpoint))
        for term, field_name in (("P", f"axisP[{other_index}]"), ("I", f"axisI[{other_index}]"), ("D", f"axisD[{other_index}]"), ("F", f"axisF[{other_index}]")):
            value = numeric.get(field_name)
            if value is None:
                continue
            abs_value = abs(value)
            cross["pid_abs_sums"][term] += abs_value
            cross["pid_abs_max"][term] = max(cross["pid_abs_max"][term], abs_value)
