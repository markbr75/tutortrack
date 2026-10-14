"""Celery tasks (thin, short): sub-processor change notices, fanned out per organisation.
Run ``notify_subprocessor_changes`` after a deploy that changes ``SUBPROCESSORS_VERSION``
(``manage.py notify_subprocessor_changes``)."""

from __future__ import annotations

from celery import shared_task

from tutortrack.core.tasks import TenantTask, fan_out_per_org


@shared_task(
    base=TenantTask,
    name="tutortrack.privacy.tasks.notify_subprocessor_change",
    ignore_result=True,
)
def notify_subprocessor_change(*, organisation_id: str) -> bool:
    from .compliance import notify_subprocessor_change as notify

    return notify()


@shared_task(name="tutortrack.privacy.tasks.notify_subprocessor_changes", ignore_result=True)
def notify_subprocessor_changes() -> int:
    return fan_out_per_org(notify_subprocessor_change)
