from __future__ import annotations

import dataclasses
import socket
import time


@dataclasses.dataclass(frozen=True)
class BridgeStatus:
    text: str

    @property
    def usb_cdc_connected(self) -> bool:
        return "USB_CDC_CONNECTED" in self.text

    @property
    def msc_raw_ready(self) -> bool:
        return "msc_raw=1" in self.text

    @property
    def msc_mounted(self) -> bool:
        return "msc_mounted=1" in self.text


def read_bridge_status(host: str, *, port: int = 5762, timeout_seconds: float = 8.0) -> BridgeStatus:
    with socket.create_connection((host, port), timeout=timeout_seconds) as sock:
        sock.settimeout(timeout_seconds)
        sock.sendall(b"STATUS_VERBOSE\n")
        return BridgeStatus(sock.recv(2048).decode(errors="replace"))


def trigger_msc_mode(host: str, *, port: int = 5761, timeout_seconds: float = 5.0) -> str:
    transcript = bytearray()
    with socket.create_connection((host, port), timeout=timeout_seconds) as sock:
        sock.settimeout(0.5)
        sock.sendall(b"#\r")
        time.sleep(0.5)
        transcript.extend(_read_until_quiet(sock, quiet_seconds=0.5))
        sock.sendall(b"msc\r")
        time.sleep(1.0)
        transcript.extend(_read_until_quiet(sock, quiet_seconds=0.5))
    return transcript.decode("latin1", errors="replace")


def wait_for_msc_raw(
    host: str,
    *,
    port: int = 5762,
    timeout_seconds: float = 8.0,
    wait_seconds: float = 20.0,
) -> BridgeStatus:
    deadline = time.time() + wait_seconds
    last_status = BridgeStatus("")
    while time.time() < deadline:
        last_status = read_bridge_status(host, port=port, timeout_seconds=timeout_seconds)
        if last_status.msc_raw_ready:
            return last_status
        time.sleep(1.0)
    raise TimeoutError(f"MSC raw mode not ready; last status: {last_status.text}")


def _read_until_quiet(sock: socket.socket, *, quiet_seconds: float) -> bytes:
    deadline = time.time() + quiet_seconds
    chunks: list[bytes] = []
    while time.time() < deadline:
        try:
            data = sock.recv(4096)
        except socket.timeout:
            break
        if not data:
            break
        chunks.append(data)
        deadline = time.time() + quiet_seconds
    return b"".join(chunks)
