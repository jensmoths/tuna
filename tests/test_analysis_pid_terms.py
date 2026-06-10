from __future__ import annotations

import csv
import unittest

from tests.analysis_helpers import AnalysisTestCase
from tuna_blackbox.csv_summary import analyze_csv_log


class AnalysisPidTermTests(AnalysisTestCase):
    def test_analyze_csv_log_summarizes_pid_term_analysis(self):
        path = self.root / "pid-term-analysis.csv"
        fieldnames = ["time", "gyroADC[0]", "gyroADC[1]", "gyroADC[2]", "setpoint[0]", "setpoint[1]", "setpoint[2]", "motor[0]", "axisP[0]", "axisI[0]", "axisD[0]", "axisF[0]", "rcCommand[3]"]
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for index in range(80):
                setpoint = 0 if index < 10 or index >= 50 else 300
                throttle = 1200 if index < 30 else 1800
                dterm = 120 if index in (30, 31) else 5
                iterm = 80 if index >= 50 else 10
                feedforward = 60 if 10 <= index <= 12 else 0
                writer.writerow({name: 0 for name in fieldnames} | {"time": index * 10_000, "gyroADC[0]": setpoint, "setpoint[0]": setpoint, "motor[0]": 1200, "axisP[0]": 40, "axisI[0]": iterm, "axisD[0]": dterm, "axisF[0]": feedforward, "rcCommand[3]": throttle})

        summary = analyze_csv_log(path)

        roll = summary["pid_term_analysis"]["axes"]["roll"]
        self.assertEqual(roll["terms"]["P"]["samples"], 80)
        self.assertEqual(roll["terms"]["I"]["max"], 80.0)
        self.assertEqual(roll["dterm_noise"]["spike_count"], 2)
        self.assertEqual(roll["throttle_coupling"]["dterm_spikes_near_throttle_changes"], 2)
        self.assertGreater(roll["iterm_windup"]["samples"], 0)
        self.assertEqual(roll["feedforward"]["setpoint_transition_count"], 2)
        self.assertEqual(roll["feedforward"]["active_transition_count"], 1)
        self.assertIn("dterm_spikes_near_throttle_changes", roll["flags"])
        self.assertIn("possible_iterm_windup", roll["flags"])


if __name__ == "__main__":
    unittest.main()
