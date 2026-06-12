from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tuna_blackbox import parse_blackbox_metadata
from tuna_core.services.builds import create_build
from tuna_core.services.diagnoses import record_diagnosis
from tuna_core.services.iterations import complete_no_change, create_iteration
from tuna_core.services.logs import import_blackbox_log
from tuna_core.services.loops import create_loop
from tuna_core.services.tune_updates import approve_for_write, mark_applied, propose_tune_update, reject
from tuna_core.storage import connect, init_db


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
        with self.assertRaises(ValueError):
            mark_applied(self.conn, update_id)
        approve_for_write(self.conn, update_id)
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

    def test_tune_update_status_transitions_are_enforced(self):
        build_id = create_build(self.conn, "5 inch")
        loop_id = create_loop(self.conn, build_id, "reduce propwash")
        iteration_id = create_iteration(self.conn, loop_id)
        record_diagnosis(self.conn, iteration_id, "Needs review")
        update_id = propose_tune_update(self.conn, iteration_id, build_id, {"p_roll": 44})

        with self.assertRaises(ValueError):
            mark_applied(self.conn, update_id)
        approve_for_write(self.conn, update_id)
        with self.assertRaises(ValueError):
            reject(self.conn, update_id, "too late")
        mark_applied(self.conn, update_id)
        with self.assertRaises(ValueError):
            approve_for_write(self.conn, update_id)

    def test_storage_status_contracts_reject_invalid_states(self):
        build_id = create_build(self.conn, "5 inch")
        with self.assertRaises(Exception):
            self.conn.execute("INSERT INTO loops (build_id, tune_goal, status) VALUES (?, ?, ?)", (build_id, "baseline", "maybe"))
        with self.assertRaises(Exception):
            self.conn.execute(
                "INSERT INTO blackbox_logs (build_id, source_path, managed_path, sha256, size_bytes, parse_status, metadata_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (build_id, "source", "managed", "abc", 1, "mystery", "{}"),
            )

    def test_complete_iteration_with_no_change_requires_diagnosis_and_reason(self):
        build_id = create_build(self.conn, "5 inch")
        loop_id = create_loop(self.conn, build_id, "baseline")
        iteration_id = create_iteration(self.conn, loop_id)

        with self.assertRaises(ValueError):
            complete_no_change(self.conn, iteration_id, "")
        with self.assertRaises(ValueError):
            complete_no_change(self.conn, iteration_id, "No safe Tune Update")

        record_diagnosis(self.conn, iteration_id, "Baseline reviewed; no change", confidence="low")
        complete_no_change(self.conn, iteration_id, "No safe Tune Update from this Blackbox Log alone")

        row = self.conn.execute("SELECT status, result, no_change_reason FROM tuning_iterations WHERE id = ?", (iteration_id,)).fetchone()
        self.assertEqual(row["status"], "completed")
        self.assertEqual(row["result"], "no_change")
        self.assertIn("Blackbox Log", row["no_change_reason"])

        next_iteration_id = create_iteration(self.conn, loop_id)
        self.assertNotEqual(next_iteration_id, iteration_id)


if __name__ == "__main__":
    unittest.main()
