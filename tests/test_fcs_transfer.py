from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tune.services.fcs_transfer import BLACKBOX_HEADER, download_msc_raw


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


if __name__ == "__main__":
    unittest.main()
