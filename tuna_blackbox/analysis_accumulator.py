from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .analysis_rows import chirp_row as _chirp_row
from .analysis_rows import extract_numeric_fields as _extract_numeric_fields
from .analysis_rows import motor_saturated as _motor_saturated
from .analysis_rows import record_axis_samples as _record_axis_samples
from .analysis_rows import record_throttle_bins as _record_throttle_bins
from .analysis_rows import update_armed_builder as _update_armed_builder
from .analysis_rows import update_axis_overview as _update_axis_overview
from .analysis_rows import update_throttle_chop_builder as _update_throttle_chop_builder
from .analysis_rows import update_throttle_punch_builder as _update_throttle_punch_builder
from .analysis_segments import finish_armed_segments as _finish_armed_segments
from .analysis_segments import finish_segments as _finish_segments
from .analysis_segments import finish_throttle_chop_segments as _finish_throttle_chop_segments
from .analysis_high_rate import update_high_rate_segments as _update_high_rate_segments
from .analysis_summary import active_window as _active_window
from .analysis_summary import add_timing_gaps as _add_timing_gaps
from .analysis_summary import cross_axis_flip_analysis as _cross_axis_flip_analysis
from .analysis_summary import quality_warnings as _quality_warnings
from .analysis_summary import rough_noise_summary as _rough_noise_summary
from .analysis_summary import throttle_chop_analysis as _throttle_chop_analysis
from .analysis_summary import tracking_summary as _tracking_summary
from .analysis_views import config_snapshot as _config_snapshot
from .capabilities import summarize_analysis_capabilities as _analysis_capabilities
from .chirp import summarize_chirp_analysis as _summarize_chirp_analysis
from .common import AXES, MIN_USEFUL_DURATION_SECONDS, to_float as _to_float, truthy_field as _truthy_field
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


def _axis_counts() -> dict[str, int]:
    return {axis: 0 for axis in AXES.values()}


def _axis_floats() -> dict[str, float]:
    return {axis: 0.0 for axis in AXES.values()}


def _tracking_accumulators() -> dict[str, dict[str, Any]]:
    return {axis: {"samples": 0, "sum_abs_error": 0.0, "max_abs_error": 0.0, "samples_over_threshold": 0} for axis in AXES.values()}


def _axis_lists() -> dict[str, list[Any]]:
    return {axis: [] for axis in AXES.values()}


def _high_rate_builders() -> dict[str, dict[str, Any] | None]:
    return {axis: None for axis in AXES.values()}


