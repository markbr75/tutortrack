"""Sending messages (E13-T05) and the G4 digests. Lesson reminders are the "Lesson reminders"
built-in workflow (E33 T05)."""

from __future__ import annotations

from celery import shared_task

from tutortrack.core.tasks import TenantTask, fan_out_per_org


@shared_task(
    base=TenantTask,
    name="tutortrack.comms.tasks.send_message",
    autoretry_for=(ConnectionError, TimeoutError),
    retry_backoff=True,
    max_retries=5,
)
def send_message(*, organisation_id: str, message_id: str) -> str:
    from . import services
    from .models import Message

    message = Message.objects.filter(pk=message_id).first()
    if message is None:
        return "missing"
    return str(services.send_now(message).status)


@shared_task(base=TenantTask, name="tutortrack.comms.tasks.send_scheduled_comms")
def send_scheduled_comms(*, organisation_id: str) -> dict[str, int]:
    """G4: every 15 minutes, the digests due now (each person's local time). Dedupe keys
    make repeats harmless. Card-expiry notices and monthly statements belong to payments
    and billing (G3)."""
    from tutortrack.core.time import now

    from . import digests

    return dict(digests.run(now()))


@shared_task(name="tutortrack.comms.tasks.send_all_scheduled_comms", ignore_result=True)
def send_all_scheduled_comms() -> int:
    return fan_out_per_org(send_scheduled_comms)


@shared_task(
    base=TenantTask,
    name="tutortrack.comms.tasks.sync_marketing_contact",
    autoretry_for=(ConnectionError, TimeoutError),
    retry_backoff=True,
    max_retries=5,
)
def sync_marketing_contact(*, organisation_id: str, contact_id: str) -> int:
    """E13-T12: one contact into the connected Mailchimp/Brevo audiences."""
    from tutortrack.integrations.providers import ProviderError

    from . import marketing

    try:
        return marketing.sync_contact(contact_id)
    except ProviderError as exc:
        raise ConnectionError(str(exc)) from exc  # retried with backoff
