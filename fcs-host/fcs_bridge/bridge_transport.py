from __future__ import annotations

import socket
import time
from dataclasses import dataclass
from typing import Optional


class BridgeConnectionError(RuntimeError):
    pass


@dataclass
class SingleClientProbeResult:
    first_connected: bool
    second_connected: bool
    second_rejected: bool
    detail: str


class BridgeTransport:
    """Owns the host-side Bridge TCP connection lifecycle for FCS."""

    def __init__(self, host: str, port: int, *, timeout_seconds: float = 3.0):
        self.host = host
        self.port = port
        self.timeout_seconds = timeout_seconds
        self._socket: Optional[socket.socket] = None

    @property
    def is_connected(self) -> bool:
        return self._socket is not None

    def connect(self) -> None:
        if self._socket is not None:
            raise BridgeConnectionError("BridgeTransport already connected")

        try:
            sock = socket.create_connection((self.host, self.port), self.timeout_seconds)
            sock.settimeout(self.timeout_seconds)
        except OSError as exc:
            raise BridgeConnectionError(
                f"Failed to connect to Bridge at {self.host}:{self.port}: {exc}"
            ) from exc

        self._socket = sock

    def disconnect(self) -> None:
        sock = self._socket
        self._socket = None
        if sock is None:
            return
        try:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        finally:
            sock.close()

    def send(self, payload: bytes) -> None:
        if self._socket is None:
            raise BridgeConnectionError("BridgeTransport is not connected")
        try:
            self._socket.sendall(payload)
        except OSError as exc:
            self.disconnect()
            raise BridgeConnectionError(f"Bridge send failed: {exc}") from exc

    def recv(self, size: int = 4096) -> bytes:
        if self._socket is None:
            raise BridgeConnectionError("BridgeTransport is not connected")
        try:
            data = self._socket.recv(size)
        except socket.timeout:
            return b""
        except OSError as exc:
            self.disconnect()
            raise BridgeConnectionError(f"Bridge receive failed: {exc}") from exc

        if data == b"":
            self.disconnect()
        return data

    def __enter__(self) -> "BridgeTransport":
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.disconnect()


def probe_single_client_behavior(
    host: str,
    port: int,
    *,
    timeout_seconds: float = 3.0,
    settle_seconds: float = 0.25,
) -> SingleClientProbeResult:
    """Check whether a second client gets rejected while the first is connected."""

    first = None
    second = None
    try:
        first = socket.create_connection((host, port), timeout_seconds)
        first.settimeout(timeout_seconds)

        second = socket.create_connection((host, port), timeout_seconds)
        second.settimeout(timeout_seconds)
        time.sleep(settle_seconds)

        second_connected = True
        second_rejected = False
        detail = "second client accepted"

        try:
            second.sendall(b"\x00")
            data = second.recv(1)
            if data == b"":
                second_rejected = True
                detail = "second client accepted TCP handshake then closed immediately"
        except (BrokenPipeError, ConnectionResetError, OSError):
            second_rejected = True
            detail = "second client rejected or reset"

        return SingleClientProbeResult(
            first_connected=True,
            second_connected=second_connected,
            second_rejected=second_rejected,
            detail=detail,
        )
    except OSError as exc:
        return SingleClientProbeResult(
            first_connected=first is not None,
            second_connected=second is not None,
            second_rejected=False,
            detail=f"probe failed: {exc}",
        )
    finally:
        for sock in (second, first):
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
