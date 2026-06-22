from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from tuna_blackbox import cli


class TunaBlackboxCliTests(unittest.TestCase):
    def run_cli_json_with_code(self, *args: str):
        stdout = StringIO()
        with redirect_stdout(stdout):
            code = cli.main([*args, "--json"])
        return code, json.loads(stdout.getvalue())

    def test_metadata_outputs_concise_summary_without_tuna_db(self):
        code, result = self.run_cli_json_with_code("metadata", "reference-logs/btfl_001.bbl")

        self.assertEqual(code, 0)
        self.assertEqual(result["parse_status"], "readable")
        self.assertEqual(result["metadata_summary"]["pids"]["roll"], [45, 80, 40])
        self.assertNotIn("metadata", result)

    def test_analyze_csv_outputs_concise_summary_without_tuna_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "flight.csv"
            csv_path.write_text("time,gyroADC[0],gyroADC[1],gyroADC[2],setpoint[0],setpoint[1],setpoint[2],motor[0]\n0,0,0,0,0,0,0,1000\n1000000,10,0,0,20,0,0,1200\n")
            code, result = self.run_cli_json_with_code("analyze", str(csv_path))

        self.assertEqual(code, 0)
        self.assertEqual(result["row_count"], 2)
        self.assertIn("quality", result)

    def test_decode_analyze_runs_decode_then_analysis_without_tuna_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "flight.bbl"
            source.write_bytes(b"dummy")
            csv_path = Path(tmp) / "flight.csv"
            csv_path.write_text("time,gyroADC[0],gyroADC[1],gyroADC[2],setpoint[0],setpoint[1],setpoint[2],motor[0]\n0,0,0,0,0,0,0,1000\n")
            with patch("tuna_blackbox.cli.decode_blackbox_log", return_value=csv_path) as decode:
                code, result = self.run_cli_json_with_code("decode-analyze", str(source), "--output", str(csv_path))

        self.assertEqual(code, 0)
        self.assertEqual(result["csv_path"], str(csv_path))
        decode.assert_called_once()

    def test_compact_evidence_views_work_without_tuna_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "flight.csv"
            csv_path.write_text(
                "time,gyroADC[0],gyroADC[1],gyroADC[2],gyroUnfilt[0],gyroUnfilt[1],gyroUnfilt[2],setpoint[0],setpoint[1],setpoint[2],motor[0],axisP[0],axisI[0],axisD[0],rcCommand[3]\n"
                "0,0,0,0,0,0,0,0,0,0,1000,1,1,1,1200\n"
                "1000,10,0,0,20,0,0,0,0,0,1200,1,1,5,1200\n"
                "2000,20,0,0,40,0,0,250,0,0,1200,1,1,10,1200\n"
            )
            code, filter_result = self.run_cli_json_with_code("filter-evidence", str(csv_path))
            _, pid_result = self.run_cli_json_with_code("pid-response", str(csv_path))
            _, capture_result = self.run_cli_json_with_code("capture-plan", str(csv_path))
            _, noise_result = self.run_cli_json_with_code("noise-peaks", str(csv_path), "--limit", "1")
            _, propwash_result = self.run_cli_json_with_code("propwash", str(csv_path), "--limit", "1")

        self.assertEqual(code, 0)
        self.assertIn("filter_diagnosis", filter_result)
        self.assertIn("pid_response", pid_result)
        self.assertIn("need_more_data", capture_result)
        self.assertIn("noise_peaks", noise_result)
        self.assertIn("segments", propwash_result)


if __name__ == "__main__":
    unittest.main()
