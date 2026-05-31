from __future__ import annotations

import math
from typing import Any

from .common import (
    DTERM_SPIKE_MIN_ABS,
    DTERM_SPIKE_STD_MULTIPLIER,
    FEEDFORWARD_ACTIVE_MIN_ABS,
    ITERM_WINDUP_MIN_ABS,
    ITERM_WINDUP_SETPOINT_THRESHOLD,
    STEP_SETPOINT_DELTA_THRESHOLD,
    THROTTLE_CHANGE_THRESHOLD,
    THROTTLE_CHANGE_WINDOW_US,
)


def _term_stats(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"samples": 0, "min": None, "max": None, "mean": None, "mean_abs": None, "max_abs": None}
    return {
        "samples": len(values),
        "min": min(values),
        "max": max(values),
        "mean": sum(values) / len(values),
        "mean_abs": sum(abs(value) for value in values) / len(values),
        "max_abs": max(abs(value) for value in values),
    }


def summarize_pid_term_analysis(pid_samples: dict[str, list[dict[str, float | None]]], step_response: dict[str, Any]) -> dict[str, Any]:
    axes = {}
    warnings = []
    for axis, samples in pid_samples.items():
        term_values = {
            term: [float(sample[term]) for sample in samples if sample.get(term) is not None]
            for term in ("P", "I", "D", "F")
        }
        terms = {term: _term_stats(values) for term, values in term_values.items()}
        flags = []

        d_values = term_values["D"]
        d_spike_threshold = None
        d_spike_count = 0
        d_delta_samples = 0
        d_mean_abs_delta = None
        d_max_abs_delta = None
        if d_values:
            mean_abs_d = sum(abs(value) for value in d_values) / len(d_values)
            variance = sum((abs(value) - mean_abs_d) ** 2 for value in d_values) / len(d_values)
            d_spike_threshold = max(DTERM_SPIKE_MIN_ABS, mean_abs_d + DTERM_SPIKE_STD_MULTIPLIER * math.sqrt(variance))
            d_spike_count = sum(1 for value in d_values if abs(value) >= d_spike_threshold)
            deltas = [abs(d_values[index] - d_values[index - 1]) for index in range(1, len(d_values))]
            d_delta_samples = len(deltas)
            d_mean_abs_delta = sum(deltas) / len(deltas) if deltas else None
            d_max_abs_delta = max(deltas) if deltas else None
            if d_spike_count:
                flags.append("dterm_spikes")

        throttle_change_times = []
        for index in range(1, len(samples)):
            previous_throttle = samples[index - 1].get("throttle")
            throttle = samples[index].get("throttle")
            if previous_throttle is None or throttle is None:
                continue
            if abs(float(throttle) - float(previous_throttle)) >= THROTTLE_CHANGE_THRESHOLD:
                throttle_change_times.append(float(samples[index]["time_us"]))

        dterm_spikes_near_throttle_changes = 0
        if d_spike_threshold is not None and throttle_change_times:
            for sample in samples:
                d_value = sample.get("D")
                if d_value is None or abs(float(d_value)) < d_spike_threshold:
                    continue
                time_us = float(sample["time_us"])
                if any(abs(time_us - change_time) <= THROTTLE_CHANGE_WINDOW_US for change_time in throttle_change_times):
                    dterm_spikes_near_throttle_changes += 1
            if dterm_spikes_near_throttle_changes:
                flags.append("dterm_spikes_near_throttle_changes")

        windup_samples = [
            sample
            for sample in samples
            if sample.get("I") is not None
            and sample.get("setpoint") is not None
            and abs(float(sample["setpoint"])) <= ITERM_WINDUP_SETPOINT_THRESHOLD
            and abs(float(sample["I"])) >= ITERM_WINDUP_MIN_ABS
        ]
        if windup_samples:
            flags.append("possible_iterm_windup")

        transition_count = 0
        feedforward_active_transitions = 0
        for index in range(1, len(samples)):
            previous_setpoint = samples[index - 1].get("setpoint")
            setpoint = samples[index].get("setpoint")
            if previous_setpoint is None or setpoint is None:
                continue
            if abs(float(setpoint) - float(previous_setpoint)) < STEP_SETPOINT_DELTA_THRESHOLD:
                continue
            transition_count += 1
            window = samples[index : min(len(samples), index + 6)]
            if any(sample.get("F") is not None and abs(float(sample["F"])) >= FEEDFORWARD_ACTIVE_MIN_ABS for sample in window):
                feedforward_active_transitions += 1
        if transition_count and feedforward_active_transitions == 0:
            flags.append("feedforward_inactive_on_setpoint_steps")

        p_mean_abs = terms["P"]["mean_abs"]
        d_mean_abs = terms["D"]["mean_abs"]
        d_to_p_ratio = d_mean_abs / p_mean_abs if p_mean_abs and d_mean_abs is not None else None
        axis_step_flags = step_response.get("axes", {}).get(axis, {}).get("flags", [])
        if d_to_p_ratio is not None:
            if d_to_p_ratio > 1.0:
                flags.append("dterm_dominant")
            elif d_to_p_ratio < 0.10:
                flags.append("pterm_dominant")
        if "overshooting" in axis_step_flags and d_spike_count:
            flags.append("overshoot_with_dterm_spikes")

        axes[axis] = {
            "samples": len(samples),
            "terms": terms,
            "dterm_noise": {
                "spike_threshold": d_spike_threshold,
                "spike_count": d_spike_count,
                "delta_samples": d_delta_samples,
                "mean_abs_delta": d_mean_abs_delta,
                "max_abs_delta": d_max_abs_delta,
            },
            "throttle_coupling": {
                "throttle_change_count": len(throttle_change_times),
                "dterm_spikes_near_throttle_changes": dterm_spikes_near_throttle_changes,
            },
            "iterm_windup": {
                "samples": len(windup_samples),
                "fraction": len(windup_samples) / len(samples) if samples else None,
                "threshold_abs": ITERM_WINDUP_MIN_ABS,
                "setpoint_threshold": ITERM_WINDUP_SETPOINT_THRESHOLD,
            },
            "feedforward": {
                "setpoint_transition_count": transition_count,
                "active_transition_count": feedforward_active_transitions,
                "active_transition_fraction": feedforward_active_transitions / transition_count if transition_count else None,
            },
            "pd_balance": {
                "d_to_p_mean_abs_ratio": d_to_p_ratio,
                "step_response_flags": axis_step_flags,
            },
            "flags": sorted(set(flags)),
        }

        for flag in axes[axis]["flags"]:
            warnings.append(f"{axis}: {flag}")

    return {"axes": axes, "warnings": warnings}
