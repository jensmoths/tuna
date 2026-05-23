from __future__ import annotations

import dataclasses

from .msp import (
    MSP_API_VERSION,
    MSP_DATAFLASH_SUMMARY,
    MSP_FC_VARIANT,
    MSP_FC_VERSION,
    MSP_SDCARD_SUMMARY,
    MspProtocolError,
    parse_api_version,
    parse_dataflash_summary,
    parse_fc_variant,
    parse_fc_version,
)
from .msp_client import MspClient


@dataclasses.dataclass(frozen=True)
class FcIdentity:
    msp_protocol: int
    api_version: tuple[int, int]
    fc_variant: str
    fc_version: tuple[int, int, int]


@dataclasses.dataclass(frozen=True)
class BlackboxLogStorageStatus:
    dataflash_available: bool
    dataflash_supported: bool = False
    dataflash_ready: bool = False
    sector_count: int = 0
    total_size: int = 0
    used_size: int = 0
    sdcard_summary_available: bool = False
    diagnostic: str = ""


@dataclasses.dataclass(frozen=True)
class FcCapabilities:
    identity: FcIdentity
    blackbox_storage: BlackboxLogStorageStatus


def discover_fc_identity(client: MspClient, *, timeout_seconds: float) -> FcIdentity:
    protocol, api_major, api_minor = parse_api_version(
        client.request(MSP_API_VERSION, timeout_seconds=timeout_seconds).payload
    )
    variant = parse_fc_variant(
        client.request(MSP_FC_VARIANT, timeout_seconds=timeout_seconds).payload
    )
    version = parse_fc_version(
        client.request(MSP_FC_VERSION, timeout_seconds=timeout_seconds).payload
    )
    return FcIdentity(
        msp_protocol=protocol,
        api_version=(api_major, api_minor),
        fc_variant=variant,
        fc_version=version,
    )


def get_blackbox_log_storage_status(
    client: MspClient, *, timeout_seconds: float
) -> BlackboxLogStorageStatus:
    """Read-only Blackbox Log storage discovery through FCS."""

    try:
        summary = parse_dataflash_summary(
            client.request(MSP_DATAFLASH_SUMMARY, timeout_seconds=timeout_seconds).payload
        )
    except (MspProtocolError, TimeoutError) as exc:
        return BlackboxLogStorageStatus(
            dataflash_available=False,
            diagnostic=f"MSP_DATAFLASH_SUMMARY unavailable: {exc}",
        )

    sdcard_summary_available = True
    try:
        client.request(MSP_SDCARD_SUMMARY, timeout_seconds=timeout_seconds)
    except (MspProtocolError, TimeoutError):
        sdcard_summary_available = False

    return BlackboxLogStorageStatus(
        dataflash_available=True,
        dataflash_supported=bool(summary["supported"]),
        dataflash_ready=bool(summary["ready"]),
        sector_count=int(summary["sector_count"]),
        total_size=int(summary["total_size"]),
        used_size=int(summary["used_size"]),
        sdcard_summary_available=sdcard_summary_available,
    )


def discover_fc_capabilities(client: MspClient, *, timeout_seconds: float) -> FcCapabilities:
    return FcCapabilities(
        identity=discover_fc_identity(client, timeout_seconds=timeout_seconds),
        blackbox_storage=get_blackbox_log_storage_status(
            client, timeout_seconds=timeout_seconds
        ),
    )
