"""CRM event handlers: @mentions in a new note notify the mentioned staff (FR-05-7) through
E13. Each delivery is keyed by the event, so a redelivered event never notifies twice."""

from __future__ import annotations

from tutortrack.core.events import EventEnvelope, subscribe


@subscribe("note.created")
def notify_mentions(event: EventEnvelope) -> None:
    if not event.data.get("mentions"):
        return
    from tutortrack.comms.services import notify

    from .notifications import load_note

    note = load_note(event.subject["id"])
    if note is not None:
        notify("note_mention", note, key=str(event.id))
