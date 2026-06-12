from __future__ import annotations

import dataclasses
import json
from pathlib import Path

BLACKBOX_HEADER = b"H Product:Blackbox"


@dataclasses.dataclass(frozen=True)
class MscOutputState:
    header_offset: int
    next_header_offset: int
    target_raw_size: int
    output_bytes: bytes


def part_path(output_path: Path) -> Path:
    return output_path.with_suffix(output_path.suffix + ".part")


def state_path(output_path: Path) -> Path:
    return output_path.with_suffix(output_path.suffix + ".state.json")


def load_resume_state(output_path: Path) -> tuple[int, int]:
    resume_state = state_path(output_path)
    part = part_path(output_path)
    if not resume_state.exists() or not part.exists():
        return 0, -1
    state = json.loads(resume_state.read_text())
    return int(state.get("raw_bytes_downloaded", 0)), int(state.get("header_offset", -1))


def write_resume_state(output_path: Path, raw_bytes_downloaded: int, header_offset: int) -> None:
    state_path(output_path).write_text(json.dumps({"raw_bytes_downloaded": raw_bytes_downloaded, "header_offset": header_offset}))


def materialize_msc_output(
    raw: bytes,
    *,
    header_offset: int,
    next_header_offset: int,
    target_raw_size: int,
    output_size: int | None,
    keep_leading_padding: bool,
    stop_at_next_header: bool,
) -> MscOutputState:
    if header_offset < 0:
        header_offset = raw.find(BLACKBOX_HEADER)
    if output_size is not None and header_offset >= 0:
        target_raw_size = max(target_raw_size, header_offset + output_size)
    if stop_at_next_header and header_offset >= 0 and next_header_offset < 0:
        next_header_offset = raw.find(BLACKBOX_HEADER, header_offset + len(BLACKBOX_HEADER))
    output_end = next_header_offset if next_header_offset >= 0 else None
    output_bytes = raw if keep_leading_padding or header_offset < 0 else raw[header_offset:output_end]
    return MscOutputState(
        header_offset=header_offset,
        next_header_offset=next_header_offset,
        target_raw_size=target_raw_size,
        output_bytes=output_bytes,
    )


def msc_raw_download_result(
    *,
    output_path: Path,
    part_path: Path,
    raw_bytes_downloaded: int,
    target_raw_size: int,
    header_offset: int,
    next_header_offset: int,
    output_bytes: bytes,
    chunk_size: int,
    chunks_completed: int,
    retries: int,
    progress_events: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "output_path": str(output_path),
        "part_path": str(part_path),
        "state_path": str(state_path(output_path)),
        "raw_bytes_downloaded": raw_bytes_downloaded,
        "requested_size": target_raw_size,
        "header_offset": header_offset,
        "next_header_offset": next_header_offset,
        "stopped_at_next_header": next_header_offset >= 0,
        "written_bytes": len(output_bytes),
        "starts_with_blackbox_header": output_bytes.startswith(BLACKBOX_HEADER),
        "chunk_size": chunk_size,
        "chunks_completed": chunks_completed,
        "retries": retries,
        "progress_events": progress_events,
    }
