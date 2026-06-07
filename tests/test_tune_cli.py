from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import ANY, patch

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

    def run_cli_json_with_code(self, *args: str):
        out = StringIO()
        with redirect_stdout(out):
            code = main(["--db", str(self.db), *args, "--json"])
        return code, json.loads(out.getvalue())

    def test_python_module_entrypoint_shows_help(self):
        result = subprocess.run(
            [sys.executable, "-m", "tune", "--help"],
            cwd=Path.cwd(),
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0)
        self.assertIn("Tune helper tool", result.stdout)

    def test_web_cli_enables_verbose_mode(self):
        class FakeApp:
            def __init__(self):
                self.config = {}
                self.run_kwargs = None

            def run(self, **kwargs):
                self.run_kwargs = kwargs

        fake_app = FakeApp()
        with patch("tune.web.app.create_app", return_value=fake_app) as create_app:
            code = main([
                "--db",
                str(self.db),
                "web",
                "--host",
                "0.0.0.0",
                "--port",
                "9999",
                "--verbose",
            ])

        self.assertEqual(code, 0)
        create_app.assert_called_once_with(str(self.db))
        self.assertTrue(fake_app.config["TUNE_VERBOSE"])
        self.assertEqual(fake_app.run_kwargs, {"host": "0.0.0.0", "port": 9999})

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
            "--full-metadata",
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

    def test_iteration_complete_no_change_returns_json_error(self):
        self.run_cli_json("db", "init")
        build = self.run_cli_json("build", "create", "5 inch")
        loop = self.run_cli_json("loop", "create", "--build-id", str(build["build_id"]), "--tune-goal", "baseline")
        iteration = self.run_cli_json("iteration", "create", "--loop-id", str(loop["loop_id"]))

        code, result = self.run_cli_json_with_code(
            "iteration",
            "complete-no-change",
            "--iteration-id",
            str(iteration["iteration_id"]),
            "--reason",
            "No change",
        )

        self.assertEqual(code, 1)
        self.assertEqual(result["error"]["kind"], "ValueError")
        self.assertIn("Diagnosis", result["error"]["message"])

    def test_iteration_complete_with_diagnosis_is_atomic(self):
        self.run_cli_json("db", "init")
        build = self.run_cli_json("build", "create", "5 inch")
        loop = self.run_cli_json("loop", "create", "--build-id", str(build["build_id"]), "--tune-goal", "baseline")
        iteration = self.run_cli_json("iteration", "create", "--loop-id", str(loop["loop_id"]))

        completed = self.run_cli_json(
            "iteration",
            "complete-with-diagnosis",
            "--iteration-id",
            str(iteration["iteration_id"]),
            "--body",
            "Usable Blackbox Log, no safe change",
            "--reason",
            "No safe Tune Update",
            "--confidence",
            "medium",
            "--evidence-json",
            '{"logs":[1]}',
        )

        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["result"], "no_change")
        self.assertIn("diagnosis_id", completed)

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
            "analysis",
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

        summary = self.run_cli_json("analysis", "summary", "--log-id", str(log["log_id"]))
        self.assertEqual(summary["log_id"], log["log_id"])
        self.assertEqual(summary["row_count"], 2)
        self.assertIn("segment_counts", summary)
        self.assertNotIn("ranges", summary)

    def test_log_decode_analyze_runs_in_sequence(self):
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
        csv_path = self.root / "decoded.csv"
        analysis = {"row_count": 1, "duration_seconds": 0.0, "quality": {"usable": False}, "warnings": []}
        with patch("tune.cli.main.decode_imported_log", return_value={"log_id": log["log_id"], "csv_path": str(csv_path)}) as decode:
            with patch("tune.cli.main.analyze_imported_log", return_value=analysis) as analyze:
                result = self.run_cli_json("analysis", "decode-analyze", "--log-id", str(log["log_id"]))

        decode.assert_called_once()
        analyze.assert_called_once_with(ANY, log["log_id"], csv_path=str(csv_path))
        self.assertEqual(result["csv_path"], str(csv_path))
        self.assertEqual(result["row_count"], 1)

    def test_log_analyze_without_decoded_csv_returns_json_error(self):
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

        code, result = self.run_cli_json_with_code("analysis", "analyze", "--log-id", str(log["log_id"]))

        self.assertEqual(code, 1)
        self.assertEqual(result["error"]["kind"], "ValueError")
        self.assertIn("no decoded CSV", result["error"]["message"])

    def test_log_import_json_is_concise_by_default_and_can_write_metadata(self):
        self.run_cli_json("db", "init")
        build = self.run_cli_json("build", "create", "5 inch")
        metadata_file = self.root / "metadata.json"

        result = self.run_cli_json(
            "log",
            "import",
            "reference-logs/btfl_001.bbl",
            "--build-id",
            str(build["build_id"]),
            "--storage-dir",
            str(self.root / "logs"),
            "--metadata-json-file",
            str(metadata_file),
        )

        self.assertEqual(result["parse_status"], "readable")
        self.assertNotIn("metadata", result)
        self.assertIn("metadata_summary", result)
        self.assertEqual(result["metadata_json_file"], str(metadata_file))
        self.assertEqual(json.loads(metadata_file.read_text())["pids"]["roll"], [45, 80, 40])

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
        self.assertIn("operator_message", payload)
        self.assertIn("1. Pilot:", payload["operator_message"])
        self.assertIn("4. Operator:", payload["operator_message"])
        self.assertIn("pilot_instructions", payload)
        self.assertIn("operator_post_flight_steps", payload)
        self.assertIn("tuning_agent_follow_up_steps", payload)
        self.assertIn("captured_needs_transfer", payload["decision_options"])
        self.assertNotIn("imported_log_id", payload["decision_options"])

    def test_request_fcs_connection_cli_records_operator_task(self):
        self.run_cli_json("db", "init")
        result = self.run_cli_json(
            "task",
            "request-fcs-connection",
            "--build-id",
            "1",
            "--loop-id",
            "2",
            "--bridge-host",
            "tuna-bridge-usb",
            "--reason",
            "Bridge timed out during Post-flight Transfer",
        )

        self.assertEqual(result["kind"], "request_fcs_connection")
        tasks = self.run_cli_json("task", "list", "--status", "open", "--limit", "1")
        self.assertEqual(tasks[0]["id"], result["task_id"])
        self.assertEqual(tasks[0]["payload"]["bridge_host"], "tuna-bridge-usb")
        self.assertEqual(json.loads(tasks[0]["payload_json"])["loop_id"], 2)

        task = self.run_cli_json("task", "show", "--task-id", str(result["task_id"]))
        self.assertEqual(task["id"], result["task_id"])
        self.assertEqual(task["payload"]["bridge_host"], "tuna-bridge-usb")

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
        self.assertEqual(payload["reason"], "")

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
            "notification",
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
        notifications = self.run_cli_json("notification", "list")
        self.assertEqual(notifications[0]["id"], result["notification_id"])
        self.assertEqual(notifications[0]["kind"], "blackbox_config_changed")
        payload = json.loads(notifications[0]["payload_json"])
        self.assertFalse(payload["requires_operator_approval"])
        self.assertEqual(payload["settings"], {"debug_mode": "CHIRP"})

    def test_loop_context_compacts_state(self):
        self.run_cli_json("db", "init")
        build = self.run_cli_json("build", "create", "5 inch", "--fc-snapshot-json", '{"fc_variant":"BTFL"}')
        loop = self.run_cli_json("loop", "create", "--build-id", str(build["build_id"]), "--tune-goal", "reduce propwash")
        self.run_cli_json("task", "request-flight-capture", "--build-id", str(build["build_id"]), "--loop-id", str(loop["loop_id"]))

        context = self.run_cli_json("loop", "context", "--loop-id", str(loop["loop_id"]))

        self.assertEqual(context["loop"]["id"], loop["loop_id"])
        self.assertEqual(context["build"]["fc_snapshot"], {"fc_variant": "BTFL"})
        self.assertEqual(context["open_tasks"][0]["kind"], "request_flight_capture")

        status = self.run_cli_json("loop", "status", "--loop-id", str(loop["loop_id"]))
        self.assertEqual(status["loop"]["id"], loop["loop_id"])
        self.assertEqual(status["open_tasks"][0]["kind"], "request_flight_capture")
        self.assertNotIn("payload", status["open_tasks"][0])

    def test_build_show_returns_one_build(self):
        self.run_cli_json("db", "init")
        build = self.run_cli_json("build", "create", "5 inch", "--fc-snapshot-json", '{"identity":{"fc_variant":"BTFL"}}')

        shown = self.run_cli_json("build", "show", "--build-id", str(build["build_id"]))

        self.assertEqual(shown["id"], build["build_id"])
        self.assertEqual(shown["fc_snapshot"]["identity"]["fc_variant"], "BTFL")



if __name__ == "__main__":
    unittest.main()
