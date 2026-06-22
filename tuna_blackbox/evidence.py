from __future__ import annotations

from typing import Any

from .common import AXES

FILTER_LIGHT_ATTENUATION_RATIO = 0.80
FILTER_HEAVY_ATTENUATION_RATIO = 0.08
DTERM_HIGH_BAND_FRACTION = 0.25
DTERM_SPIKE_FRACTION_WARNING = 0.001


def summarize_segment_gated_analysis(high_rate_segments: list[dict[str, Any]]) -> dict[str, Any]:
    clean_segments = [segment for segment in high_rate_segments if not segment.get("motor_saturation_samples")]
    axes = {}
    for axis in AXES.values():
        axis_segments = [segment for segment in clean_segments if segment.get("axis") == axis]
        axes[axis] = _summarize_axis_segments(axis_segments)
    return {
        "segment_quality": [_segment_quality(segment) for segment in high_rate_segments],
        "clean_high_rate_segments": clean_segments,
        "summary": {
            "high_rate_segment_count": len(high_rate_segments),
            "clean_high_rate_segment_count": len(clean_segments),
            "motor_saturated_segment_count": len(high_rate_segments) - len(clean_segments),
        },
        "axes": axes,
        "warnings": [] if clean_segments else ["No clean high-rate segments without motor saturation found"],
    }


def build_tuning_evidence(analysis: dict[str, Any]) -> dict[str, Any]:
    return {
        "filter_diagnosis": build_filter_diagnosis(analysis),
        "pid_response": build_pid_response(analysis),
        "capture_plan": build_capture_plan(analysis),
    }


def build_filter_diagnosis(analysis: dict[str, Any]) -> dict[str, Any]:
    axes = {}
    warnings = []
    for index, axis in AXES.items():
        evidence = []
        flags = []
        filter_axis = ((analysis.get("filter_analysis") or {}).get("axes") or {}).get(axis, {})
        pid_axis = ((analysis.get("pid_term_analysis") or {}).get("axes") or {}).get(axis, {})
        step_axis = ((analysis.get("step_response") or {}).get("axes") or {}).get(axis, {})
        dterm_signal = ((analysis.get("spectrum") or {}).get("signals") or {}).get(f"axisD[{index}]", {})

        high_ratio = _nested(filter_axis, ("bands", "250-500Hz", "attenuation_ratio"))
        if high_ratio is not None:
            evidence.append({"metric": "gyro_high_band_attenuation_ratio", "value": high_ratio})
            if high_ratio > FILTER_LIGHT_ATTENUATION_RATIO:
                flags.append("low_high_frequency_attenuation")
            if high_ratio < FILTER_HEAVY_ATTENUATION_RATIO:
                flags.append("very_high_high_frequency_attenuation")

        dterm_high_fraction = _nested(dterm_signal, ("bands", "250-500Hz", "fraction"))
        if dterm_high_fraction is not None:
            evidence.append({"metric": "dterm_250_500hz_power_fraction", "value": dterm_high_fraction})
            if dterm_high_fraction >= DTERM_HIGH_BAND_FRACTION:
                flags.append("high_dterm_high_frequency_energy")

        dterm_spikes = _meaningful_dterm_spikes(pid_axis)
        if dterm_spikes["spike_count"]:
            evidence.append({"metric": "dterm_spike_count", "value": dterm_spikes["spike_count"]})
            evidence.append({"metric": "dterm_spike_fraction", "value": dterm_spikes["spike_fraction"]})
        if dterm_spikes["meaningful"]:
            flags.append("dterm_spikes")

        step_flags = step_axis.get("flags") if isinstance(step_axis.get("flags"), list) else []
        if any(flag in step_flags for flag in ("sluggish", "slow_rise")):
            evidence.append({"metric": "step_response_flags", "value": step_flags})
            flags.append("slow_response")

        classification = _filter_classification(flags, filter_axis)
        confidence = _filter_confidence(filter_axis, pid_axis, analysis)
        if classification == "inconclusive":
            warnings.append(f"{axis}: filter evidence is inconclusive")
        axes[axis] = {
            "classification": classification,
            "confidence": confidence,
            "flags": sorted(set(flags)),
            "evidence": evidence,
        }
    return {"axes": axes, "warnings": warnings}


