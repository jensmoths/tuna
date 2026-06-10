from __future__ import annotations

import csv
import math
import unittest

from tests.analysis_helpers import AnalysisTestCase
from tuna_blackbox.csv_summary import analyze_csv_log


class AnalysisFilterTests(AnalysisTestCase):
    def test_analyze_csv_log_estimates_filter_attenuation(self):
        path = self.root / "filter-analysis.csv"
        fieldnames = ["time", "gyroADC[0]", "gyroADC[1]", "gyroADC[2]", "gyroUnfilt[0]", "gyroUnfilt[1]", "gyroUnfilt[2]", "setpoint[0]", "setpoint[1]", "setpoint[2]", "motor[0]", "axisP[0]", "axisI[0]", "axisD[0]", "rcCommand[3]"]
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for index in range(1000):
                low_frequency = math.sin(2 * math.pi * 50 * index / 1000)
                high_frequency = math.sin(2 * math.pi * 300 * index / 1000)
                writer.writerow({name: 0 for name in fieldnames} | {"time": index * 1000, "gyroUnfilt[0]": low_frequency + high_frequency, "gyroADC[0]": low_frequency + high_frequency * 0.1, "motor[0]": 1000, "rcCommand[3]": 1200})

        summary = analyze_csv_log(path)

        roll = summary["filter_analysis"]["axes"]["roll"]
        self.assertTrue(roll["available"])
        high_band = roll["bands"]["250-500Hz"]
        low_band = roll["bands"]["0-100Hz"]
        self.assertLess(high_band["attenuation_ratio"], 0.05)
        self.assertLess(high_band["attenuation_db"], -10.0)
        self.assertGreater(low_band["attenuation_ratio"], 0.8)


if __name__ == "__main__":
    unittest.main()
