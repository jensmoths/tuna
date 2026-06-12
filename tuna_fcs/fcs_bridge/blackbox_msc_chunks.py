from __future__ import annotations

import dataclasses
import time
from collections.abc import Callable
from pathlib import Path

from .blackbox_msc_output import MscOutputState, materialize_msc_output, write_resume_state


@dataclasses.dataclass(frozen=True)
class MscRawDownloadProgress:
    raw_bytes_downloaded: int
    header_offset: int
    next_header_offset: int
    target_raw_size: int
    output_bytes: bytes
    chunks_completed: int
    retries: int
    progress_events: list[dict[str, object]]


def download_msc_raw_chunks(
    host: str,
    *,
    output_path: Path,
    part_path: Path,
    port: int,
    timeout_seconds: float,
    raw_bytes_downloaded: int,
    header_offset: int,
    target_raw_size: int,
    output_size: int | None,
    keep_leading_padding: bool,
    stop_at_next_header: bool,
    chunk_size: int,
    max_attempts: int,
    recover_msc_raw: Callable[[], None] | None,
    progress: Callable[[dict[str, object]], None] | None,
    read_range: Callable[..., bytes],
) -> MscRawDownloadProgress:
    progress_events: list[dict[str, object]] = []
    chunks_completed = 0
    retries = 0
    next_header_offset = -1
    output_bytes = b""
    while raw_bytes_downloaded < target_raw_size:
        requested = min(chunk_size, target_raw_size - raw_bytes_downloaded)
        data, chunk_retries = _read_msc_raw_range_with_retries(
            host,
            port=port,
            timeout_seconds=timeout_seconds,
            offset=raw_bytes_downloaded,
            size=requested,
            max_attempts=max_attempts,
            recover_msc_raw=recover_msc_raw,
            read_range=read_range,
        )
        retries += chunk_retries
        chunks_completed += 1
        raw_bytes_downloaded, output_state = append_msc_raw_chunk(
            output_path=output_path,
            part_path=part_path,
            data=data,
            raw_bytes_downloaded=raw_bytes_downloaded,
            header_offset=header_offset,
            next_header_offset=next_header_offset,
            target_raw_size=target_raw_size,
            output_size=output_size,
            keep_leading_padding=keep_leading_padding,
            stop_at_next_header=stop_at_next_header,
        )
        header_offset = output_state.header_offset
        next_header_offset = output_state.next_header_offset
        target_raw_size = output_state.target_raw_size
        output_bytes = output_state.output_bytes
        event = msc_raw_progress_event(
            raw_bytes_downloaded=raw_bytes_downloaded,
            target_raw_size=target_raw_size,
            output_bytes=output_bytes,
            header_offset=header_offset,
            chunks_completed=chunks_completed,
            retries=retries,
            next_header_offset=next_header_offset,
        )
        progress_events.append(event)
        if progress is not None:
            progress(event)
        if next_header_offset >= 0:
            break
    return MscRawDownloadProgress(
        raw_bytes_downloaded=raw_bytes_downloaded,
        header_offset=header_offset,
        next_header_offset=next_header_offset,
        target_raw_size=target_raw_size,
        output_bytes=output_bytes,
        chunks_completed=chunks_completed,
        retries=retries,
        progress_events=progress_events,
    )


def append_msc_raw_chunk(
    *,
    output_path: Path,
    part_path: Path,
    data: bytes,
    raw_bytes_downloaded: int,
    header_offset: int,
    next_header_offset: int,
    target_raw_size: int,
    output_size: int | None,
    keep_leading_padding: bool,
    stop_at_next_header: bool,
) -> tuple[int, MscOutputState]:
    with part_path.open("ab") as part:
        part.write(data)
    raw_bytes_downloaded += len(data)
    output_state = materialize_msc_output(
        part_path.read_bytes(),
        header_offset=header_offset,
        next_header_offset=next_header_offset,
        target_raw_size=target_raw_size,
        output_size=output_size,
        keep_leading_padding=keep_leading_padding,
        stop_at_next_header=stop_at_next_header,
    )
    output_path.write_bytes(output_state.output_bytes)
    write_resume_state(output_path, raw_bytes_downloaded, output_state.header_offset)
    return raw_bytes_downloaded, output_state


def msc_raw_progress_event(
    *,
    raw_bytes_downloaded: int,
    target_raw_size: int,
    output_bytes: bytes,
    header_offset: int,
    chunks_completed: int,
    retries: int,
    next_header_offset: int,
) -> dict[str, object]:
    return {
        "raw_bytes_downloaded": raw_bytes_downloaded,
        "requested_size": target_raw_size,
        "written_bytes": len(output_bytes),
        "header_offset": header_offset,
        "chunks_completed": chunks_completed,
        "retries": retries,
        "next_header_offset": next_header_offset,
    }


def _read_msc_raw_range_with_retries(
    host: str,
    *,
    port: int,
    timeout_seconds: float,
    offset: int,
    size: int,
    max_attempts: int,
    recover_msc_raw: Callable[[], None] | None,
    read_range: Callable[..., bytes],
) -> tuple[bytes, int]:
    retries = 0
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return read_range(
                host,
                port=port,
                timeout_seconds=timeout_seconds,
                offset=offset,
                size=size,
            ), retries
        except (OSError, RuntimeError) as exc:
            last_error = exc
            if attempt >= max_attempts:
                raise RuntimeError(f"MSC raw read failed after {max_attempts} attempts at offset {offset}: {exc}") from exc
            retries += 1
            if recover_msc_raw is not None:
                try:
                    recover_msc_raw()
                except (OSError, RuntimeError, TimeoutError) as recovery_exc:
                    last_error = recovery_exc
            time.sleep(min(0.25 * attempt, 2.0))
    raise RuntimeError(f"MSC raw read failed at offset {offset}: {last_error}")
