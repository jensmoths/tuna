from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


def _ensure_fcs_host_importable() -> None:
    fcs_host = Path(__file__).resolve().parents[2] / "fcs-host"
    if not fcs_host.exists():
        raise RuntimeError(f"FCS host tools not found at {fcs_host}")
    if str(fcs_host) not in sys.path:
        sys.path.insert(0, str(fcs_host))


def inspect_fcs(host: str, *, port: int = 5761, timeout_seconds: float = 2.5) -> dict[str, Any]:
    _ensure_fcs_host_importable()
    from fcs_bridge import BridgeTransport, MspClient, discover_fc_capabilities

    with BridgeTransport(host, port, timeout_seconds=timeout_seconds) as transport:
        capabilities = discover_fc_capabilities(MspClient(transport), timeout_seconds=timeout_seconds)

    identity = capabilities.identity
    storage = capabilities.blackbox_storage
    return {
        "bridge_host": host,
        "bridge_port": port,
        "identity": {
            "fc_variant": identity.fc_variant,
            "fc_version": ".".join(str(part) for part in identity.fc_version),
            "msp_api": f"{identity.api_version[0]}.{identity.api_version[1]}",
        },
        "blackbox_storage": {
            "dataflash_available": storage.dataflash_available,
            "dataflash_supported": storage.dataflash_supported,
            "dataflash_ready": storage.dataflash_ready,
            "sector_count": storage.sector_count,
            "total_size": storage.total_size,
            "used_size": storage.used_size,
            "sdcard_summary_available": storage.sdcard_summary_available,
            "diagnostic": storage.diagnostic,
        },
    }
