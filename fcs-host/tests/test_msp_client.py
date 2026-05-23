from __future__ import annotations

import unittest

from fcs_bridge import MSP_API_VERSION, MspProtocolError, build_msp_v1_request
from fcs_bridge.msp_client import MspClient


def _response(command: int, payload: bytes = b"", *, error: bool = False) -> bytes:
    checksum = len(payload) ^ command
    for byte in payload:
        checksum ^= byte
    direction = b"!" if error else b">"
    return b"$M" + direction + bytes([len(payload), command]) + payload + bytes([checksum])


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


class MspClientTests(unittest.TestCase):
    def test_request_sends_msp_frame_and_returns_response(self):
        transport = _FakeTransport([_response(MSP_API_VERSION, b"\x00\x01\x2e")])
        client = MspClient(transport)

        frame = client.request(MSP_API_VERSION, timeout_seconds=0.1)

        self.assertEqual(transport.sent, [build_msp_v1_request(MSP_API_VERSION)])
        self.assertEqual(frame.command, MSP_API_VERSION)
        self.assertEqual(frame.payload, b"\x00\x01\x2e")

    def test_request_reuses_buffered_remainder(self):
        transport = _FakeTransport(
            [_response(1, b"a") + _response(2, b"BTFL")]
        )
        client = MspClient(transport)

        first = client.request(1, timeout_seconds=0.1)
        second = client.request(2, timeout_seconds=0.1)

        self.assertEqual(first.payload, b"a")
        self.assertEqual(second.payload, b"BTFL")

    def test_request_rejects_unexpected_command(self):
        transport = _FakeTransport([_response(2, b"")])
        client = MspClient(transport)

        with self.assertRaises(MspProtocolError):
            client.request(1, timeout_seconds=0.1)

    def test_request_rejects_msp_error_response(self):
        transport = _FakeTransport([_response(1, b"", error=True)])
        client = MspClient(transport)

        with self.assertRaises(MspProtocolError):
            client.request(1, timeout_seconds=0.1)

    def test_read_frame_times_out(self):
        transport = _FakeTransport([])
        client = MspClient(transport)

        with self.assertRaises(TimeoutError):
            client.read_frame(timeout_seconds=0.01)


if __name__ == "__main__":
    unittest.main()
