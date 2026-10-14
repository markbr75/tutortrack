"""Gap G3 (FR-07-6): "jobs needing attention" adds no upcoming lessons, low prepaid balance
or package units, and overdue lesson reports, each with its reason in the list."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.db import transaction

from tutortrack.billing.tests.test_billing import (  # noqa: F401 - fixtures
    complete,
    family,
    lesson,
    make_job,
    set_settings,
)
from tutortrack.billing.tests.test_phase2 import sold, template
from tutortrack.core.context import tenant_context
from tutortrack.core.time import now
from tutortrack.delivery import services as delivery
from tutortrack.delivery.models import LessonReport
from tutortrack.jobs import selectors
from tutortrack.jobs.models import Job
from tutortrack.scheduling import services as scheduling

pytestmark = pytest.mark.django_db


def reasons(org, job):
    with tenant_context(org):
        found = selectors.with_attention(Job.objects.filter(pk=job.pk)).get()
        return selectors.attention_reasons(found)


def future_lesson(org, family, job):  # noqa: F811
    start = (now() + timedelta(days=3)).replace(minute=0, second=0, microsecond=0)
    with tenant_context(org):
        scheduling.create_lesson(
            start=start,
            end=start + timedelta(minutes=60),
            service=family["service"],
            job=job,
            attendees=[{"student": family["students"][0]}],
            tutors=[{"tutor": family["tutor"]}],
            timezone="Europe/London",
            override_conflicts=True,
        )


def test_active_job_without_upcoming_lessons(org, family):  # noqa: F811
    job = make_job(org, family, "pay_as_you_go")
    assert reasons(org, job) == ["no_upcoming_lessons"]
    future_lesson(org, family, job)
    assert reasons(org, job) == []


def test_low_prepaid_balance_and_package_units(org, family):  # noqa: F811
    set_settings(org, "billing", {"billing.topup_threshold": 20})
    prepaid = make_job(org, family, "prepaid_credit")
    future_lesson(org, family, prepaid)
    assert "low_balance" in reasons(org, prepaid)
    package = make_job(org, family, "package")
    future_lesson(org, family, package)
    assert "low_balance" in reasons(org, package)
    sold(org, family, template(org, quantity="10"))
    assert "low_balance" not in reasons(org, package)


def test_overdue_reports(org, family):  # noqa: F811
    job = make_job(org, family, "pay_as_you_go")
    future_lesson(org, family, job)
    done = lesson(org, family, job=job, hours_ago=30)
    complete(org, done)
    with tenant_context(org), transaction.atomic():
        report = delivery.open_report(done, family["tutor"])
        LessonReport.objects.filter(pk=report.pk).update(due_at=now() - timedelta(hours=1))
    assert reasons(org, job) == ["overdue_reports"]


def test_list_filters_and_shows_reasons(org, family, admin_api):  # noqa: F811
    quiet = make_job(org, family, "pay_as_you_go")
    busy = make_job(org, family, "pay_as_you_go")
    future_lesson(org, family, busy)
    listed = admin_api.get("/api/v1/jobs", {"attention": "true"}).json()["results"]
    assert [(r["id"], r["attention_reasons"]) for r in listed] == [
        (str(quiet.pk), ["no_upcoming_lessons"])
    ]
    by_reason = admin_api.get("/api/v1/jobs", {"attention_reason": "overdue_reports"}).json()
    assert by_reason["results"] == []
    both = admin_api.get("/api/v1/jobs", {"attention": "true", "attention_reason": "open_offer"})
    assert both.status_code == 200
    plain = admin_api.get("/api/v1/jobs").json()["results"]
    assert all(r["attention_reasons"] == [] for r in plain)
