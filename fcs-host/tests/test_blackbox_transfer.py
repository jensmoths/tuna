from __future__ import annotations

import unittest

from fcs_bridge import MSP_DATAFLASH_READ, MspClient, build_msp_v2_request, read_dataflash_range


def _response(command: int, payload: bytes = b"") -> bytes:
    checksum = len(payload) ^ command
    for byte in payload:
        checksum ^= byte
    return b"$M>" + bytes([len(payload), command]) + payload + bytes([checksum])


def _dataflash_read_response(address: int, data: bytes) -> bytes:
    payload = address.to_bytes(4, "little") + len(data).to_bytes(2, "little") + b"\x00" + data
    return _response(MSP_DATAFLASH_READ, payload)


def _dataflash_read_response_v2(address: int, data: bytes) -> bytes:
    payload = address.to_bytes(4, "little") + len(data).to_bytes(2, "little") + b"\x00" + data
    return build_msp_v2_request(MSP_DATAFLASH_READ, payload).replace(b"$X<", b"$X>")


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
    def test_read_dataflash_range_chunks_until_requested_size(self):
        transport = _FakeTransport(
            [
                _dataflash_read_response(0, b"a" * 240),
                _dataflash_read_response(240, b"b" * 16),
            ]
        )

        data = read_dataflash_range(
            MspClient(transport), address=0, size=256, timeout_seconds=0.1
        )

        self.assertEqual(data, b"a" * 240 + b"b" * 16)
        self.assertEqual(len(transport.sent), 2)

    def test_read_dataflash_range_uses_larger_msp_v2_chunks(self):
        transport = _FakeTransport([_dataflash_read_response_v2(0, b"a" * 4096)])

        data = read_dataflash_range(
            MspClient(transport),
            address=0,
            size=4096,
            timeout_seconds=0.1,
            chunk_size=4096,
            msp_version=2,
        )

        self.assertEqual(data, b"a" * 4096)
        self.assertEqual(len(transport.sent), 1)

    def test_read_dataflash_range_stops_on_short_read(self):
        transport = _FakeTransport([_dataflash_read_response(0, b"short")])

        data = read_dataflash_range(
            MspClient(transport), address=0, size=240, timeout_seconds=0.1
        )

        self.assertEqual(data, b"short")

    def test_read_dataflash_range_rejects_wrong_address(self):
        transport = _FakeTransport([_dataflash_read_response(10, b"abc")])

        with self.assertRaises(RuntimeError):
            read_dataflash_range(
                MspClient(transport), address=0, size=3, timeout_seconds=0.1
            )


if __name__ == "__main__":
    unittest.main()