def build_pid_response(analysis: dict[str, Any]) -> dict[str, Any]:
    axes = {}
    warnings = []
    for axis in AXES.values():
        step_axis = ((analysis.get("step_response") or {}).get("axes") or {}).get(axis, {})
        pid_axis = ((analysis.get("pid_term_analysis") or {}).get("axes") or {}).get(axis, {})
        step_flags = step_axis.get("flags") if isinstance(step_axis.get("flags"), list) else []
        pid_flags = pid_axis.get("flags") if isinstance(pid_axis.get("flags"), list) else []
        classifications = []
        evidence = []
        if step_flags:
            evidence.append({"metric": "step_response_flags", "value": step_flags})
        if pid_flags:
            evidence.append({"metric": "pid_term_flags", "value": pid_flags})
        if "overshooting" in step_flags or "bounce_back" in step_flags:
            classifications.append("underdamped_or_excessive_response")
        if "slow_rise" in step_flags or "sluggish" in step_flags:
            classifications.append("sluggish_response")
        if "possible_iterm_windup" in pid_flags:
            classifications.append("possible_iterm_windup")
        if "feedforward_inactive_on_setpoint_steps" in pid_flags:
            classifications.append("feedforward_evidence_missing_or_inactive")
        dterm_spikes = _meaningful_dterm_spikes(pid_axis)
        if dterm_spikes["meaningful"] or dterm_spikes["throttle_coupled_count"]:
            classifications.append("dterm_noise_or_throttle_coupling")
        if not classifications:
            classifications.append("no_strong_pid_response_evidence")
        if classifications == ["no_strong_pid_response_evidence"]:
            warnings.append(f"{axis}: no strong PID response evidence")
        axes[axis] = {
            "classifications": sorted(set(classifications)),
            "confidence": _pid_confidence(step_axis, pid_axis, analysis),
            "evidence": evidence,
        }
    return {"axes": axes, "warnings": warnings}


def build_capture_plan(analysis: dict[str, Any]) -> dict[str, Any]:
    reasons = []
    recommended_blackbox_settings = []
    recommended_maneuvers = []
    quality = analysis.get("quality") if isinstance(analysis.get("quality"), dict) else {}
    if not quality.get("usable"):
        reasons.extend(quality.get("warnings") or [])

    for limitation in (analysis.get("analysis_capabilities") or {}).get("limitations", []):
        feature = limitation.get("feature")
        if feature == "filter_attenuation":
            recommended_blackbox_settings.append("log gyroUnfilt fields for filtered-vs-unfiltered gyro attenuation")
        elif feature == "rpm_filter_effectiveness":
            recommended_blackbox_settings.append("use an RPM/filter-related debug mode for a diagnostic Blackbox Log")
        elif feature == "throttle_dependent_noise":
            recommended_blackbox_settings.append("include rcCommand[3] throttle data")
        reasons.append(limitation.get("message"))

    segments = analysis.get("segments") if isinstance(analysis.get("segments"), dict) else {}
    if not segments.get("high_rate"):
        reasons.append("No high-rate roll/pitch/yaw segments were detected")
        recommended_maneuvers.append("capture clean roll and pitch snap moves without motor saturation")
    propwash = analysis.get("propwash_analysis") if isinstance(analysis.get("propwash_analysis"), dict) else {}
    if propwash.get("available") and not propwash.get("segments"):
        reasons.append("No propwash recovery segments were detected")
        recommended_maneuvers.append("capture low-throttle descent followed by controlled throttle recovery for propwash evidence")
    rpm = analysis.get("rpm_analysis") if isinstance(analysis.get("rpm_analysis"), dict) else {}
    if rpm.get("available") is False and rpm.get("recommendation"):
        reasons.append(rpm.get("recommendation"))
    elif rpm.get("available") is True and rpm.get("debug_mode_family") == "unknown":
        reasons.append("Debug fields are present but debug_mode is unknown; RPM/dynamic-notch conclusions are limited")
        recommended_blackbox_settings.append("record debug_mode with RPM/filter debug fields for dynamic-notch evidence")

    seen = set()
    compact_reasons = [reason for reason in reasons if reason and not (reason in seen or seen.add(reason))]
    return {
        "need_more_data": bool(compact_reasons or recommended_blackbox_settings or recommended_maneuvers),
        "reasons": compact_reasons,
        "recommended_blackbox_settings": sorted(set(recommended_blackbox_settings)),
        "recommended_maneuvers": sorted(set(recommended_maneuvers)),
    }


