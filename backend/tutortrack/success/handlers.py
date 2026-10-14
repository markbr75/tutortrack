"""The setup checklist ticks itself from other apps' domain events (E30 FR-30-5).
Idempotent: a step is ticked once (unique per organisation and key)."""

from __future__ import annotations

from tutortrack.core.events import EventEnvelope, subscribe

from .models import SetupChecklistItem

Key = SetupChecklistItem.Key
STEPS = {
    "service.created": Key.SERVICE,
    "student.created": Key.STUDENT,
    "lesson.scheduled": Key.LESSON,
    "provider_account.connected": Key.PAYMENTS,
    "invoice.issued": Key.INVOICE,
    "invoice.sent": Key.INVOICE,
}


@subscribe(*STEPS, name="success.setup_checklist")
def tick_setup_step(event: EventEnvelope) -> None:
    from . import services

    services.complete_item(STEPS[event.type])
