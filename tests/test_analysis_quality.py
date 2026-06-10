from __future__ import annotations

import csv
import unittest

from tests.analysis_helpers import AnalysisTestCase
from tuna_blackbox.csv_summary import analyze_csv_log


class AnalysisQualityTests(AnalysisTestCase):
    def test_analyze_csv_log_detects_timing_gaps(self):
        path = self.root / "gaps.csv"
        fieldnames = ["time", "gyroADC[0]", "gyroADC[1]", "gyroADC[2]", "setpoint[0]", "setpoint[1]", "setpoint[2]", "motor[0]", "axisP[0]", "axisI[0]", "axisD[0]"]
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for time_us in (0, 1000, 2000, 12000, 13000):
                writer.writerow({name: 0 for name in fieldnames} | {"time": time_us, "motor[0]": 1000})

        summary = analyze_csv_log(path)

        self.assertEqual(summary["timing"]["nominal_interval_us"], 1000.0)
        self.assertEqual(summary["timing"]["nominal_logging_rate_hz"], 1000.0)
        self.assertAlmostEqual(summary["timing"]["effective_logging_rate_hz"], 307.6923076923077)
        self.assertEqual(summary["timing"]["gap_count"], 1)
        self.assertEqual(summary["timing"]["estimated_missing_samples"], 9)
        self.assertEqual(summary["timing"]["gaps"][0]["start_row"], 3)
        self.assertEqual(summary["timing"]["gaps"][0]["end_row"], 4)
        self.assertIn("timing gap/dropout", " ".join(summary["quality"]["warnings"]))

    def test_analyze_csv_log_reports_capability_warnings(self):
        summary = analyze_csv_log(self.write_csv())

        features = {item["feature"] for item in summary["analysis_capabilities"]["limitations"]}
        self.assertIn("filter_attenuation", features)
        self.assertIn("dterm_noise", features)
        self.assertIn("rpm_filter_effectiveness", features)
        self.assertIn("throttle_dependent_noise", features)
        self.assertGreater(len(summary["analysis_capabilities"]["warnings"]), 0)

    def test_analyze_csv_log_detects_active_window_for_idle_trim(self):
        path = self.root / "active-window.csv"
        fieldnames = ["time", "gyroADC[0]", "gyroADC[1]", "gyroADC[2]", "setpoint[0]", "setpoint[1]", "setpoint[2]", "motor[0]", "axisP[0]", "axisI[0]", "axisD[0]", "rcCommand[3]"]
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row_number, time_us in enumerate((0, 1000, 2000, 3000, 4000, 5000, 6000), start=1):
                active = 3 <= row_number <= 5
                writer.writerow({name: 0 for name in fieldnames} | {"time": time_us, "motor[0]": 1200 if active else 1000, "rcCommand[3]": 1200 if active else 1000})

        summary = analyze_csv_log(path)

        active_window = summary["flight"]["active_window"]
        self.assertEqual(active_window["start_row"], 3)
        self.assertEqual(active_window["end_row"], 5)
        self.assertEqual(active_window["leading_idle_rows"], 2)
        self.assertEqual(active_window["trailing_idle_rows"], 2)
        self.assertEqual(summary["flight"]["detected_active_rows"], 3)
        self.assertEqual(summary["flight"]["detection_methods"], ["motor_or_throttle_activity"])


if __name__ == "__main__":
    unittest.main()
