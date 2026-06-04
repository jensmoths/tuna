from __future__ import annotations

import tempfile
import unittest

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
        page = client.get(f"/tasks/{task_id}")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Flight capture request", page.data)
        self.assertIn(b"Post-flight Transfer", page.data)
        response = client.post(f"/tasks/{task_id}/resolve-flight-capture", data={"imported": "yes", "notes": "Imported LOG001"})
        self.assertEqual(response.status_code, 302)
        task = self.conn.execute("SELECT status, response_json FROM operator_tasks WHERE id = ?", (task_id,)).fetchone()
        self.assertEqual(task["status"], "resolved")
        self.assertIn("imported", task["response_json"])

    def test_build_confirmation_task_shows_snapshot_and_resolves(self):
        task_id = create_build_confirmation_task(
            self.conn,
            candidate_build_id=3,
            fc_snapshot={"fc_variant": "BTFL", "fc_version": "4.5.2"},
        )
        client = create_app(self.db_path).test_client()
        page = client.get(f"/tasks/{task_id}")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Build confirmation", page.data)
        self.assertIn(b"BTFL", page.data)
        response = client.post(
            f"/tasks/{task_id}/resolve-build-confirmation",
            data={"decision": "matches_existing_build", "build_id": "3", "notes": "Confirmed airframe"},
        )
        self.assertEqual(response.status_code, 302)
        task = self.conn.execute("SELECT status, response_json FROM operator_tasks WHERE id = ?", (task_id,)).fetchone()
        self.assertEqual(task["status"], "resolved")
        self.assertIn("matches_existing_build", task["response_json"])

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


if __name__ == "__main__":
    unittest.main()
