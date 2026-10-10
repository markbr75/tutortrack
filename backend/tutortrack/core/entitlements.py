"""Plan entitlements (E04 FR-04-2): boolean features and numeric limits.

Any app can enforce them without depending on the subscriptions app, which registers the
resolver at start-up (until then everything is allowed)::

    from tutortrack.core import entitlements

    entitlements.require("payroll")                       # feature
    entitlements.require_capacity("max_tutors", used=3)   # limit, adding one more

Both raise ``UpgradeRequired`` (403 ``upgrade-required``, with ``required_plan``).
"""

from __future__ import annotations

import functools
import uuid
from collections.abc import Callable
from typing import Any, Protocol, TypeVar

from django.utils.translation import gettext as _

from .context import current_organisation_id
from .exceptions import UpgradeRequired

F = TypeVar("F", bound=Callable[..., Any])


class Resolver(Protocol):
    def has(self, key: str, organisation_id: uuid.UUID | None) -> bool: ...

    def limit(self, key: str, organisation_id: uuid.UUID | None) -> int | None:
        """None means unlimited."""
        ...

    def required_plan(self, key: str, needed: int | None = None) -> str | None: ...


class _AllowAll:
    def has(self, key: str, organisation_id: uuid.UUID | None) -> bool:
        return True

    def limit(self, key: str, organisation_id: uuid.UUID | None) -> int | None:
        return None

    def required_plan(self, key: str, needed: int | None = None) -> str | None:
        return None


_resolver: Resolver = _AllowAll()


def set_resolver(resolver: Resolver) -> None:
    global _resolver
    _resolver = resolver


def has(key: str, organisation_id: uuid.UUID | None = None) -> bool:
    return _resolver.has(key, organisation_id or current_organisation_id())


def limit(key: str, organisation_id: uuid.UUID | None = None) -> int | None:
    return _resolver.limit(key, organisation_id or current_organisation_id())


def require(key: str) -> None:
    if not has(key):
        raise UpgradeRequired(
            _("Your plan doesn't include this feature."),
            extra={"feature": key, "required_plan": _resolver.required_plan(key)},
        )


def require_capacity(key: str, *, used: int, adding: int = 1, unit: int = 1) -> None:
    """Raise if ``used + adding`` would exceed the plan's limit ``key`` (limits counted in
    ``unit``s, e.g. bytes per GB for ``storage_gb``)."""
    allowed = limit(key)
    if allowed is None or used + adding <= allowed * unit:
        return
    raise UpgradeRequired(
        _("Your plan allows %(allowed)s. Upgrade to add more.") % {"allowed": allowed},
        extra={
            "limit": key,
            "allowed": allowed,
            "used": used // unit,
            "required_plan": _resolver.required_plan(key, -(-(used + adding) // unit)),
        },
    )


def requires_entitlement(key: str) -> Callable[[F], F]:
    """Decorate a service function or DRF view method with a feature check."""

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            require(key)
            return func(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator
