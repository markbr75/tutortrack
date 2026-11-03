"""Short jobs for pathways (E34 T02)."""

from __future__ import annotations

from celery import shared_task

from tutortrack.core.tasks import TenantTask


@shared_task(base=TenantTask, name="tutortrack.pathways.tasks.provision_call")
def provision_call(*, organisation_id: str, step_id: str) -> str:
    from . import services

    return services.provision_call(step_id)
