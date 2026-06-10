from __future__ import annotations

from typing import Any

from .common import LOW_SPECTRUM_RATE_HZ


def summarize_analysis_capabilities(fields: list[str], timing: dict[str, Any]) -> dict[str, Any]:
    limitations = []

    def has_prefix(prefix: str) -> bool:
        return any(field.startswith(prefix) for field in fields)

    if not has_prefix("gyroUnfilt["):
        limitations.append({
            "feature": "filter_attenuation",
            "severity": "limited",
            "missing": ["gyroUnfilt[0]", "gyroUnfilt[1]", "gyroUnfilt[2]"],
            "message": "Filtered vs unfiltered gyro attenuation cannot be estimated without gyroUnfilt fields.",
            "recommendation": "Log unfiltered gyro data for filter attenuation analysis.",
        })
    if not has_prefix("axisD["):
        limitations.append({
            "feature": "dterm_noise",
            "severity": "limited",
            "missing": ["axisD[0]", "axisD[1]", "axisD[2]"],
            "message": "D-term noise and D-term spike analysis is limited without axisD fields.",
            "recommendation": "Include PID term fields in future Blackbox Logs.",
        })
    if not has_prefix("debug["):
        limitations.append({
            "feature": "rpm_filter_effectiveness",
            "severity": "unavailable",
            "missing": ["debug[*]", "RPM-related debug mode"],
            "message": "RPM harmonics and RPM/dynamic-notch effectiveness cannot be assessed without relevant debug fields.",
            "recommendation": "Capture a diagnostic Blackbox Log with the appropriate RPM/filter debug mode when needed.",
        })
    if not has_prefix("motor["):
        limitations.append({
            "feature": "motor_saturation_and_noise",
            "severity": "limited",
            "missing": ["motor[*]"],
            "message": "Motor saturation, motor noise, and motor imbalance analysis is limited without motor fields.",
            "recommendation": "Include motor output fields in future Blackbox Logs.",
        })
    if "rcCommand[3]" not in fields:
        limitations.append({
            "feature": "throttle_dependent_noise",
            "severity": "limited",
            "missing": ["rcCommand[3]"],
            "message": "Throttle-dependent noise and frequency-vs-throttle analysis is unavailable without throttle command.",
            "recommendation": "Include rcCommand fields in future Blackbox Logs.",
        })

    nominal_rate = timing.get("nominal_logging_rate_hz")
    if nominal_rate is not None and nominal_rate < LOW_SPECTRUM_RATE_HZ:
        limitations.append({
            "feature": "spectrum_and_step_response",
            "severity": "low_confidence",
            "missing": [],
            "message": f"Nominal logging rate is {nominal_rate:.1f}Hz; high-frequency spectrum and response metrics have reduced confidence.",
            "recommendation": "Use a higher Blackbox logging rate for diagnostic analysis when storage bandwidth allows.",
        })

    return {"limitations": limitations, "warnings": [item["message"] for item in limitations]}
