"""Minimal clamd client using the INSTREAM command (no extra dependency)."""

from __future__ import annotations

import socket
import struct
from collections.abc import Iterable
from dataclasses import dataclass

CHUNK_SIZE = 64 * 1024


class ScanError(RuntimeError):
    pass


@dataclass(frozen=True)
class ScanResult:
    clean: bool
    signature: str | None = None


def scan_stream(
    chunks: Iterable[bytes], *, host: str, port: int, timeout: float = 60.0
) -> ScanResult:
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.sendall(b"zINSTREAM\0")
        for chunk in chunks:
            for offset in range(0, len(chunk), CHUNK_SIZE):
                part = chunk[offset : offset + CHUNK_SIZE]
                sock.sendall(struct.pack("!L", len(part)) + part)
        sock.sendall(struct.pack("!L", 0))
        response = b""
        while not response.endswith(b"\0"):
            data = sock.recv(4096)
            if not data:
                break
            response += data
    return parse_response(response.rstrip(b"\0").decode("utf-8", "replace"))


def parse_response(text: str) -> ScanResult:
    # "stream: OK" | "stream: Eicar-Test-Signature FOUND" | "INSTREAM size limit exceeded. ERROR"
    text = text.strip()
    if text.endswith("OK"):
        return ScanResult(clean=True)
    if text.endswith("FOUND"):
        signature = text.removeprefix("stream:").removesuffix("FOUND").strip()
        return ScanResult(clean=False, signature=signature)
    raise ScanError(text or "empty response from clamd")
