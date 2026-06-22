from __future__ import annotations

import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from tuna_fcs import cli as fcs_cli


class FcsCliTests(unittest.TestCase):
    def run_cli_json_with_code(self, *args: str):
        stdout = StringIO()
        with redirect_stdout(stdout):
            code = fcs_cli.main([*args, "--json"])
        return code, json.loads(stdout.getvalue())


    def test_inspect_defaults_bridge_host_from_environment_variable(self):
        payload = {"bridge_host": "env-bridge"}
        with patch.dict(os.environ, {"FCS_BRIDGE_HOST": "env-bridge"}, clear=False):
            with patch("tuna_fcs.cli._inspect_bridge", return_value=payload) as inspect:
                code, result = self.run_cli_json_with_code("inspect")
        self.assertEqual(code, 0)
        self.assertEqual(result, payload)
        inspect.assert_called_once_with("env-bridge", port=5761, timeout_seconds=2.5)

    def test_inspect_usb_delegates_to_usb_transport(self):
        payload = {"connection": "usb", "usb_device": "/dev/ttyACM0"}
        with patch("tuna_fcs.cli._inspect_usb", return_value=payload) as inspect:
            code, result = self.run_cli_json_with_code("inspect", "--connection", "usb", "--usb-device", "/dev/ttyACM0")
        self.assertEqual(code, 0)
        self.assertEqual(result, payload)
        inspect.assert_called_once_with("/dev/ttyACM0", timeout_seconds=2.5)

    def test_fake_inspect_uses_explicit_environment_fixture(self):
        with patch.dict(os.environ, {"TUNA_FCS_FAKE": "1"}, clear=False):
            with patch("tuna_fcs.cli._inspect_bridge") as inspect:
                code, result = self.run_cli_json_with_code("inspect", "--bridge-host", "bench-bridge")

        self.assertEqual(code, 0)
        self.assertEqual(result["fixture"]["source"], "TUNA_FCS_FAKE")
        self.assertEqual(result["connection"], "bridge")
        self.assertEqual(result["bridge_host"], "bench-bridge")
        self.assertEqual(result["identity"]["fc_variant"], "BTFL")
        self.assertEqual(result["settings"]["d_roll"], 40)
        inspect.assert_not_called()

    def test_fake_inspect_accepts_custom_fixture_json(self):
        custom = json.dumps({"identity": {"fc_variant": "BTFL", "fc_version": "4.6.0"}, "settings": {"d_roll": 38}})
        with patch.dict(os.environ, {"TUNA_FCS_FAKE": "1", "TUNA_FCS_INSPECT_FIXTURE_JSON": custom}, clear=False):
            code, result = self.run_cli_json_with_code("inspect", "--connection", "usb", "--usb-device", "/dev/ttyFAKE0")

        self.assertEqual(code, 0)
        self.assertEqual(result["fixture"]["enabled"], True)
        self.assertEqual(result["connection"], "usb")
        self.assertEqual(result["usb_device"], "/dev/ttyFAKE0")
        self.assertEqual(result["settings"], {"d_roll": 38})

    def test_fake_status_reports_ready_bridge_without_network(self):
        with patch.dict(os.environ, {"TUNA_FCS_FAKE": "1"}, clear=False):
            code, result = self.run_cli_json_with_code("status", "--bridge-host", "bench-bridge")

        self.assertEqual(code, 0)
        self.assertTrue(result["usb_cdc_connected"])
        self.assertEqual(result["fixture"]["source"], "TUNA_FCS_FAKE")

    def test_blackbox_transfer_delegates_to_fcs_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "flight.bbl"
            payload = {"download": {"output_path": str(output), "starts_with_blackbox_header": True}}
            with patch("tuna_fcs.cli.transfer_blackbox_log_from_bridge", return_value=payload) as transfer:
                code, result = self.run_cli_json_with_code(
                    "blackbox",
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
        self.assertEqual(code, 0)
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

    def test_blackbox_transfer_usb_delegates_to_usb_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "flight.bbl"
            payload = {"connection": "usb", "download": {"output_path": str(output)}}
            with patch("tuna_fcs.cli.transfer_blackbox_log_from_usb", return_value=payload) as transfer:
                code, result = self.run_cli_json_with_code(
                    "blackbox",
                    "transfer",
                    "--connection",
                    "usb",
                    "--usb-device",
                    "/dev/ttyACM0",
                    "--output",
                    str(output),
                    "--timeout",
                    "12",
                )
        self.assertEqual(code, 0)
        self.assertEqual(result, payload)
        transfer.assert_called_once_with("/dev/ttyACM0", output_path=output, trigger_msc=True, timeout_seconds=12.0)

    def test_blackbox_transfer_json_error_is_structured(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "flight.bbl"
            with patch("tuna_fcs.cli.transfer_blackbox_log_from_bridge", side_effect=TimeoutError("bridge status timed out")):
                code, result = self.run_cli_json_with_code(
                    "blackbox",
                    "transfer",
                    "--bridge-host",
                    "bridge.local",
                    "--output",
                    str(output),
                )
        self.assertEqual(code, 1)
        self.assertEqual(result["error"]["kind"], "TimeoutError")
        self.assertTrue(result["error"]["retryable"])
        self.assertEqual(result["error"]["output_path"], str(output))

    def test_cli_write_requires_confirmation(self):
        code, result = self.run_cli_json_with_code(
            "cli",
            "write",
            "--bridge-host",
            "bridge.local",
            "--command",
            "set d_pitch = 46",
            "--confirm",
            "wrong",
        )
        self.assertEqual(code, 1)
        self.assertEqual(result["error"]["kind"], "ValueError")


if __name__ == "__main__":
    unittest.main()
