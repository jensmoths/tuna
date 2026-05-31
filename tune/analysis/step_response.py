from __future__ import annotations

from typing import Any

from .common import STEP_RESPONSE_MIN_GAP_US, STEP_RESPONSE_WINDOW_US, STEP_SETPOINT_DELTA_THRESHOLD


def summarize_step_response(axis_samples: dict[str, list[tuple[float, float, float]]]) -> dict[str, Any]:
    axes = {}
    warnings = []
    for axis, samples in axis_samples.items():
        events = []
        last_event_time = -STEP_RESPONSE_MIN_GAP_US
        for index in range(1, len(samples)):
            time_us, setpoint, gyro = samples[index]
            _previous_time_us, previous_setpoint, previous_gyro = samples[index - 1]
            step_delta = setpoint - previous_setpoint
            step_size = abs(step_delta)
            if step_size < STEP_SETPOINT_DELTA_THRESHOLD or time_us - last_event_time < STEP_RESPONSE_MIN_GAP_US:
                continue

            direction = 1.0 if step_delta > 0 else -1.0
            window = [sample for sample in samples[index:] if sample[0] <= time_us + STEP_RESPONSE_WINDOW_US]
            if len(window) < 3:
                continue

            response = [(sample_time, (sample_gyro - previous_gyro) * direction, sample_setpoint, sample_gyro) for sample_time, sample_setpoint, sample_gyro in window]
            latency_threshold = max(10.0, step_size * 0.10)
            rise_threshold = step_size * 0.90
            latency_seconds = None
            rise_time_seconds = None
            for sample_time, response_value, _sample_setpoint, _sample_gyro in response:
                elapsed = (sample_time - time_us) / 1_000_000.0
                if latency_seconds is None and response_value >= latency_threshold:
                    latency_seconds = elapsed
                if rise_time_seconds is None and response_value >= rise_threshold:
                    rise_time_seconds = elapsed
                    break

            max_response = max(item[1] for item in response)
            min_response = min(item[1] for item in response)
            overshoot_fraction = max(0.0, max_response - step_size) / step_size
            undershoot_fraction = max(0.0, -min_response) / step_size
            peak_index = max(range(len(response)), key=lambda item_index: response[item_index][1])
            bounce_back = any(item[1] < step_size * 0.80 for item in response[peak_index + 1 :]) if max_response >= step_size else False
            settling_slice = response[max(0, int(len(response) * 0.8)) :]
            settling_errors = [abs(sample_setpoint - sample_gyro) for _sample_time, _response_value, sample_setpoint, sample_gyro in settling_slice]
            settling_error = sum(settling_errors) / len(settling_errors) if settling_errors else None
            settling_error_fraction = settling_error / step_size if settling_error is not None and step_size > 0 else None

            events.append({
                "start_time_seconds": time_us / 1_000_000.0,
                "start_row_offset": index,
                "direction": "positive" if direction > 0 else "negative",
                "initial_setpoint": previous_setpoint,
                "target_setpoint": setpoint,
                "step_size": step_size,
                "initial_gyro": previous_gyro,
                "latency_seconds": latency_seconds,
                "rise_time_seconds": rise_time_seconds,
                "overshoot_fraction": overshoot_fraction,
                "undershoot_fraction": undershoot_fraction,
                "settling_error": settling_error,
                "settling_error_fraction": settling_error_fraction,
                "bounce_back": bounce_back,
            })
            last_event_time = time_us

        if not events:
            warnings.append(f"No step-like setpoint events found for {axis}")
            axes[axis] = {"events": [], "summary": {"event_count": 0}, "flags": []}
            continue

        def mean_metric(name: str) -> float | None:
            values = [event[name] for event in events if event[name] is not None]
            return sum(values) / len(values) if values else None

        mean_latency = mean_metric("latency_seconds")
        mean_rise_time = mean_metric("rise_time_seconds")
        mean_overshoot = mean_metric("overshoot_fraction")
        mean_settling_error = mean_metric("settling_error_fraction")
        flags = []
        if mean_latency is not None and mean_latency > 0.08:
            flags.append("sluggish")
        if mean_rise_time is not None and mean_rise_time > 0.20:
            flags.append("slow_rise")
        if mean_overshoot is not None and mean_overshoot > 0.20:
            flags.append("overshooting")
        if any(event["bounce_back"] for event in events):
            flags.append("bounce_back")
        if mean_settling_error is not None and mean_settling_error > 0.25:
            flags.append("poor_settling")

        axes[axis] = {
            "events": events,
            "summary": {
                "event_count": len(events),
                "mean_latency_seconds": mean_latency,
                "mean_rise_time_seconds": mean_rise_time,
                "mean_overshoot_fraction": mean_overshoot,
                "mean_settling_error_fraction": mean_settling_error,
                "bounce_back_events": sum(1 for event in events if event["bounce_back"]),
            },
            "flags": flags,
        }

    return {"axes": axes, "warnings": warnings}
