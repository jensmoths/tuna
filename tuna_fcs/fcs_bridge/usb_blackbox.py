from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Any

from .blackbox_download import BLACKBOX_HEADER
from .usb_transport import trigger_usb_msc_mode


def _candidate_roots() -> list[Path]:
    roots: list[Path] = []
    env_roots = os.environ.get("FCS_USB_MSC_ROOTS", "")
    for value in env_roots.split(os.pathsep):
        if value:
            roots.append(Path(value))
    user = os.environ.get("USER") or os.environ.get("USERNAME") or ""
    for value in (f"/media/{user}", f"/run/media/{user}", "/media", "/mnt", "/Volumes"):
        path = Path(value)
        if path not in roots:
            roots.append(path)
    return roots


def _blackbox_files_under(root: Path) -> list[Path]:
    if not root.exists():
        return []
    try:
        return [path for path in root.rglob("*") if path.is_file() and path.suffix.lower() == ".bbl"]
    except (OSError, PermissionError):
        return []


def find_mounted_blackbox_file() -> Path | None:
    files: list[Path] = []
    for root in _candidate_roots():
        files.extend(_blackbox_files_under(root))
    if not files:
        return None
    return max(files, key=lambda path: path.stat().st_size)


def transfer_blackbox_log_from_usb(
    device: str | None,
    *,
    output_path: Path,
    trigger_msc: bool = True,
    timeout_seconds: float = 60.0,
) -> dict[str, Any]:
    transcript = b""
    if trigger_msc:
        transcript = trigger_usb_msc_mode(device, timeout_seconds=min(timeout_seconds, 8.0))
    deadline = time.monotonic() + timeout_seconds
    source: Path | None = None
    while time.monotonic() < deadline:
        source = find_mounted_blackbox_file()
        if source is not None:
            break
        time.sleep(1.0)
    if source is None:
        raise TimeoutError("Timed out waiting for a mounted Betaflight USB MSC .bbl Blackbox Log")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, output_path)
    data = output_path.read_bytes()
    starts = data.startswith(BLACKBOX_HEADER)
    if not starts:
        raise RuntimeError(f"transferred USB MSC file does not start with Blackbox header: {source}")
    return {
        "connection": "usb",
        "usb_device": device or "auto",
        "triggered_msc": trigger_msc,
        "source_path": str(source),
        "trigger_transcript": transcript.decode("latin1", errors="replace"),
        "download": {
            "output_path": str(output_path),
            "written_bytes": len(data),
            "starts_with_blackbox_header": starts,
            "header_offset": 0,
        },
        "operator_next_step": "Power-cycle/reset the FC back to USB CDC/MSP mode before further FC operations.",
    }
