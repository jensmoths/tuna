from __future__ import annotations

import dataclasses
import time

from .bridge_transport import BridgeTransport


@dataclasses.dataclass(frozen=True)
class CliWriteResult:
    success: bool
    transcript: str


def _read_until_quiet(transport, *, timeout_seconds: float, quiet_seconds: float = 0.2) -> bytes:
    deadline = time.time() + timeout_seconds
    quiet_deadline = time.time() + quiet_seconds
    chunks: list[bytes] = []
    while time.time() < deadline:
        data = transport.recv(4096)
        if data:
            chunks.append(data)
            quiet_deadline = time.time() + quiet_seconds
        elif time.time() >= quiet_deadline:
            break
        else:
            time.sleep(0.02)
    return b"".join(chunks)


def write_betaflight_cli_text(transport, cli_text: str, *, timeout_seconds: float = 5.0) -> CliWriteResult:
    """Write Betaflight CLI text over an already-connected raw Bridge transport.

    The caller owns safety checks and FC identity verification before invoking this.
    This function only performs the low-level CLI session and returns a transcript.
    """
    commands = [line.strip() for line in cli_text.splitlines() if line.strip()]
    if not commands:
        raise ValueError("Betaflight CLI text must contain at least one command")
    if commands[-1].lower() != "save":
        commands.append("save")

    transcript = bytearray()
    transport.send(b"#\r")
    transcript.extend(_read_until_quiet(transport, timeout_seconds=timeout_seconds))

    for command in commands:
        transport.send(command.encode("ascii") + b"\r")
        transcript.extend(_read_until_quiet(transport, timeout_seconds=timeout_seconds))

    text = transcript.decode("latin1", errors="replace")
    failed = any(marker in text.lower() for marker in ("###error", "invalid name", "parse error", "unknown command"))
    return CliWriteResult(success=not failed, transcript=text)


def write_betaflight_cli_text_to_bridge(host: str, port: int, cli_text: str, *, timeout_seconds: float = 5.0) -> CliWriteResult:
    with BridgeTransport(host, port, timeout_seconds=timeout_seconds) as transport:
        return write_betaflight_cli_text(transport, cli_text, timeout_seconds=timeout_seconds)
