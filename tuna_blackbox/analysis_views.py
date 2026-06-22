from __future__ import annotations

from typing import Any

CONFIG_KEYS = (
    "pid_profile",
    "rate_profile",
    "debug_mode",
    "blackbox_rate_num",
    "blackbox_rate_denom",
    "blackbox_high_resolution",
    "rollPID",
    "pitchPID",
    "yawPID",
    "levelPID",
    "roll_rate",
    "pitch_rate",
    "yaw_rate",
    "roll_expo",
    "pitch_expo",
    "yaw_expo",
    "rates_type",
    "d_min_roll",
    "d_min_pitch",
    "d_min_yaw",
    "d_max_roll",
    "d_max_pitch",
    "d_max_yaw",
    "gyro_lowpass_hz",
    "gyro_lowpass2_hz",
    "gyro_notch_hz",
    "gyro_notch_cutoff_hz",
    "dyn_notch_count",
    "dyn_notch_q",
    "dyn_notch_min_hz",
    "dyn_notch_max_hz",
    "rpm_filter_harmonics",
    "rpm_filter_q",
    "rpm_filter_min_hz",
    "dterm_lowpass_hz",
    "dterm_lowpass2_hz",
    "dterm_notch_hz",
    "dterm_notch_cutoff_hz",
    "anti_gravity_gain",
    "anti_gravity_cutoff_hz",
    "throttle_boost",
    "pid_at_min_throttle",
    "iterm_windup",
    "iterm_relax",
    "iterm_relax_cutoff",
    "motor_idle",
    "motor_idle_percent",
    "motor_output_limit",
    "min_throttle",
    "max_throttle",
    "min_command",
)


def config_snapshot(analysis: dict[str, Any]) -> dict[str, Any]:
    settings = analysis.get("blackbox_settings") if isinstance(analysis.get("blackbox_settings"), dict) else {}
    snapshot = {key: settings[key] for key in CONFIG_KEYS if key in settings}
    pids = {key: settings[key] for key in ("rollPID", "pitchPID", "yawPID", "levelPID") if key in settings}
    return {"available": bool(snapshot), "pids": pids, "settings": snapshot}


def compact_analysis(analysis: dict[str, Any]) -> dict[str, Any]:
    return {
        "csv_path": analysis.get("csv_path"),
        "row_count": analysis.get("row_count"),
        "duration_seconds": analysis.get("duration_seconds"),
        "quality": analysis.get("quality"),
        "warnings": analysis.get("warnings", []),
        "activity": analysis.get("activity"),
        "flight": analysis.get("flight"),
        "config_snapshot": analysis.get("config_snapshot") or config_snapshot(analysis),
    }


def recording_summary(analysis: dict[str, Any]) -> dict[str, Any]:
    flight = analysis.get("flight") if isinstance(analysis.get("flight"), dict) else {}
    active_window = flight.get("active_window") if isinstance(flight.get("active_window"), dict) else None
    return {
        "csv_path": analysis.get("csv_path"),
        "row_count": analysis.get("row_count"),
        "duration_seconds": analysis.get("duration_seconds"),
        "start_time_seconds": analysis.get("start_time_seconds", active_window.get("start_time_seconds") if active_window else None),
        "activity": analysis.get("activity"),
        "detected_active_rows": flight.get("detected_active_rows"),
        "quality": analysis.get("quality"),
        "config_snapshot": analysis.get("config_snapshot") or config_snapshot(analysis),
    }


def _metric_delta(before: Any, after: Any) -> dict[str, Any] | None:
    if before is None and after is None:
        return None
    delta = after - before if isinstance(before, (int, float)) and isinstance(after, (int, float)) else None
    return {"before": before, "after": after, "delta": delta}


