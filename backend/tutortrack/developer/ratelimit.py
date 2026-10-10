"""Per-token rate limits (FR-27-2): a per-minute budget (default 600) and a per-second burst
(default 100), counted in the shared cache (Redis in production) with fixed windows.

Responses carry ``X-RateLimit-Limit``, ``X-RateLimit-Remaining`` and ``X-RateLimit-Reset``
(Unix seconds); a refused request gets 429 with ``Retry-After``.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

from django.conf import settings
from django.core.cache import cache

DEFAULT_PER_MINUTE = 600
DEFAULT_BURST_PER_SECOND = 100


@dataclass(frozen=True)
class Verdict:
    limit: int
    remaining: int
    reset: int
    retry_after: int = 0

    @property
    def exceeded(self) -> bool:
        return self.retry_after > 0

    def headers(self) -> dict[str, str]:
        out = {
            "X-RateLimit-Limit": str(self.limit),
            "X-RateLimit-Remaining": str(self.remaining),
            "X-RateLimit-Reset": str(self.reset),
        }
        if self.exceeded:
            out["Retry-After"] = str(self.retry_after)
        return out


def limits(per_minute_override: int | None = None) -> tuple[int, int]:
    config = getattr(settings, "DEVELOPER_API", {})
    per_minute = per_minute_override or int(config.get("RATE_LIMIT_PER_MINUTE", DEFAULT_PER_MINUTE))
    burst = int(config.get("BURST_PER_SECOND", DEFAULT_BURST_PER_SECOND))
    return per_minute, min(burst, per_minute)


def _incr(key: str, ttl: int) -> int:
    cache.add(key, 0, ttl)
    try:
        return int(cache.incr(key))
    except ValueError:  # expired between add and incr
        cache.set(key, 1, ttl)
        return 1


def hit(bucket: str, per_minute_override: int | None = None, *, at: float | None = None) -> Verdict:
    """Count one request for ``bucket`` (a token prefix) and say whether it may proceed."""
    moment = time.time() if at is None else at
    per_minute, burst = limits(per_minute_override)
    minute = int(moment // 60)
    second = int(moment)
    used_minute = _incr(f"rl:{bucket}:m:{minute}", 70)
    used_second = _incr(f"rl:{bucket}:s:{second}", 3)
    reset = (minute + 1) * 60
    remaining = max(per_minute - used_minute, 0)
    if used_minute > per_minute:
        return Verdict(per_minute, 0, reset, retry_after=max(math.ceil(reset - moment), 1))
    if used_second > burst:
        return Verdict(per_minute, remaining, reset, retry_after=1)
    return Verdict(per_minute, remaining, reset)
