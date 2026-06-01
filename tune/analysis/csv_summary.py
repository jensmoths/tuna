from __future__ import annotations

import csv
from pathlib import Path
from typing import Any


from .capabilities import summarize_analysis_capabilities as _analysis_capabilities
from .chirp import summarize_chirp_analysis as _summarize_chirp_analysis
from .common import (
    ACTIVE_MOTOR_THRESHOLD,
    ACTIVE_THROTTLE_THRESHOLD,
    AXES,
    GAP_MULTIPLIER,
    HIGH_RATE_THRESHOLD,
    MIN_SEGMENT_DURATION_US,
    MIN_USEFUL_DURATION_SECONDS,
    MOTOR_SATURATION_THRESHOLD,
    SEGMENT_GAP_US,
    SPECTRAL_PREFIXES,
    THROTTLE_PUNCH_THRESHOLD,
    TRACKING_THRESHOLD,
    empty_axis_metric as _empty_axis_metric,
    normalize_field as _normalize_field,
    throttle_bin_label as _throttle_bin_label,
    to_float as _to_float,
    track_range as _track_range,
    truthy_field as _truthy_field,
)
from .filters import summarize_filter_analysis as _summarize_filter_analysis
from .motors import summarize_motor_analysis as _summarize_motor_analysis
from .pid_terms import summarize_pid_term_analysis as _summarize_pid_term_analysis
from .spectrum import (
    summarize_frequency_throttle_heatmap as _summarize_frequency_throttle_heatmap,
    summarize_noise_peaks as _summarize_noise_peaks,
    summarize_rpm_analysis as _summarize_rpm_analysis,
    summarize_spectrum as _summarize_spectrum,
)
from .step_response import summarize_step_response as _summarize_step_response
from .timing import summarize_timing as _summarize_timing


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
    previous_time: float | None = None
    previous_time_row: int | None = None
    sample_intervals_us: list[float] = []
    time_intervals: list[tuple[int, int, float, float, float]] = []
    non_monotonic_time_samples = 0
    spectral_values: dict[str, list[float]] = {}
    heatmap_values: dict[str, dict[str, list[float]]] = {}
    armed_segments = []
    armed_builder = None
    detected_active_rows = 0
    active_detection_methods: set[str] = set()
    step_response_samples = {axis: [] for axis in AXES.values()}
    motor_values: dict[str, list[float]] = {}
    motor_throttle_bins: dict[str, dict[str, list[float]]] = {}
    pid_samples = {axis: [] for axis in AXES.values()}
    chirp_rows: list[dict[str, float | int]] = []
    blackbox_settings: dict[str, Any] = {}

    with csv_path.open(newline="", errors="replace") as handle:
        blackbox_settings, fields, reader = _iter_csv_data(handle)
        for raw_row in reader:
            row_count += 1
            if max_rows is not None and row_count > max_rows:
                warnings.append(f"Stopped after max_rows={max_rows}")
                row_count -= 1
                break

            row = raw_row
            time_value = _to_float(row.get("time", ""))
            if time_value is not None:
                first_time = time_value if first_time is None else first_time
                last_time = time_value
                if previous_time is not None:
                    interval_us = time_value - previous_time
                    if interval_us > 0:
                        sample_intervals_us.append(interval_us)
                        if previous_time_row is not None:
                            time_intervals.append((previous_time_row, row_count, previous_time, time_value, interval_us))
                    else:
                        non_monotonic_time_samples += 1
                previous_time = time_value
                previous_time_row = row_count

            numeric: dict[str, float] = {}
            deltas: dict[str, float] = {}
            for name, value_text in row.items():
                if not name.startswith(("gyroADC[", "gyroUnfilt[", "setpoint[", "motor[", "axisP[", "axisI[", "axisD[", "axisF[", "rcCommand[", "debug[")):
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
                if name.startswith(("gyroADC[", "gyroUnfilt[", "axisD[")):
                    previous = previous_values.get(name)
                    if previous is not None:
                        acc = rough_noise_acc.setdefault(name, {"samples": 0, "sum_abs_delta": 0.0, "max_abs_delta": 0.0})
                        delta = abs(value - previous)
                        deltas[name] = delta
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
                explicit_armed = None
                for armed_field in ("armed", "isArmed", "armState"):
                    if armed_field in row:
                        explicit_armed = _truthy_field(row.get(armed_field))
                        if explicit_armed is not None:
                            break
                throttle = numeric.get("rcCommand[3]")
                motor_active = any(name.startswith("motor[") and value > ACTIVE_MOTOR_THRESHOLD for name, value in numeric.items())
                throttle_active_for_flight = throttle is not None and throttle > ACTIVE_THROTTLE_THRESHOLD
                active_flight = explicit_armed if explicit_armed is not None else motor_active or throttle_active_for_flight
                if active_flight:
                    current_detection_method = "explicit_armed_field" if explicit_armed is not None else "motor_or_throttle_activity"
                    detected_active_rows += 1
                    active_detection_methods.add(current_detection_method)
                    if armed_builder is None or time_value - armed_builder["last_time_us"] > SEGMENT_GAP_US:
                        if armed_builder is not None:
                            armed_segments.append(armed_builder)
                        armed_builder = {
                            "start_time_us": time_value,
                            "end_time_us": time_value,
                            "last_time_us": time_value,
                            "start_row": row_count,
                            "end_row": row_count,
                            "samples": 0,
                            "detection_methods": set(),
                        }
                    armed_builder["end_time_us"] = time_value
                    armed_builder["last_time_us"] = time_value
                    armed_builder["end_row"] = row_count
                    armed_builder["samples"] += 1
                    armed_builder["detection_methods"].add(current_detection_method)

                if throttle is not None:
                    throttle_bin = _throttle_bin_label(throttle)
                    if throttle_bin is not None:
                        for name, value in numeric.items():
                            if name.startswith(SPECTRAL_PREFIXES):
                                heatmap_values.setdefault(name, {}).setdefault(throttle_bin, []).append(value)
                            if name.startswith("motor["):
                                motor_throttle_bins.setdefault(name, {}).setdefault(throttle_bin, []).append(value)

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
                    if any(pid_sample[term] is not None for term in ("P", "I", "D", "F")):
                        pid_samples[axis].append(pid_sample)
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
                            }
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
                        delta = deltas.get(f"gyroADC[{index}]")
                        if delta is not None:
                            builder["gyro_sum_abs_delta"] += delta
                            builder["gyro_max_abs_delta"] = max(builder["gyro_max_abs_delta"], delta)
                            builder["gyro_delta_samples"] += 1
                        delta = deltas.get(f"axisD[{index}]")
                        if delta is not None:
                            builder["dterm_sum_abs_delta"] += delta
                            builder["dterm_max_abs_delta"] = max(builder["dterm_max_abs_delta"], delta)
                            builder["dterm_delta_samples"] += 1
                        if saturated_this_row:
                            builder["motor_saturation_samples"] += 1
                        high_rate_builders[axis] = builder

                if time_value is not None:
                    chirp_row: dict[str, float | int] = {"_row": row_count, "time": time_value}
                    has_chirp_values = True
                    for field in (
                        "debug[0]", "debug[1]", "debug[2]", "debug[3]",
                        "setpoint[0]", "setpoint[1]", "setpoint[2]",
                        "gyroADC[0]", "gyroADC[1]", "gyroADC[2]",
                    ):
                        value = numeric.get(field)
                        if value is None:
                            has_chirp_values = False
                            break
                        chirp_row[field] = value
                    if has_chirp_values:
                        chirp_rows.append(chirp_row)

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
                            "start_row": row_count,
                            "end_row": row_count,
                            "throttle_start": throttle,
                            "throttle_peak": throttle,
                            "motor_saturation_samples": 0,
                        }
                    throttle_builder["end_time_us"] = time_value
                    throttle_builder["last_time_us"] = time_value
                    throttle_builder["end_row"] = row_count
                    throttle_builder["samples"] += 1
                    throttle_builder["throttle_peak"] = max(throttle_builder["throttle_peak"], throttle)
                    if saturated_this_row:
                        throttle_builder["motor_saturation_samples"] += 1

    for builder in high_rate_builders.values():
        if builder is not None:
            high_rate_segments.append(builder)
    if throttle_builder is not None:
        throttle_segments.append(throttle_builder)
    if armed_builder is not None:
        armed_segments.append(armed_builder)

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
            item["raw_data_ref"] = {
                "csv_path": str(csv_path),
                "start_row": item.get("start_row"),
                "end_row": item.get("end_row"),
                "start_time_seconds": item["start_time_seconds"],
                "end_time_seconds": item["end_time_seconds"],
            }
            if "tracking_sum_abs_error" in item:
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
            finished.append(item)
        return finished

    high_rate_segments = finish_segments(high_rate_segments)
    throttle_segments = finish_segments(throttle_segments)

    def finish_armed_segments(segments):
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
                "raw_data_ref": {
                    "csv_path": str(csv_path),
                    "start_row": segment["start_row"],
                    "end_row": segment["end_row"],
                    "start_time_seconds": start_time_seconds,
                    "end_time_seconds": end_time_seconds,
                },
            }
            finished.append(item)
        return finished

    armed_segments = finish_armed_segments(armed_segments)

    required = ["time", "gyroADC[0]", "gyroADC[1]", "gyroADC[2]", "setpoint[0]", "setpoint[1]", "setpoint[2]"]
    missing = [name for name in required if name not in fields]
    if missing:
        warnings.append("Missing expected fields: " + ", ".join(missing))

    duration_seconds = None
    if first_time is not None and last_time is not None and last_time >= first_time:
        duration_seconds = (last_time - first_time) / 1_000_000.0

    timing = _summarize_timing(sample_intervals_us, duration_seconds, row_count)
    if timing["nominal_interval_us"] is not None:
        gap_threshold_us = float(timing["nominal_interval_us"]) * GAP_MULTIPLIER
        gaps = []
        for start_row, end_row, start_time, end_time, interval_us in time_intervals:
            if interval_us > gap_threshold_us:
                estimated_missing = max(1, round(interval_us / float(timing["nominal_interval_us"])) - 1)
                gaps.append({
                    "start_row": start_row,
                    "end_row": end_row,
                    "start_time_seconds": start_time / 1_000_000.0,
                    "end_time_seconds": end_time / 1_000_000.0,
                    "duration_seconds": interval_us / 1_000_000.0,
                    "estimated_missing_samples": estimated_missing,
                })
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
    spectrum = _summarize_spectrum(spectral_values, timing["nominal_logging_rate_hz"])
    frequency_throttle_heatmap = _summarize_frequency_throttle_heatmap(heatmap_values, timing["nominal_logging_rate_hz"], "rcCommand[3]" in fields)
    filter_analysis = _summarize_filter_analysis(spectral_values, timing["nominal_logging_rate_hz"])
    noise_peaks = _summarize_noise_peaks(spectrum)
    rpm_analysis = _summarize_rpm_analysis(spectrum)
    step_response = _summarize_step_response(step_response_samples)
    motor_analysis = _summarize_motor_analysis(motor_values, motor_throttle_bins)
    pid_term_analysis = _summarize_pid_term_analysis(pid_samples, step_response)
    capabilities = _analysis_capabilities(fields, timing)
    chirp_analysis = _summarize_chirp_analysis(
        chirp_rows,
        fields,
        timing["nominal_logging_rate_hz"],
        str(csv_path),
        blackbox_settings,
    )

    active_window = None
    if armed_segments:
        active_start = armed_segments[0]
        active_end = armed_segments[-1]
        leading_idle_rows = max(0, active_start["start_row"] - 1)
        trailing_idle_rows = max(0, row_count - active_end["end_row"])
        active_window = {
            "start_row": active_start["start_row"],
            "end_row": active_end["end_row"],
            "start_time_seconds": active_start["start_time_seconds"],
            "end_time_seconds": active_end["end_time_seconds"],
            "duration_seconds": active_end["end_time_seconds"] - active_start["start_time_seconds"],
            "leading_idle_rows": leading_idle_rows,
            "trailing_idle_rows": trailing_idle_rows,
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

    has_motor = any(field.startswith("motor[") for field in fields)
    has_pid_terms = all(any(field.startswith(prefix) for field in fields) for prefix in ("axisP[", "axisI[", "axisD["))
    quality_warnings = list(warnings)
    if duration_seconds is None or duration_seconds < MIN_USEFUL_DURATION_SECONDS:
        quality_warnings.append("Blackbox Log duration is short for tuning analysis")
    if not has_motor:
        quality_warnings.append("No motor fields found")
    if not has_pid_terms:
        quality_warnings.append("PID term fields are incomplete")
    if timing["gap_count"]:
        quality_warnings.append(
            f"Detected {timing['gap_count']} timing gap/dropout(s); estimated {timing['estimated_missing_samples']} missing sample(s)"
        )
    if non_monotonic_time_samples:
        quality_warnings.append(f"Detected {non_monotonic_time_samples} non-monotonic timestamp sample(s)")

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
        "blackbox_settings": blackbox_settings,
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
        "flight": {
            "active_window": active_window,
            "armed_segments": armed_segments,
            "detected_active_rows": detected_active_rows,
            "detection_methods": sorted(active_detection_methods),
        },
        "analysis_capabilities": capabilities,
        "timing": timing,
        "tracking": tracking,
        "rough_noise": rough_noise,
        "spectrum": spectrum,
        "frequency_throttle_heatmap": frequency_throttle_heatmap,
        "filter_analysis": filter_analysis,
        "noise_peaks": noise_peaks,
        "rpm_analysis": rpm_analysis,
        "step_response": step_response,
        "motor_analysis": motor_analysis,
        "pid_term_analysis": pid_term_analysis,
        "chirp_analysis": chirp_analysis,
        "segments": {
            "high_rate": high_rate_segments,
            "throttle_punch": throttle_segments,
        },
        "warnings": warnings,
    }
