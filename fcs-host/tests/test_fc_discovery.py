from __future__ import annotations

import unittest

from fcs_bridge import (
    MSP_API_VERSION,
    MSP_DATAFLASH_SUMMARY,
    MSP_FC_VARIANT,
    MSP_FC_VERSION,
    MSP_SDCARD_SUMMARY,
    MspClient,
    discover_fc_capabilities,
    get_blackbox_log_storage_status,
)


def _response(command: int, payload: bytes = b"", *, bad_checksum: bool = False) -> bytes:
    checksum = len(payload) ^ command
    for byte in payload:
        checksum ^= byte
    if bad_checksum:
        checksum ^= 0xFF
    return b"$M>" + bytes([len(payload), command]) + payload + bytes([checksum])


def _dataflash_payload(
    *, flags: int = 3, sectors: int = 16, total_size: int = 1048576, used_size: int = 4096
) -> bytes:
    return (
        bytes([flags])
        + sectors.to_bytes(4, "little")
        + total_size.to_bytes(4, "little")
        + used_size.to_bytes(4, "little")
    )


class _FakeTransport:
    def __init__(self, chunks: list[bytes]):
        self.chunks = chunks

    def send(self, payload: bytes) -> None:
        pass

    def recv(self, size: int = 4096) -> bytes:
        if not self.chunks:
            return b""
        return self.chunks.pop(0)


class FcDiscoveryTests(unittest.TestCase):
    def test_discovers_identity_and_blackbox_storage(self):
        transport = _FakeTransport(
            [
                _response(MSP_API_VERSION, b"\x00\x01\x2e"),
                _response(MSP_FC_VARIANT, b"BTFL"),
                _response(MSP_FC_VERSION, b"\x04\x05\x02"),
                _response(MSP_DATAFLASH_SUMMARY, _dataflash_payload()),
                _response(MSP_SDCARD_SUMMARY, b"\x00" * 11),
            ]
        )

        capabilities = discover_fc_capabilities(MspClient(transport), timeout_seconds=0.1)

        self.assertEqual(capabilities.identity.fc_variant, "BTFL")
        self.assertEqual(capabilities.identity.fc_version, (4, 5, 2))
        self.assertTrue(capabilities.blackbox_storage.dataflash_available)
        self.assertTrue(capabilities.blackbox_storage.dataflash_supported)
        self.assertTrue(capabilities.blackbox_storage.dataflash_ready)
        self.assertEqual(capabilities.blackbox_storage.total_size, 1048576)
        self.assertEqual(capabilities.blackbox_storage.used_size, 4096)
        self.assertTrue(capabilities.blackbox_storage.sdcard_summary_available)

    def test_storage_discovery_retains_malformed_response_as_diagnostic(self):
        transport = _FakeTransport(
            [_response(MSP_DATAFLASH_SUMMARY, _dataflash_payload(), bad_checksum=True)]
        )

        status = get_blackbox_log_storage_status(MspClient(transport), timeout_seconds=0.1)

        self.assertFalse(status.dataflash_available)
        self.assertIn("MSP_DATAFLASH_SUMMARY unavailable", status.diagnostic)
        self.assertIn("checksum", status.diagnostic)

    def test_storage_discovery_retains_timeout_as_diagnostic(self):
        status = get_blackbox_log_storage_status(
            MspClient(_FakeTransport([])), timeout_seconds=0.01
        )

        self.assertFalse(status.dataflash_available)
        self.assertIn("timed out", status.diagnostic)


if __name__ == "__main__":
    unittest.main()
