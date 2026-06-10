from __future__ import annotations

import csv
import unittest

from tests.analysis_helpers import AnalysisTestCase
from tuna_blackbox.csv_summary import analyze_csv_log


class AnalysisStepResponseTests(AnalysisTestCase):
    def test_analyze_csv_log_summarizes_step_response(self):
        path = self.root / "step-response.csv"
        fieldnames = ["time", "gyroADC[0]", "gyroADC[1]", "gyroADC[2]", "setpoint[0]", "setpoint[1]", "setpoint[2]", "motor[0]", "axisP[0]", "axisI[0]", "axisD[0]", "rcCommand[3]"]
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for index in range(80):
                time_us = index * 10_000
                setpoint = 0 if index < 10 else 300
                if index < 12:
                    gyro = 0
                elif index < 20:
                    gyro = (index - 12) / 8 * 300
                elif index < 30:
                    gyro = 380
                else:
                    gyro = 300
                writer.writerow({name: 0 for name in fieldnames} | {"time": time_us, "setpoint[0]": setpoint, "gyroADC[0]": gyro, "motor[0]": 1200, "rcCommand[3]": 1200})

        summary = analyze_csv_log(path)

        roll = summary["step_response"]["axes"]["roll"]
        self.assertEqual(roll["summary"]["event_count"], 1)
        self.assertAlmostEqual(roll["summary"]["mean_latency_seconds"], 0.03)
        self.assertAlmostEqual(roll["summary"]["mean_rise_time_seconds"], 0.10)
        self.assertGreater(roll["summary"]["mean_overshoot_fraction"], 0.09)
        self.assertIn("overshooting", roll["flags"])


if __name__ == "__main__":
    unittest.main()
