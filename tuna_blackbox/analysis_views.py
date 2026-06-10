from __future__ import annotations

from typing import Any

CONFIG_KEYS = (
    "rollPID",
    "pitchPID",
    "yawPID",
    "levelPID",
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
        "segment_count_changes": segment_counts,
        "quality": {"before": before.get("quality"), "after": after.get("quality")},
    }


def limited_events(payload: dict[str, Any], key: str, limit: int) -> dict[str, Any]:
    events = payload.get(key)
    if not isinstance(events, list):
        return payload
    compact = dict(payload)
    compact[key] = events[:limit]
    compact["returned_event_count"] = min(len(events), limit)
    compact["total_event_count"] = len(events)
    return compact
