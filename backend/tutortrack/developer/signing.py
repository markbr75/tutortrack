"""Webhook signatures (FR-27-3).

``Webhook-Signature: t=<unix seconds>,v1=<hex HMAC-SHA256(secret, "<t>." + body)>``.
While a rotated secret overlaps, a second ``v1=`` is appended for the previous secret, so
receivers that accept any matching ``v1`` keep working. Receivers must reject timestamps
more than five minutes away from their clock (replay window).
"""

from __future__ import annotations

import hashlib
import hmac
import time

TOLERANCE_SECONDS = 300


def compute(secret: str, timestamp: int, body: bytes) -> str:
    message = f"{timestamp}.".encode() + body
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def header(secrets: list[str], timestamp: int, body: bytes) -> str:
    parts = [f"t={timestamp}"] + [f"v1={compute(s, timestamp, body)}" for s in secrets if s]
    return ",".join(parts)


def verify(
    secret: str, signature_header: str, body: bytes, *, now: int | None = None,
    tolerance: int = TOLERANCE_SECONDS,
) -> bool:  # fmt: skip
    """The documented receiver algorithm (also used by our tests and docs samples)."""
    timestamp: int | None = None
    candidates: list[str] = []
    for part in signature_header.split(","):
        key, _sep, value = part.strip().partition("=")
        if key == "t" and value.isdigit():
            timestamp = int(value)
        elif key == "v1":
            candidates.append(value)
    if timestamp is None or not candidates:
        return False
    current = int(time.time()) if now is None else now
    if abs(current - timestamp) > tolerance:
        return False
    expected = compute(secret, timestamp, body)
    return any(hmac.compare_digest(expected, c) for c in candidates)
