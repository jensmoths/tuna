from __future__ import annotations

import csv
import unittest

from tests.analysis_helpers import AnalysisTestCase
from tune.analysis.csv_summary import analyze_csv_log


class AnalysisMotorTests(AnalysisTestCase):
    def test_analyze_csv_log_summarizes_motor_analysis(self):
        path = self.root / "motor-analysis.csv"
        fieldnames = ["time", "gyroADC[0]", "gyroADC[1]", "gyroADC[2]", "setpoint[0]", "setpoint[1]", "setpoint[2]", "motor[0]", "motor[1]", "motor[2]", "motor[3]", "axisP[0]", "axisI[0]", "axisD[0]", "rcCommand[3]"]
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for index in range(100):
                high_throttle = index >= 50
                writer.writerow({name: 0 for name in fieldnames} | {"time": index * 1000, "motor[0]": 1200 if not high_throttle else 1400, "motor[1]": 1220 if not high_throttle else 1420, "motor[2]": 1500 if not high_throttle else 1980, "motor[3]": 1190 if not high_throttle else 1390, "rcCommand[3]": 1200 if not high_throttle else 1800})

        summary = analyze_csv_log(path)

        motor_analysis = summary["motor_analysis"]
        self.assertEqual(motor_analysis["summary"]["motor_count"], 4)
        self.assertGreater(motor_analysis["motors"]["motor[2]"]["mean_offset_from_fleet"], 100.0)
        self.assertEqual(motor_analysis["motors"]["motor[2]"]["near_max_samples"], 50)
        self.assertIn("1700-1900", motor_analysis["motors"]["motor[2]"]["throttle_bins"])
        self.assertGreater(motor_analysis["summary"]["imbalance_score"], 120.0)
        self.assertTrue(any("Persistent motor offset" in warning for warning in motor_analysis["warnings"]))


if __name__ == "__main__":
    unittest.main()