@dataclass
class BlackboxAnalysisAccumulator:
    csv_path: Path
    fields: list[str]
    blackbox_settings: dict[str, Any]
    warnings: list[str] = field(default_factory=list)
    ranges: dict[str, dict[str, float]] = field(default_factory=dict)
    first_time: float | None = None
    last_time: float | None = None
    row_count: int = 0
    high_rate_samples: dict[str, int] = field(default_factory=_axis_counts)
    max_abs_setpoint: dict[str, float] = field(default_factory=_axis_floats)
    motor_saturation_samples: int = 0
    tracking_acc: dict[str, dict[str, Any]] = field(default_factory=_tracking_accumulators)
    previous_values: dict[str, float] = field(default_factory=dict)
    rough_noise_acc: dict[str, dict[str, float | int]] = field(default_factory=dict)
    high_rate_builders: dict[str, dict[str, Any] | None] = field(default_factory=_high_rate_builders)
    high_rate_segments: list[dict[str, Any]] = field(default_factory=list)
    throttle_builder: dict[str, Any] | None = None
    throttle_segments: list[dict[str, Any]] = field(default_factory=list)
    previous_time: float | None = None
    previous_time_row: int | None = None
    sample_intervals_us: list[float] = field(default_factory=list)
    time_intervals: list[tuple[int, int, float, float, float]] = field(default_factory=list)
    non_monotonic_time_samples: int = 0
    spectral_values: dict[str, list[float]] = field(default_factory=dict)
    heatmap_values: dict[str, dict[str, list[float]]] = field(default_factory=dict)
    armed_segments: list[dict[str, Any]] = field(default_factory=list)
    armed_builder: dict[str, Any] | None = None
    detected_active_rows: int = 0
    active_detection_methods: set[str] = field(default_factory=set)
    step_response_samples: dict[str, list[Any]] = field(default_factory=_axis_lists)
    motor_values: dict[str, list[float]] = field(default_factory=dict)
    motor_throttle_bins: dict[str, dict[str, list[float]]] = field(default_factory=dict)
    pid_samples: dict[str, list[Any]] = field(default_factory=_axis_lists)
    chirp_rows: list[dict[str, float | int]] = field(default_factory=list)
    throttle_chop_segments: list[dict[str, Any]] = field(default_factory=list)
    throttle_chop_builder: dict[str, Any] | None = None
    previous_throttle_for_chop: float | None = None

    def process_row(self, row: dict[str, str], *, max_rows: int | None = None) -> bool:
        self.row_count += 1
        if max_rows is not None and self.row_count > max_rows:
            self.warnings.append(f"Stopped after max_rows={max_rows}")
            self.row_count -= 1
            return False

        time_value = _to_float(row.get("time", ""))
        self._record_timing(time_value)
        numeric, deltas = _extract_numeric_fields(
            row,
            spectral_values=self.spectral_values,
            motor_values=self.motor_values,
            ranges=self.ranges,
            previous_values=self.previous_values,
            rough_noise_acc=self.rough_noise_acc,
        )
        _update_axis_overview(
            numeric,
            max_abs_setpoint=self.max_abs_setpoint,
            high_rate_samples=self.high_rate_samples,
            tracking_acc=self.tracking_acc,
        )
        saturated_this_row = _motor_saturated(numeric)
        if saturated_this_row:
            self.motor_saturation_samples += 1
        if time_value is not None:
            self._process_timed_row(row, time_value, numeric, deltas, saturated_this_row)
        return True

    def finalize(self) -> dict[str, Any]:
        self._finish_open_builders()
        high_rate_segments = _finish_segments(self.high_rate_segments, self.csv_path)
        throttle_segments = _finish_segments(self.throttle_segments, self.csv_path)
        throttle_chop_segments = _finish_throttle_chop_segments(self.throttle_chop_segments, self.csv_path)
        armed_segments = _finish_armed_segments(self.armed_segments, self.csv_path)
        self._add_missing_field_warnings()

        duration_seconds = self._duration_seconds()
        timing = _summarize_timing(self.sample_intervals_us, duration_seconds, self.row_count)
        _add_timing_gaps(timing, self.time_intervals, self.non_monotonic_time_samples)
        spectrum = _summarize_spectrum(self.spectral_values, timing["nominal_logging_rate_hz"])
        step_response = _summarize_step_response(self.step_response_samples)
        chirp_analysis = _summarize_chirp_analysis(
            self.chirp_rows,
            self.fields,
            timing["nominal_logging_rate_hz"],
            str(self.csv_path),
            self.blackbox_settings,
        )
        has_motor = any(field.startswith("motor[") for field in self.fields)
        has_pid_terms = all(any(field.startswith(prefix) for field in self.fields) for prefix in ("axisP[", "axisI[", "axisD["))
        quality_warnings = _quality_warnings(
            self.warnings,
            duration_seconds=duration_seconds,
            has_motor=has_motor,
            has_pid_terms=has_pid_terms,
            timing=timing,
            non_monotonic_time_samples=self.non_monotonic_time_samples,
        )
        return {
            "csv_path": str(self.csv_path),
            "row_count": self.row_count,
            "fields": self.fields,
            "field_count": len(self.fields),
            "blackbox_settings": self.blackbox_settings,
            "config_snapshot": _config_snapshot({"blackbox_settings": self.blackbox_settings}),
            "start_time_seconds": self.first_time / 1_000_000.0 if self.first_time is not None else None,
            "end_time_seconds": self.last_time / 1_000_000.0 if self.last_time is not None else None,
            "duration_seconds": duration_seconds,
            "ranges": self.ranges,
            "quality": {
                "usable": not quality_warnings,
                "duration_ok": duration_seconds is not None and duration_seconds >= MIN_USEFUL_DURATION_SECONDS,
                "has_gyro": all(f"gyroADC[{i}]" in self.fields for i in AXES),
                "has_setpoint": all(f"setpoint[{i}]" in self.fields for i in AXES),
                "has_motor": has_motor,
                "has_pid_terms": has_pid_terms,
                "warnings": quality_warnings,
            },
            "activity": {
                "max_abs_setpoint": self.max_abs_setpoint,
                "high_rate_samples": self.high_rate_samples,
                "motor_saturation_samples": self.motor_saturation_samples,
                "throttle_range": self.ranges.get("rcCommand[3]"),
            },
            "flight": {
                "active_window": _active_window(armed_segments, row_count=self.row_count, first_time=self.first_time, last_time=self.last_time, csv_path=self.csv_path),
                "armed_segments": armed_segments,
                "detected_active_rows": self.detected_active_rows,
                "detection_methods": sorted(self.active_detection_methods),
            },
            "analysis_capabilities": _analysis_capabilities(self.fields, timing),
            "timing": timing,
            "tracking": _tracking_summary(self.tracking_acc),
            "rough_noise": _rough_noise_summary(self.rough_noise_acc),
            "spectrum": spectrum,
            "frequency_throttle_heatmap": _summarize_frequency_throttle_heatmap(self.heatmap_values, timing["nominal_logging_rate_hz"], "rcCommand[3]" in self.fields),
            "filter_analysis": _summarize_filter_analysis(self.spectral_values, timing["nominal_logging_rate_hz"]),
            "noise_peaks": _summarize_noise_peaks(spectrum),
            "rpm_analysis": _summarize_rpm_analysis(spectrum),
            "step_response": step_response,
            "motor_analysis": _summarize_motor_analysis(self.motor_values, self.motor_throttle_bins),
            "pid_term_analysis": _summarize_pid_term_analysis(self.pid_samples, step_response),
            "chirp_analysis": chirp_analysis,
            "throttle_chop_analysis": _throttle_chop_analysis(throttle_chop_segments, self.fields),
            "cross_axis_flip_analysis": _cross_axis_flip_analysis(high_rate_segments),
            "segments": {
                "high_rate": high_rate_segments,
                "throttle_punch": throttle_segments,
                "throttle_chop": throttle_chop_segments,
                "chirp": chirp_analysis.get("segments", []),
            },
            "warnings": self.warnings,
        }

    def _record_timing(self, time_value: float | None) -> None:
        if time_value is None:
            return
        self.first_time = time_value if self.first_time is None else self.first_time
        self.last_time = time_value
        if self.previous_time is not None:
            interval_us = time_value - self.previous_time
            if interval_us > 0:
                self.sample_intervals_us.append(interval_us)
                if self.previous_time_row is not None:
                    self.time_intervals.append((self.previous_time_row, self.row_count, self.previous_time, time_value, interval_us))
            else:
                self.non_monotonic_time_samples += 1
        self.previous_time = time_value
        self.previous_time_row = self.row_count

    def _process_timed_row(
        self,
        row: dict[str, str],
        time_value: float,
        numeric: dict[str, float],
        deltas: dict[str, float],
        saturated_this_row: bool,
    ) -> None:
        throttle = numeric.get("rcCommand[3]")
        self.armed_builder, detection_method = _update_armed_builder(
            row=row,
            numeric=numeric,
            time_value=time_value,
            row_count=self.row_count,
            builder=self.armed_builder,
            segments=self.armed_segments,
            truthy_field=_truthy_field,
        )
        if detection_method is not None:
            self.detected_active_rows += 1
            self.active_detection_methods.add(detection_method)
        self.throttle_chop_builder = _update_throttle_chop_builder(
            time_value=time_value,
            row_count=self.row_count,
            throttle=throttle,
            numeric=numeric,
            previous_throttle=self.previous_throttle_for_chop,
            builder=self.throttle_chop_builder,
            segments=self.throttle_chop_segments,
        )
        if throttle is not None:
            self.previous_throttle_for_chop = throttle
        _record_throttle_bins(
            throttle,
            numeric,
            heatmap_values=self.heatmap_values,
            motor_throttle_bins=self.motor_throttle_bins,
        )
        _record_axis_samples(
            time_value=time_value,
            throttle=throttle,
            numeric=numeric,
            step_response_samples=self.step_response_samples,
            pid_samples=self.pid_samples,
        )
        _update_high_rate_segments(
            high_rate_builders=self.high_rate_builders,
            high_rate_segments=self.high_rate_segments,
            row_count=self.row_count,
            time_value=time_value,
            numeric=numeric,
            deltas=deltas,
            saturated_this_row=saturated_this_row,
        )
        chirp_row = _chirp_row(self.row_count, time_value, numeric, saturated_this_row)
        if chirp_row is not None:
            self.chirp_rows.append(chirp_row)
        self.throttle_builder = _update_throttle_punch_builder(
            time_value=time_value,
            row_count=self.row_count,
            throttle=throttle,
            saturated_this_row=saturated_this_row,
            builder=self.throttle_builder,
            segments=self.throttle_segments,
        )

    def _finish_open_builders(self) -> None:
        for builder in self.high_rate_builders.values():
            if builder is not None:
                self.high_rate_segments.append(builder)
        if self.throttle_builder is not None:
            self.throttle_segments.append(self.throttle_builder)
        if self.throttle_chop_builder is not None:
            self.throttle_chop_segments.append(self.throttle_chop_builder)
        if self.armed_builder is not None:
            self.armed_segments.append(self.armed_builder)

    def _add_missing_field_warnings(self) -> None:
        required = ["time", "gyroADC[0]", "gyroADC[1]", "gyroADC[2]", "setpoint[0]", "setpoint[1]", "setpoint[2]"]
        missing = [name for name in required if name not in self.fields]
        if missing:
            self.warnings.append("Missing expected fields: " + ", ".join(missing))

    def _duration_seconds(self) -> float | None:
        if self.first_time is None or self.last_time is None or self.last_time < self.first_time:
            return None
        return (self.last_time - self.first_time) / 1_000_000.0