def _nested_get(payload: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = payload
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _changed_settings(before: dict[str, Any], after: dict[str, Any]) -> dict[str, dict[str, Any]]:
    before_settings = (before.get("config_snapshot") or config_snapshot(before)).get("settings", {})
    after_settings = (after.get("config_snapshot") or config_snapshot(after)).get("settings", {})
    keys = sorted(set(before_settings) | set(after_settings))
    return {
        key: {"before": before_settings.get(key), "after": after_settings.get(key)}
        for key in keys
        if before_settings.get(key) != after_settings.get(key)
    }


def compare_analyses(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    axes = ("roll", "pitch", "yaw")
    tracking = {
        axis: {
            "mean_abs_error": _metric_delta(
                _nested_get(before, ("tracking", axis, "mean_abs_error")),
                _nested_get(after, ("tracking", axis, "mean_abs_error")),
            ),
            "max_abs_error": _metric_delta(
                _nested_get(before, ("tracking", axis, "max_abs_error")),
                _nested_get(after, ("tracking", axis, "max_abs_error")),
            ),
        }
        for axis in axes
    }
    pid_terms: dict[str, Any] = {}
    for axis in axes:
        axis_terms: dict[str, Any] = {}
        for term in ("P", "I", "D"):
            axis_terms[term] = {
                "mean_abs": _metric_delta(
                    _nested_get(before, ("pid_term_analysis", "axes", axis, "terms", term, "mean_abs")),
                    _nested_get(after, ("pid_term_analysis", "axes", axis, "terms", term, "mean_abs")),
                ),
                "max_abs": _metric_delta(
                    _nested_get(before, ("pid_term_analysis", "axes", axis, "terms", term, "max_abs")),
                    _nested_get(after, ("pid_term_analysis", "axes", axis, "terms", term, "max_abs")),
                ),
            }
        pid_terms[axis] = axis_terms

    segment_counts = {}
    for kind in sorted(set((before.get("segments") or {}).keys()) | set((after.get("segments") or {}).keys())):
        b_items = before.get("segments", {}).get(kind, []) if isinstance(before.get("segments"), dict) else []
        a_items = after.get("segments", {}).get(kind, []) if isinstance(after.get("segments"), dict) else []
        segment_counts[kind] = _metric_delta(len(b_items) if isinstance(b_items, list) else None, len(a_items) if isinstance(a_items, list) else None)

    return {
        "before": {"csv_path": before.get("csv_path"), "duration_seconds": before.get("duration_seconds")},
        "after": {"csv_path": after.get("csv_path"), "duration_seconds": after.get("duration_seconds")},
        "config_changes": _changed_settings(before, after),
        "saturation_changes": {
            "motor_saturation_samples": _metric_delta(
                _nested_get(before, ("activity", "motor_saturation_samples")),
                _nested_get(after, ("activity", "motor_saturation_samples")),
            ),
            "motor_near_max_samples": _metric_delta(
                _nested_get(before, ("motor_analysis", "summary", "total_near_max_samples")),
                _nested_get(after, ("motor_analysis", "summary", "total_near_max_samples")),
            ),
        },
        "tracking_changes": tracking,
        "pid_term_changes": pid_terms,
        "step_response_changes": _step_response_changes(before, after, axes),
        "filter_changes": _filter_changes(before, after, axes),
        "noise_changes": _noise_changes(before, after),
        "rpm_filter_changes": {
            "harmonic_match_count": _metric_delta(
                len(_nested_get(before, ("rpm_analysis", "possible_harmonic_matches")) or []),
                len(_nested_get(after, ("rpm_analysis", "possible_harmonic_matches")) or []),
            ),
            "warnings": {"before": _nested_get(before, ("rpm_analysis", "warnings")), "after": _nested_get(after, ("rpm_analysis", "warnings"))},
        },
        "propwash_changes": _propwash_changes(before, after),
        "chirp_changes": _chirp_changes(before, after, axes),
        "outcome_summary": _outcome_summary(before, after, axes),
        "segment_count_changes": segment_counts,
        "tuning_evidence_changes": {
            "filter": {
                axis: {
                    "before": _nested_get(before, ("tuning_evidence", "filter_diagnosis", "axes", axis, "classification")),
                    "after": _nested_get(after, ("tuning_evidence", "filter_diagnosis", "axes", axis, "classification")),
                }
                for axis in axes
            },
            "pid_response": {
                axis: {
                    "before": _nested_get(before, ("tuning_evidence", "pid_response", "axes", axis, "classifications")),
                    "after": _nested_get(after, ("tuning_evidence", "pid_response", "axes", axis, "classifications")),
                }
                for axis in axes
            },
        },
        "quality": {"before": before.get("quality"), "after": after.get("quality")},
    }


def filter_evidence_view(analysis: dict[str, Any]) -> dict[str, Any]:
    tuning_evidence = _tuning_evidence(analysis)
    return {
        "filter_diagnosis": tuning_evidence.get("filter_diagnosis"),
        "filter_analysis": analysis.get("filter_analysis"),
        "active_filter_analysis": _nested_get(analysis, ("active_analysis", "filter_analysis")),
        "rpm_analysis": analysis.get("rpm_analysis"),
        "noise_peaks": limited_events(analysis.get("noise_peaks", {}), "peaks", 8),
        "capture_plan": tuning_evidence.get("capture_plan"),
    }


def pid_response_view(analysis: dict[str, Any]) -> dict[str, Any]:
    tuning_evidence = _tuning_evidence(analysis)
    return {
        "pid_response": tuning_evidence.get("pid_response"),
        "step_response": analysis.get("step_response"),
        "pid_term_analysis": analysis.get("pid_term_analysis"),
        "active_step_response": _nested_get(analysis, ("active_analysis", "step_response")),
        "active_pid_term_analysis": _nested_get(analysis, ("active_analysis", "pid_term_analysis")),
    }


def noise_peak_view(analysis: dict[str, Any], limit: int = 8) -> dict[str, Any]:
    return {
        "noise_peaks": limited_events(analysis.get("noise_peaks", {}), "peaks", limit),
        "active_noise_peaks": limited_events(_nested_get(analysis, ("active_analysis", "noise_peaks")) or {}, "peaks", limit),
        "spectrum_warnings": _nested_get(analysis, ("spectrum", "warnings")),
    }


def rpm_filter_view(analysis: dict[str, Any]) -> dict[str, Any]:
    tuning_evidence = _tuning_evidence(analysis)
    return {
        "rpm_analysis": analysis.get("rpm_analysis"),
        "windowed_frequency_throttle_heatmap": analysis.get("windowed_frequency_throttle_heatmap"),
        "filter_diagnosis": tuning_evidence.get("filter_diagnosis"),
    }


def propwash_view(analysis: dict[str, Any], limit: int = 5) -> dict[str, Any]:
    return limited_events(analysis.get("propwash_analysis", {}), "segments", limit)


def capture_plan_view(analysis: dict[str, Any]) -> dict[str, Any]:
    return _tuning_evidence(analysis).get("capture_plan") or {}


def _tuning_evidence(analysis: dict[str, Any]) -> dict[str, Any]:
    evidence = analysis.get("tuning_evidence")
    if isinstance(evidence, dict):
        return evidence
    from .evidence import build_tuning_evidence

    return build_tuning_evidence(analysis)


def _step_response_changes(before: dict[str, Any], after: dict[str, Any], axes: tuple[str, ...]) -> dict[str, Any]:
    metrics = ("mean_latency_seconds", "mean_rise_time_seconds", "mean_overshoot_fraction", "mean_settling_error_fraction", "bounce_back_events")
    return {
        axis: {
            metric: _metric_delta(
                _nested_get(before, ("step_response", "axes", axis, "summary", metric)),
                _nested_get(after, ("step_response", "axes", axis, "summary", metric)),
            )
            for metric in metrics
        }
        for axis in axes
    }


def _filter_changes(before: dict[str, Any], after: dict[str, Any], axes: tuple[str, ...]) -> dict[str, Any]:
    return {
        axis: {
            "250_500hz_attenuation_ratio": _metric_delta(
                _nested_get(before, ("filter_analysis", "axes", axis, "bands", "250-500Hz", "attenuation_ratio")),
                _nested_get(after, ("filter_analysis", "axes", axis, "bands", "250-500Hz", "attenuation_ratio")),
            ),
            "classification": {
                "before": _nested_get(before, ("tuning_evidence", "filter_diagnosis", "axes", axis, "classification")),
                "after": _nested_get(after, ("tuning_evidence", "filter_diagnosis", "axes", axis, "classification")),
            },
        }
        for axis in axes
    }


def _noise_changes(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    return {
        "noise_peak_count": _metric_delta(
            len(_nested_get(before, ("noise_peaks", "peaks")) or []),
            len(_nested_get(after, ("noise_peaks", "peaks")) or []),
        ),
        "warnings": {"before": _nested_get(before, ("noise_peaks", "warnings")), "after": _nested_get(after, ("noise_peaks", "warnings"))},
    }


def _propwash_changes(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    return {
        "segment_count": _metric_delta(
            _nested_get(before, ("propwash_analysis", "summary", "segment_count")),
            _nested_get(after, ("propwash_analysis", "summary", "segment_count")),
        ),
        "max_gyro_mean_abs_delta": _metric_delta(
            _nested_get(before, ("propwash_analysis", "summary", "max_gyro_mean_abs_delta")),
            _nested_get(after, ("propwash_analysis", "summary", "max_gyro_mean_abs_delta")),
        ),
        "max_tracking_error": _metric_delta(
            _nested_get(before, ("propwash_analysis", "summary", "max_tracking_error")),
            _nested_get(after, ("propwash_analysis", "summary", "max_tracking_error")),
        ),
    }


def _chirp_changes(before: dict[str, Any], after: dict[str, Any], axes: tuple[str, ...]) -> dict[str, Any]:
    return {
        axis: {
            "bandwidth_hz": _metric_delta(
                _nested_get(before, ("chirp_analysis", "axes", axis, "bandwidth_hz")),
                _nested_get(after, ("chirp_analysis", "axes", axis, "bandwidth_hz")),
            ),
            "phase_margin_deg": _metric_delta(
                _nested_get(before, ("chirp_analysis", "axes", axis, "phase_margin_deg")),
                _nested_get(after, ("chirp_analysis", "axes", axis, "phase_margin_deg")),
            ),
            "resonant_peak_db": _metric_delta(
                _nested_get(before, ("chirp_analysis", "axes", axis, "resonant_peak_db")),
                _nested_get(after, ("chirp_analysis", "axes", axis, "resonant_peak_db")),
            ),
        }
        for axis in axes
    }


def _outcome_summary(before: dict[str, Any], after: dict[str, Any], axes: tuple[str, ...]) -> dict[str, Any]:
    improvements = []
    regressions = []
    notes = []
    for axis in axes:
        _score_lower_is_better(
            improvements,
            regressions,
            f"{axis} tracking mean error",
            _nested_get(before, ("tracking", axis, "mean_abs_error")),
            _nested_get(after, ("tracking", axis, "mean_abs_error")),
        )
        _score_lower_is_better(
            improvements,
            regressions,
            f"{axis} step overshoot",
            _nested_get(before, ("step_response", "axes", axis, "summary", "mean_overshoot_fraction")),
            _nested_get(after, ("step_response", "axes", axis, "summary", "mean_overshoot_fraction")),
        )
        _score_lower_is_better(
            improvements,
            regressions,
            f"{axis} D-term high-frequency energy",
            _nested_get(before, ("spectrum", "signals", f"axisD[{axes.index(axis)}]", "bands", "250-500Hz", "fraction")),
            _nested_get(after, ("spectrum", "signals", f"axisD[{axes.index(axis)}]", "bands", "250-500Hz", "fraction")),
        )
    _score_lower_is_better(
        improvements,
        regressions,
        "motor saturation samples",
        _nested_get(before, ("activity", "motor_saturation_samples")),
        _nested_get(after, ("activity", "motor_saturation_samples")),
        minimum_change=1.0,
    )
    _score_lower_is_better(
        improvements,
        regressions,
        "propwash max tracking error",
        _nested_get(before, ("propwash_analysis", "summary", "max_tracking_error")),
        _nested_get(after, ("propwash_analysis", "summary", "max_tracking_error")),
    )
    before_quality = before.get("quality") if isinstance(before.get("quality"), dict) else {}
    after_quality = after.get("quality") if isinstance(after.get("quality"), dict) else {}
    if before_quality.get("usable") is False or after_quality.get("usable") is False:
        notes.append("At least one Blackbox Log has quality warnings; outcome confidence is limited")
    if improvements and regressions:
        classification = "mixed"
    elif improvements:
        classification = "improved"
    elif regressions:
        classification = "worse"
    else:
        classification = "inconclusive"
    return {
        "classification": classification,
        "improvements": improvements,
        "regressions": regressions,
        "notes": notes,
    }


def _score_lower_is_better(
    improvements: list[dict[str, Any]],
    regressions: list[dict[str, Any]],
    metric: str,
    before: Any,
    after: Any,
    *,
    minimum_change: float = 0.05,
) -> None:
    if not isinstance(before, (int, float)) or not isinstance(after, (int, float)):
        return
    delta = after - before
    threshold = max(minimum_change, abs(before) * 0.05)
    item = {"metric": metric, "before": before, "after": after, "delta": delta}
    if delta <= -threshold:
        improvements.append(item)
    elif delta >= threshold:
        regressions.append(item)


def limited_events(payload: dict[str, Any], key: str, limit: int) -> dict[str, Any]:
    events = payload.get(key)
    if not isinstance(events, list):
        return payload
    compact = dict(payload)
    compact[key] = events[:limit]
    compact["returned_event_count"] = min(len(events), limit)
    compact["total_event_count"] = len(events)
    return compact
