from __future__ import annotations

import socket


def read_msc_raw_range(
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


def _recv_line(sock: socket.socket) -> bytes:
    line = bytearray()
    while not line.endswith(b"\n"):
        chunk = sock.recv(1)
        if not chunk:
            break
        line.extend(chunk)
    return bytes(line)
