from __future__ import annotations

import csv
import math

from tests.analysis_helpers import AnalysisTestCase
from tuna_blackbox.csv_summary import analyze_csv_log
from tuna_core.services.analysis import analyze_imported_log
from tuna_core.services.builds import create_build
from tuna_core.services.logs import import_blackbox_log
from tuna_core.services.segment_rows import get_segment_rows
from tuna_core.storage import connect, init_db


class ChirpAnalysisTests(AnalysisTestCase):
    def write_chirp_csv(self) -> Path:
        path = self.root / "chirp.csv"
        sample_rate_hz = 1000
        fieldnames = [
            "time",
            "gyroADC[0]", "gyroADC[1]", "gyroADC[2]",
            "setpoint[0]", "setpoint[1]", "setpoint[2]",
            "debug[0]", "debug[1]", "debug[2]", "debug[3]",
            "motor[0]",
        ]
        with path.open("w", newline="") as handle:
            handle.write('"debug_mode",97\n')
            handle.write('"blackbox_high_resolution",0\n')
            handle.write('"chirp_time_seconds",2\n')
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for index in range(2200):
                active = 100 <= index < 2100
                t = index / sample_rate_hz
                signal = math.sin(2 * math.pi * 20 * t) if active else 0.0
                writer.writerow({
                    "time": index * 1000,
                    "gyroADC[0]": 0.8 * signal,
                    "gyroADC[1]": 0,
                    "gyroADC[2]": 0,
                    "setpoint[0]": signal,
                    "setpoint[1]": 0,
                    "setpoint[2]": 0,
                    "debug[0]": 5000 * (2 * math.pi * 20 * t % (2 * math.pi)) if active else 0,
                    "debug[1]": 0 if active else -1,
                    "debug[2]": 200 if active else 0,
                    "debug[3]": 1000 * signal,
                    "motor[0]": 1500,
                })
        return path

    def test_analyze_csv_log_summarizes_chirp_segments_and_response(self):
        path = self.write_chirp_csv()

        summary = analyze_csv_log(path)

        chirp = summary["chirp_analysis"]
        self.assertTrue(chirp["available"])
        self.assertEqual(chirp["confidence"], "medium")
        self.assertEqual(chirp["debug_mode"], 97)
        self.assertEqual(chirp["settings"]["chirp_time_seconds"], 2)
        self.assertEqual(len(chirp["segments"]), 1)
        self.assertEqual(len(summary["segments"]["chirp"]), 1)
        self.assertEqual(chirp["segments"][0]["axis"], "roll")
        self.assertTrue(chirp["segments"][0]["usable"])
        self.assertIn("Missing usable chirp axes", "\n".join(chirp["warnings"]))
        self.assertGreater(chirp["axes"]["roll"]["mean_coherence_5_100hz"], 0.9)
        self.assertEqual(chirp["segments"][0]["raw_data_ref"]["start_row"], 101)

    def test_analyze_csv_log_reports_chirp_unavailable_without_debug_fields(self):
        summary = analyze_csv_log(self.write_csv())
        chirp = summary["chirp_analysis"]
        self.assertFalse(chirp["available"])
        self.assertEqual(chirp["reason"], "missing_fields")
        self.assertIn("Missing CHIRP debug fields", chirp["warnings"][0])

    def test_analyze_csv_log_does_not_treat_generic_debug_fields_as_chirp(self):
        path = self.root / "generic-debug.csv"
        fieldnames = [
            "time",
            "gyroADC[0]", "gyroADC[1]", "gyroADC[2]",
            "setpoint[0]", "setpoint[1]", "setpoint[2]",
            "debug[0]", "debug[1]", "debug[2]", "debug[3]",
            "motor[0]",
        ]
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for index in range(100):
                writer.writerow({name: 0 for name in fieldnames} | {"time": index * 1000, "debug[1]": index % 3, "motor[0]": 1200})

        summary = analyze_csv_log(path)

        chirp = summary["chirp_analysis"]
        self.assertFalse(chirp["available"])
        self.assertEqual(chirp["reason"], "debug_mode_not_chirp")
        self.assertEqual(summary["segments"]["chirp"], [])

    def test_service_returns_chirp_segment_rows_from_latest_analysis(self):
        conn = connect(self.root / "tune.sqlite3")
        init_db(conn)
        build_id = create_build(conn, "5 inch")
        log_id = import_blackbox_log(conn, "reference-logs/btfl_001.bbl", build_id=build_id, storage_dir=self.root / "logs")
        analyze_imported_log(conn, log_id, csv_path=self.write_chirp_csv())

        payload = get_segment_rows(conn, log_id=log_id, segment_kind="chirp", segment_index=0, fields=["time", "setpoint[0]", "gyroADC[0]", "debug[1]"], max_rows=5)

        self.assertEqual(payload["segment_kind"], "chirp")
        self.assertEqual(payload["segment"]["axis"], "roll")
        self.assertEqual(payload["fields"], ["time", "setpoint[0]", "gyroADC[0]", "debug[1]"])
        self.assertEqual(len(payload["rows"]), 5)


if __name__ == "__main__":
    import unittest

    unittest.main()
