"""Test helpers shared by every app.

``TenantIsolationTestMixin`` is mandatory for every list/detail endpoint (CLAUDE.md rule 1):

    class TestWidgetIsolation(TenantIsolationTestMixin):
        list_url = "/api/v1/widgets"

        def make_object(self, organisation):
            return WidgetFactory(organisation=organisation)

It asserts that a user acting in organisation A can neither list nor fetch organisation
B's records, and that guessed ids return 404 (never 403, which would leak existence).
"""

from __future__ import annotations

from typing import Any

import pytest
from django.db import models
from rest_framework.test import APIClient

from tutortrack.tenancy.models import Organisation


def client_for(organisation: Organisation, user: Any | None = None) -> APIClient:
    """API client whose requests resolve to ``organisation`` (via its subdomain)."""
    from django.conf import settings

    client = APIClient(HTTP_HOST=f"{organisation.slug}.{settings.TENANT_BASE_DOMAIN}")
    if user is not None:
        client.force_login(user)
    return client


def result_ids(response: Any) -> set[str]:
    data = response.json()
    rows = data["results"] if isinstance(data, dict) and "results" in data else data
    return {str(row["id"]) for row in rows}


@pytest.mark.django_db
class TenantIsolationTestMixin:
    list_url: str = ""

    def make_object(self, organisation: Organisation) -> models.Model:
        raise NotImplementedError

    def detail_url(self, obj: models.Model) -> str:
        return f"{self.list_url}/{obj.pk}"

    def acting_user(self, organisation: Organisation) -> Any:
        from tutortrack.identity.tests.factories import UserFactory

        return UserFactory(is_superuser=True)  # even superusers must not cross tenants

    def test_list_only_returns_own_organisation(
        self, org: Organisation, other_org: Organisation
    ) -> None:
        mine = self.make_object(org)
        theirs = self.make_object(other_org)
        response = client_for(org, self.acting_user(org)).get(self.list_url)
        assert response.status_code == 200, response.content
        ids = result_ids(response)
        assert str(mine.pk) in ids
        assert str(theirs.pk) not in ids

    def test_detail_of_other_organisation_is_404(
        self, org: Organisation, other_org: Organisation
    ) -> None:
        theirs = self.make_object(other_org)
        response = client_for(org, self.acting_user(org)).get(self.detail_url(theirs))
        assert response.status_code == 404, response.content
