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
from tune.services.iterations import create_iteration
from tune.services.loops import create_loop
from tune.services.operator_tasks import create_task
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


if __name__ == "__main__":
    unittest.main()
