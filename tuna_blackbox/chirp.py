from __future__ import annotations

from typing import Any

import numpy as np

from .common import AXES

MIN_CHIRP_SEGMENT_SECONDS = 1.0
MIN_CHIRP_SAMPLES = 32
COHERENCE_THRESHOLD = 0.3
GOOD_MEAN_COHERENCE = 0.7


def summarize_chirp_analysis(
    chirp_rows: list[dict[str, float | int]],
    fields: list[str],
    sample_rate_hz: float | None,
    csv_path: str,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    settings = settings or {}
    warnings: list[str] = []
    required = ["debug[0]", "debug[1]", "debug[2]", "debug[3]"]
    missing_debug = [name for name in required if name not in fields]
    missing_signals = [
        name
        for axis in AXES
        for name in (f"setpoint[{axis}]", f"gyroADC[{axis}]")
        if name not in fields
    ]
    debug_mode = settings.get("debug_mode")
    debug_mode_looks_chirp = debug_mode in ("CHIRP", "chirp", 97, "97")

    if missing_debug or missing_signals:
        reason = "missing_fields"
        if missing_debug:
            warnings.append("Missing CHIRP debug fields: " + ", ".join(missing_debug))
        if missing_signals:
            warnings.append("Missing chirp input/output fields: " + ", ".join(missing_signals))
        return {
            "available": False,
            "reason": reason,
            "debug_mode": debug_mode,
            "fields_present": {"debug": not missing_debug, "setpoint_gyro": not missing_signals},
            "segments": [],
            "axes": {},
            "warnings": warnings,
        }

    if debug_mode is not None and not debug_mode_looks_chirp:
        warnings.append(f"Log header debug_mode is {debug_mode!r}; expected CHIRP or numeric index 97 for supported firmware")

    segments = _find_segments(chirp_rows, csv_path)
    if not segments:
        return {
            "available": False,
            "reason": "no_active_chirp_segments",
            "debug_mode": debug_mode,
            "fields_present": {"debug": True, "setpoint_gyro": True},
            "segments": [],
            "axes": {},
            "warnings": warnings + ["No active chirp segments found from debug[1] axis markers"],
        }

    if sample_rate_hz is None or sample_rate_hz <= 0:
        return {
            "available": False,
            "reason": "missing_sample_rate",
            "debug_mode": debug_mode,
            "fields_present": {"debug": True, "setpoint_gyro": True},
            "segments": segments,
            "axes": {},
            "warnings": warnings + ["No logging rate available for chirp frequency-response analysis"],
        }

    axes: dict[str, Any] = {}
    analysis_warnings: list[str] = []
    for segment in segments:
        axis_name = segment["axis"]
        axis_index = segment["axis_index"]
        rows = chirp_rows[segment["start_index"] : segment["end_index"] + 1]
        if len(rows) < MIN_CHIRP_SAMPLES or segment["duration_seconds"] < MIN_CHIRP_SEGMENT_SECONDS:
            segment["usable"] = False
            segment["warning"] = "segment_too_short"
            analysis_warnings.append(f"{axis_name} chirp segment at {segment['start_time_seconds']:.2f}s is too short")
            continue
        setpoint = np.asarray([row[f"setpoint[{axis_index}]"] for row in rows], dtype=float)
        gyro = np.asarray([row[f"gyroADC[{axis_index}]"] for row in rows], dtype=float)
        try:
            tf = _welch_transfer_function(setpoint, gyro, sample_rate_hz)
        except ValueError as exc:
            segment["usable"] = False
            segment["warning"] = str(exc)
            continue
        metrics = _transfer_metrics(tf)
        motor_saturation_samples = sum(1 for row in rows if row.get("motor_saturated"))
        segment.update({
            "usable": True,
            "motor_saturation_samples": motor_saturation_samples,
            "frequency_response": metrics,
        })
        if motor_saturation_samples:
            analysis_warnings.append(f"{axis_name} chirp segment at {segment['start_time_seconds']:.2f}s has motor saturation samples")
        if (metrics.get("mean_coherence_5_100hz") or 0.0) < GOOD_MEAN_COHERENCE:
            analysis_warnings.append(f"{axis_name} chirp segment at {segment['start_time_seconds']:.2f}s has low mean coherence")
        axis_summary = axes.setdefault(axis_name, {"segments": 0, "usable_segments": 0, "mean_coherence_5_100hz": None, "bandwidth_hz": None, "resonant_peak_db": None, "phase_margin_deg": None})
        axis_summary["segments"] += 1
        axis_summary["usable_segments"] += 1
        _accumulate_axis(axis_summary, metrics)

    for axis_summary in axes.values():
        count = axis_summary.pop("_metric_count", 0)
        if count:
            for key in ("mean_coherence_5_100hz", "bandwidth_hz", "resonant_peak_db", "phase_margin_deg"):
                total_key = f"_{key}_sum"
                axis_summary[key] = axis_summary.pop(total_key) / count if total_key in axis_summary else None

    usable_count = sum(1 for segment in segments if segment.get("usable"))
    if usable_count == 0:
        warnings.append("No chirp segment was long enough for frequency-response analysis")
    present_axes = {segment["axis"] for segment in segments if segment.get("usable")}
    missing_axes = [axis for axis in AXES.values() if axis not in present_axes]
    if missing_axes:
        analysis_warnings.append("Missing usable chirp axes: " + ", ".join(missing_axes))

    warnings.extend(sorted(set(analysis_warnings)))
    confidence = _confidence(usable_count, present_axes, segments)

    return {
        "available": usable_count > 0,
        "reason": None if usable_count > 0 else "no_usable_segments",
        "confidence": confidence,
        "debug_mode": debug_mode,
        "settings": {key: settings[key] for key in sorted(settings) if key.startswith("chirp_") or key in {"debug_mode", "blackbox_high_resolution"}},
        "sample_rate_hz": sample_rate_hz,
        "segments": segments,
        "axes": axes,
        "warnings": warnings,
    }


def _find_segments(rows: list[dict[str, float | int]], csv_path: str) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for index, row in enumerate(rows):
        axis_value = int(round(float(row.get("debug[1]", -1))))
        axis_index = axis_value if axis_value in AXES else None
        if axis_index is None:
            if current is not None:
                _close_segment(current, rows[index - 1], index - 1, csv_path)
                segments.append(current)
                current = None
            continue
        if current is None or current["axis_index"] != axis_index:
            if current is not None:
                _close_segment(current, rows[index - 1], index - 1, csv_path)
                segments.append(current)
            current = {
                "axis_index": axis_index,
                "axis": AXES[axis_index],
                "start_index": index,
                "end_index": index,
                "start_row": int(row["_row"]),
                "end_row": int(row["_row"]),
                "start_time_seconds": float(row["time"]) / 1_000_000.0,
                "end_time_seconds": float(row["time"]) / 1_000_000.0,
                "samples": 1,
                "motor_saturation_samples": 0,
            }
        else:
            current["end_index"] = index
            current["end_row"] = int(row["_row"])
            current["end_time_seconds"] = float(row["time"]) / 1_000_000.0
            current["samples"] += 1
    if current is not None:
        _close_segment(current, rows[-1], len(rows) - 1, csv_path)
        segments.append(current)
    return segments


def _close_segment(segment: dict[str, Any], row: dict[str, float | int], end_index: int, csv_path: str) -> None:
    segment["end_index"] = end_index
    segment["end_row"] = int(row["_row"])
    segment["end_time_seconds"] = float(row["time"]) / 1_000_000.0
    segment["duration_seconds"] = max(0.0, segment["end_time_seconds"] - segment["start_time_seconds"])
    segment["raw_data_ref"] = {
        "csv_path": csv_path,
        "start_row": segment["start_row"],
        "end_row": segment["end_row"],
        "start_time_seconds": segment["start_time_seconds"],
        "end_time_seconds": segment["end_time_seconds"],
    }


def _welch_transfer_function(input_values: np.ndarray, output_values: np.ndarray, sample_rate_hz: float) -> dict[str, np.ndarray]:
    if input_values.size != output_values.size:
        raise ValueError("input_output_length_mismatch")
    if input_values.size < MIN_CHIRP_SAMPLES:
        raise ValueError("segment_too_short")
    segment_size = _choose_segment_size(input_values.size, sample_rate_hz)
    if segment_size < 16:
        raise ValueError("segment_too_short")
    hop = max(1, segment_size // 2)
    window = np.hanning(segment_size)
    starts = range(0, input_values.size - segment_size + 1, hop)
    num_bins = segment_size // 2 + 1
    sxx = np.zeros(num_bins, dtype=complex)
    syy = np.zeros(num_bins, dtype=complex)
    syx = np.zeros(num_bins, dtype=complex)
    segments = 0
    for start in starts:
        x = input_values[start : start + segment_size]
        y = output_values[start : start + segment_size]
        x = (x - np.mean(x)) * window
        y = (y - np.mean(y)) * window
        X = np.fft.rfft(x)
        Y = np.fft.rfft(y)
        sxx += X * np.conjugate(X)
        syy += Y * np.conjugate(Y)
        syx += Y * np.conjugate(X)
        segments += 1
    if segments == 0:
        raise ValueError("segment_too_short")
    sxx /= segments
    syy /= segments
    syx /= segments
    h = np.divide(syx, sxx, out=np.zeros(num_bins, dtype=complex), where=np.abs(sxx) > 1e-20)
    coherence = np.divide(np.abs(syx) ** 2, np.real(sxx) * np.real(syy), out=np.zeros(num_bins), where=(np.real(sxx) * np.real(syy)) > 1e-30)
    return {
        "frequencies": np.fft.rfftfreq(segment_size, d=1.0 / sample_rate_hz),
        "h": h,
        "magnitude_db": 20.0 * np.log10(np.maximum(np.abs(h), 1e-20)),
        "phase_deg": np.angle(h, deg=True),
        "coherence": np.clip(np.real(coherence), 0.0, 1.0),
        "fft_size": np.asarray(segment_size),
        "welch_segments": np.asarray(segments),
    }


def _choose_segment_size(sample_count: int, sample_rate_hz: float) -> int:
    target = max(64, int(sample_rate_hz * 0.5))
    size = 1
    while size < target:
        size <<= 1
    size = min(size, 4096)
    while size > sample_count:
        size >>= 1
    return size


def _transfer_metrics(tf: dict[str, np.ndarray]) -> dict[str, Any]:
    frequencies = tf["frequencies"]
    magnitude_db = tf["magnitude_db"]
    phase_deg = tf["phase_deg"]
    coherence = tf["coherence"]
    coherent = coherence >= COHERENCE_THRESHOLD
    mean_mask = (frequencies >= 5.0) & (frequencies <= 100.0)
    mean_coherence = float(np.mean(coherence[mean_mask])) if np.any(mean_mask) else None
    bandwidth = _find_crossing(frequencies, magnitude_db, coherent, -3.0)
    crossover = _find_crossing(frequencies, magnitude_db, coherent, 0.0)
    phase_margin = None
    if crossover is not None:
        phase_margin = 180.0 + _interp(frequencies, phase_deg, crossover)
    resonance_mask = (frequencies > 0.0) & (frequencies < 500.0) & coherent
    resonant_peak_db = None
    resonant_freq_hz = None
    if np.any(resonance_mask):
        indexes = np.where(resonance_mask)[0]
        index = indexes[int(np.argmax(magnitude_db[indexes]))]
        resonant_peak_db = float(magnitude_db[index])
        resonant_freq_hz = float(frequencies[index])
    return {
        "fft_size": int(tf["fft_size"]),
        "welch_segments": int(tf["welch_segments"]),
        "mean_coherence_5_100hz": mean_coherence,
        "bandwidth_hz": bandwidth,
        "gain_crossover_hz": crossover,
        "phase_margin_deg": phase_margin,
        "resonant_peak_db": resonant_peak_db,
        "resonant_frequency_hz": resonant_freq_hz,
    }


def _find_crossing(frequencies: np.ndarray, magnitude_db: np.ndarray, coherent: np.ndarray, target_db: float) -> float | None:
    for index in range(1, len(frequencies)):
        if not (coherent[index - 1] and coherent[index]):
            continue
        prev_mag = magnitude_db[index - 1]
        mag = magnitude_db[index]
        if mag <= target_db < prev_mag:
            frac = (target_db - prev_mag) / (mag - prev_mag) if mag != prev_mag else 0.0
            return float(frequencies[index - 1] + frac * (frequencies[index] - frequencies[index - 1]))
    return None


def _interp(x: np.ndarray, y: np.ndarray, target: float) -> float:
    return float(np.interp(target, x, y))


def _accumulate_axis(axis_summary: dict[str, Any], metrics: dict[str, Any]) -> None:
    axis_summary["_metric_count"] = axis_summary.get("_metric_count", 0) + 1
    for key in ("mean_coherence_5_100hz", "bandwidth_hz", "resonant_peak_db", "phase_margin_deg"):
        value = metrics.get(key)
        if value is not None and np.isfinite(value):
            axis_summary[f"_{key}_sum"] = axis_summary.get(f"_{key}_sum", 0.0) + float(value)


def _confidence(usable_count: int, present_axes: set[str], segments: list[dict[str, Any]]) -> str:
    if usable_count == 0:
        return "none"
    usable_segments = [segment for segment in segments if segment.get("usable")]
    if not usable_segments:
        return "none"
    coherence_values = [
        segment["frequency_response"].get("mean_coherence_5_100hz") or 0.0
        for segment in usable_segments
    ]
    min_coherence = min(coherence_values)
    has_saturation = any((segment.get("motor_saturation_samples") or 0) > 0 for segment in usable_segments)
    if len(present_axes) == 3 and min_coherence >= GOOD_MEAN_COHERENCE and not has_saturation:
        return "high"
    if min_coherence >= COHERENCE_THRESHOLD and not has_saturation:
        return "medium"
    return "low"
