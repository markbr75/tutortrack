"""Gap G3 (E09): "max free cancellations per term" on E20 terms (FR-09-3) and report
attachments as real uploads (FR-09-4)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.db import transaction

from tutortrack.core.context import tenant_context
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.models import StoredFile
from tutortrack.core.storage.services import can_access
from tutortrack.core.time import now
from tutortrack.courses.tests.factories import TermFactory
from tutortrack.delivery import policies, services
from tutortrack.delivery.tests.test_delivery import (  # noqa: F401 - fixtures
    future,
    people,
    staff,
    tutor_api,
)
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.people.models import Contact

pytestmark = pytest.mark.django_db


# --- max free cancellations per term (FR-09-3) --------------------------------------------------


def test_term_limit_rule_is_validated():
    assert policies.clean_rules({"max_free_per_term": 2})["max_free_per_term"] == 2
    assert policies.clean_rules({})["max_free_per_term"] is None
    with pytest.raises(BusinessRuleViolation):
        policies.clean_rules({"max_free_per_term": -1})


def test_free_cancellations_are_limited_per_term(org, staff, people):  # noqa: F811
    with tenant_context(org):
        TermFactory(
            organisation=org,
            start_date=now().date(),
            end_date=now().date() + timedelta(days=60),
        )
        services.save_policy(
            name="House rules",
            scope_type="organisation",
            rules={"max_free_per_term": 1, "free_window_hours": 24},
        )
    first = future(org, people, hours=72)
    second = future(org, people, hours=24 * 20)  # same term, possibly another month
    one = staff.post(
        f"/api/v1/lessons/{first.pk}/cancel", {"cancelled_by": "client"}, format="json"
    ).json()
    assert one["outcome"]["kind"] == "free"
    two = staff.post(
        f"/api/v1/lessons/{second.pk}/cancel?preview=1", {"cancelled_by": "client"}, format="json"
    ).json()
    assert two["outcome"]["kind"] == "late"  # the term's free cancellation is used up


def test_lessons_outside_terms_ignore_the_term_limit(org, staff, people):  # noqa: F811
    with tenant_context(org):
        services.save_policy(
            name="House rules",
            scope_type="organisation",
            rules={"max_free_per_term": 0, "free_window_hours": 24},
        )
    lesson = future(org, people, hours=72)  # no terms set up: the holidays
    out = staff.post(
        f"/api/v1/lessons/{lesson.pk}/cancel?preview=1", {"cancelled_by": "client"}, format="json"
    ).json()
    assert out["outcome"]["kind"] == "free"


def test_policy_api_round_trips_the_term_limit(org, staff):  # noqa: F811
    created = staff.post(
        "/api/v1/cancellation-policies",
        {"name": "Termly", "scope_type": "organisation", "rules": {"max_free_per_term": 3}},
        format="json",
    )
    assert created.status_code == 201, created.content
    assert created.json()["rules"]["max_free_per_term"] == 3


# --- report attachments (FR-09-4) ---------------------------------------------------------------


def stored(org, user, name="worksheet.pdf"):
    with tenant_context(org):
        return StoredFile.objects.create(
            filename=name,
            content_type="application/pdf",
            size_bytes=1200,
            storage_key=f"org/{org.pk}/test/{name}-{now().timestamp()}",
            status=StoredFile.Status.UPLOADED,
            scan_status=StoredFile.ScanStatus.CLEAN,
            uploaded_by=user,
        )


def attachment_template(org):
    with tenant_context(org):
        return services.create_template(
            name="With files",
            is_default=True,
            fields=[
                {
                    "key": "covered",
                    "label": "Covered",
                    "type": "rich_text",
                    "required": True,
                    "visibility": "student",
                },
                {
                    "key": "files",
                    "label": "Worksheets",
                    "type": "attachment",
                    "visibility": "client",
                },
                {
                    "key": "notes",
                    "label": "Staff files",
                    "type": "attachment",
                    "visibility": "staff",
                },
            ],
        )


def test_attachments_are_uploaded_files_and_families_can_open_shared_ones(org, tutor_api, people):  # noqa: F811
    attachment_template(org)
    lesson = future(org, people, hours=-2)
    report = tutor_api.post(f"/api/v1/lessons/{lesson.pk}/reports", {}, format="json").json()
    url = f"/api/v1/lesson-reports/{report['id']}"
    named = tutor_api.put(url, {"answers": {"files": ["worksheet.pdf"]}}, format="json")
    assert named.status_code == 422  # names alone aren't attachments any more
    someone_else = stored(org, MembershipFactory(organisation=org, role="tutor").user)
    theirs = tutor_api.put(url, {"answers": {"files": [str(someone_else.pk)]}}, format="json")
    assert theirs.status_code == 422
    sheet = stored(org, people["tutor_user"])
    private = stored(org, people["tutor_user"], name="private.pdf")
    saved = tutor_api.put(
        url, {"answers": {"files": [str(sheet.pk)], "notes": [str(private.pk)]}}, format="json"
    )
    assert saved.status_code == 200, saved.content
    with tenant_context(org):
        sheet.refresh_from_db()
        assert sheet.owner_object_id == report["id"]
    done = tutor_api.post(
        f"{url}/submit", {"answers": {**saved.json()["answers"], "covered": "x"}}, format="json"
    )
    assert done.status_code == 200, done.content
    parent = MembershipFactory(organisation=org, role="client")
    with tenant_context(org), transaction.atomic():
        Contact.objects.create(
            client=people["client"],
            first_name="Priya",
            last_name="Patel",
            user=parent.user,
            email="priya@example.com",
        )
        sheet.refresh_from_db()
        private.refresh_from_db()

        assert can_access(parent.user, sheet) is True
        assert can_access(parent.user, private) is False  # staff-only field
        stranger = MembershipFactory(organisation=org, role="client").user
        assert can_access(stranger, sheet) is False
