from __future__ import annotations

import time

from .bridge_transport import BridgeTransport
from .msp import (
    MspFrame,
    MspProtocolError,
    build_msp_v1_request,
    build_msp_v2_request,
    try_parse_msp_frame,
)


class MspClient:
    """Synchronous MSP v1 client over a connected Bridge transport."""

    def __init__(self, transport: BridgeTransport):
        self.transport = transport
        self._buffer = b""

    def read_frame(self, *, timeout_seconds: float) -> MspFrame:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            frame, self._buffer = try_parse_msp_frame(self._buffer)
            if frame is not None:
                return frame

            data = self.transport.recv(4096)
            if data:
                self._buffer += data
            else:
                time.sleep(0.05)

        raise TimeoutError("timed out waiting for MSP response")

    def request(self, command: int, payload: bytes = b"", *, timeout_seconds: float) -> MspFrame:
        self.transport.send(build_msp_v1_request(command, payload))
        return self._read_matching_response(command, timeout_seconds=timeout_seconds)

    def request_v2(self, command: int, payload: bytes = b"", *, timeout_seconds: float) -> MspFrame:
        self.transport.send(build_msp_v2_request(command, payload))
        return self._read_matching_response(command, timeout_seconds=timeout_seconds)

    def _read_matching_response(self, command: int, *, timeout_seconds: float) -> MspFrame:
        frame = self.read_frame(timeout_seconds=timeout_seconds)
        if frame.command != command:
            raise MspProtocolError(
                f"unexpected MSP command in response: got {frame.command}, expected {command}"
            )
        if frame.is_error:
            raise MspProtocolError(f"MSP error response for command {command}")
        return frame
