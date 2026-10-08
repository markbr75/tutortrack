from functools import cache

import redis
from django.conf import settings


@cache
def get_redis() -> redis.Redis:
    """Shared Redis client for locks and counters (cache access goes via django.core.cache)."""
    return redis.Redis.from_url(settings.REDIS_URL)
