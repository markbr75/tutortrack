"""G6 (FR-27-1): reviews and form submissions in the public API, with scoped API keys."""

from __future__ import annotations

import pytest

from tutortrack.core.context import tenant_context
from tutortrack.core.testing import TenantIsolationTestMixin
from tutortrack.growth.tests.factories import ReviewFactory
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.leads.models import Form, FormSubmission

from .conftest import bearer, make_key

pytestmark = pytest.mark.django_db


def submission(org, *, spam=False, **data):
    with tenant_context(org):
        form, _ = Form.objects.get_or_create(
            slug="enquire", defaults={"name": "Enquire", "schema": {"steps": []}}
        )
        return FormSubmission.objects.create(
            form=form,
            data=data or {"first_name": "Priya"},
            ip="203.0.113.9",
            user_agent="Browser",
            spam=spam,
        )


def test_reviews_need_the_reviews_scope(org, other_org, user, member):
    mine = ReviewFactory(organisation=org)
    theirs = ReviewFactory(organisation=other_org)
    _key, token = make_key(org, user, ["reviews:read"])
    response = bearer(token).get("/api/v1/reviews")
    assert response.status_code == 200, response.content
    ids = {row["id"] for row in response.json()["results"]}
    assert ids == {str(mine.pk)}
    assert str(theirs.pk) not in ids
    _key, other = make_key(org, user, ["clients:read"])
    denied = bearer(other).get("/api/v1/reviews")
    assert denied.status_code == 403
    assert denied.json()["required_scope"] == "reviews:read"


def test_form_submissions_are_listed_without_ip_or_browser(org, user, member):
    kept = submission(org, first_name="Priya")
    submission(org, spam=True)
    _key, token = make_key(org, user, ["enquiries:read"])
    response = bearer(token).get("/api/v1/form-submissions")
    assert response.status_code == 200, response.content
    rows = response.json()["results"]
    assert [r["id"] for r in rows] == [str(kept.pk)]
    assert rows[0]["answers"] == {"first_name": "Priya"}
    assert rows[0]["form_name"] == "Enquire"
    assert "ip" not in rows[0]
    assert "user_agent" not in rows[0]
    spam = bearer(token).get("/api/v1/form-submissions", {"spam": "true"}).json()["results"]
    assert len(spam) == 1


def test_form_submissions_are_read_only(org, user, member):
    _key, token = make_key(org, user, ["enquiries:write"])
    response = bearer(token).post("/api/v1/form-submissions", {}, format="json")
    assert response.status_code in (403, 405)


def test_staff_who_see_some_enquiries_see_only_their_submissions(org):
    from tutortrack.core.testing import client_for

    tutor = MembershipFactory(organisation=org, role="tutor").user
    submission(org)
    response = client_for(org, tutor).get("/api/v1/form-submissions")
    assert response.status_code in (200, 403)
    if response.status_code == 200:
        assert response.json()["results"] == []


class TestFormSubmissionIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/form-submissions"

    def make_object(self, organisation):
        return submission(organisation)


class TestPublicReviewIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/reviews"

    def make_object(self, organisation):
        return ReviewFactory(organisation=organisation)
