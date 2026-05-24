from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class BlackboxDecodeError(RuntimeError):
    pass


def decode_blackbox_log(source_path: str | Path, output_csv: str | Path, *, decoder_command: str = "blackbox_decode") -> Path:
    decoder = shutil.which(decoder_command)
    if decoder is None:
        raise BlackboxDecodeError(f"{decoder_command!r} not found on PATH")

    source = Path(source_path)
    output = Path(output_csv)
    output.parent.mkdir(parents=True, exist_ok=True)
    before = set(output.parent.glob(f"{source.stem}*.csv"))
    completed = subprocess.run(
        [decoder, "--output-dir", str(output.parent), str(source)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise BlackboxDecodeError(completed.stderr.strip() or completed.stdout.strip() or "blackbox_decode failed")

    produced = sorted(set(output.parent.glob(f"{source.stem}*.csv")) - before)
    if not produced:
        produced = sorted(output.parent.glob(f"{source.stem}*.csv"))
    if not produced:
        raise BlackboxDecodeError(f"blackbox_decode did not create a CSV in: {output.parent}")

    first = produced[0]
    if first != output:
        if output.exists():
            output.unlink()
        first.rename(output)
    return output
