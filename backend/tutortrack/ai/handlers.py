"""AI reactions to domain events (idempotent: re-classifying gives the same insight)."""

from __future__ import annotations

from django.db import transaction

from tutortrack.core.events import EventEnvelope, subscribe


@subscribe("message.received")
def classify_new_message(event: EventEnvelope) -> None:
    """FR-31-3: classify inbound messages by intent when the organisation turned it on.
    The model call runs in a Celery task, never in the outbox dispatcher."""
    if event.data.get("flagged") or event.data.get("author_type") in ("user", "system"):
        return
    from tutortrack.tenancy.settings_service import get_setting

    from .selectors import is_enabled

    if not get_setting("ai.inbox_auto_classify") or not is_enabled("inbox"):
        return
    from .tasks import classify_thread

    organisation_id = str(event.organisation_id)
    thread_id = str(event.data["thread_id"])
    transaction.on_commit(
        lambda: classify_thread.delay(organisation_id=organisation_id, thread_id=thread_id)
    )
