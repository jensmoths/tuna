from __future__ import annotations

import dataclasses
from typing import Optional

MSP_API_VERSION = 1
MSP_FC_VARIANT = 2
MSP_FC_VERSION = 3
MSP_DATAFLASH_SUMMARY = 70
MSP_DATAFLASH_READ = 71
MSP_SDCARD_SUMMARY = 79
MSP_BLACKBOX_CONFIG = 80
MSP_IDENT = 100

MSP_FLASHFS_FLAG_READY = 1 << 0
MSP_FLASHFS_FLAG_SUPPORTED = 1 << 1


class MspProtocolError(RuntimeError):
    pass


@dataclasses.dataclass
class MspFrame:
    direction: str
    command: int
    payload: bytes
    is_error: bool = False
    version: int = 1


def _crc8_dvb_s2(crc: int, byte: int) -> int:
    crc ^= byte
    for _ in range(8):
        if crc & 0x80:
            crc = ((crc << 1) ^ 0xD5) & 0xFF
        else:
            crc = (crc << 1) & 0xFF
    return crc


def _crc8_dvb_s2_bytes(payload: bytes) -> int:
    crc = 0
    for byte in payload:
        crc = _crc8_dvb_s2(crc, byte)
    return crc


def build_msp_v1_request(command: int, payload: bytes = b"") -> bytes:
    if not 0 <= command <= 255:
        raise ValueError("MSP v1 command must fit in one byte")
    if len(payload) > 255:
        raise ValueError("MSP v1 payload too large")

    checksum = len(payload) ^ command
    for byte in payload:
        checksum ^= byte
    return b"$M<" + bytes([len(payload), command]) + payload + bytes([checksum])


def build_msp_v2_request(command: int, payload: bytes = b"") -> bytes:
    if not 0 <= command <= 0xFFFF:
        raise ValueError("MSP v2 command must fit in uint16")
    if len(payload) > 0xFFFF:
        raise ValueError("MSP v2 payload too large")

    header = b"\x00" + command.to_bytes(2, "little") + len(payload).to_bytes(2, "little")
    checksum = _crc8_dvb_s2_bytes(header + payload)
    return b"$X<" + header + payload + bytes([checksum])


def try_parse_msp_v1_frame(buffer: bytes) -> tuple[Optional[MspFrame], bytes]:
    start = buffer.find(b"$M")
    if start == -1:
        return None, b""
    if start > 0:
        buffer = buffer[start:]

    if len(buffer) < 6:
        return None, buffer

    direction = chr(buffer[2])
    if direction not in (">", "!"):
        return None, buffer[1:]

    size = buffer[3]
    total = 6 + size
    if len(buffer) < total:
        return None, buffer

    command = buffer[4]
    payload = buffer[5 : 5 + size]
    checksum = buffer[5 + size]

    expected = size ^ command
    for byte in payload:
        expected ^= byte
    if checksum != expected:
        raise MspProtocolError(
            f"MSP checksum mismatch for command {command}: got {checksum}, expected {expected}"
        )

    frame = MspFrame(
        direction=direction,
        command=command,
        payload=payload,
        is_error=(direction == "!"),
    )
    return frame, buffer[total:]


def try_parse_msp_v2_frame(buffer: bytes) -> tuple[Optional[MspFrame], bytes]:
    start = buffer.find(b"$X")
    if start == -1:
        return None, b""
    if start > 0:
        buffer = buffer[start:]

    if len(buffer) < 9:
        return None, buffer

    direction = chr(buffer[2])
    if direction not in (">", "!"):
        return None, buffer[1:]

    header = buffer[3:8]
    flags = header[0]
    command = int.from_bytes(header[1:3], "little")
    size = int.from_bytes(header[3:5], "little")
    total = 9 + size
    if len(buffer) < total:
        return None, buffer

    payload = buffer[8 : 8 + size]
    checksum = buffer[8 + size]
    expected = _crc8_dvb_s2_bytes(header + payload)
    if checksum != expected:
        raise MspProtocolError(
            f"MSP v2 checksum mismatch for command {command}: got {checksum}, expected {expected}"
        )

    frame = MspFrame(
        direction=direction,
        command=command,
        payload=payload,
        is_error=(direction == "!"),
        version=2,
    )
    return frame, buffer[total:]


def try_parse_msp_frame(buffer: bytes) -> tuple[Optional[MspFrame], bytes]:
    starts = [(pos, version) for pos, version in ((buffer.find(b"$M"), 1), (buffer.find(b"$X"), 2)) if pos != -1]
    if not starts:
        return None, b""
    _, version = min(starts)
    if version == 2:
        return try_parse_msp_v2_frame(buffer)
    return try_parse_msp_v1_frame(buffer)


def parse_api_version(payload: bytes) -> tuple[int, int, int]:
    if len(payload) < 3:
        raise MspProtocolError("MSP_API_VERSION payload too short")
    return payload[0], payload[1], payload[2]


def parse_fc_variant(payload: bytes) -> str:
    if len(payload) < 4:
        raise MspProtocolError("MSP_FC_VARIANT payload too short")
    return payload[:4].decode("ascii", errors="replace")


def parse_fc_version(payload: bytes) -> tuple[int, int, int]:
    if len(payload) < 3:
        raise MspProtocolError("MSP_FC_VERSION payload too short")
    return payload[0], payload[1], payload[2]


def parse_ident(payload: bytes) -> dict[str, int]:
    if len(payload) < 7:
        raise MspProtocolError("MSP_IDENT payload too short")
    return {
        "version": payload[0],
        "multitype": payload[1],
        "msp_version": payload[2],
        "capability": int.from_bytes(payload[3:7], "little"),
    }


def parse_dataflash_summary(payload: bytes) -> dict[str, int | bool]:
    if len(payload) < 13:
        raise MspProtocolError("MSP_DATAFLASH_SUMMARY payload too short")

    flags = payload[0]
    return {
        "flags": flags,
        "supported": bool(flags & MSP_FLASHFS_FLAG_SUPPORTED),
        "ready": bool(flags & MSP_FLASHFS_FLAG_READY),
        "sector_count": int.from_bytes(payload[1:5], "little"),
        "total_size": int.from_bytes(payload[5:9], "little"),
        "used_size": int.from_bytes(payload[9:13], "little"),
    }


def build_dataflash_read_payload(
    address: int, size: int, *, allow_compression: bool = False
) -> bytes:
    if not 0 <= address <= 0xFFFFFFFF:
        raise ValueError("dataflash read address must fit in uint32")
    if not 0 <= size <= 0xFFFF:
        raise ValueError("dataflash read size must fit in uint16")

    return (
        address.to_bytes(4, "little")
        + size.to_bytes(2, "little")
        + bytes([1 if allow_compression else 0])
    )


def parse_dataflash_read(payload: bytes) -> dict[str, int | bytes]:
    if len(payload) < 7:
        raise MspProtocolError("MSP_DATAFLASH_READ payload too short")

    address = int.from_bytes(payload[0:4], "little")
    read_size = int.from_bytes(payload[4:6], "little")
    compression_type = payload[6]
    data = payload[7:]

    if compression_type != 0:
        raise MspProtocolError(
            f"unsupported MSP_DATAFLASH_READ compression type {compression_type}"
        )
    if len(data) < read_size:
        raise MspProtocolError(
            f"MSP_DATAFLASH_READ payload shorter than declared read size: {len(data)} < {read_size}"
        )

    return {
        "address": address,
        "read_size": read_size,
        "compression_type": compression_type,
        "data": data[:read_size],
    }
