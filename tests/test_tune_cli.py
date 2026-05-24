from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

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
        applied = self.run_cli_json("update", "apply", "--update-id", str(update["update_id"]))
        self.assertEqual(applied["status"], "applied")
        status = self.run_cli_json("status")
        self.assertEqual(status["builds"], 1)
        self.assertEqual(status["logs"], 1)
        self.assertEqual(status["iterations_open"], 0)


if __name__ == "__main__":
    unittest.main()
