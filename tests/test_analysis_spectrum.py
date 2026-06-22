from __future__ import annotations

import csv
import math
import unittest

from tests.analysis_helpers import AnalysisTestCase
from tuna_blackbox.csv_summary import analyze_csv_log


class AnalysisSpectrumTests(AnalysisTestCase):
    def test_analyze_csv_log_summarizes_spectral_peak(self):
        path = self.root / "spectrum.csv"
        fieldnames = ["time", "gyroADC[0]", "gyroADC[1]", "gyroADC[2]", "setpoint[0]", "setpoint[1]", "setpoint[2]", "motor[0]", "axisP[0]", "axisI[0]", "axisD[0]"]
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for index in range(1000):
                writer.writerow({name: 0 for name in fieldnames} | {"time": index * 1000, "gyroADC[0]": math.sin(2 * math.pi * 100 * index / 1000), "motor[0]": 1000})

        summary = analyze_csv_log(path)

        peaks = summary["spectrum"]["signals"]["gyroADC[0]"]["peaks"]
        self.assertAlmostEqual(peaks[0]["frequency_hz"], 100.0)
        self.assertGreater(summary["spectrum"]["signals"]["gyroADC[0]"]["bands"]["100-250Hz"]["fraction"], 0.8)

    def test_analyze_csv_log_builds_frequency_throttle_heatmap(self):
        path = self.root / "heatmap.csv"
        fieldnames = ["time", "gyroADC[0]", "gyroADC[1]", "gyroADC[2]", "setpoint[0]", "setpoint[1]", "setpoint[2]", "motor[0]", "axisP[0]", "axisI[0]", "axisD[0]", "rcCommand[3]"]
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for index in range(2000):
                low_throttle = index < 1000
                frequency_hz = 50 if low_throttle else 200
                throttle = 1200 if low_throttle else 1800
                phase_index = index if low_throttle else index - 1000
                writer.writerow({name: 0 for name in fieldnames} | {"time": index * 1000, "gyroADC[0]": math.sin(2 * math.pi * frequency_hz * phase_index / 1000), "motor[0]": 1000, "rcCommand[3]": throttle})

        summary = analyze_csv_log(path)

        bins = summary["frequency_throttle_heatmap"]["signals"]["gyroADC[0]"]["bins"]
        self.assertAlmostEqual(bins["0-1300"]["peak_frequency_hz"], 50.0)
        self.assertAlmostEqual(bins["1700-1900"]["peak_frequency_hz"], 200.0)
        windowed_bins = summary["windowed_frequency_throttle_heatmap"]["signals"]["gyroADC[0]"]["bins"]
        self.assertAlmostEqual(windowed_bins["0-1300"]["dominant_peak_frequency_hz"], 50.0)
        self.assertAlmostEqual(windowed_bins["1700-1900"]["dominant_peak_frequency_hz"], 200.0)

    def test_analyze_csv_log_summarizes_noise_peaks_and_rpm_matches(self):
        path = self.root / "rpm-analysis.csv"
        fieldnames = ["time", "gyroADC[0]", "gyroADC[1]", "gyroADC[2]", "setpoint[0]", "setpoint[1]", "setpoint[2]", "motor[0]", "axisP[0]", "axisI[0]", "axisD[0]", "rcCommand[3]", "debug[0]"]
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for index in range(1000):
                base_frequency = 130
                harmonic_frequency = 260
                writer.writerow({name: 0 for name in fieldnames} | {"time": index * 1000, "gyroADC[0]": math.sin(2 * math.pi * harmonic_frequency * index / 1000), "axisD[0]": math.sin(2 * math.pi * harmonic_frequency * index / 1000), "motor[0]": math.sin(2 * math.pi * base_frequency * index / 1000), "rcCommand[3]": 1500, "debug[0]": math.sin(2 * math.pi * base_frequency * index / 1000)})

        summary = analyze_csv_log(path)

        self.assertIn("possible_frame_resonance", summary["noise_peaks"]["warnings"])
        self.assertIn("possible_motor_harmonic", summary["noise_peaks"]["warnings"])
        self.assertTrue(summary["rpm_analysis"]["available"])
        self.assertIn("debug[0]", summary["rpm_analysis"]["debug_fields"])
        matches = summary["rpm_analysis"]["possible_harmonic_matches"]
        self.assertTrue(any(match["harmonic"] == 2 and match["matched_signal"] == "gyroADC[0]" for match in matches))
        self.assertIn("possible_motor_harmonic", summary["rpm_analysis"]["warnings"])

    def test_analyze_csv_log_adds_debug_mode_specific_rpm_evidence(self):
        path = self.root / "rpm-debug-mode.csv"
        fieldnames = ["time", "gyroADC[0]", "gyroADC[1]", "gyroADC[2]", "setpoint[0]", "setpoint[1]", "setpoint[2]", "motor[0]", "axisP[0]", "axisI[0]", "axisD[0]", "rcCommand[3]", "debug[0]"]
        with path.open("w", newline="") as handle:
            handle.write("debug_mode,RPM_FILTER\n")
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for index in range(1000):
                base_frequency = 130
                harmonic_frequency = 260
                writer.writerow({name: 0 for name in fieldnames} | {"time": index * 1000, "gyroADC[0]": math.sin(2 * math.pi * harmonic_frequency * index / 1000), "axisD[0]": math.sin(2 * math.pi * harmonic_frequency * index / 1000), "motor[0]": 1200, "rcCommand[3]": 1500, "debug[0]": math.sin(2 * math.pi * base_frequency * index / 1000)})

        summary = analyze_csv_log(path)

        rpm = summary["rpm_analysis"]
        self.assertEqual(rpm["debug_mode_family"], "rpm")
        self.assertEqual(rpm["dynamic_notch_evidence"]["classification"], "possible_residual_motor_harmonics")
        self.assertIn("residual_motor_harmonics_after_filtering", rpm["warnings"])

    def test_analyze_csv_log_reports_rpm_analysis_unavailable_without_debug(self):
        summary = analyze_csv_log(self.write_csv())

        self.assertFalse(summary["rpm_analysis"]["available"])
        self.assertEqual(summary["rpm_analysis"]["reason"], "missing_debug_fields")
        self.assertIn("rpm_debug_missing", summary["rpm_analysis"]["warnings"])


if __name__ == "__main__":
    unittest.main()