def _summarize_axis_segments(segments: list[dict[str, Any]]) -> dict[str, Any]:
    if not segments:
        return {"segment_count": 0}
    return {
        "segment_count": len(segments),
        "mean_tracking_error": _mean([_nested(segment, ("tracking", "mean_abs_error")) for segment in segments]),
        "max_tracking_error": max((_nested(segment, ("tracking", "max_abs_error")) or 0.0 for segment in segments), default=None),
        "mean_gyro_abs_delta": _mean([_nested(segment, ("rough_noise", "gyro_mean_abs_delta")) for segment in segments]),
        "mean_dterm_abs_delta": _mean([_nested(segment, ("rough_noise", "dterm_mean_abs_delta")) for segment in segments]),
    }


def _segment_quality(segment: dict[str, Any]) -> dict[str, Any]:
    invalid_reasons = []
    useful_for = []
    if segment.get("motor_saturation_samples"):
        invalid_reasons.append("motor_saturation")
    if (segment.get("duration_seconds") or 0.0) < 0.15:
        invalid_reasons.append("short_segment")
    if segment.get("axis") in {"roll", "pitch"}:
        useful_for.extend([f"{segment['axis']}_pid", "response_tracking"])
    elif segment.get("axis") == "yaw":
        useful_for.append("yaw_pid")
    rough_noise = segment.get("rough_noise") if isinstance(segment.get("rough_noise"), dict) else {}
    if rough_noise.get("dterm_mean_abs_delta") is not None:
        useful_for.append("dterm_noise")
    return {
        "axis": segment.get("axis"),
        "start_time_seconds": segment.get("start_time_seconds"),
        "duration_seconds": segment.get("duration_seconds"),
        "raw_data_ref": segment.get("raw_data_ref"),
        "useful_for": sorted(set(useful_for)),
        "invalid_reasons": invalid_reasons,
        "confidence": "high" if not invalid_reasons else "low",
    }


def _filter_classification(flags: list[str], filter_axis: dict[str, Any]) -> str:
    if not filter_axis.get("available") and not flags:
        return "inconclusive"
    too_light = any(flag in flags for flag in ("low_high_frequency_attenuation", "high_dterm_high_frequency_energy", "dterm_spikes"))
    too_heavy = "very_high_high_frequency_attenuation" in flags and ("slow_response" in flags or too_light)
    if too_light and too_heavy:
        return "mixed_filter_evidence"
    if too_light:
        return "possibly_too_light"
    if too_heavy:
        return "possibly_too_heavy"
    return "no_strong_filter_evidence"


def _meaningful_dterm_spikes(pid_axis: dict[str, Any]) -> dict[str, Any]:
    samples = pid_axis.get("samples") or 0
    spike_count = _nested(pid_axis, ("dterm_noise", "spike_count")) or 0
    throttle_coupled_count = _nested(pid_axis, ("throttle_coupling", "dterm_spikes_near_throttle_changes")) or 0
    spike_fraction = spike_count / samples if isinstance(samples, (int, float)) and samples else None
    meaningful = bool(
        spike_count
        and (
            throttle_coupled_count
            or samples < 1000
            or (spike_fraction is not None and spike_fraction >= DTERM_SPIKE_FRACTION_WARNING)
        )
    )
    return {
        "spike_count": spike_count,
        "spike_fraction": spike_fraction,
        "throttle_coupled_count": throttle_coupled_count,
        "meaningful": meaningful,
    }


def _filter_confidence(filter_axis: dict[str, Any], pid_axis: dict[str, Any], analysis: dict[str, Any]) -> str:
    quality = analysis.get("quality") if isinstance(analysis.get("quality"), dict) else {}
    if filter_axis.get("available") and pid_axis.get("samples") and quality.get("usable"):
        return "high"
    if filter_axis.get("available") or pid_axis.get("samples"):
        return "medium"
    return "low"


def _pid_confidence(step_axis: dict[str, Any], pid_axis: dict[str, Any], analysis: dict[str, Any]) -> str:
    event_count = _nested(step_axis, ("summary", "event_count")) or 0
    has_pid = bool(pid_axis.get("samples"))
    quality = analysis.get("quality") if isinstance(analysis.get("quality"), dict) else {}
    if event_count and has_pid and quality.get("usable"):
        return "high"
    if event_count or has_pid:
        return "medium"
    return "low"


def _nested(payload: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = payload
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _mean(values: list[Any]) -> float | None:
    numeric = [float(value) for value in values if isinstance(value, (int, float))]
    return sum(numeric) / len(numeric) if numeric else None
