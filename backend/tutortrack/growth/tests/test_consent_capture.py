"""G6 (FR-29-3): agreeing on the review page to publish a review is E29 evidence.

Referral links land on the website's enquiry form, so a referred family's consent is
captured by that form (see ``leads/tests/test_consent_capture.py``)."""

from __future__ import annotations

import pytest

from tutortrack.core.context import tenant_context
from tutortrack.core.testing import client_for
from tutortrack.growth import services
from tutortrack.privacy.models import ConsentRecord

from .test_growth import ask, world  # noqa: F401 - the world fixture

pytestmark = pytest.mark.django_db


def post_review(org, world, publish_consent):  # noqa: F811
    request = ask(org, world, contact=world["family"]["contact"])
    with tenant_context(org):
        token = services.review_token(request)
    body = {
        "rating": 4,
        "text": "Good",
        "reviewer_name": "Priya",
        "publish_consent": publish_consent,
    }
    response = client_for(org).post(f"/api/v1/public/review/{token}", body, format="json")
    assert response.status_code == 201, response.content
    return request


def test_review_publication_consent_is_recorded(org, world):  # noqa: F811
    request = post_review(org, world, True)
    with tenant_context(org):
        record = ConsentRecord.objects.select_related("consent_type").get()
        assert record.consent_type.key == "review-publication"
        assert (record.subject_type, record.subject_id) == (
            "people.contact",
            str(request.contact_id),
        )
        assert (record.method, record.source, record.granted) == (
            "form",
            f"review:{request.pk}",
            True,
        )
        assert record.given_by_name == "Priya"


def test_no_consent_no_record(org, world):  # noqa: F811
    post_review(org, world, False)
    with tenant_context(org):
        assert not ConsentRecord.objects.exists()
