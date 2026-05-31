from __future__ import annotations

import dataclasses
import json
import socket
import time
from collections.abc import Callable
from pathlib import Path


BLACKBOX_HEADER = b"H Product:Blackbox"


@dataclasses.dataclass(frozen=True)
class BridgeStatus:
    text: str

    @property
    def usb_cdc_connected(self) -> bool:
        return "USB_CDC_CONNECTED" in self.text

    @property
    def msc_raw_ready(self) -> bool:
        return "msc_raw=1" in self.text


def _recv_line(sock: socket.socket) -> bytes:
    line = bytearray()
    while not line.endswith(b"\n"):
        chunk = sock.recv(1)
        if not chunk:
            break
        line.extend(chunk)
    return bytes(line)


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


def _part_path(output_path: Path) -> Path:
    return output_path.with_suffix(output_path.suffix + ".part")


def _state_path(output_path: Path) -> Path:
    return output_path.with_suffix(output_path.suffix + ".state.json")


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


def _load_resume_state(output_path: Path) -> tuple[int, int]:
    state_path = _state_path(output_path)
    part_path = _part_path(output_path)
    if not state_path.exists() or not part_path.exists():
        return 0, -1
    state = json.loads(state_path.read_text())
    return int(state.get("raw_bytes_downloaded", 0)), int(state.get("header_offset", -1))


def _write_resume_state(output_path: Path, raw_bytes_downloaded: int, header_offset: int) -> None:
    _state_path(output_path).write_text(json.dumps({"raw_bytes_downloaded": raw_bytes_downloaded, "header_offset": header_offset}))


def _read_msc_raw_range(
    host: str,
    *,
    port: int,
    timeout_seconds: float,
    offset: int,
    size: int,
) -> bytes:
    with socket.create_connection((host, port), timeout=timeout_seconds) as sock:
        sock.settimeout(timeout_seconds)
        sock.sendall(f"MSC_GET_RAW {offset} {size}\n".encode("ascii"))
        header = _recv_line(sock)
        if not header.startswith(b"DATA "):
            raise RuntimeError(f"unexpected Bridge reply {header!r}")
        total = int(header.split()[1])
        data = bytearray()
        while len(data) < total:
            chunk = sock.recv(min(8192, total - len(data)))
            if not chunk:
                break
            data.extend(chunk)
    if len(data) != total:
        raise RuntimeError(f"short read got={len(data)} expected={total}")
    return bytes(data)


def download_msc_raw(
    host: str,
    *,
    output_path: Path,
    size: int,
    port: int = 5762,
    timeout_seconds: float = 60.0,
    resume: bool = True,
    keep_leading_padding: bool = False,
    chunk_size: int = 1024 * 1024,
    max_attempts: int = 3,
    progress: Callable[[dict[str, object]], None] | None = None,
) -> dict[str, object]:
    if size < 0:
        raise ValueError("size must be non-negative")
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if max_attempts <= 0:
        raise ValueError("max_attempts must be positive")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    part_path = _part_path(output_path)
    raw_bytes_downloaded, header_offset = _load_resume_state(output_path) if resume else (0, -1)

    progress_events: list[dict[str, object]] = []
    chunks_completed = 0
    retries = 0
    while raw_bytes_downloaded < size:
        requested = min(chunk_size, size - raw_bytes_downloaded)
        last_error: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                data = _read_msc_raw_range(
                    host,
                    port=port,
                    timeout_seconds=timeout_seconds,
                    offset=raw_bytes_downloaded,
                    size=requested,
                )
                break
            except (OSError, RuntimeError) as exc:
                last_error = exc
                if attempt >= max_attempts:
                    raise RuntimeError(
                        f"MSC raw read failed after {max_attempts} attempts at offset {raw_bytes_downloaded}: {exc}"
                    ) from exc
                retries += 1
                time.sleep(min(0.25 * attempt, 2.0))
        else:  # pragma: no cover - defensive; for-loop either breaks or raises.
            raise RuntimeError(f"MSC raw read failed at offset {raw_bytes_downloaded}: {last_error}")

        with part_path.open("ab") as part:
            part.write(data)
        raw_bytes_downloaded += len(data)
        chunks_completed += 1

        raw = part_path.read_bytes()
        if header_offset < 0:
            header_offset = raw.find(BLACKBOX_HEADER)
        output_bytes = raw if keep_leading_padding or header_offset < 0 else raw[header_offset:]
        output_path.write_bytes(output_bytes)
        _write_resume_state(output_path, raw_bytes_downloaded, header_offset)

        event = {
            "raw_bytes_downloaded": raw_bytes_downloaded,
            "requested_size": size,
            "written_bytes": len(output_bytes),
            "header_offset": header_offset,
            "chunks_completed": chunks_completed,
            "retries": retries,
        }
        progress_events.append(event)
        if progress is not None:
            progress(event)

    raw = part_path.read_bytes()
    if header_offset < 0:
        header_offset = raw.find(BLACKBOX_HEADER)
    output_bytes = raw if keep_leading_padding or header_offset < 0 else raw[header_offset:]
    output_path.write_bytes(output_bytes)
    _write_resume_state(output_path, raw_bytes_downloaded, header_offset)

    return {
        "output_path": str(output_path),
        "part_path": str(part_path),
        "state_path": str(_state_path(output_path)),
        "raw_bytes_downloaded": raw_bytes_downloaded,
        "header_offset": header_offset,
        "written_bytes": len(output_bytes),
        "starts_with_blackbox_header": output_bytes.startswith(BLACKBOX_HEADER),
        "chunk_size": chunk_size,
        "chunks_completed": chunks_completed,
        "retries": retries,
        "progress_events": progress_events,
    }


def transfer_blackbox_log_from_bridge(
    host: str,
    *,
    output_path: Path,
    size: int,
    trigger_msc: bool = True,
    timeout_seconds: float = 60.0,
    resume: bool = True,
    chunk_size: int = 1024 * 1024,
    max_attempts: int = 3,
    progress: Callable[[dict[str, object]], None] | None = None,
) -> dict[str, object]:
    initial = read_bridge_status(host, timeout_seconds=min(timeout_seconds, 8.0))
    transcript = ""
    msc_status = initial
    if not initial.msc_raw_ready:
        if not trigger_msc:
            raise RuntimeError(f"Bridge is not in MSC raw mode: {initial.text}")
        if not initial.usb_cdc_connected:
            raise RuntimeError(f"FC is not in CDC/MSP mode and MSC raw is not ready: {initial.text}")
        transcript = trigger_msc_mode(host, timeout_seconds=min(timeout_seconds, 8.0))
        msc_status = wait_for_msc_raw(host, timeout_seconds=min(timeout_seconds, 8.0))

    download = download_msc_raw(
        host,
        output_path=output_path,
        size=size,
        timeout_seconds=timeout_seconds,
        resume=resume,
        chunk_size=chunk_size,
        max_attempts=max_attempts,
        progress=progress,
    )
    if not download["starts_with_blackbox_header"]:
        raise RuntimeError(f"transferred file does not start with Blackbox header: {download}")

    return {
        "initial_status": initial.text,
        "msc_status": msc_status.text,
        "trigger_transcript": transcript,
        "download": download,
        "operator_next_step": "Power-cycle/reset the FC back to USB CDC/MSP mode before further FC operations.",
    }
