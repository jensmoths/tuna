from __future__ import annotations

from typing import Any

from .common import MOTOR_IMBALANCE_WARNING_THRESHOLD, MOTOR_MAX_OUTPUT_THRESHOLD, MOTOR_MIN_OUTPUT_THRESHOLD, MOTOR_OFFSET_WARNING_THRESHOLD


def summarize_motor_analysis(motor_values: dict[str, list[float]], motor_throttle_bins: dict[str, dict[str, list[float]]]) -> dict[str, Any]:
    if not motor_values:
        return {"motors": {}, "summary": {"motor_count": 0}, "warnings": ["No motor fields found"]}

    motors = {}
    means = {}
    warnings = []
    for name, values in sorted(motor_values.items()):
        if not values:
            continue
        sample_count = len(values)
        mean_output = sum(values) / sample_count
        means[name] = mean_output
        near_min_samples = sum(1 for value in values if value <= MOTOR_MIN_OUTPUT_THRESHOLD)
        near_max_samples = sum(1 for value in values if value >= MOTOR_MAX_OUTPUT_THRESHOLD)
        bins = {}
        for label, bin_values in motor_throttle_bins.get(name, {}).items():
            if not bin_values:
                continue
            bins[label] = {
                "samples": len(bin_values),
                "min": min(bin_values),
                "max": max(bin_values),
                "mean": sum(bin_values) / len(bin_values),
                "near_min_samples": sum(1 for value in bin_values if value <= MOTOR_MIN_OUTPUT_THRESHOLD),
                "near_max_samples": sum(1 for value in bin_values if value >= MOTOR_MAX_OUTPUT_THRESHOLD),
            }
        motors[name] = {
            "samples": sample_count,
            "min": min(values),
            "max": max(values),
            "mean": mean_output,
            "near_min_samples": near_min_samples,
            "near_min_fraction": near_min_samples / sample_count,
            "near_max_samples": near_max_samples,
            "near_max_fraction": near_max_samples / sample_count,
            "throttle_bins": bins,
        }

    fleet_mean = sum(means.values()) / len(means) if means else None
    offsets = {name: mean - fleet_mean for name, mean in means.items()} if fleet_mean is not None else {}
    for name, offset in offsets.items():
        motors[name]["mean_offset_from_fleet"] = offset
        if abs(offset) >= MOTOR_OFFSET_WARNING_THRESHOLD:
            warnings.append(f"Persistent motor offset on {name}: {offset:.1f}")

    imbalance_score = max(offsets.values()) - min(offsets.values()) if offsets else None
    total_near_max_samples = sum(item["near_max_samples"] for item in motors.values())
    total_near_min_samples = sum(item["near_min_samples"] for item in motors.values())
    if total_near_max_samples:
        warnings.append(f"Motor outputs reached near max for {total_near_max_samples} motor-sample(s)")
    if imbalance_score is not None and imbalance_score >= MOTOR_IMBALANCE_WARNING_THRESHOLD:
        warnings.append(f"Motor imbalance score is high: {imbalance_score:.1f}")

    return {
        "motors": motors,
        "summary": {
            "motor_count": len(motors),
            "fleet_mean": fleet_mean,
            "imbalance_score": imbalance_score,
            "total_near_min_samples": total_near_min_samples,
            "total_near_max_samples": total_near_max_samples,
        },
        "warnings": warnings,
    }
