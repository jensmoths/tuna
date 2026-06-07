from __future__ import annotations

import tempfile
import unittest
import json

try:
    import flask  # noqa: F401
except ModuleNotFoundError as exc:
    raise unittest.SkipTest("Flask is not installed") from exc
from pathlib import Path

from tune.services.builds import create_build
from tune.services.diagnoses import record_diagnosis
from tune.services.iterations import complete_no_change, create_iteration
from tune.services.loops import create_loop
from tune.services.operator_notifications import create_blackbox_config_notification
from tune.services.operator_tasks import create_build_confirmation_task, create_flight_capture_task, create_task, create_tune_goal_task
from tune.services.tune_updates import propose_tune_update
from tune.storage import connect, init_db
from tune.services.analysis import analyze_imported_log
from tune.web.app import create_app


class OperatorWebTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "tune.sqlite3"
        self.conn = connect(self.db_path)
        init_db(self.conn)

    def tearDown(self):
        self.tmp.cleanup()

    def test_review_task_approval_marks_update_pending_for_agent_write(self):
        build_id = create_build(self.conn, "5 inch")
        loop_id = create_loop(self.conn, build_id, "reduce propwash")
        iteration_id = create_iteration(self.conn, loop_id)
        record_diagnosis(self.conn, iteration_id, "Try a small D increase", confidence="medium")
        update_id = propose_tune_update(self.conn, iteration_id, build_id, {"d_pitch": 48}, cli_text="set d_pitch = 48")
        task_id = create_task(
            self.conn,
            "review_tune_update",
            "Review Tune Update",
            body="Review and approve write-back if safe.",
            payload={"tune_update_id": update_id},
        )
        client = create_app(self.db_path).test_client()
        page = client.get(f"/tasks/{task_id}")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Approve for Tuning Agent write-back", page.data)
        response = client.post(f"/tasks/{task_id}/approve-write", data={"safety_confirmed": "yes"})
        self.assertEqual(response.status_code, 302)
        update = self.conn.execute("SELECT status FROM tune_updates WHERE id = ?", (update_id,)).fetchone()
        task = self.conn.execute("SELECT status FROM operator_tasks WHERE id = ?", (task_id,)).fetchone()
        self.assertEqual(update["status"], "approved_pending_write")
        self.assertEqual(task["status"], "resolved")

    def test_analysis_pages_show_latest_analysis(self):
        build_id = create_build(self.conn, "5 inch")
        from tune.services.logs import import_blackbox_log
        imported_log_id = import_blackbox_log(self.conn, "reference-logs/btfl_001.bbl", build_id=build_id, storage_dir=self.root / "logs")
        csv_path = self.root / "summary.csv"
        csv_path.write_text("time,gyroADC[0],gyroADC[1],gyroADC[2],setpoint[0],setpoint[1],setpoint[2],motor[0],axisP[0],axisI[0],axisD[0]\n0,0,0,0,0,0,0,1000,0,0,0\n6000000,10,0,0,20,0,0,1200,1,1,1\n")
        analyze_imported_log(self.conn, imported_log_id, csv_path=csv_path)
        client = create_app(self.db_path).test_client()
        page = client.get("/analysis")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Blackbox Log #", page.data)
        detail = client.get(f"/logs/{imported_log_id}/analysis")
        self.assertEqual(detail.status_code, 200)
        self.assertIn(b"Quality", detail.data)
        self.assertIn(b"Tracking", detail.data)
        self.assertIn(b"Segments", detail.data)
        self.assertIn(b"Chirp analysis", detail.data)

    def test_flight_capture_task_shows_instructions_and_resolves(self):
        task_id = create_flight_capture_task(self.conn, build_id=1, loop_id=2, reason="Need cleaner roll/pitch/yaw response evidence")
        client = create_app(self.db_path).test_client()
        tasks_page = client.get("/tasks")
        self.assertEqual(tasks_page.status_code, 200)
        self.assertIn(b'class="local-time"', tasks_page.data)
        self.assertIn(b'data-utc="', tasks_page.data)
        page = client.get(f"/tasks/{task_id}")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Flight capture request", page.data)
        self.assertIn(b"1. Pilot:", page.data)
        self.assertIn(b"4. Operator:", page.data)
        self.assertIn(b"Operator post-flight steps", page.data)
        self.assertIn(b"Tuning Agent follow-up", page.data)
        self.assertIn(b"Post-flight Transfer", page.data)
        response = client.post(
            f"/tasks/{task_id}/resolve-flight-capture",
            data={"decision": "captured_needs_transfer", "notes": "Captured; Tuning Agent should transfer"},
        )
        self.assertEqual(response.status_code, 302)
        task = self.conn.execute("SELECT status, response_json FROM operator_tasks WHERE id = ?", (task_id,)).fetchone()
        self.assertEqual(task["status"], "resolved")
        self.assertIn("captured_needs_transfer", task["response_json"])

    def test_build_confirmation_task_shows_snapshot_and_resolves(self):
        create_build(self.conn, "5 inch")
        task_id = create_build_confirmation_task(
            self.conn,
            candidate_build_id=1,
            fc_snapshot={"fc_variant": "BTFL", "fc_version": "4.5.2"},
        )
        client = create_app(self.db_path).test_client()
        page = client.get(f"/tasks/{task_id}")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Build confirmation", page.data)
        self.assertIn(b"Candidate Build:</strong> #1 5 inch", page.data)
        self.assertIn(b">#1 5 inch</option>", page.data)
        self.assertNotIn(b"Reason:", page.data)
        self.assertIn(b"BTFL", page.data)
        response = client.post(
            f"/tasks/{task_id}/resolve-build-confirmation",
            data={"decision": "matches_existing_build", "build_id": "1", "notes": "Confirmed airframe"},
        )
        self.assertEqual(response.status_code, 302)
        task = self.conn.execute("SELECT status, response_json FROM operator_tasks WHERE id = ?", (task_id,)).fetchone()
        self.assertEqual(task["status"], "resolved")
        self.assertIn("matches_existing_build", task["response_json"])
        build = self.conn.execute("SELECT fc_snapshot_json FROM builds WHERE id = 1").fetchone()
        self.assertEqual(json.loads(build["fc_snapshot_json"])["fc_variant"], "BTFL")

    def test_tune_goal_task_shows_prompt_and_resolves(self):
        task_id = create_tune_goal_task(self.conn, build_id=3)
        client = create_app(self.db_path).test_client()
        page = client.get(f"/tasks/{task_id}")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Tune Goal request", page.data)
        response = client.post(
            f"/tasks/{task_id}/resolve-tune-goal",
            data={"tune_goal": "Reduce propwash", "notes": "Keep freestyle feel"},
        )
        self.assertEqual(response.status_code, 302)
        task = self.conn.execute("SELECT status, response_json FROM operator_tasks WHERE id = ?", (task_id,)).fetchone()
        self.assertEqual(task["status"], "resolved")
        self.assertIn("Reduce propwash", task["response_json"])

    def test_generic_operator_task_can_resolve_request_fcs_connection(self):
        build_id = create_build(self.conn, "5 inch")
        loop_id = create_loop(self.conn, build_id, "baseline")
        task_id = create_task(
            self.conn,
            "request_fcs_connection",
            "Connect FCS",
            body="Connect the FCS Bridge so the Tuning Agent can inspect the FC.",
            payload={"loop_id": loop_id, "bridge_host": "tuna-bridge-usb"},
        )
        client = create_app(self.db_path).test_client()
        page = client.get(f"/tasks/{task_id}")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Resolve Operator Task", page.data)

        response = client.post(
            f"/tasks/{task_id}/resolve-generic",
            data={"decision": "completed", "notes": "FCS Bridge is connected at tuna-bridge-usb"},
        )

        self.assertEqual(response.status_code, 302)
        task = self.conn.execute("SELECT status, response_json FROM operator_tasks WHERE id = ?", (task_id,)).fetchone()
        self.assertEqual(task["status"], "resolved")
        self.assertIn("FCS Bridge is connected", task["response_json"])
        session = self.conn.execute("SELECT resume_cursor_json FROM tuning_agent_sessions WHERE loop_id = ?", (loop_id,)).fetchone()
        cursor = json.loads(session["resume_cursor_json"])
        self.assertEqual(cursor["last_resolved_operator_task"]["id"], task_id)

    def test_blackbox_config_notification_shows_change_and_acknowledges(self):
        notification_id = create_blackbox_config_notification(
            self.conn,
            build_id=1,
            loop_id=2,
            settings={"debug_mode": "CHIRP", "blackbox_high_resolution": "ON"},
            previous_settings={"debug_mode": "GYRO_SCALED"},
            reason="Need chirp frequency-response evidence in the next Blackbox Log",
            impact="Higher Blackbox Log storage use while diagnostic logging is enabled",
        )
        client = create_app(self.db_path).test_client()
        page = client.get(f"/notifications/{notification_id}")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Operator Notification", page.data)
        self.assertIn(b"debug_mode", page.data)
        self.assertIn(b"Approval required", page.data)

        response = client.post(f"/notifications/{notification_id}/acknowledge", data={"notes": "Seen"})
        self.assertEqual(response.status_code, 302)
        notification = self.conn.execute("SELECT status, acknowledged_json FROM operator_notifications WHERE id = ?", (notification_id,)).fetchone()
        self.assertEqual(notification["status"], "acknowledged")
        self.assertIn("acknowledged", notification["acknowledged_json"])

    def test_loop_pages_show_iteration_diagnosis_and_no_change_result(self):
        build_id = create_build(self.conn, "5 inch", fc_snapshot={"fc_variant": "BTFL"}, operator_notes="Operator-confirmed Build")
        loop_id = create_loop(self.conn, build_id, "baseline")
        from tune.services.logs import import_blackbox_log
        imported_log_id = import_blackbox_log(self.conn, "reference-logs/btfl_001.bbl", build_id=build_id, storage_dir=self.root / "logs")
        iteration_id = create_iteration(self.conn, loop_id, [imported_log_id])
        record_diagnosis(self.conn, iteration_id, "No safe Tune Update yet", confidence="low", evidence={"log_ids": [imported_log_id]})
        complete_no_change(self.conn, iteration_id, "Need a better follow-up Blackbox Log")

        client = create_app(self.db_path).test_client()
        page = client.get("/loops")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Loop #", page.data)
        self.assertIn(b"baseline", page.data)
        detail = client.get(f"/loops/{loop_id}")
        self.assertEqual(detail.status_code, 200)
        self.assertIn(b"Tuning Iteration", detail.data)
        self.assertIn(b"no change", detail.data)
        self.assertIn(b"No safe Tune Update yet", detail.data)
        self.assertIn(b"Need a better follow-up Blackbox Log", detail.data)

    def test_loop_page_can_create_and_close_loop(self):
        build_id = create_build(self.conn, "5 inch", fc_snapshot={"fc_variant": "BTFL"})
        client = create_app(self.db_path).test_client()

        page = client.get("/loops")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Start new Loop", page.data)
        self.assertNotIn(b"Close Loop", page.data)

        response = client.post(
            "/loops",
            data={"build_id": str(build_id), "tune_goal": "Validate e2e workflow"},
        )
        self.assertEqual(response.status_code, 302)
        loop = self.conn.execute("SELECT * FROM loops WHERE build_id = ?", (build_id,)).fetchone()
        self.assertEqual(loop["status"], "open")
        self.assertEqual(loop["tune_goal"], "Validate e2e workflow")

        detail = client.get(f"/loops/{loop['id']}")
        self.assertIn(b"Close Loop", detail.data)
        from tune.services.operator_tasks import create_flight_capture_task
        task_id = create_flight_capture_task(self.conn, build_id=build_id, loop_id=loop["id"])
        close_response = client.post(f"/loops/{loop['id']}/close")
        self.assertEqual(close_response.status_code, 302)
        closed = self.conn.execute("SELECT status, ended_at FROM loops WHERE id = ?", (loop["id"],)).fetchone()
        self.assertEqual(closed["status"], "closed")
        self.assertIsNotNone(closed["ended_at"])
        task = self.conn.execute("SELECT status, response_json FROM operator_tasks WHERE id = ?", (task_id,)).fetchone()
        self.assertEqual(task["status"], "resolved")
        self.assertIn("closed_with_loop", task["response_json"])

    def test_build_page_can_create_build(self):
        client = create_app(self.db_path).test_client()

        page = client.get("/builds")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Create a new Build", page.data)

        response = client.post(
            "/builds",
            data={
                "name": "Darwin 5 inch",
                "fc_snapshot_json": '{"fc_variant":"BTFL","fc_version":"25.12.3"}',
                "operator_notes": "Operator-created Build",
            },
        )
        self.assertEqual(response.status_code, 302)
        build = self.conn.execute("SELECT * FROM builds WHERE name = ?", ("Darwin 5 inch",)).fetchone()
        self.assertIsNotNone(build)
        self.assertIn("25.12.3", build["fc_snapshot_json"])

        updated = client.get("/builds")
        self.assertIn(b"Darwin 5 inch", updated.data)
        self.assertIn(b"Operator-created Build", updated.data)


if __name__ == "__main__":
    unittest.main()
