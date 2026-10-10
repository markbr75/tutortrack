"""Short, stateless calendar pushes on the ``integrations`` Celery queue (task names are
under ``tutortrack.integrations.`` for routing). Provider failures retry with backoff;
the connection's workflow also re-pushes anything missed when it starts a new run."""

from __future__ import annotations

from typing import Any

from celery import shared_task

from tutortrack.core.tasks import TenantTask

MAX_RETRIES = 5


@shared_task(
    base=TenantTask,
    bind=True,
    max_retries=MAX_RETRIES,
    name="tutortrack.integrations.calendar.sync_lesson",
)
def sync_lesson(self: Any, *, organisation_id: str, lesson_id: str) -> dict[str, int]:
    from . import services

    counts = services.sync_lesson(lesson_id)
    if counts["failed"] and not self.request.is_eager:
        raise self.retry(countdown=60 * 2**self.request.retries)
    return counts


@shared_task(base=TenantTask, name="tutortrack.integrations.calendar.sync_lessons")
def sync_lessons(*, organisation_id: str, lesson_ids: list[str]) -> int:
    for lesson_id in lesson_ids:
        sync_lesson.delay(organisation_id=organisation_id, lesson_id=lesson_id)
    return len(lesson_ids)


@shared_task(base=TenantTask, name="tutortrack.integrations.calendar.backfill")
def backfill(*, organisation_id: str, connection_id: str) -> int:
    from tutortrack.integrations.models import IntegrationConnection

    from . import services

    connection = IntegrationConnection.objects.filter(pk=connection_id).first()
    return services.backfill(connection) if connection is not None else 0


@shared_task(base=TenantTask, name="tutortrack.integrations.calendar.delete_events")
def delete_events(*, organisation_id: str, items: list[dict[str, str]]) -> int:
    """External events of deleted lessons (the links went with the lesson)."""
    from tutortrack.integrations import providers
    from tutortrack.integrations import services as integrations
    from tutortrack.integrations.models import IntegrationConnection
    from tutortrack.integrations.providers import NotFound, ProviderError

    done = 0
    for item in items:
        connection = IntegrationConnection.objects.filter(pk=item["connection_id"]).first()
        if connection is None or connection.status not in ("active", "error"):
            continue
        try:
            providers.calendar_client(connection.provider).delete_event(
                integrations.credentials(connection), item["calendar_id"], item["external_id"]
            )
            done += 1
        except NotFound:
            done += 1
        except ProviderError as exc:
            integrations.record_failure(connection, exc)
    return done


@shared_task(base=TenantTask, name="tutortrack.integrations.meetings.delete")
def delete_meeting(
    *, organisation_id: str, provider: str, connection_id: str | None, external_id: str
) -> bool:
    from tutortrack.integrations import providers
    from tutortrack.integrations import services as integrations
    from tutortrack.integrations.models import IntegrationConnection
    from tutortrack.integrations.providers import Credentials, NotFound, ProviderError

    connection = (
        IntegrationConnection.objects.filter(pk=connection_id).first() if connection_id else None
    )
    try:
        creds = integrations.credentials(connection) if connection else Credentials()
        providers.meeting_client(provider).delete_meeting(creds, external_id)
    except NotFound:
        return True
    except ProviderError:
        return False
    return True
