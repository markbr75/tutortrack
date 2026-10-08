"""Feature flags. Resolution: unexpired org override > plan (E04) > global default.

from tutortrack.core.flags import is_enabled, requires_feature

if is_enabled("courses"): ...

@requires_feature("courses")
def create(self, request): ...
"""

from __future__ import annotations

import functools
import uuid
from collections.abc import Callable
from typing import Any, TypeVar

from django.core.cache import cache
from django.db.models import Q
from django.utils.module_loading import import_string

from .context import current_organisation_id
from .exceptions import FeatureDisabled
from .models import FeatureFlag, FeatureFlagOverride
from .time import now

CACHE_TTL_SECONDS = 60
_VERSION_KEY = "ff:version"

F = TypeVar("F", bound=Callable[..., Any])

# E04 replaces this with a resolver that returns the organisation's plan key.
PLAN_RESOLVER = "tutortrack.core.flags.no_plan"


def no_plan(organisation_id: uuid.UUID) -> str | None:
    return None


def _version() -> int:
    version = cache.get(_VERSION_KEY)
    if version is None:
        version = 1
        cache.set(_VERSION_KEY, version, None)
    return int(version)


def invalidate_cache() -> None:
    """Called on any flag/override change; bumping the version orphans all cached values."""
    try:
        cache.incr(_VERSION_KEY)
    except ValueError:
        cache.set(_VERSION_KEY, 2, None)


def _resolve(key: str, organisation_id: uuid.UUID | None) -> bool:
    flag = FeatureFlag.objects.filter(key=key).first()
    if flag is None:
        return False
    if organisation_id is not None:
        override = (
            FeatureFlagOverride.objects.filter(flag=flag, organisation_id=organisation_id)
            .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now()))
            .first()
        )
        if override is not None:
            return override.enabled
        plan_key = import_string(PLAN_RESOLVER)(organisation_id)
        if plan_key and plan_key in (flag.plan_keys or []):
            return True
    return flag.enabled_globally


def is_enabled(key: str, organisation_id: uuid.UUID | None = None) -> bool:
    org_id = organisation_id or current_organisation_id()
    cache_key = f"ff:{_version()}:{key}:{org_id or '-'}"
    cached = cache.get(cache_key)
    if cached is not None:
        return bool(cached)
    value = _resolve(key, org_id)
    cache.set(cache_key, value, CACHE_TTL_SECONDS)
    return value


def enabled_flags(organisation_id: uuid.UUID | None = None) -> dict[str, bool]:
    org_id = organisation_id or current_organisation_id()
    return {
        key: is_enabled(key, org_id) for key in FeatureFlag.objects.values_list("key", flat=True)
    }


def require(key: str) -> None:
    if not is_enabled(key):
        raise FeatureDisabled(key)


def requires_feature(key: str) -> Callable[[F], F]:
    """Decorate a function or DRF view method; raises ``FeatureDisabled`` when off."""

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            require(key)
            return func(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator


def set_override(
    key: str, organisation_id: uuid.UUID, *, enabled: bool, reason: str = ""
) -> FeatureFlagOverride | None:
    """Turn a flag on/off for one organisation (onboarding defaults, platform console).

    Unknown flags are ignored (returns None) so callers don't depend on seed data.
    """
    flag = FeatureFlag.objects.filter(key=key).first()
    if flag is None:
        return None
    override, _ = FeatureFlagOverride.objects.update_or_create(
        flag=flag,
        organisation_id=organisation_id,
        defaults={"enabled": enabled, "reason": reason[:255], "expires_at": None},
    )
    invalidate_cache()
    return override
