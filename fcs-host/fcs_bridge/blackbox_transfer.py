from __future__ import annotations

from .msp import (
    MSP_DATAFLASH_READ,
    build_dataflash_read_payload,
    parse_dataflash_read,
)
from .msp_client import MspClient


MAX_MSP_V1_DATAFLASH_READ_SIZE = 240
MAX_MSP_V2_DATAFLASH_READ_SIZE = 4096


def read_dataflash_range(
    client: MspClient,
    *,
    address: int,
    size: int,
    timeout_seconds: float,
    chunk_size: int = MAX_MSP_V1_DATAFLASH_READ_SIZE,
    msp_version: int = 1,
) -> bytes:
    """Read a byte range from FC dataflash without changing FC state."""

    if address < 0:
        raise ValueError("dataflash read address must be non-negative")
    if size < 0:
        raise ValueError("dataflash read size must be non-negative")
    max_chunk_size = MAX_MSP_V2_DATAFLASH_READ_SIZE if msp_version == 2 else MAX_MSP_V1_DATAFLASH_READ_SIZE
    if msp_version not in (1, 2):
        raise ValueError("MSP version must be 1 or 2")
    if not 1 <= chunk_size <= max_chunk_size:
        raise ValueError(f"dataflash read chunk size must be 1..{max_chunk_size} bytes")

    chunks: list[bytes] = []
    remaining = size
    cursor = address

    while remaining > 0:
        requested = min(chunk_size, remaining)
        request = client.request_v2 if msp_version == 2 else client.request
        frame = request(
            MSP_DATAFLASH_READ,
            build_dataflash_read_payload(cursor, requested),
            timeout_seconds=timeout_seconds,
        )
        parsed = parse_dataflash_read(frame.payload)
        if int(parsed["address"]) != cursor:
            raise RuntimeError(
                f"dataflash read returned address {parsed['address']}, expected {cursor}"
            )

        data = parsed["data"]
        assert isinstance(data, bytes)
        if not data:
            break

        chunks.append(data)
        cursor += len(data)
        remaining -= len(data)

        if len(data) < requested:
            break

    return b"".join(chunks)
