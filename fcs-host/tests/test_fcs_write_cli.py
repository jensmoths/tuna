from __future__ import annotations

import importlib.util
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from fcs_bridge import CliWriteResult


_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "fcs_write_cli.py"
_SPEC = importlib.util.spec_from_file_location("fcs_write_cli", _SCRIPT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
fcs_write_cli = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(fcs_write_cli)


class FcsWriteCliTests(unittest.TestCase):
    def test_command_write_delegates_to_fcs_writeback(self):
        with patch.object(
            fcs_write_cli,
            "write_betaflight_cli_text_to_bridge",
            return_value=CliWriteResult(success=True, transcript="ok\r\n"),
        ) as write:
            with redirect_stdout(StringIO()):
                code = fcs_write_cli.main(
                    [
                        "bridge.local",
                        "--command",
                        "set d_pitch = 48",
                        "--confirm",
                        "write-fc-cli",
                        "--no-transcript",
                    ]
                )

        self.assertEqual(code, 0)
        write.assert_called_once_with(
            "bridge.local",
            5761,
            "set d_pitch = 48",
            timeout_seconds=5.0,
        )

    def test_bad_confirmation_does_not_write(self):
        with patch.object(fcs_write_cli, "write_betaflight_cli_text_to_bridge") as write:
            with redirect_stdout(StringIO()):
                code = fcs_write_cli.main(
                    ["bridge.local", "--command", "set d_pitch = 48", "--confirm", "wrong"]
                )

        self.assertEqual(code, 2)
        write.assert_not_called()

    def test_failed_write_returns_error(self):
        with patch.object(
            fcs_write_cli,
            "write_betaflight_cli_text_to_bridge",
            return_value=CliWriteResult(success=False, transcript="###ERROR: invalid name\r\n"),
        ):
            with redirect_stdout(StringIO()):
                code = fcs_write_cli.main(
                    ["bridge.local", "--command", "set nope = 1", "--confirm", "write-fc-cli"]
                )

        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
