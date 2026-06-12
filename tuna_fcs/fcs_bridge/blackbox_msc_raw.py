from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .blackbox_msc_chunks import MscRawDownloadProgress, download_msc_raw_chunks
from .blackbox_msc_output import BLACKBOX_HEADER, load_resume_state, materialize_msc_output, msc_raw_download_result, part_path, state_path, write_resume_state
from .blackbox_msc_socket import read_msc_raw_range


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
    read_range: Callable[..., bytes] = read_msc_raw_range,
) -> dict[str, object]:
    _validate_msc_raw_download_options(
        size=size,
        output_size=output_size,
        chunk_size=chunk_size,
        max_attempts=max_attempts,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    part = part_path(output_path)
    raw_bytes_downloaded, header_offset = load_resume_state(output_path) if resume else (0, -1)

    target_raw_size = size
    if output_size is not None and header_offset >= 0:
        target_raw_size = max(target_raw_size, header_offset + output_size)
    download = download_msc_raw_chunks(
        host,
        output_path=output_path,
        part_path=part,
        port=port,
        timeout_seconds=timeout_seconds,
        raw_bytes_downloaded=raw_bytes_downloaded,
        header_offset=header_offset,
        target_raw_size=target_raw_size,
        output_size=output_size,
        keep_leading_padding=keep_leading_padding,
        stop_at_next_header=stop_at_next_header,
        chunk_size=chunk_size,
        max_attempts=max_attempts,
        recover_msc_raw=recover_msc_raw,
        progress=progress,
        read_range=read_range,
    )

    return _finalize_msc_raw_download(
        output_path=output_path,
        part_path=part,
        download=download,
        output_size=output_size,
        keep_leading_padding=keep_leading_padding,
        stop_at_next_header=stop_at_next_header,
        chunk_size=chunk_size,
    )


def _validate_msc_raw_download_options(
    *,
    size: int,
    output_size: int | None,
    chunk_size: int,
    max_attempts: int,
) -> None:
    if size < 0:
        raise ValueError("size must be non-negative")
    if output_size is not None and output_size < 0:
        raise ValueError("output_size must be non-negative")
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if max_attempts <= 0:
        raise ValueError("max_attempts must be positive")


def _finalize_msc_raw_download(
    *,
    output_path: Path,
    part_path: Path,
    download: MscRawDownloadProgress,
    output_size: int | None,
    keep_leading_padding: bool,
    stop_at_next_header: bool,
    chunk_size: int,
) -> dict[str, object]:
    output_state = materialize_msc_output(
        part_path.read_bytes(),
        header_offset=download.header_offset,
        next_header_offset=download.next_header_offset,
        target_raw_size=download.target_raw_size,
        output_size=output_size,
        keep_leading_padding=keep_leading_padding,
        stop_at_next_header=stop_at_next_header,
    )
    output_path.write_bytes(output_state.output_bytes)
    write_resume_state(output_path, download.raw_bytes_downloaded, output_state.header_offset)
    return msc_raw_download_result(
        output_path=output_path,
        part_path=part_path,
        raw_bytes_downloaded=download.raw_bytes_downloaded,
        target_raw_size=output_state.target_raw_size,
        header_offset=output_state.header_offset,
        next_header_offset=output_state.next_header_offset,
        output_bytes=output_state.output_bytes,
        chunk_size=chunk_size,
        chunks_completed=download.chunks_completed,
        retries=download.retries,
        progress_events=download.progress_events,
    )
