#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import socket
import sys
from pathlib import Path


def _default_output_path(output_dir: Path) -> Path:
    timestamp = dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    return output_dir / f"blackbox-msc-raw-{timestamp}.bbl"


def _recv_line(sock: socket.socket) -> bytes:
    line = bytearray()
    while not line.endswith(b"\n"):
        chunk = sock.recv(1)
        if not chunk:
            break
        line.extend(chunk)
    return bytes(line)


def _state_path(output_path: Path) -> Path:
    return output_path.with_suffix(output_path.suffix + ".state.json")


def _part_path(output_path: Path) -> Path:
    return output_path.with_suffix(output_path.suffix + ".part")


def _load_resume_state(output_path: Path) -> tuple[int, int]:
    state_path = _state_path(output_path)
    part_path = _part_path(output_path)
    if not state_path.exists() or not part_path.exists():
        return 0, -1
    try:
        state = json.loads(state_path.read_text())
        return int(state.get("raw_bytes_downloaded", 0)), int(state.get("header_offset", -1))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return 0, -1


def _write_resume_state(output_path: Path, raw_bytes_downloaded: int, header_offset: int) -> None:
    _state_path(output_path).write_text(
        json.dumps({"raw_bytes_downloaded": raw_bytes_downloaded, "header_offset": header_offset})
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Download raw Betaflight MSC Blackbox Log bytes through the Tuna Bridge control port")
    parser.add_argument("host", help="Bridge hostname or IP")
    parser.add_argument("--port", type=int, default=5762, help="Bridge control TCP port")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--size", type=int, default=1024 * 1024, help="raw bytes to request from MSC device")
    parser.add_argument("--output-dir", default="transferred-logs")
    parser.add_argument("--output", help="specific .bbl output path")
    parser.add_argument("--keep-leading-padding", action="store_true", help="do not trim bytes before the Blackbox header")
    parser.add_argument("--resume", action="store_true", help="resume an interrupted download using the .part state file")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = Path(args.output) if args.output else _default_output_path(output_dir)

    part_path = _part_path(output_path)
    state_path = _state_path(output_path)
    raw_bytes_downloaded = 0
    header_offset = -1
    if args.resume:
        raw_bytes_downloaded, header_offset = _load_resume_state(output_path)

    with socket.create_connection((args.host, args.port), timeout=args.timeout) as sock:
        sock.settimeout(args.timeout)
        sock.sendall(f"MSC_GET_RAW {raw_bytes_downloaded} {max(args.size - raw_bytes_downloaded, 0)}\n".encode("ascii"))
        header = _recv_line(sock)
        if not header.startswith(b"DATA "):
            print(f"download fail reason=unexpected Bridge reply {header!r}")
            return 1
        total = int(header.split()[1])
        data = bytearray()
        while len(data) < total:
            chunk = sock.recv(min(8192, total - len(data)))
            if not chunk:
                break
            data.extend(chunk)

    if len(data) != total:
        print(f"download fail reason=short read got={len(data)} expected={total}")
        return 1

    with part_path.open("ab") as part:
        part.write(data)
    raw_bytes_downloaded += len(data)

    raw = part_path.read_bytes()
    if header_offset < 0:
        header_offset = raw.find(b"H Product:Blackbox")
    if header_offset >= 0 and not args.keep_leading_padding:
        output_path.write_bytes(raw[header_offset:])
    else:
        output_path.write_bytes(raw)
    _write_resume_state(output_path, raw_bytes_downloaded, header_offset)
    print(f"download ok raw_bytes={raw_bytes_downloaded} header_offset={header_offset} written={output_path.stat().st_size} path={output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
