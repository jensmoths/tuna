from __future__ import annotations

import math
from typing import Any

from .common import AXES
from .spectrum import signal_spectrum


def summarize_filter_analysis(signal_values: dict[str, list[float]], sample_rate_hz: float | None) -> dict[str, Any]:
    if sample_rate_hz is None or sample_rate_hz <= 0:
        return {"sample_rate_hz": sample_rate_hz, "axes": {}, "warnings": ["No logging rate available for filter attenuation analysis"]}

    axes = {}
    warnings = []
    for index, axis in AXES.items():
        filtered_name = f"gyroADC[{index}]"
        unfiltered_name = f"gyroUnfilt[{index}]"
        filtered_values = signal_values.get(filtered_name)
        unfiltered_values = signal_values.get(unfiltered_name)
        if filtered_values is None or unfiltered_values is None:
            missing = []
            if filtered_values is None:
                missing.append(filtered_name)
            if unfiltered_values is None:
                missing.append(unfiltered_name)
            warnings.append(f"Missing fields for {axis} filter attenuation analysis: " + ", ".join(missing))
            axes[axis] = {"available": False, "missing": missing}
            continue

        filtered_spectrum = signal_spectrum(filtered_values, sample_rate_hz)
        unfiltered_spectrum = signal_spectrum(unfiltered_values, sample_rate_hz)
        if filtered_spectrum is None or unfiltered_spectrum is None:
            warnings.append(f"Not enough samples for {axis} filter attenuation analysis")
            axes[axis] = {"available": False, "missing": [], "reason": "not_enough_samples"}
            continue

        bands = {}
        for label, unfiltered_band in unfiltered_spectrum["bands"].items():
            unfiltered_power = unfiltered_band["power"]
            filtered_power = filtered_spectrum["bands"][label]["power"]
            ratio = filtered_power / unfiltered_power if unfiltered_power > 0 else None
            bands[label] = {
                "unfiltered_power": unfiltered_power,
                "filtered_power": filtered_power,
                "attenuation_ratio": ratio,
                "attenuation_db": 10.0 * math.log10(ratio) if ratio and ratio > 0 else None,
                "reduction_fraction": 1.0 - ratio if ratio is not None else None,
            }

        high_band_ratio = bands.get("250-500Hz", {}).get("attenuation_ratio")
        if high_band_ratio is not None and high_band_ratio > 0.8:
            warnings.append(f"High-frequency gyro attenuation appears low on {axis}")

        axes[axis] = {
            "available": True,
            "filtered_field": filtered_name,
            "unfiltered_field": unfiltered_name,
            "sample_rate_hz": sample_rate_hz,
            "bands": bands,
        }

    return {"sample_rate_hz": sample_rate_hz, "axes": axes, "warnings": warnings}
