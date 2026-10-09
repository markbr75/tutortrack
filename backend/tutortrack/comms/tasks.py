"""Sending messages and lesson reminders (E13-T05/T06)."""

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


@shared_task(base=TenantTask, name="tutortrack.comms.tasks.send_lesson_reminders")
def send_lesson_reminders(*, organisation_id: str) -> int:
    """Every 5 minutes: lessons whose reminder (per offset) fell due in the last hour.
    Dedupe keys make repeats harmless; lessons booked after a reminder's moment skip it."""
    from tutortrack.core.time import now
    from tutortrack.scheduling.models import Lesson

    from . import catalogue, services

    setting = services.effective("lesson_reminder")
    if not setting.enabled:
        return 0
    sent = 0
    moment = now()
    for minutes in setting.timing:
        start, end = catalogue.reminder_window(moment, minutes)
        lessons = Lesson.objects.filter(
            status=Lesson.Status.PLANNED, start__gt=start, start__lte=end
        ).values_list("pk", flat=True)
        for pk in lessons:
            lesson = catalogue.load_lesson(str(pk))
            if lesson is not None:
                sent += len(services.notify("lesson_reminder", lesson, key=f"{pk}:{minutes}"))
    return sent


@shared_task(name="tutortrack.comms.tasks.send_all_lesson_reminders", ignore_result=True)
def send_all_lesson_reminders() -> int:
    return fan_out_per_org(send_lesson_reminders)
