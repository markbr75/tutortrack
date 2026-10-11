"""Our own per-company request budget (FR-23-3: rate limit compliance, Xero 60/min).

A fixed one-minute window counted in the shared cache. Going over raises
``RateLimited`` with the seconds left in the window; the sync activity hands that to
Temporal as the next retry delay instead of hammering the provider into a 429."""

from __future__ import annotations

import time

from django.core.cache import cache

from tutortrack.integrations.providers import RateLimited


def acquire(account_id: str, per_minute: int, *, cost: int = 1) -> None:
    window = int(time.time() // 60)
    key = f"accounting:rate:{account_id}:{window}"
    cache.add(key, 0, 90)
    try:
        used = cache.incr(key, cost)
    except ValueError:  # expired between add and incr
        cache.set(key, cost, 90)
        used = cost
    if used > per_minute:
        raise RateLimited("Rate limit reached for this company.", 60 - time.time() % 60 + 1)
