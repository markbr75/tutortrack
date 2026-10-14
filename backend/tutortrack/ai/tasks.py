"""Short, stateless AI jobs (Celery, ADR 0029): classifying a new inbox message."""

from __future__ import annotations

from celery import shared_task

from tutortrack.core.tasks import TenantTask


@shared_task(
    base=TenantTask,
    name="tutortrack.ai.tasks.classify_thread",
    autoretry_for=(ConnectionError, TimeoutError),
    retry_backoff=True,
    max_retries=3,
)
def classify_thread(*, organisation_id: str, thread_id: str) -> str:
    from tutortrack.core.exceptions import DomainError

    from .features import inbox

    try:
        return inbox.auto_classify(thread_id)
    except DomainError as exc:  # credits, refusal, provider down: the inbox works without it
        return exc.problem_type
