from __future__ import annotations

import unittest

from fcs_bridge import MSP_DATAFLASH_ERASE, MspClient, erase_dataflash


def _response(command: int, payload: bytes = b"") -> bytes:
    checksum = len(payload) ^ command
    for byte in payload:
        checksum ^= byte
    return b"$M>" + bytes([len(payload), command]) + payload + bytes([checksum])


class _FakeTransport:
    def __init__(self, chunks: list[bytes]):
        self.chunks = chunks
        self.sent: list[bytes] = []

    def send(self, payload: bytes) -> None:
        self.sent.append(payload)

    def recv(self, size: int = 4096) -> bytes:
        if not self.chunks:
            return b""
        return self.chunks.pop(0)


class BlackboxTransferTests(unittest.TestCase):
    def test_erase_dataflash_sends_msp_erase_command(self):
        transport = _FakeTransport([_response(MSP_DATAFLASH_ERASE)])

        erase_dataflash(MspClient(transport), timeout_seconds=0.1)

        self.assertEqual(len(transport.sent), 1)
        self.assertIn(bytes([MSP_DATAFLASH_ERASE]), transport.sent[0])


if __name__ == "__main__":
    unittest.main()
