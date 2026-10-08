"""Domain exceptions. The API exception handler maps these to RFC 7807 problem responses."""

from __future__ import annotations

from typing import Any


class DomainError(Exception):
    """Base class for errors raised by services that should reach API clients."""

    status_code = 400
    problem_type = "about:blank"
    title = "Bad request"

    def __init__(self, detail: str | None = None, *, extra: dict[str, Any] | None = None):
        self.detail = detail or self.title
        self.extra = extra or {}
        super().__init__(self.detail)


class BusinessRuleViolation(DomainError):
    status_code = 422
    problem_type = "business-rule-violation"
    title = "Business rule violated"


class PermissionDenied(DomainError):
    status_code = 403
    problem_type = "permission-denied"
    title = "You do not have permission to perform this action"


class NotFound(DomainError):
    status_code = 404
    problem_type = "not-found"
    title = "Not found"


class Conflict(DomainError):
    status_code = 409
    problem_type = "conflict"
    title = "Conflict"


class NoTenantContext(DomainError):
    """Raised when tenant-scoped data is accessed without an organisation in context."""

    status_code = 400
    problem_type = "no-tenant-context"
    title = "No organisation selected"


class CrossTenantWrite(DomainError):
    status_code = 403
    problem_type = "cross-tenant-write"
    title = "Object belongs to a different organisation"


class CrossBranchWrite(DomainError):
    status_code = 403
    problem_type = "cross-branch-write"
    title = "You do not have access to this branch"


class FeatureDisabled(DomainError):
    status_code = 403
    problem_type = "feature-disabled"
    title = "This feature is not enabled for your organisation"

    def __init__(self, feature: str):
        super().__init__(f"Feature '{feature}' is not enabled.", extra={"feature": feature})
