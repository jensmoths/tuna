from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tune.blackbox import parse_blackbox_metadata
from tune.services.builds import create_build
from tune.services.diagnoses import record_diagnosis
from tune.services.iterations import create_iteration
from tune.services.logs import import_blackbox_log
from tune.services.loops import create_loop
from tune.services.tune_updates import mark_applied, propose_tune_update, reject
from tune.storage import connect, init_db


class TuneWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.conn = connect(self.root / "tune.sqlite3")
        init_db(self.conn)

    def tearDown(self):
        self.tmp.cleanup()

    def test_parse_blackbox_metadata_from_reference_log(self):
        parsed = parse_blackbox_metadata("reference-logs/btfl_001.bbl")
        self.assertEqual(parsed.parse_status, "readable")
        self.assertEqual(parsed.metadata["firmware_revision"], "Betaflight 4.5.2 (024f8e13d) AT32F435G")
        self.assertEqual(parsed.metadata["pids"]["roll"], [45, 80, 40])
        self.assertIn("time", parsed.metadata["fields"]["I"])

    def test_import_log_copies_hashes_extracts_metadata_and_deduplicates(self):
        build_id = create_build(self.conn, "5 inch", fc_snapshot={"fc": "BTFL"})
        log_id = import_blackbox_log(
            self.conn,
            "reference-logs/btfl_001.bbl",
            build_id=build_id,
            storage_dir=self.root / "logs",
        )
        duplicate_id = import_blackbox_log(
            self.conn,
            "reference-logs/btfl_001.bbl",
            build_id=build_id,
            storage_dir=self.root / "logs",
        )
        self.assertEqual(log_id, duplicate_id)
        row = self.conn.execute("SELECT * FROM blackbox_logs WHERE id = ?", (log_id,)).fetchone()
        self.assertEqual(row["parse_status"], "readable")
        self.assertTrue(Path(row["managed_path"]).exists())
        metadata = json.loads(row["metadata_json"])
        self.assertEqual(metadata["pids"]["pitch"], [47, 84, 46])

    def test_only_one_open_iteration_per_loop(self):
        build_id = create_build(self.conn, "5 inch")
        loop_id = create_loop(self.conn, build_id, "reduce propwash")
        create_iteration(self.conn, loop_id)
        with self.assertRaises(ValueError):
            create_iteration(self.conn, loop_id)

    def test_tune_update_apply_and_reject_rules(self):
        build_id = create_build(self.conn, "5 inch")
        loop_id = create_loop(self.conn, build_id, "reduce propwash")
        iteration_id = create_iteration(self.conn, loop_id)
        record_diagnosis(self.conn, iteration_id, "Needs more D on pitch", confidence="medium")
        with self.assertRaises(ValueError):
            propose_tune_update(self.conn, iteration_id, build_id, {"d_pitch": "+2"})
        update_id = propose_tune_update(
            self.conn,
            iteration_id,
            build_id,
            {"d_pitch": 48},
            cli_text="set d_pitch = 48",
        )
        mark_applied(self.conn, update_id)
        row = self.conn.execute("SELECT status FROM tuning_iterations WHERE id = ?", (iteration_id,)).fetchone()
        self.assertEqual(row["status"], "completed")

        iteration_id = create_iteration(self.conn, loop_id)
        update_id = propose_tune_update(self.conn, iteration_id, build_id, {"p_roll": 44})
        with self.assertRaises(ValueError):
            reject(self.conn, update_id, "")
        reject(self.conn, update_id, "Operator wants another confirmation flight")
        row = self.conn.execute("SELECT status, rejection_reason FROM tune_updates WHERE id = ?", (update_id,)).fetchone()
        self.assertEqual(row["status"], "rejected")
        self.assertIn("confirmation", row["rejection_reason"])


if __name__ == "__main__":
    unittest.main()
