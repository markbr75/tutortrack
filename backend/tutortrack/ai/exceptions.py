"""AI errors, mapped to RFC 7807 problems by the core exception handler.

Provider (SDK) failures are translated in ``providers.anthropic`` so callers never see
``anthropic.*`` exceptions.
"""

from __future__ import annotations

from typing import Any

from tutortrack.core.exceptions import DomainError


class AICreditsExhausted(DomainError):
    status_code = 402
    problem_type = "ai-credits-exhausted"
    title = "No AI credits left this month"


class AIRateLimited(DomainError):
    """Too many AI requests from this user (ours) or from TutorTrack (the provider's)."""

    status_code = 429
    problem_type = "ai-rate-limited"
    title = "Too many AI requests; try again shortly"

    def __init__(self, detail: str | None = None, *, retry_after: int = 30) -> None:
        super().__init__(detail, extra={"retry_after": retry_after})


class AIUnavailable(DomainError):
    status_code = 503
    problem_type = "ai-unavailable"
    title = "The AI service is unavailable; try again shortly"


class AIProviderError(DomainError):
    status_code = 502
    problem_type = "ai-provider-error"
    title = "The AI service rejected the request"


class AIRefused(DomainError):
    status_code = 422
    problem_type = "ai-refused"
    title = "The AI declined this request"

    def __init__(self, detail: str | None = None, *, category: str | None = None) -> None:
        extra: dict[str, Any] = {"category": category} if category else {}
        super().__init__(detail, extra=extra)


class AIIncomplete(DomainError):
    status_code = 422
    problem_type = "ai-incomplete"
    title = "The AI response was incomplete; try a shorter request"
