from __future__ import annotations

import csv
import unittest
from unittest.mock import patch

from tests.analysis_helpers import AnalysisTestCase
from tune.analysis.csv_summary import analyze_csv_log
from tune.analysis.decode import BlackboxDecodeError, decode_blackbox_log
from tune.analysis.segment_rows import read_segment_rows
from tune.services.analysis import analyze_imported_log, decode_imported_log
from tune.services.builds import create_build
from tune.services.logs import import_blackbox_log
from tune.services.segment_rows import get_segment_rows
from tune.storage import connect, init_db


class AnalysisTests(AnalysisTestCase):
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
        self.assertEqual(summary["timing"]["nominal_interval_us"], 500000.0)
        self.assertEqual(summary["timing"]["nominal_logging_rate_hz"], 2.0)
        self.assertEqual(summary["timing"]["effective_logging_rate_hz"], 2.0)
        self.assertEqual(summary["timing"]["gap_count"], 0)
        self.assertIn("high_rate", summary["segments"])
        self.assertIn("throttle_punch", summary["segments"])
        self.assertIn("chirp", summary["segments"])
        self.assertIn("analysis_capabilities", summary)

    def test_read_segment_rows_returns_selected_window(self):
        csv_path = self.write_csv()
        payload = read_segment_rows(csv_path, start_row=1, end_row=1, fields=["time", "gyroADC[0]"], pad_rows=1, max_rows=10)
        self.assertEqual(payload["returned_start_row"], 1)
        self.assertEqual(payload["returned_end_row"], 2)
        self.assertEqual(payload["fields"], ["time", "gyroADC[0]"])
        self.assertEqual(payload["rows"][0]["_row"], "1")
        self.assertIn("gyroADC[0]", payload["rows"][0])

    def test_segments_include_per_segment_metrics_and_raw_data_refs(self):
        path = self.root / "segments.csv"
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["time", "gyroADC[0]", "gyroADC[1]", "gyroADC[2]", "setpoint[0]", "setpoint[1]", "setpoint[2]", "motor[0]", "rcCommand[3]", "axisD[0]"])
            writer.writeheader()
            writer.writerow({"time": 0, "gyroADC[0]": 0, "gyroADC[1]": 0, "gyroADC[2]": 0, "setpoint[0]": 0, "setpoint[1]": 0, "setpoint[2]": 0, "motor[0]": 1000, "rcCommand[3]": 1000, "axisD[0]": 0})
            writer.writerow({"time": 100000, "gyroADC[0]": 150, "gyroADC[1]": 0, "gyroADC[2]": 0, "setpoint[0]": 250, "setpoint[1]": 0, "setpoint[2]": 0, "motor[0]": 1500, "rcCommand[3]": 1750, "axisD[0]": 10})
            writer.writerow({"time": 250000, "gyroADC[0]": 260, "gyroADC[1]": 0, "gyroADC[2]": 0, "setpoint[0]": 300, "setpoint[1]": 0, "setpoint[2]": 0, "motor[0]": 2000, "rcCommand[3]": 1800, "axisD[0]": 30})
        summary = analyze_csv_log(path)
        high_rate = summary["segments"]["high_rate"]
        self.assertEqual(len(high_rate), 1)
        self.assertEqual(high_rate[0]["axis"], "roll")
        self.assertEqual(high_rate[0]["raw_data_ref"]["csv_path"], str(path))
        self.assertEqual(high_rate[0]["raw_data_ref"]["start_row"], 2)
        self.assertGreater(high_rate[0]["tracking"]["mean_abs_error"], 0)
        self.assertGreater(high_rate[0]["rough_noise"]["gyro_mean_abs_delta"], 0)
        self.assertEqual(len(summary["segments"]["throttle_punch"]), 1)

    def test_decode_blackbox_log_reports_missing_decoder(self):
        with self.assertRaises(BlackboxDecodeError):
            decode_blackbox_log("missing.bbl", self.root / "out.csv", decoder_command="definitely-not-blackbox-decode")

    def test_service_returns_segment_rows_from_latest_analysis(self):
        conn = connect(self.root / "tune.sqlite3")
        init_db(conn)
        build_id = create_build(conn, "5 inch")
        log_id = import_blackbox_log(conn, "reference-logs/btfl_001.bbl", build_id=build_id, storage_dir=self.root / "logs")
        csv_path = self.root / "segments.csv"
        csv_path.write_text("time,gyroADC[0],gyroADC[1],gyroADC[2],setpoint[0],setpoint[1],setpoint[2],motor[0],rcCommand[3],axisP[0],axisI[0],axisD[0]\n0,0,0,0,0,0,0,1000,1000,0,0,0\n100000,150,0,0,250,0,0,1500,1750,0,0,10\n250000,260,0,0,300,0,0,2000,1800,0,0,30\n")
        analyze_imported_log(conn, log_id, csv_path=csv_path)
        payload = get_segment_rows(conn, log_id=log_id, segment_kind="high_rate", segment_index=0, fields=["time", "setpoint[0]", "gyroADC[0]"], max_rows=10)
        self.assertEqual(payload["log_id"], log_id)
        self.assertEqual(payload["segment_kind"], "high_rate")
        self.assertEqual(len(payload["rows"]), 2)
        self.assertEqual(payload["fields"], ["time", "setpoint[0]", "gyroADC[0]"])

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
