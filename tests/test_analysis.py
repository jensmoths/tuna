from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tune.analysis.csv_summary import analyze_csv_log
from tune.analysis.decode import BlackboxDecodeError, decode_blackbox_log
from tune.services.analysis import analyze_imported_log, decode_imported_log
from tune.services.builds import create_build
from tune.services.logs import import_blackbox_log
from tune.storage import connect, init_db


class AnalysisTests(unittest.TestCase):
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

    def test_analyze_csv_log_summarizes_ranges_and_duration(self):
        summary = analyze_csv_log(self.write_csv())
        self.assertEqual(summary["row_count"], 2)
        self.assertEqual(summary["duration_seconds"], 0.5)
        self.assertEqual(summary["ranges"]["gyroADC[0]"], {"min": -10.0, "max": 20.0})
        self.assertEqual(summary["ranges"]["motor[0]"], {"min": 1100.0, "max": 1500.0})
        self.assertTrue(summary["quality"]["duration_ok"] is False)
        self.assertEqual(summary["activity"]["max_abs_setpoint"]["roll"], 200.0)
        self.assertEqual(summary["activity"]["high_rate_samples"]["roll"], 1)
        self.assertGreater(summary["tracking"]["roll"]["mean_abs_error"], 0)
        self.assertIn("gyroADC[0]", summary["rough_noise"])
        self.assertIn("high_rate", summary["segments"])
        self.assertIn("throttle_punch", summary["segments"])

    def test_decode_blackbox_log_reports_missing_decoder(self):
        with self.assertRaises(BlackboxDecodeError):
            decode_blackbox_log("missing.bbl", self.root / "out.csv", decoder_command="definitely-not-blackbox-decode")

    def test_services_store_decode_and_analysis_artifacts(self):
        conn = connect(self.root / "tune.sqlite3")
        init_db(conn)
        build_id = create_build(conn, "5 inch")
        log_id = import_blackbox_log(conn, "reference-logs/btfl_001.bbl", build_id=build_id, storage_dir=self.root / "logs")
        csv_path = self.write_csv()

        with patch("tune.services.analysis.decode_blackbox_log", return_value=csv_path):
            decoded = decode_imported_log(conn, log_id, output_dir=self.root / "decoded")
        self.assertEqual(decoded["csv_path"], str(csv_path))

        summary = analyze_imported_log(conn, log_id)
        self.assertEqual(summary["row_count"], 2)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM decoded_logs").fetchone()[0], 1)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM log_analyses").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
