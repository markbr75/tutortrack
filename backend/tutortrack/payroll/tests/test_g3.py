"""Gap G3 (E12): editing items in the pay-run review (FR-12-5), the annual earnings summary
(FR-12-9) and re-authentication before full bank details (E12 §6)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from tutortrack.core.context import tenant_context
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.money import Money
from tutortrack.core.testing import client_for
from tutortrack.core.time import now
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.payroll import earnings, services
from tutortrack.payroll.models import PayItem, PayRun
from tutortrack.payroll.tests.test_payroll import completed, items, make_run, world  # noqa: F401

pytestmark = pytest.mark.django_db


def gbp(amount: str) -> Money:
    return Money(Decimal(amount), "GBP")


# --- edit items in the pay-run review (FR-12-5) ------------------------------------------------


def test_editing_an_amount_adds_a_linked_correction(org, world):  # noqa: F811
    completed(org, world)
    run = make_run(org)
    [item] = items(org, kind="lesson")
    with tenant_context(org):
        with pytest.raises(BusinessRuleViolation):
            services.edit_item(run, item, amount=gbp("30.00"))  # needs a reason
        services.edit_item(run, item, amount=gbp("30.00"), reason="Longer lesson")
        services.edit_item(run, item, amount=gbp("28.00"), reason="Agreed rate")
        run.refresh_from_db()
        item.refresh_from_db()
        fixes = list(item.corrections.order_by("created_at"))
        assert services.effective_amount(item) == gbp("28.00")
    assert item.amount == gbp("25.00")  # the original item never changes
    assert [(f.kind, f.amount, f.status) for f in fixes] == [
        ("adjustment", gbp("5.00"), "in_pay_run"),
        ("adjustment", gbp("-2.00"), "in_pay_run"),
    ]
    assert run.totals == {"GBP": "28.00"}


def test_only_manual_items_can_be_renamed(org, world):  # noqa: F811
    completed(org, world)
    with tenant_context(org):
        bonus = services.create_manual_item(
            tutor=world["tutor"],
            kind="bonus",
            description="Bonus",
            amount=gbp("10.00"),
            day=now().date(),
        )
    run = make_run(org)
    [lesson_item] = items(org, kind="lesson")
    with tenant_context(org):
        bonus.refresh_from_db()
        services.edit_item(run, bonus, description="Exam season bonus")
        bonus.refresh_from_db()
        assert bonus.description == "Exam season bonus"
        with pytest.raises(BusinessRuleViolation):
            services.edit_item(run, lesson_item, description="Renamed")


def test_edit_item_api_and_locked_runs(org, world):  # noqa: F811
    completed(org, world)
    run = make_run(org)
    [item] = items(org, kind="lesson")
    finance = client_for(org, world["finance"])
    url = f"/api/v1/pay-runs/{run.pk}/edit-item"
    done = finance.post(
        url,
        {"item": str(item.pk), "amount": {"amount": "20.00", "currency": "GBP"}, "reason": "Short"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="edit-1",
    )
    assert done.status_code == 200, done.content
    assert done.json()["totals"] == {"GBP": "20.00"}
    run_items = finance.get("/api/v1/pay-items", {"pay_run": str(run.pk)}).json()["results"]
    assert any(i["adjusts"] == str(item.pk) for i in run_items)
    with tenant_context(org):
        services.approve(run, user=world["finance"])
    locked = finance.post(
        url,
        {"item": str(item.pk), "amount": {"amount": "25.00", "currency": "GBP"}, "reason": "x"},
        format="json",
    )
    assert locked.status_code == 422
    tutor = client_for(org, world["tutor_user"])
    assert tutor.post(url, {"item": str(item.pk)}, format="json").status_code in (403, 404)


# --- annual earnings summary (FR-12-9) -----------------------------------------------------------


def paid_run(org, world):  # noqa: F811
    with tenant_context(org):
        services.update_profile(world["tutor"], method="manual")
    run = make_run(org)
    with tenant_context(org):
        services.approve(run, user=world["finance"])
        services.mark_paid(run, reference="Bank")
        services.finalise(run.pk)
    return run


def test_annual_summary_counts_what_was_paid_in_the_year(org, world):  # noqa: F811
    completed(org, world)
    completed(org, world, hours_ago=6)
    with tenant_context(org):
        services.create_manual_item(
            tutor=world["tutor"],
            kind="bonus",
            description="Bonus",
            amount=gbp("10.00"),
            day=now().date(),
        )
    paid_run(org, world)
    completed(org, world, hours_ago=9)  # not paid yet: not in the summary
    year = now().year
    with tenant_context(org):
        calendar = earnings.summary(world["tutor"], year, "calendar")
    [gbp_row] = calendar.currencies
    assert gbp_row.earnings == gbp("60.00")
    assert gbp_row.reimbursements == gbp("0.00")
    assert {k["kind"]: k["amount"] for k in gbp_row.by_kind} == {
        "bonus": gbp("10.00"),
        "lesson": gbp("50.00"),
    }
    assert sum((m["amount"] for m in gbp_row.by_month), gbp("0.00")) == gbp("60.00")
    assert gbp_row.payouts == 1
    with tenant_context(org):
        last_year = earnings.summary(world["tutor"], year - 1, "calendar")
    assert last_year.currencies == []


def test_uk_tax_year_basis():
    from datetime import date

    assert earnings.period(2026, "tax_year") == (date(2026, 4, 6), date(2027, 4, 5))
    assert earnings.period(2026, "calendar") == (date(2026, 1, 1), date(2026, 12, 31))


def test_tutors_get_their_summary_and_pdf(org, world):  # noqa: F811
    completed(org, world)
    paid_run(org, world)
    tutor = client_for(org, world["tutor_user"])
    today = now()
    year = (
        today.year if today.month > 4 or (today.month == 4 and today.day >= 6) else today.year - 1
    )
    data = tutor.get("/api/v1/me/earnings/annual", {"year": year}).json()
    assert data["basis"] == "tax_year"  # a UK organisation
    assert data["currencies"][0]["earnings"] == {"amount": "25.00", "currency": "GBP"}
    pdf = tutor.get("/api/v1/me/earnings/annual", {"year": year, "pdf": "true"})
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF")
    staff = client_for(org, world["finance"]).get(
        f"/api/v1/tutors/{world['tutor'].pk}/earnings/annual",
        {"year": today.year, "basis": "calendar"},
    )
    assert staff.status_code == 200
    assert staff.json()["basis"] == "calendar"
    other = MembershipFactory(organisation=org, role="tutor")
    from tutortrack.people.tests.factories import TutorProfileFactory

    TutorProfileFactory(organisation=org, membership=other)
    nosy = client_for(org, other.user).get(f"/api/v1/tutors/{world['tutor'].pk}/earnings/annual")
    assert nosy.status_code in (403, 404)
    bad = tutor.get("/api/v1/me/earnings/annual", {"year": "1999"})
    assert bad.status_code == 422


def test_unpaid_runs_dont_count(org, world):  # noqa: F811
    completed(org, world)
    make_run(org)
    with tenant_context(org):
        assert earnings.summary(world["tutor"], now().year, "calendar").currencies == []
        assert PayRun.objects.count() == 1
        assert PayItem.objects.filter(status="in_pay_run").exists()


def test_reauth_window_expires(org, world, monkeypatch):  # noqa: F811
    from tutortrack.identity import reauth
    from tutortrack.identity.tests.factories import TEST_PASSWORD

    finance = client_for(org, world["finance"])
    assert finance.get("/api/v1/auth/reauthenticate").json() == {
        "recent": False,
        "methods": ["password"],
    }
    assert finance.post(
        "/api/v1/auth/reauthenticate", {"password": TEST_PASSWORD}, format="json"
    ).json()["recent"]
    path = f"/api/v1/tutors/{world['tutor'].pk}/pay-profile"
    assert finance.get(path, {"full": "true"}).status_code == 200
    later = now() + reauth.REAUTH_MAX_AGE + timedelta(seconds=5)
    monkeypatch.setattr(reauth, "now", lambda: later)
    assert finance.get(path, {"full": "true"}).status_code == 403
    assert finance.get(path).status_code == 200  # masked details need nothing extra
