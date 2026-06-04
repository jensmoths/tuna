from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from tune.cli.main import main


class TuneCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "tune.sqlite3"

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli_json(self, *args: str):
        out = StringIO()
        with redirect_stdout(out):
            code = main(["--db", str(self.db), *args, "--json"])
        self.assertEqual(code, 0)
        return json.loads(out.getvalue())

    def test_agent_friendly_cli_flow(self):
        self.run_cli_json("db", "init")
        build = self.run_cli_json("build", "create", "5 inch", "--fc-snapshot-json", '{"fc":"BTFL"}')
        loop = self.run_cli_json("loop", "create", "--build-id", str(build["build_id"]), "--tune-goal", "reduce propwash")
        log = self.run_cli_json(
            "log",
            "import",
            "reference-logs/btfl_001.bbl",
            "--build-id",
            str(build["build_id"]),
            "--storage-dir",
            str(self.root / "logs"),
        )
        self.assertEqual(log["parse_status"], "readable")
        self.assertEqual(log["metadata"]["pids"]["roll"], [45, 80, 40])
        iteration = self.run_cli_json("iteration", "create", "--loop-id", str(loop["loop_id"]), "--log-id", str(log["log_id"]))
        current = self.run_cli_json("iteration", "current", "--loop-id", str(loop["loop_id"]))
        self.assertEqual(current["id"], iteration["iteration_id"])
        self.run_cli_json("diagnosis", "record", "--iteration-id", str(iteration["iteration_id"]), "--body", "Good log")
        update = self.run_cli_json(
            "update",
            "propose",
            "--iteration-id",
            str(iteration["iteration_id"]),
            "--build-id",
            str(build["build_id"]),
            "--settings-json",
            '{"d_pitch":48}',
        )
        self.run_cli_json("update", "approve-for-write", "--update-id", str(update["update_id"]))
        pending = self.run_cli_json("update", "pending-writes")
        self.assertEqual(pending[0]["update_id"], update["update_id"])
        self.assertEqual(pending[0]["settings"], {"d_pitch": 48})
        applied = self.run_cli_json("update", "apply", "--update-id", str(update["update_id"]))
        self.assertEqual(applied["status"], "applied")
        status = self.run_cli_json("status")
        self.assertEqual(status["builds"], 1)
        self.assertEqual(status["logs"], 1)
        self.assertEqual(status["iterations_open"], 0)

    def test_iteration_complete_no_change_cli(self):
        self.run_cli_json("db", "init")
        build = self.run_cli_json("build", "create", "5 inch")
        loop = self.run_cli_json("loop", "create", "--build-id", str(build["build_id"]), "--tune-goal", "baseline")
        iteration = self.run_cli_json("iteration", "create", "--loop-id", str(loop["loop_id"]))
        self.run_cli_json("diagnosis", "record", "--iteration-id", str(iteration["iteration_id"]), "--body", "No safe change")

        completed = self.run_cli_json(
            "iteration",
            "complete-no-change",
            "--iteration-id",
            str(iteration["iteration_id"]),
            "--reason",
            "No safe Tune Update from this Blackbox Log alone",
        )

        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["result"], "no_change")
        self.assertIn("Blackbox Log", completed["no_change_reason"])

    def test_log_transfer_command_delegates_to_fcs_transfer_with_validation(self):
        output = self.root / "flight.bbl"
        payload = {
            "download": {
                "output_path": str(output),
                "starts_with_blackbox_header": True,
            },
            "operator_next_step": "Power-cycle/reset the FC back to USB CDC/MSP mode before further FC operations.",
        }
        with patch("tune.cli.main.transfer_blackbox_log_from_bridge", return_value=payload) as transfer:
            result = self.run_cli_json(
                "log",
                "transfer",
                "--bridge-host",
                "bridge.local",
                "--output",
                str(output),
                "--size",
                "1048576",
                "--timeout",
                "12",
            )
        self.assertEqual(result, payload)
        transfer.assert_called_once_with(
            "bridge.local",
            output_path=output,
            size=1048576,
            trigger_msc=True,
            timeout_seconds=12.0,
            resume=True,
            chunk_size=1024 * 1024,
            max_attempts=3,
            progress=None,
        )

    def test_log_analyze_json_is_concise_and_can_write_full_json_file(self):
        self.run_cli_json("db", "init")
        build = self.run_cli_json("build", "create", "5 inch")
        log = self.run_cli_json(
            "log",
            "import",
            "reference-logs/btfl_001.bbl",
            "--build-id",
            str(build["build_id"]),
            "--storage-dir",
            str(self.root / "logs"),
        )
        csv_path = self.root / "log.csv"
        csv_path.write_text(
            "time,gyroADC[0],gyroADC[1],gyroADC[2],setpoint[0],setpoint[1],setpoint[2],motor[0],rcCommand[3],axisP[0],axisI[0],axisD[0]\n"
            "0,0,0,0,0,0,0,1000,1000,0,0,0\n"
            "500000,10,0,0,20,0,0,1200,1100,1,0,0\n"
        )
        full_json = self.root / "analysis.json"

        result = self.run_cli_json(
            "log",
            "analyze",
            "--log-id",
            str(log["log_id"]),
            "--csv-path",
            str(csv_path),
            "--output-json-file",
            str(full_json),
        )

        self.assertEqual(result["log_id"], log["log_id"])
        self.assertEqual(result["row_count"], 2)
        self.assertIn("analysis_id", result)
        self.assertEqual(result["analysis_json_file"], str(full_json))
        self.assertNotIn("ranges", result)
        self.assertIn("ranges", json.loads(full_json.read_text()))

    def test_request_flight_capture_cli_records_operator_task(self):
        self.run_cli_json("db", "init")
        result = self.run_cli_json(
            "task",
            "request-flight-capture",
            "--build-id",
            "1",
            "--loop-id",
            "2",
            "--reason",
            "Need a follow-up Blackbox Log",
            "--capture-goal",
            "Capture propwash recovery maneuvers",
        )

        self.assertEqual(result["kind"], "request_flight_capture")
        tasks = self.run_cli_json("task", "list")
        self.assertEqual(tasks[0]["id"], result["task_id"])
        self.assertEqual(tasks[0]["kind"], "request_flight_capture")
        payload = json.loads(tasks[0]["payload_json"])
        self.assertEqual(payload["capture_goal"], "Capture propwash recovery maneuvers")
        self.assertIn("pilot_instructions", payload)
        self.assertIn("post_flight_steps", payload)

    def test_confirm_build_cli_records_operator_task(self):
        self.run_cli_json("db", "init")
        result = self.run_cli_json(
            "task",
            "confirm-build",
            "--candidate-build-id",
            "3",
            "--fc-snapshot-json",
            '{"fc_variant":"BTFL","fc_version":"4.5.2"}',
        )

        self.assertEqual(result["kind"], "confirm_build")
        tasks = self.run_cli_json("task", "list")
        self.assertEqual(tasks[0]["kind"], "confirm_build")
        payload = json.loads(tasks[0]["payload_json"])
        self.assertEqual(payload["candidate_build_id"], 3)
        self.assertEqual(payload["fc_snapshot"]["fc_variant"], "BTFL")

    def test_request_tune_goal_cli_records_operator_task(self):
        self.run_cli_json("db", "init")
        result = self.run_cli_json("task", "request-tune-goal", "--build-id", "3")

        self.assertEqual(result["kind"], "request_tune_goal")
        tasks = self.run_cli_json("task", "list")
        self.assertEqual(tasks[0]["kind"], "request_tune_goal")
        payload = json.loads(tasks[0]["payload_json"])
        self.assertEqual(payload["build_id"], 3)
        self.assertIn("prompt", payload)
        self.assertIn("examples", payload)

    def test_notify_blackbox_config_changed_cli_records_operator_notification(self):
        self.run_cli_json("db", "init")
        result = self.run_cli_json(
            "notify",
            "blackbox-config-changed",
            "--build-id",
            "1",
            "--settings-json",
            '{"debug_mode":"CHIRP"}',
            "--previous-settings-json",
            '{"debug_mode":"GYRO_SCALED"}',
            "--reason",
            "Need chirp evidence in the next Blackbox Log",
            "--impact",
            "Higher Blackbox Log storage use",
        )

        self.assertEqual(result["kind"], "blackbox_config_changed")
        notifications = self.run_cli_json("notify", "list")
        self.assertEqual(notifications[0]["id"], result["notification_id"])
        self.assertEqual(notifications[0]["kind"], "blackbox_config_changed")
        payload = json.loads(notifications[0]["payload_json"])
        self.assertFalse(payload["requires_operator_approval"])
        self.assertEqual(payload["settings"], {"debug_mode": "CHIRP"})


if __name__ == "__main__":
    unittest.main()
