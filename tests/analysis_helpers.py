from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path


class AnalysisTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write_csv(self) -> Path:
        path = self.root / "log.csv"
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["time", "gyroADC[0]", "gyroADC[1]", "gyroADC[2]", "setpoint[0]", "setpoint[1]", "setpoint[2]", "motor[0]"])
            writer.writeheader()
            writer.writerow({"time": 1000000, "gyroADC[0]": -10, "gyroADC[1]": 0, "gyroADC[2]": 5, "setpoint[0]": 100, "setpoint[1]": 0, "setpoint[2]": 0, "motor[0]": 1100})
            writer.writerow({"time": 1500000, "gyroADC[0]": 20, "gyroADC[1]": -30, "gyroADC[2]": 15, "setpoint[0]": 200, "setpoint[1]": 50, "setpoint[2]": 0, "motor[0]": 1500})
        return path
