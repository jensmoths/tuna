from __future__ import annotations

import socket
from pathlib import Path

from .blackbox_msc_raw import BLACKBOX_HEADER


def download_preferred_msc_file(
    host: str,
    *,
    output_path: Path,
    timeout_seconds: float = 15.0,
) -> dict[str, object] | None:
    files = _list_msc_blackbox_files(host, timeout_seconds=min(timeout_seconds, 5.0))
    if not files:
        return None
    name, _size = max(files, key=lambda item: item[1])
    return _download_msc_blackbox_file(host, name=name, output_path=output_path, timeout_seconds=timeout_seconds)


def _list_msc_blackbox_files(host: str, *, port: int = 5762, timeout_seconds: float = 5.0) -> list[tuple[str, int]]:
    with socket.create_connection((host, port), timeout=timeout_seconds) as sock:
        sock.settimeout(timeout_seconds)
        sock.sendall(b"MSC_LIST\n")
        lines = _read_control_lines_until_done(sock)
    if not lines or lines[-1] != "OK":
        return []
    files: list[tuple[str, int]] = []
    for line in lines[:-1]:
        if not line.startswith("MSC_LOG "):
            continue
        rest = line[len("MSC_LOG ") :]
        name, _, size_text = rest.rpartition(" ")
        if not name or not size_text.isdigit():
            continue
        if name.lower().endswith(".bbl"):
            files.append((name, int(size_text)))
    return files


def _download_msc_blackbox_file(
    host: str,
    *,
    name: str,
    output_path: Path,
    port: int = 5762,
    timeout_seconds: float = 15.0,
) -> dict[str, object]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with socket.create_connection((host, port), timeout=timeout_seconds) as sock:
        sock.settimeout(timeout_seconds)
        sock.sendall(f"MSC_GET {name}\n".encode("utf-8"))
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
    output_path.write_bytes(data)
    return {
        "method": "msc_file",
        "name": name,
        "output_path": str(output_path),
        "written_bytes": len(data),
        "starts_with_blackbox_header": bytes(data).startswith(BLACKBOX_HEADER),
    }


def _recv_line(sock: socket.socket) -> bytes:
    line = bytearray()
    while not line.endswith(b"\n"):
        chunk = sock.recv(1)
        if not chunk:
            break
        line.extend(chunk)
    return bytes(line)


def _read_control_lines_until_done(sock: socket.socket) -> list[str]:
    lines: list[str] = []
    while True:
        raw = _recv_line(sock)
        if not raw:
            break
        line = raw.decode(errors="replace").rstrip("\r\n")
        lines.append(line)
        if line == "OK" or line.startswith("ERR "):
            break
    return lines
