from __future__ import annotations

from typing import Any

import numpy as np

from .common import (
    HARMONIC_MATCH_TOLERANCE_FRACTION,
    NOISE_PEAK_MIN_POWER_FRACTION,
    SPECTRAL_BANDS_HZ,
    THROTTLE_HEATMAP_BINS,
)


def signal_spectrum(values: list[float], sample_rate_hz: float) -> dict[str, Any] | None:
    if len(values) < 8:
        return None
    samples = np.asarray(values, dtype=float)
    samples = samples - float(np.mean(samples))
    window = np.hanning(len(samples))
    spectrum = np.fft.rfft(samples * window)
    power = np.abs(spectrum) ** 2
    frequencies = np.fft.rfftfreq(len(samples), d=1.0 / sample_rate_hz)
    if len(power) > 1:
        power[0] = 0.0
    total_power = float(np.sum(power))

    peak_indexes = np.argsort(power)[::-1][:3]
    peaks = [
        {"frequency_hz": float(frequencies[index]), "power": float(power[index])}
        for index in peak_indexes
        if power[index] > 0
    ]

    bands = {}
    for low_hz, high_hz in SPECTRAL_BANDS_HZ:
        mask = (frequencies >= low_hz) & (frequencies < high_hz)
        band_power = float(np.sum(power[mask]))
        bands[f"{int(low_hz)}-{int(high_hz)}Hz"] = {
            "power": band_power,
            "fraction": band_power / total_power if total_power > 0 else None,
        }

    return {
        "samples": len(values),
        "nyquist_hz": sample_rate_hz / 2.0,
        "total_power": total_power,
        "peaks": peaks,
        "bands": bands,
    }


def signal_kind(name: str) -> str:
    if name.startswith("gyroADC["):
        return "gyro"
    if name.startswith("gyroUnfilt["):
        return "unfiltered_gyro"
    if name.startswith("axisD["):
        return "dterm"
    if name.startswith("motor["):
        return "motor"
    if name.startswith("debug["):
        return "debug"
    return "unknown"


def frequency_region(frequency_hz: float) -> str:
    if frequency_hz < 100.0:
        return "low"
    if frequency_hz < 250.0:
        return "mid"
    return "high"


def summarize_spectrum(signal_values: dict[str, list[float]], sample_rate_hz: float | None) -> dict[str, Any]:
    if sample_rate_hz is None or sample_rate_hz <= 0:
        return {"sample_rate_hz": sample_rate_hz, "signals": {}, "warnings": ["No logging rate available for spectral analysis"]}

    summaries = {}
    for name, values in signal_values.items():
        summary = signal_spectrum(values, sample_rate_hz)
        if summary is not None:
            summaries[name] = summary

    return {"sample_rate_hz": sample_rate_hz, "signals": summaries, "warnings": []}


def summarize_frequency_throttle_heatmap(signal_bins: dict[str, dict[str, list[float]]], sample_rate_hz: float | None, has_throttle: bool) -> dict[str, Any]:
    bins = [{"label": f"{int(low)}-{int(high)}", "min": low, "max": high} for low, high in THROTTLE_HEATMAP_BINS]
    if not has_throttle:
        return {
            "sample_rate_hz": sample_rate_hz,
            "throttle_field": "rcCommand[3]",
            "bins": bins,
            "signals": {},
            "warnings": ["Missing rcCommand[3]; frequency-vs-throttle heatmap is unavailable"],
        }
    if sample_rate_hz is None or sample_rate_hz <= 0:
        return {
            "sample_rate_hz": sample_rate_hz,
            "throttle_field": "rcCommand[3]",
            "bins": bins,
            "signals": {},
            "warnings": ["No logging rate available for frequency-vs-throttle heatmap"],
        }

    signals = {}
    for name, by_bin in signal_bins.items():
        bin_summaries = {}
        for label, values in by_bin.items():
            summary = signal_spectrum(values, sample_rate_hz)
            if summary is None:
                continue
            bin_summaries[label] = {
                "samples": summary["samples"],
                "total_power": summary["total_power"],
                "peak_frequency_hz": summary["peaks"][0]["frequency_hz"] if summary["peaks"] else None,
                "bands": summary["bands"],
            }
        if bin_summaries:
            signals[name] = {"bins": bin_summaries}
    return {"sample_rate_hz": sample_rate_hz, "throttle_field": "rcCommand[3]", "bins": bins, "signals": signals, "warnings": []}


