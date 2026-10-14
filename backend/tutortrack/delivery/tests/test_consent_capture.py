"""G6 (FR-29-3): "don't ask me again" on the lesson-feedback page is an E29 withdrawal."""

from __future__ import annotations

import pytest

from tutortrack.core.context import tenant_context
from tutortrack.core.testing import client_for
from tutortrack.delivery import feedback
from tutortrack.delivery.models import LessonFeedback
from tutortrack.privacy.models import ConsentRecord

from .test_feedback import (  # noqa: F401 - fixtures
    completed_lesson,
    enabled,
    make_request,
    people,
    send,
)

pytestmark = pytest.mark.django_db


def test_dont_ask_again_withdraws_the_feedback_consent(
    org,
    people,  # noqa: F811
    enabled,  # noqa: F811
    django_capture_on_commit_callbacks,
):
    item, token = make_request(org, people, django_capture_on_commit_callbacks)
    response = client_for(org).post(
        f"/api/v1/public/lesson-feedback/{token}",
        {"rating": 4, "stop_asking": True},
        format="json",
    )
    assert response.status_code == 200, response.content
    with tenant_context(org):
        record = ConsentRecord.objects.select_related("consent_type").get()
        assert record.consent_type.key == "lesson-feedback"
        assert (record.granted, record.method, record.source) == (
            False,
            "form",
            f"lesson-feedback:{item.pk}",
        )
        assert feedback._opted_out(item.contact)
    # The next completed lesson asks nobody.
    lesson = completed_lesson(org, people, days_ago=0)
    send(org, lesson, django_capture_on_commit_callbacks)
    with tenant_context(org):
        assert LessonFeedback.objects.get(lesson=lesson).skip_reason == "no_consent"


def test_answering_without_the_tick_records_nothing(
    org,
    people,  # noqa: F811
    enabled,  # noqa: F811
    django_capture_on_commit_callbacks,
):
    _item, token = make_request(org, people, django_capture_on_commit_callbacks)
    response = client_for(org).post(
        f"/api/v1/public/lesson-feedback/{token}", {"rating": 5}, format="json"
    )
    assert response.status_code == 200
    with tenant_context(org):
        assert not ConsentRecord.objects.exists()
