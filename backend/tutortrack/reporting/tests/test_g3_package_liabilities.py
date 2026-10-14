"""Gap G3 (FR-26-2): the "package liabilities" finance report."""

from __future__ import annotations

import pytest

from tutortrack.billing.tests.test_billing import (  # noqa: F401 - fixtures
    complete,
    family,
    finance,
    lesson,
    make_job,
)
from tutortrack.billing.tests.test_phase2 import sold, template

pytestmark = pytest.mark.django_db


def test_package_liabilities_report(org, family, finance):  # noqa: F811
    job = make_job(org, family, "package")
    sold(org, family, template(org, quantity="4", price="160.00", name="4 hours"))
    complete(org, lesson(org, family, job=job, minutes=60))
    response = finance.get(
        "/api/v1/reporting/reports/package_liabilities", {"period": "this_month"}
    )
    assert response.status_code == 200, response.content
    body = response.json()
    [row] = body["rows"]
    assert (row["package"], row["units_remaining"], row["liability"]) == ("4 hours", "3", "120.00")
    assert body["totals"] == [{"currency": "GBP", "liability": "120.00"}]
    assert {c["key"] for c in body["columns"]} >= {"client", "liability", "units_remaining"}


def test_package_liabilities_need_finance_access(org, family):  # noqa: F811
    from tutortrack.core.testing import client_for
    from tutortrack.identity.tests.factories import MembershipFactory

    coordinator = client_for(org, MembershipFactory(organisation=org, role="coordinator").user)
    response = coordinator.get("/api/v1/reporting/reports/package_liabilities")
    assert response.status_code == 403