def summarize_noise_peaks(spectrum: dict[str, Any]) -> dict[str, Any]:
    peaks = []
    warnings = []
    for signal_name, signal in spectrum.get("signals", {}).items():
        total_power = signal.get("total_power") or 0.0
        if total_power <= 0:
            continue
        kind = signal_kind(signal_name)
        for peak in signal.get("peaks", []):
            power_fraction = peak["power"] / total_power
            if power_fraction < NOISE_PEAK_MIN_POWER_FRACTION:
                continue
            frequency_hz = peak["frequency_hz"]
            classification = []
            if kind in {"gyro", "unfiltered_gyro", "dterm"} and frequency_hz >= 100.0:
                classification.append("possible_frame_resonance")
            if kind in {"motor", "debug"} and frequency_hz >= 50.0:
                classification.append("possible_motor_harmonic")
            if kind == "dterm" and frequency_hz >= 100.0:
                classification.append("possible_dterm_amplification")

            peaks.append({
                "signal": signal_name,
                "signal_kind": kind,
                "frequency_hz": frequency_hz,
                "frequency_region": frequency_region(frequency_hz),
                "power": peak["power"],
                "power_fraction": power_fraction,
                "classification": classification,
            })
            warnings.extend(classification)

    peaks.sort(key=lambda item: item["power_fraction"], reverse=True)
    return {"peaks": peaks, "warnings": sorted(set(warnings))}


def summarize_rpm_analysis(spectrum: dict[str, Any]) -> dict[str, Any]:
    signals = spectrum.get("signals", {})
    debug_signals = {name: signal for name, signal in signals.items() if name.startswith("debug[")}
    if not debug_signals:
        return {
            "available": False,
            "reason": "missing_debug_fields",
            "warnings": ["rpm_debug_missing", "dynamic_notch_effectiveness_unknown"],
            "recommendation": "Capture a diagnostic Blackbox Log with RPM/filter debug fields to assess motor harmonics and dynamic notch behavior.",
        }

    debug_peaks = []
    for name, signal in debug_signals.items():
        total_power = signal.get("total_power") or 0.0
        for peak in signal.get("peaks", []):
            debug_peaks.append({
                "signal": name,
                "frequency_hz": peak["frequency_hz"],
                "power": peak["power"],
                "power_fraction": peak["power"] / total_power if total_power > 0 else None,
            })

    harmonic_matches = []
    candidate_signals = {
        name: signal
        for name, signal in signals.items()
        if name not in debug_signals and name.startswith(("gyroADC[", "gyroUnfilt[", "axisD[", "motor["))
    }
    for debug_peak in debug_peaks:
        base_frequency = debug_peak["frequency_hz"]
        if base_frequency <= 0:
            continue
        for signal_name, signal in candidate_signals.items():
            for peak in signal.get("peaks", []):
                for harmonic in (1, 2, 3, 4):
                    expected = base_frequency * harmonic
                    tolerance = max(5.0, expected * HARMONIC_MATCH_TOLERANCE_FRACTION)
                    if abs(peak["frequency_hz"] - expected) <= tolerance:
                        harmonic_matches.append({
                            "debug_signal": debug_peak["signal"],
                            "base_frequency_hz": base_frequency,
                            "harmonic": harmonic,
                            "matched_signal": signal_name,
                            "matched_signal_kind": signal_kind(signal_name),
                            "matched_frequency_hz": peak["frequency_hz"],
                            "frequency_error_hz": peak["frequency_hz"] - expected,
                        })
                        break

    warnings = ["dynamic_notch_effectiveness_unknown"]
    if harmonic_matches:
        warnings.append("possible_motor_harmonic")

    debug_peaks.sort(key=lambda item: item["power_fraction"] or 0.0, reverse=True)
    return {
        "available": True,
        "debug_fields": sorted(debug_signals),
        "debug_peaks": debug_peaks,
        "possible_harmonic_matches": harmonic_matches,
        "warnings": sorted(set(warnings)),
        "note": "First-pass RPM analysis treats debug field spectra as diagnostic evidence; exact RPM semantics depend on the logged debug mode.",
    }
