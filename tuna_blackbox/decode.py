from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class BlackboxDecodeError(RuntimeError):
    pass


def _run_decoder(source: Path, output_dir: Path, decoder_command: str) -> list[Path]:
    decoder = shutil.which(decoder_command)
    if decoder is None:
        raise BlackboxDecodeError(f"{decoder_command!r} not found on PATH")

    output_dir.mkdir(parents=True, exist_ok=True)
    before = set(output_dir.glob(f"{source.stem}*.csv"))
    completed = subprocess.run(
        [decoder, "--output-dir", str(output_dir), str(source)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise BlackboxDecodeError(completed.stderr.strip() or completed.stdout.strip() or "blackbox_decode failed")

    produced = sorted(set(output_dir.glob(f"{source.stem}*.csv")) - before)
    if not produced:
        produced = sorted(output_dir.glob(f"{source.stem}*.csv"))
    if not produced:
        raise BlackboxDecodeError(f"blackbox_decode did not create a CSV in: {output_dir}")
    return produced


def decode_blackbox_recordings(source_path: str | Path, output_dir: str | Path, *, decoder_command: str = "blackbox_decode") -> list[Path]:
    """Decode all internal Blackbox Log CSVs produced by blackbox_decode."""
    return _run_decoder(Path(source_path), Path(output_dir), decoder_command)


def decode_blackbox_log(source_path: str | Path, output_csv: str | Path, *, decoder_command: str = "blackbox_decode") -> Path:
    source = Path(source_path)
    output = Path(output_csv)
    produced = _run_decoder(source, output.parent, decoder_command)

    selected = max(produced, key=lambda path: path.stat().st_size)
    if selected != output:
        if output.exists():
            output.unlink()
        selected.rename(output)
    return output
