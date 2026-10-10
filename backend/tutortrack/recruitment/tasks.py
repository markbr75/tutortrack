"""Nightly compliance check (FR-18-6 AC): expire overdue records and restrict tutors."""

from __future__ import annotations

from celery import shared_task

from tutortrack.core.tasks import TenantTask, fan_out_per_org


@shared_task(base=TenantTask, name="tutortrack.recruitment.tasks.compliance_sweep")
def compliance_sweep(*, organisation_id: str) -> int:
    from . import compliance

    return compliance.sweep()


@shared_task(name="tutortrack.recruitment.tasks.compliance_sweep_all")
def compliance_sweep_all() -> int:
    return fan_out_per_org(compliance_sweep)
