from __future__ import annotations

AXES = {0: "roll", 1: "pitch", 2: "yaw"}
TRACKING_THRESHOLD = 50.0
HIGH_RATE_THRESHOLD = 200.0
MOTOR_SATURATION_THRESHOLD = 1990.0
MIN_USEFUL_DURATION_SECONDS = 5.0
SEGMENT_GAP_US = 200_000.0
MIN_SEGMENT_DURATION_US = 100_000.0
THROTTLE_PUNCH_THRESHOLD = 1700.0
GAP_MULTIPLIER = 3.0
SPECTRAL_PREFIXES = ("gyroADC[", "gyroUnfilt[", "axisD[", "motor[", "debug[")
SPECTRAL_BANDS_HZ = ((0.0, 100.0), (100.0, 250.0), (250.0, 500.0), (500.0, 1000.0))
THROTTLE_HEATMAP_BINS = ((0.0, 1300.0), (1300.0, 1500.0), (1500.0, 1700.0), (1700.0, 1900.0), (1900.0, 2200.0))
ACTIVE_THROTTLE_THRESHOLD = 1050.0
ACTIVE_MOTOR_THRESHOLD = 1050.0
LOW_SPECTRUM_RATE_HZ = 500.0
NOISE_PEAK_MIN_POWER_FRACTION = 0.10
HARMONIC_MATCH_TOLERANCE_FRACTION = 0.05
STEP_SETPOINT_DELTA_THRESHOLD = 150.0
STEP_RESPONSE_WINDOW_US = 500_000.0
STEP_RESPONSE_MIN_GAP_US = 300_000.0
MOTOR_MIN_OUTPUT_THRESHOLD = 1050.0
MOTOR_MAX_OUTPUT_THRESHOLD = 1950.0
MOTOR_OFFSET_WARNING_THRESHOLD = 100.0
MOTOR_IMBALANCE_WARNING_THRESHOLD = 120.0
DTERM_SPIKE_MIN_ABS = 50.0
DTERM_SPIKE_STD_MULTIPLIER = 3.0
THROTTLE_CHANGE_THRESHOLD = 150.0
THROTTLE_CHANGE_WINDOW_US = 100_000.0
ITERM_WINDUP_SETPOINT_THRESHOLD = 50.0
ITERM_WINDUP_MIN_ABS = 50.0
FEEDFORWARD_ACTIVE_MIN_ABS = 10.0


def to_float(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_field(name: str) -> str:
    name = name.strip()
    if " (" in name:
        name = name.split(" (", 1)[0]
    return name


def track_range(ranges: dict[str, dict[str, float]], name: str, value: float) -> None:
    current = ranges.setdefault(name, {"min": value, "max": value})
    current["min"] = min(current["min"], value)
    current["max"] = max(current["max"], value)


def empty_axis_metric() -> dict[str, float | int | None]:
    return {"samples": 0, "mean_abs_error": None, "max_abs_error": None, "samples_over_threshold": 0}


def truthy_field(value: str | None) -> bool | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in {"", "0", "false", "no", "disarmed"}:
        return False
    if normalized in {"1", "true", "yes", "armed"}:
        return True
    numeric = to_float(normalized)
    if numeric is not None:
        return numeric > 0
    return None


def throttle_bin_label(throttle: float) -> str | None:
    for low, high in THROTTLE_HEATMAP_BINS:
        if low <= throttle < high:
            return f"{int(low)}-{int(high)}"
    return None
