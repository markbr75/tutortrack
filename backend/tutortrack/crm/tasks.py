"""Bulk actions run in the background with progress (FR-05-12)."""

from __future__ import annotations

from typing import Any

from celery import shared_task

from tutortrack.core.tasks import TenantTask


def _run_one(entity_type: str, action: str, target_id: str, params: dict[str, Any]) -> None:
    from tutortrack.people import services as people
    from tutortrack.people.models import Client, Student, TutorProfile

    from . import services
    from .models import Tag

    if action in {"tag", "untag"}:
        tag = Tag.objects.get(pk=params["tag"])
        services.apply_tag(tag, entity_type, [target_id], remove=action == "untag")
        return
    if entity_type == "people.client":
        client = Client.objects.get(pk=target_id)
        if action == "archive":
            people.archive_client(client)
        elif action == "set_status":
            people.update_client(client, status=params["status"])
        elif action == "assign_manager":
            people.update_client(client, account_manager_id=params["account_manager"])
        return
    if entity_type == "people.student":
        student = Student.objects.get(pk=target_id)
        status = Student.Status.ARCHIVED if action == "archive" else params["status"]
        people.change_student_status(student, status)
        return
    if entity_type == "people.tutor" and action == "set_status":
        people.change_tutor_status(TutorProfile.objects.get(pk=target_id), params["status"])
        return
    raise ValueError(f"Unsupported action {action} for {entity_type}")


@shared_task(base=TenantTask, name="tutortrack.crm.tasks.run_bulk_job", ignore_result=True)
def run_bulk_job(*, job_id: str, organisation_id: str) -> None:
    from django.db import transaction

    from tutortrack.core.context import request_context
    from tutortrack.core.exceptions import DomainError
    from tutortrack.core.time import now

    from .models import BulkJob

    job = BulkJob.objects.get(pk=job_id)
    BulkJob.objects.filter(pk=job.pk).update(status=BulkJob.Status.RUNNING)
    errors: dict[str, str] = {}
    succeeded = 0
    with request_context(user_id=job.requested_by_id):  # audit as the person who asked
        for index, target_id in enumerate(job.target_ids, start=1):
            try:
                with transaction.atomic():
                    _run_one(job.entity_type, job.action, target_id, job.params)
                succeeded += 1
            except (DomainError, ValueError, KeyError, LookupError) as exc:
                errors[target_id] = str(getattr(exc, "detail", exc))[:300]
            if index % 25 == 0:
                BulkJob.objects.filter(pk=job.pk).update(processed=index, succeeded=succeeded)
    BulkJob.objects.filter(pk=job.pk).update(
        status=BulkJob.Status.COMPLETED,
        processed=len(job.target_ids),
        succeeded=succeeded,
        errors=errors,
        finished_at=now(),
    )
