from __future__ import annotations

import json
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

from tuna_fcs import cli as fcs_cli
from tuna_fcs.fcs_bridge import CliWriteResult


class FcsWriteCliTests(unittest.TestCase):
    def run_cli_json_with_code(self, *args: str):
        stdout = StringIO()
        with redirect_stdout(stdout):
            code = fcs_cli.main([*args, "--json"])
        return code, json.loads(stdout.getvalue())

    def test_command_write_delegates_to_fcs_writeback(self):
        with patch(
            "tuna_fcs.cli.write_betaflight_cli_text_to_bridge",
            return_value=CliWriteResult(success=True, transcript="ok\r\n"),
        ) as write:
            code, result = self.run_cli_json_with_code(
                "cli",
                "write",
                "--bridge-host",
                "bridge.local",
                "--command",
                "set d_pitch = 48",
                "--confirm",
                "write-fc-cli",
            )

        self.assertEqual(code, 0)
        self.assertTrue(result["success"])
        write.assert_called_once_with("bridge.local", 5761, "set d_pitch = 48", timeout_seconds=5.0)

    def test_bad_confirmation_does_not_write(self):
        with patch("tuna_fcs.cli.write_betaflight_cli_text_to_bridge") as write:
            code, result = self.run_cli_json_with_code(
                "cli",
                "write",
                "--bridge-host",
                "bridge.local",
                "--command",
                "set d_pitch = 48",
                "--confirm",
                "wrong",
            )

        self.assertEqual(code, 1)
        self.assertEqual(result["error"]["kind"], "ValueError")
        write.assert_not_called()

    def test_failed_write_returns_error(self):
        with patch(
            "tuna_fcs.cli.write_betaflight_cli_text_to_bridge",
            return_value=CliWriteResult(success=False, transcript="###ERROR: invalid name\r\n"),
        ):
            code, result = self.run_cli_json_with_code(
                "cli",
                "write",
                "--bridge-host",
                "bridge.local",
                "--command",
                "set nope = 1",
                "--confirm",
                "write-fc-cli",
            )

        self.assertEqual(code, 1)
        self.assertFalse(result["success"])


if __name__ == "__main__":
    unittest.main()
