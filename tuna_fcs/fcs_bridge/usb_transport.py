from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

try:
    import serial
    from serial.tools import list_ports
except ModuleNotFoundError as exc:  # pragma: no cover - depends on host install
    serial = None
    list_ports = None
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None


class UsbConnectionError(ConnectionError):
    pass


@dataclass(frozen=True)
class UsbDevice:
    device: str
    description: str
    hwid: str


def list_usb_fc_devices() -> list[UsbDevice]:
    if list_ports is None:
        raise UsbConnectionError("pyserial is required for direct USB FC access") from _IMPORT_ERROR
    devices: list[UsbDevice] = []
    for port in list_ports.comports():
        text = f"{port.device} {port.description} {port.hwid}".lower()
        if any(token in text for token in ("betaflight", "stm", "flight", "msp", "usb serial", "cp210", "ch340")):
            devices.append(UsbDevice(port.device, port.description, port.hwid))
    return devices


def resolve_usb_device(device: str | None = None) -> str:
    if device:
        return device
    devices = list_usb_fc_devices()
    if not devices:
        raise UsbConnectionError("No USB flight controller serial device found; pass --usb-device")
    if len(devices) > 1:
        names = ", ".join(item.device for item in devices)
        raise UsbConnectionError(f"Multiple USB serial devices found ({names}); pass --usb-device")
    return devices[0].device


class UsbSerialTransport:
    """Serial USB CDC transport with the same send/recv shape as BridgeTransport."""

    def __init__(self, device: str | None = None, *, baudrate: int = 115200, timeout_seconds: float = 2.5):
        if serial is None:
            raise UsbConnectionError("pyserial is required for direct USB FC access") from _IMPORT_ERROR
        self.device = resolve_usb_device(device)
        self.baudrate = baudrate
        self.timeout_seconds = timeout_seconds
        self._serial = None

    def connect(self) -> None:
        if self._serial is not None:
            raise UsbConnectionError("USB transport already connected")
        self._serial = serial.Serial(self.device, self.baudrate, timeout=self.timeout_seconds, write_timeout=self.timeout_seconds)
        time.sleep(0.2)
        self._serial.reset_input_buffer()

    def disconnect(self) -> None:
        if self._serial is not None:
            self._serial.close()
            self._serial = None

    def send(self, data: bytes) -> None:
        if self._serial is None:
            raise UsbConnectionError("USB transport is not connected")
        self._serial.write(data)
        self._serial.flush()

    def recv(self, size: int) -> bytes:
        if self._serial is None:
            raise UsbConnectionError("USB transport is not connected")
        return self._serial.read(size)

    def __enter__(self) -> "UsbSerialTransport":
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.disconnect()


def read_until_quiet(transport, *, timeout_seconds: float, quiet_seconds: float = 0.2) -> bytes:
    deadline = time.monotonic() + timeout_seconds
    quiet_deadline = time.monotonic() + quiet_seconds
    chunks: list[bytes] = []
    while time.monotonic() < deadline:
        data = transport.recv(4096)
        if data:
            chunks.append(data)
            quiet_deadline = time.monotonic() + quiet_seconds
        elif time.monotonic() >= quiet_deadline:
            break
    return b"".join(chunks)


def trigger_usb_msc_mode(device: str | None, *, timeout_seconds: float = 5.0) -> bytes:
    with UsbSerialTransport(device, timeout_seconds=timeout_seconds) as transport:
        transport.send(b"#\r")
        read_until_quiet(transport, timeout_seconds=timeout_seconds)
        transport.send(b"msc\r")
        return read_until_quiet(transport, timeout_seconds=timeout_seconds)
