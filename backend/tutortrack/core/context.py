"""Request and tenant context carried in ``contextvars``.

Works for both sync and async code and is set by middleware (web requests) or by
``TenantTask`` (Celery). Never store tenant state in globals or thread-locals.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from typing import Any

from .exceptions import NoTenantContext

_current_organisation_id: ContextVar[uuid.UUID | None] = ContextVar(
    "current_organisation_id", default=None
)


# Branches the current user may see; None = all branches (FR-02-2 branch scoping).
_current_branch_ids: ContextVar[frozenset[uuid.UUID] | None] = ContextVar(
    "current_branch_ids", default=None
)


@dataclass(frozen=True)
class RequestContext:
    request_id: str | None = None
    ip: str | None = None
    user_agent: str | None = None
    user_id: uuid.UUID | None = None
    impersonator_id: uuid.UUID | None = None
    # Set inside Temporal activities: the workflow acting (E32 FR-32-3).
    workflow_id: str | None = None


_request_context: ContextVar[RequestContext] = ContextVar(
    "request_context",
    default=RequestContext(),  # noqa: B039 - frozen dataclass is immutable
)


# --- tenant -------------------------------------------------------------------------------------


def _as_uuid(value: Any) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    if hasattr(value, "pk"):  # an Organisation instance
        return _as_uuid(value.pk)
    return uuid.UUID(str(value))


def current_organisation_id() -> uuid.UUID | None:
    return _current_organisation_id.get()


def require_organisation_id() -> uuid.UUID:
    org_id = _current_organisation_id.get()
    if org_id is None:
        raise NoTenantContext(
            "Tenant-scoped data was accessed without an organisation in context. "
            "Use `tenant_context(org)` or the `all_tenants` manager (platform code only)."
        )
    return org_id


@contextmanager
def tenant_context(organisation: Any) -> Iterator[uuid.UUID]:
    """Run a block of code as ``organisation`` (an Organisation, UUID or UUID string)."""
    org_id = _as_uuid(organisation)
    token = _current_organisation_id.set(org_id)
    try:
        yield org_id
    finally:
        _current_organisation_id.reset(token)


def set_organisation(organisation: Any | None) -> Any:
    """Low-level setter for middleware; returns a token for ``reset_organisation``."""
    return _current_organisation_id.set(None if organisation is None else _as_uuid(organisation))


def reset_organisation(token: Any) -> None:
    _current_organisation_id.reset(token)


# --- branch scope -------------------------------------------------------------------------------


def current_branch_ids() -> frozenset[uuid.UUID] | None:
    """Branch ids the current user is restricted to, or None for unrestricted."""
    return _current_branch_ids.get()


def set_branch_ids(branch_ids: Any) -> Any:
    value = None if branch_ids is None else frozenset(_as_uuid(b) for b in branch_ids)
    return _current_branch_ids.set(value)


def reset_branch_ids(token: Any) -> None:
    _current_branch_ids.reset(token)


@contextmanager
def branch_scope(branch_ids: Any) -> Iterator[frozenset[uuid.UUID] | None]:
    """Restrict branch-scoped queries to ``branch_ids`` (None lifts the restriction)."""
    token = set_branch_ids(branch_ids)
    try:
        yield _current_branch_ids.get()
    finally:
        _current_branch_ids.reset(token)


# --- request ------------------------------------------------------------------------------------


def get_request_context() -> RequestContext:
    return _request_context.get()


def set_request_context(ctx: RequestContext) -> Any:
    return _request_context.set(ctx)


def reset_request_context(token: Any) -> None:
    _request_context.reset(token)


def update_request_context(**changes: Any) -> None:
    _request_context.set(replace(_request_context.get(), **changes))


@contextmanager
def request_context(**values: Any) -> Iterator[RequestContext]:
    """Temporarily set request context values (useful in tests, scripts and tasks)."""
    token = _request_context.set(replace(_request_context.get(), **values))
    try:
        yield _request_context.get()
    finally:
        _request_context.reset(token)
