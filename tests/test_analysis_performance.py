from __future__ import annotations

import csv
import math
import tempfile
import time
import unittest
from pathlib import Path

from tuna_blackbox.csv_summary import analyze_csv_log
from tuna_blackbox.segment_rows import read_segment_rows


LARGE_CSV_ROWS = 20_000
ANALYZE_CSV_MAX_SECONDS = 3.0
SEGMENT_ROWS_MAX_SECONDS = 0.5


class AnalysisPerformanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        cls.csv_path = cls.root / "large-analysis.csv"
        cls._write_large_csv(cls.csv_path, LARGE_CSV_ROWS)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    @staticmethod
    def _write_large_csv(path: Path, rows: int) -> None:
        fieldnames = [
            "time",
            "gyroADC[0]",
            "gyroADC[1]",
            "gyroADC[2]",
            "gyroUnfilt[0]",
            "setpoint[0]",
            "setpoint[1]",
            "setpoint[2]",
            "motor[0]",
            "motor[1]",
            "motor[2]",
            "motor[3]",
            "axisP[0]",
            "axisP[1]",
            "axisP[2]",
            "axisI[0]",
            "axisI[1]",
            "axisI[2]",
            "axisD[0]",
            "axisD[1]",
            "axisD[2]",
            "axisF[0]",
            "axisF[1]",
            "axisF[2]",
            "rcCommand[3]",
            "debug[0]",
        ]
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for index in range(rows):
                writer.writerow(
                    {
                        "time": index * 1000,
                        "gyroADC[0]": math.sin(2 * math.pi * 100 * index / 1000) * 50,
                        "gyroADC[1]": math.sin(2 * math.pi * 80 * index / 1000) * 40,
                        "gyroADC[2]": math.sin(2 * math.pi * 40 * index / 1000) * 30,
                        "gyroUnfilt[0]": math.sin(2 * math.pi * 200 * index / 1000) * 70,
                        "setpoint[0]": 250 if (index % 5000) < 500 else 0,
                        "setpoint[1]": -260 if (index % 7000) < 400 else 0,
                        "setpoint[2]": 0,
                        "motor[0]": 1000 + (index % 800),
                        "motor[1]": 1100 + (index % 700),
                        "motor[2]": 1200 + (index % 600),
                        "motor[3]": 1300 + (index % 500),
                        "axisP[0]": 1,
                        "axisP[1]": 1,
                        "axisP[2]": 1,
                        "axisI[0]": 1,
                        "axisI[1]": 1,
                        "axisI[2]": 1,
                        "axisD[0]": math.sin(2 * math.pi * 150 * index / 1000) * 10,
                        "axisD[1]": math.sin(2 * math.pi * 120 * index / 1000) * 8,
                        "axisD[2]": math.sin(2 * math.pi * 90 * index / 1000) * 6,
                        "axisF[0]": 5,
                        "axisF[1]": 5,
                        "axisF[2]": 5,
                        "rcCommand[3]": 1750 if (index % 10000) < 800 else 1300,
                        "debug[0]": math.sin(2 * math.pi * 300 * index / 1000),
                    }
                )

    def test_analyze_csv_log_large_file_is_fast_enough(self):
        started = time.perf_counter()
        summary = analyze_csv_log(self.csv_path)
        elapsed = time.perf_counter() - started

        self.assertEqual(summary["row_count"], LARGE_CSV_ROWS)
        self.assertIn("gyroADC[0]", summary["spectrum"]["signals"])
        self.assertIn("gyroADC[0]", summary["frequency_throttle_heatmap"]["signals"])
        self.assertTrue(summary["filter_analysis"]["axes"]["roll"]["available"])
        self.assertTrue(summary["rpm_analysis"]["available"])
        self.assertIn("peaks", summary["noise_peaks"])
        self.assertIn("roll", summary["step_response"]["axes"])
        self.assertEqual(summary["motor_analysis"]["summary"]["motor_count"], 4)
        self.assertIn("roll", summary["pid_term_analysis"]["axes"])
        self.assertLess(
            elapsed,
            ANALYZE_CSV_MAX_SECONDS,
            f"analyze_csv_log took {elapsed:.3f}s for {LARGE_CSV_ROWS} rows; expected < {ANALYZE_CSV_MAX_SECONDS:.3f}s",
        )

    def test_read_segment_rows_large_file_is_fast_enough(self):
        started = time.perf_counter()
        payload = read_segment_rows(
            self.csv_path,
            start_row=15_000,
            end_row=15_100,
            fields=["time", "gyroADC[0]"],
            pad_rows=10,
            max_rows=200,
        )
        elapsed = time.perf_counter() - started

        self.assertEqual(len(payload["rows"]), 121)
        self.assertLess(
            elapsed,
            SEGMENT_ROWS_MAX_SECONDS,
            f"read_segment_rows took {elapsed:.3f}s; expected < {SEGMENT_ROWS_MAX_SECONDS:.3f}s",
        )


if __name__ == "__main__":
    unittest.main()
