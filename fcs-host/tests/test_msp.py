from __future__ import annotations

import unittest

from fcs_bridge.msp import (
    MSP_API_VERSION,
    build_dataflash_read_payload,
    build_msp_v1_request,
    build_msp_v2_request,
    parse_dataflash_read,
    parse_api_version,
    parse_fc_variant,
    parse_fc_version,
    parse_ident,
    try_parse_msp_v1_frame,
    try_parse_msp_v2_frame,
)


class MspTests(unittest.TestCase):
    def test_build_request_for_zero_payload(self):
        self.assertEqual(build_msp_v1_request(MSP_API_VERSION), b"$M<\x00\x01\x01")

    def test_build_msp_v2_request_for_zero_payload(self):
        self.assertEqual(build_msp_v2_request(MSP_API_VERSION)[:8], b"$X<\x00\x01\x00\x00\x00")

    def test_parse_response_frame(self):
        frame, remainder = try_parse_msp_v1_frame(b"$M>\x03\x01\x00\x01\x30\x33")
        self.assertIsNotNone(frame)
        self.assertEqual(frame.command, 1)
        self.assertEqual(frame.payload, b"\x00\x01\x30")
        self.assertEqual(remainder, b"")

    def test_parse_msp_v2_response_frame(self):
        frame, remainder = try_parse_msp_v2_frame(build_msp_v2_request(MSP_API_VERSION).replace(b"$X<", b"$X>"))
        self.assertIsNotNone(frame)
        self.assertEqual(frame.command, MSP_API_VERSION)
        self.assertEqual(frame.version, 2)
        self.assertEqual(remainder, b"")

    def test_parse_with_leading_noise(self):
        frame, remainder = try_parse_msp_v1_frame(b"noise$M>\x04\x02BTFL\x1a")
        self.assertIsNotNone(frame)
        self.assertEqual(frame.command, 2)
        self.assertEqual(parse_fc_variant(frame.payload), "BTFL")
        self.assertEqual(remainder, b"")

    def test_payload_parsers(self):
        self.assertEqual(parse_api_version(b"\x00\x01\x30"), (0, 1, 48))
        self.assertEqual(parse_fc_version(b"\x04\x05\x06"), (4, 5, 6))
        self.assertEqual(
            parse_ident(b"\x02\x03\x04\x78\x56\x34\x12"),
            {
                "version": 2,
                "multitype": 3,
                "msp_version": 4,
                "capability": 0x12345678,
            },
        )

    def test_build_dataflash_read_payload(self):
        self.assertEqual(
            build_dataflash_read_payload(0x12345678, 240),
            b"\x78\x56\x34\x12\xf0\x00\x00",
        )

    def test_parse_dataflash_read(self):
        parsed = parse_dataflash_read(b"\x10\x00\x00\x00\x03\x00\x00abc")
        self.assertEqual(parsed["address"], 16)
        self.assertEqual(parsed["read_size"], 3)
        self.assertEqual(parsed["data"], b"abc")


if __name__ == "__main__":
    unittest.main()
