"""Gap G3 (FR-26-2, FR-23-2): package sales as deferred revenue, released to sales as
units are used (GL postings, summary journals and the individual-mode daily journal), and
discount lines posting like their lesson line."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from tutortrack.accounting import builders, journals, mappings
from tutortrack.accounting.models import AccountMapping
from tutortrack.billing.models import Invoice
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

pytestmark = pytest.mark.django_db
CODES = {
    "revenue": "4000",
    "deferred_revenue": "2300",
    "receivable": "1100",
    "sales_tax": "2200",
    "rounding": "9999",
}


def export_maps(org):
    with tenant_context(org):
        for kind, code in CODES.items():
            AccountMapping.objects.create(
                provider="export", kind=kind, key="default", external_id=code, code=code
            )
        AccountMapping.objects.create(
            provider="export", kind="revenue", key="package", external_id="4100", code="4100"
        )
        from tutortrack.accounting.models import TaxMapping

        TaxMapping.objects.create(provider="export", tax_rate=None, external_id="T9")
        return mappings.Mappings("export")


def totals(rows):
    out: dict[str, Decimal] = {}
    for r in rows:
        out[r.account.code] = out.get(r.account.code, Decimal(0)) + r.debit - r.credit
    return out


def test_package_sale_is_deferred_then_released_as_units_are_used(org, family):  # noqa: F811
    maps = export_maps(org)
    set_settings(org, "accounting", {"accounting.package_deferred_revenue": True})
    job = make_job(org, family, "package")
    sold(org, family, template(org, quantity="4", price="160.00"))
    complete(org, lesson(org, family, job=job, minutes=60))
    today = now().date()
    with tenant_context(org):
        rows = journals.sales_postings(
            maps, today - timedelta(days=1), today + timedelta(days=1), org.timezone
        )
        assert "deferred_revenue" in mappings.required_kinds(None)
    balance = totals(rows)
    # Sale: Cr deferred 160; one hour used: Dr deferred 40 / Cr package revenue 40.
    assert balance["2300"] == Decimal("-120.00")
    assert balance["4100"] == Decimal("-40.00")
    assert "4000" not in balance  # the sale never touched ordinary revenue
    assert sum(r.debit for r in rows) == sum(r.credit for r in rows)


def test_without_the_setting_package_sales_are_revenue(org, family):  # noqa: F811
    maps = export_maps(org)
    sold(org, family, template(org, quantity="4", price="160.00"))
    today = now().date()
    with tenant_context(org):
        rows = journals.sales_postings(maps, today, today, org.timezone)
        assert journals.package_postings(maps, today, today, org.timezone) == []
        assert "deferred_revenue" not in mappings.required_kinds(None)
    assert totals(rows)["4000"] == Decimal("-160.00")


def test_individual_mode_daily_package_journal(org, family):  # noqa: F811
    export_maps(org)
    set_settings(org, "accounting", {"accounting.package_deferred_revenue": True})
    job = make_job(org, family, "package")
    sold(org, family, template(org, quantity="4", price="160.00"))
    complete(org, lesson(org, family, job=job, minutes=60))
    from tutortrack.accounting.models import AccountingConnection

    with tenant_context(org):
        conn = AccountingConnection(provider="export", mode="individual")
        ctx = builders.Context(conn, mappings.Mappings("export"))
        built = builders.BUILDERS["package_revenue"](
            ctx, now().astimezone(ctx.tz).date().isoformat()
        )
    lines = {line.account_code: line for line in built.doc.lines}
    assert set(lines) == {"2300", "4100"}
    assert "package_revenue" in builders.OBJECT_TYPES


def test_discount_lines_post_to_their_lesson_lines_account(org, family):  # noqa: F811
    from tutortrack.billing import services
    from tutortrack.catalogue.models import DiscountRule
    from tutortrack.catalogue.tests.factories import DiscountRuleFactory
    from tutortrack.tenancy import settings_service

    with tenant_context(org):
        settings_service.update_settings("pricing", {"pricing.discount_display": "separate"})
        DiscountRuleFactory(
            organisation=org,
            kind=DiscountRule.Kind.CLIENT,
            client=family["client"],
            percent=Decimal("10"),
        )
    complete(org, lesson(org, family))
    with tenant_context(org):
        invoice = services.create_draft(family["client"])
        discount = invoice.lines.get(kind="discount")
        assert builders.line_charge(discount) == invoice.lines.get(kind="line").charge
        assert Invoice.objects.count() == 1
