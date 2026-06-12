from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .blackbox_bridge_control import BridgeStatus
from .blackbox_bridge_control import read_bridge_status
from .blackbox_bridge_control import trigger_msc_mode
from .blackbox_bridge_control import wait_for_msc_raw
from .blackbox_msc_file import download_preferred_msc_file
from .blackbox_msc_raw import BLACKBOX_HEADER
from .blackbox_msc_raw import download_msc_raw as _download_msc_raw
from .blackbox_msc_raw import part_path as _part_path
from .blackbox_msc_raw import read_msc_raw_range as _read_msc_raw_range
from .blackbox_msc_raw import state_path as _state_path


import dataclasses


@dataclasses.dataclass(frozen=True)
class MscTransferPreparation:
    initial: BridgeStatus
    msc_status: BridgeStatus
    resolved_size: int | None
    transcript: str



def discover_blackbox_transfer_size(host: str, *, timeout_seconds: float = 8.0) -> int:
    """Return FC-reported used Blackbox Log storage bytes through FCS/MSP."""

    from .bridge_transport import BridgeTransport
    from .fc_discovery import discover_fc_capabilities
    from .msp_client import MspClient

    with BridgeTransport(host, 5761, timeout_seconds=timeout_seconds) as transport:
        capabilities = discover_fc_capabilities(MspClient(transport), timeout_seconds=timeout_seconds)
    storage = {
        "dataflash_available": capabilities.blackbox_storage.dataflash_available,
        "dataflash_supported": capabilities.blackbox_storage.dataflash_supported,
        "dataflash_ready": capabilities.blackbox_storage.dataflash_ready,
        "used_size": capabilities.blackbox_storage.used_size,
    }
    if not storage["dataflash_available"] or not storage["dataflash_supported"] or not storage["dataflash_ready"]:
        raise RuntimeError(f"Blackbox Log storage is not ready for transfer size discovery: {storage}")
    used_size = int(storage["used_size"])
    if used_size <= 0:
        raise RuntimeError(f"FC reports no Blackbox Log bytes to transfer: {storage}")
    return used_size



def download_msc_raw(
    host: str,
    *,
    output_path: Path,
    size: int,
    port: int = 5762,
    timeout_seconds: float = 60.0,
    resume: bool = True,
    keep_leading_padding: bool = False,
    output_size: int | None = None,
    stop_at_next_header: bool = False,
    chunk_size: int = 1024 * 1024,
    max_attempts: int = 3,
    recover_msc_raw: Callable[[], None] | None = None,
    progress: Callable[[dict[str, object]], None] | None = None,
) -> dict[str, object]:
    return _download_msc_raw(
        host,
        output_path=output_path,
        size=size,
        port=port,
        timeout_seconds=timeout_seconds,
        resume=resume,
        keep_leading_padding=keep_leading_padding,
        output_size=output_size,
        stop_at_next_header=stop_at_next_header,
        chunk_size=chunk_size,
        max_attempts=max_attempts,
        recover_msc_raw=recover_msc_raw,
        progress=progress,
        read_range=_read_msc_raw_range,
    )


def transfer_blackbox_log_from_bridge(
    host: str,
    *,
    output_path: Path,
    size: int | None = None,
    trigger_msc: bool = True,
    timeout_seconds: float = 60.0,
    resume: bool = True,
    chunk_size: int = 1024 * 1024,
    max_attempts: int = 3,
    progress: Callable[[dict[str, object]], None] | None = None,
) -> dict[str, object]:
    preparation = _prepare_msc_transfer(host, size=size, trigger_msc=trigger_msc, timeout_seconds=timeout_seconds)
    file_download = _try_msc_file_download(host, output_path=output_path, msc_status=preparation.msc_status, timeout_seconds=timeout_seconds)

    if file_download is not None:
        if not file_download["starts_with_blackbox_header"]:
            raise RuntimeError(f"transferred MSC file does not start with Blackbox header: {file_download}")
        return {
            "initial_status": preparation.initial.text,
            "msc_status": preparation.msc_status.text,
            "trigger_transcript": preparation.transcript,
            "download": file_download,
            "operator_next_step": "Power-cycle/reset the FC back to USB CDC/MSP mode before further FC operations.",
        }

    if preparation.resolved_size is None:
        raise ValueError("--size is required when MSC file transfer is unavailable and MSP storage discovery is unavailable")

    def recover_msc_raw() -> None:
        _recover_msc_raw(host, trigger_msc=trigger_msc, timeout_seconds=timeout_seconds)

    download = download_msc_raw(
        host,
        output_path=output_path,
        size=preparation.resolved_size,
        timeout_seconds=min(timeout_seconds, 15.0),
        resume=resume,
        chunk_size=chunk_size,
        max_attempts=max_attempts,
        output_size=preparation.resolved_size,
        recover_msc_raw=recover_msc_raw,
        progress=progress,
    )
    if not download["starts_with_blackbox_header"]:
        raise RuntimeError(f"transferred file does not start with Blackbox header: {download}")

    return {
        "initial_status": preparation.initial.text,
        "msc_status": preparation.msc_status.text,
        "trigger_transcript": preparation.transcript,
        "download": download,
        "fallback_reason": "MSC file transfer unavailable; used raw MSC range transfer.",
        "operator_next_step": "Power-cycle/reset the FC back to USB CDC/MSP mode before further FC operations.",
    }


def _prepare_msc_transfer(host: str, *, size: int | None, trigger_msc: bool, timeout_seconds: float) -> MscTransferPreparation:
    initial = read_bridge_status(host, timeout_seconds=min(timeout_seconds, 8.0))
    if initial.msc_raw_ready:
        return MscTransferPreparation(initial=initial, msc_status=initial, resolved_size=size, transcript="")
    if not trigger_msc:
        raise RuntimeError(f"Bridge is not in MSC raw mode: {initial.text}")
    if not initial.usb_cdc_connected:
        raise RuntimeError(f"FC is not in CDC/MSP mode and MSC raw is not ready: {initial.text}")
    resolved_size = size if size is not None else discover_blackbox_transfer_size(host, timeout_seconds=min(timeout_seconds, 8.0))
    transcript = trigger_msc_mode(host, timeout_seconds=min(timeout_seconds, 8.0))
    msc_status = wait_for_msc_raw(host, timeout_seconds=min(timeout_seconds, 8.0))
    return MscTransferPreparation(initial=initial, msc_status=msc_status, resolved_size=resolved_size, transcript=transcript)


def _try_msc_file_download(host: str, *, output_path: Path, msc_status: BridgeStatus, timeout_seconds: float) -> dict[str, object] | None:
    if not msc_status.msc_mounted:
        return None
    try:
        return download_preferred_msc_file(host, output_path=output_path, timeout_seconds=min(timeout_seconds, 15.0))
    except (OSError, RuntimeError, TimeoutError):
        return None


def _recover_msc_raw(host: str, *, trigger_msc: bool, timeout_seconds: float) -> None:
    status = read_bridge_status(host, timeout_seconds=min(timeout_seconds, 8.0))
    if status.msc_raw_ready:
        return
    if not trigger_msc:
        raise RuntimeError(f"Bridge left MSC raw mode during transfer: {status.text}")
    if not status.usb_cdc_connected:
        wait_for_msc_raw(host, timeout_seconds=min(timeout_seconds, 8.0))
        return
    trigger_msc_mode(host, timeout_seconds=min(timeout_seconds, 8.0))
    wait_for_msc_raw(host, timeout_seconds=min(timeout_seconds, 8.0))
