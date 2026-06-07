from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tune.services.fcs_transfer import BLACKBOX_HEADER, transfer_blackbox_log_from_bridge, download_msc_raw


class FcsTransferTests(unittest.TestCase):
    def test_download_msc_raw_downloads_in_chunks_and_records_progress(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "flight.bbl"
            calls: list[tuple[int, int]] = []
            events: list[dict[str, object]] = []

            def fake_read(host: str, **kwargs):
                calls.append((kwargs["offset"], kwargs["size"]))
                if kwargs["offset"] == 0:
                    return b"pad" + BLACKBOX_HEADER + b"a" * (kwargs["size"] - 3 - len(BLACKBOX_HEADER))
                return b"b" * kwargs["size"]

            with patch("tune.services.fcs_transfer._read_msc_raw_range", side_effect=fake_read):
                payload = download_msc_raw(
                    "bridge.local",
                    output_path=output,
                    size=64,
                    chunk_size=32,
                    progress=events.append,
                )

            self.assertEqual(calls, [(0, 32), (32, 32)])
            self.assertEqual(payload["chunks_completed"], 2)
            self.assertEqual(payload["retries"], 0)
            self.assertEqual(payload["header_offset"], 3)
            self.assertTrue(output.read_bytes().startswith(BLACKBOX_HEADER))
            self.assertEqual(len(events), 2)
            self.assertEqual(events[-1]["raw_bytes_downloaded"], 64)

    def test_download_msc_raw_retries_failed_chunk_without_advancing_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "flight.bbl"
            attempts = 0

            def fake_read(host: str, **kwargs):
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    raise RuntimeError("temporary disconnect")
                return BLACKBOX_HEADER + b"x"

            with patch("tune.services.fcs_transfer._read_msc_raw_range", side_effect=fake_read):
                payload = download_msc_raw(
                    "bridge.local",
                    output_path=output,
                    size=len(BLACKBOX_HEADER) + 1,
                    chunk_size=len(BLACKBOX_HEADER) + 1,
                    max_attempts=2,
                )

            self.assertEqual(attempts, 2)
            self.assertEqual(payload["retries"], 1)
            self.assertEqual(payload["raw_bytes_downloaded"], len(BLACKBOX_HEADER) + 1)
            self.assertTrue(output.read_bytes().startswith(BLACKBOX_HEADER))

    def test_download_msc_raw_keeps_concatenated_logs_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "flight.bbl"
            calls: list[tuple[int, int]] = []
            first_log = BLACKBOX_HEADER + b"a" * 12
            all_logs = first_log + BLACKBOX_HEADER + b"b" * 100

            def fake_read(host: str, **kwargs):
                calls.append((kwargs["offset"], kwargs["size"]))
                return all_logs[kwargs["offset"] : kwargs["offset"] + kwargs["size"]]

            with patch("tune.services.fcs_transfer._read_msc_raw_range", side_effect=fake_read):
                payload = download_msc_raw(
                    "bridge.local",
                    output_path=output,
                    size=len(all_logs),
                    chunk_size=32,
                )

            self.assertGreater(len(calls), 2)
            self.assertEqual(output.read_bytes(), all_logs)
            self.assertFalse(payload["stopped_at_next_header"])

    def test_download_msc_raw_can_stop_output_at_next_blackbox_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "flight.bbl"
            first_log = BLACKBOX_HEADER + b"a" * 12

            def fake_read(host: str, **kwargs):
                raw = first_log + BLACKBOX_HEADER + b"b" * 100
                return raw[kwargs["offset"] : kwargs["offset"] + kwargs["size"]]

            with patch("tune.services.fcs_transfer._read_msc_raw_range", side_effect=fake_read):
                payload = download_msc_raw(
                    "bridge.local",
                    output_path=output,
                    size=128,
                    chunk_size=32,
                    stop_at_next_header=True,
                )

            self.assertEqual(output.read_bytes(), first_log)
            self.assertTrue(payload["stopped_at_next_header"])
            self.assertEqual(payload["next_header_offset"], len(first_log))

    def test_download_msc_raw_extends_raw_read_to_output_size_after_padding(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "flight.bbl"
            calls: list[tuple[int, int]] = []
            payload_bytes = BLACKBOX_HEADER + b"a" * 40
            raw = b"pad!" + payload_bytes

            def fake_read(host: str, **kwargs):
                calls.append((kwargs["offset"], kwargs["size"]))
                return raw[kwargs["offset"] : kwargs["offset"] + kwargs["size"]]

            with patch("tune.services.fcs_transfer._read_msc_raw_range", side_effect=fake_read):
                payload = download_msc_raw(
                    "bridge.local",
                    output_path=output,
                    size=len(payload_bytes),
                    output_size=len(payload_bytes),
                    chunk_size=32,
                )

            self.assertEqual(output.read_bytes(), payload_bytes)
            self.assertEqual(payload["requested_size"], len(raw))
            self.assertEqual(payload["raw_bytes_downloaded"], len(raw))

    def test_download_msc_raw_runs_recovery_before_retrying_failed_chunk(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "flight.bbl"
            attempts = 0
            recoveries = 0

            def fake_read(host: str, **kwargs):
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    raise OSError("connection reset")
                return BLACKBOX_HEADER + b"x"

            def recover():
                nonlocal recoveries
                recoveries += 1

            with patch("tune.services.fcs_transfer._read_msc_raw_range", side_effect=fake_read):
                payload = download_msc_raw(
                    "bridge.local",
                    output_path=output,
                    size=len(BLACKBOX_HEADER) + 1,
                    chunk_size=len(BLACKBOX_HEADER) + 1,
                    max_attempts=2,
                    recover_msc_raw=recover,
                )

            self.assertEqual(attempts, 2)
            self.assertEqual(recoveries, 1)
            self.assertEqual(payload["retries"], 1)
            self.assertTrue(output.read_bytes().startswith(BLACKBOX_HEADER))

    def test_transfer_discovers_size_before_triggering_msc(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "flight.bbl"

            with patch("tune.services.fcs_transfer.read_bridge_status") as status:
                status.return_value.usb_cdc_connected = True
                status.return_value.msc_raw_ready = False
                status.return_value.text = "USB_CDC_CONNECTED msc_raw=0"
                with patch("tune.services.fcs_transfer.discover_blackbox_transfer_size", return_value=1234) as discover:
                    with patch("tune.services.fcs_transfer.trigger_msc_mode", return_value="msc"):
                        with patch("tune.services.fcs_transfer.wait_for_msc_raw", return_value=status.return_value):
                            with patch("tune.services.fcs_transfer.download_msc_raw") as download:
                                download.return_value = {
                                    "output_path": str(output),
                                    "starts_with_blackbox_header": True,
                                    "written_bytes": 100,
                                }

                                transfer_blackbox_log_from_bridge("bridge.local", output_path=output)

            discover.assert_called_once_with("bridge.local", timeout_seconds=8.0)
            download.assert_called_once()
            self.assertEqual(download.call_args.kwargs["size"], 1234)
            self.assertEqual(download.call_args.kwargs["output_size"], 1234)

    def test_transfer_caps_raw_read_timeout_and_passes_recovery_callback(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "flight.bbl"
            with patch("tune.services.fcs_transfer.read_bridge_status") as status:
                status.return_value.msc_raw_ready = True
                status.return_value.text = "msc_raw=1"
                with patch("tune.services.fcs_transfer.download_msc_raw") as download:
                    download.return_value = {
                        "output_path": str(output),
                        "starts_with_blackbox_header": True,
                        "written_bytes": 100,
                    }

                    transfer_blackbox_log_from_bridge("bridge.local", output_path=output, size=4096, timeout_seconds=120.0)

            download.assert_called_once()
            self.assertEqual(download.call_args.kwargs["timeout_seconds"], 15.0)
            self.assertTrue(callable(download.call_args.kwargs["recover_msc_raw"]))

    def test_transfer_prefers_msc_file_when_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "flight.bbl"
            with patch("tune.services.fcs_transfer.read_bridge_status") as status:
                status.return_value.msc_raw_ready = True
                status.return_value.msc_mounted = True
                status.return_value.text = "msc_raw=1 msc_mounted=1"
                file_payload = {
                    "method": "msc_file",
                    "name": "btfl_all.bbl",
                    "output_path": str(output),
                    "written_bytes": 123,
                    "starts_with_blackbox_header": True,
                }
                with patch("tune.services.fcs_transfer.download_preferred_msc_file", return_value=file_payload) as file_download:
                    with patch("tune.services.fcs_transfer.download_msc_raw") as raw_download:
                        payload = transfer_blackbox_log_from_bridge("bridge.local", output_path=output)

            self.assertEqual(payload["download"], file_payload)
            file_download.assert_called_once()
            raw_download.assert_not_called()

    def test_transfer_falls_back_to_raw_when_msc_file_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "flight.bbl"
            with patch("tune.services.fcs_transfer.read_bridge_status") as status:
                status.return_value.msc_raw_ready = True
                status.return_value.msc_mounted = True
                status.return_value.text = "msc_raw=1 msc_mounted=1"
                with patch("tune.services.fcs_transfer.download_preferred_msc_file", return_value=None):
                    with patch("tune.services.fcs_transfer.download_msc_raw") as raw_download:
                        raw_download.return_value = {
                            "output_path": str(output),
                            "starts_with_blackbox_header": True,
                            "written_bytes": 100,
                        }

                        payload = transfer_blackbox_log_from_bridge("bridge.local", output_path=output, size=4096)

            self.assertEqual(payload["download"]["written_bytes"], 100)
            self.assertIn("fallback_reason", payload)

    def test_transfer_requires_size_when_already_in_msc_raw(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "flight.bbl"
            with patch("tune.services.fcs_transfer.read_bridge_status") as status:
                status.return_value.msc_raw_ready = True
                status.return_value.text = "msc_raw=1"

                with self.assertRaisesRegex(ValueError, "--size is required"):
                    transfer_blackbox_log_from_bridge("bridge.local", output_path=output)


if __name__ == "__main__":
    unittest.main()
