from __future__ import annotations

import unittest

from fcs_bridge.writeback import write_betaflight_cli_text


class FakeTransport:
    def __init__(self, responses: list[bytes]):
        self.responses = responses
        self.sent: list[bytes] = []

    def send(self, data: bytes) -> None:
        self.sent.append(data)

    def recv(self, size: int) -> bytes:
        if self.responses:
            return self.responses.pop(0)
        return b""


class WritebackTests(unittest.TestCase):
    def test_write_betaflight_cli_text_enters_cli_sends_save(self):
        transport = FakeTransport([b"CLI> ", b"ok\r\n", b"Rebooting\r\n"])
        result = write_betaflight_cli_text(transport, "set d_pitch = 48", timeout_seconds=0.01)
        self.assertTrue(result.success)
        self.assertEqual(transport.sent, [b"#\r", b"set d_pitch = 48\r", b"save\r"])

    def test_write_betaflight_cli_text_detects_error_transcript(self):
        transport = FakeTransport([b"CLI> ", b"###ERROR: invalid name\r\n", b""])
        result = write_betaflight_cli_text(transport, "set nope = 1", timeout_seconds=0.01)
        self.assertFalse(result.success)


if __name__ == "__main__":
    unittest.main()
