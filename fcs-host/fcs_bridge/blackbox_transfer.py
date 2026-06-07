from __future__ import annotations

from .msp import MSP_DATAFLASH_ERASE
from .msp_client import MspClient


def erase_dataflash(client: MspClient, *, timeout_seconds: float, msp_version: int = 1) -> None:
    """Erase FC dataflash through MSP_DATAFLASH_ERASE."""

    if msp_version not in (1, 2):
        raise ValueError("MSP version must be 1 or 2")
    request = client.request_v2 if msp_version == 2 else client.request
    request(MSP_DATAFLASH_ERASE, timeout_seconds=timeout_seconds)
