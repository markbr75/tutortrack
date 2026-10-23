"""Readable audit records (follow-up to "The Register" redesign): action, record type and
record labels on the audit API, and ``__str__`` for the models audit entries name."""

from __future__ import annotations

import ast
import pathlib
from datetime import date, time
from decimal import Decimal

import pytest
from django.apps import apps
from django.db import models

from tutortrack.core import audit, audit_labels
from tutortrack.core.context import tenant_context
from tutortrack.core.models import AuditEntry
from tutortrack.core.testing import client_for
from tutortrack.identity.tests.factories import MembershipFactory

from .factories import WidgetFactory

SERIES_ID = "01a13c73-be4e-728d-8dab-387399f8d864"

# Models whose audit entries showed Django's "X object (id)" before they had a ``__str__``.
NAMED_MODELS = [
    "billing.charge",
    "billing.creditnote",
    "courses.enrolment",
    "delivery.lessonreport",
    "delivery.reporttemplate",
    "jobs.jobtutor",
    "learning.assessmentresult",
    "learning.loan",
    "matching.matchquery",
    "payments.payment",
    "payments.provideraccount",
    "payments.refund",
    "scheduling.calendarevent",
    "scheduling.lessonseries",
    "success.setupchecklist",
    "success.setupchecklistitem",
]


@pytest.mark.parametrize("label", NAMED_MODELS)
def test_audited_models_have_their_own_str(label):
    assert apps.get_model(label).__str__ is not models.Model.__str__


def test_new_str_values_name_the_record_without_people():
    from tutortrack.billing.models import Charge
    from tutortrack.core.money import Money
    from tutortrack.payments.models import Payment, Refund
    from tutortrack.scheduling.models import LessonSeries
    from tutortrack.success.models import SetupChecklistItem

    charge = Charge(kind="lesson", date=date(2026, 10, 1), currency="GBP")
    charge.gross = Money(Decimal("40.00"), "GBP")
    assert str(charge) == "Lesson 2026-10-01 (40.00 GBP)"
    payment = Payment(method="card", currency="GBP")
    payment.amount = Money(Decimal("25.50"), "GBP")
    assert str(payment) == "Card 25.50 GBP"
    refund = Refund(currency="GBP")
    refund.amount = Money(Decimal("5.00"), "GBP")
    assert str(refund) == "Refund 5.00 GBP"
    series = LessonSeries(start_date=date(2026, 10, 5), start_time=time(16, 0))
    assert str(series) == "Lesson series from 2026-10-05 at 16:00"
    assert str(SetupChecklistItem(key="student")) == "Setup step: Add a student"


def test_display_repr_falls_back_to_type_and_number_or_short_id():
    from tutortrack.billing.models import PaymentRequest
    from tutortrack.payments.models import PaymentAllocation

    request = PaymentRequest(number="PR-0012")
    assert audit_labels.display_repr(request) == "Payment request PR-0012"
    allocation = PaymentAllocation(id="01a160ab-b0c4-73c6-8d22-97b1f9ef6de1")
    assert audit_labels.display_repr(allocation) == "Payment allocation #ef6de1"


def test_display_repr_never_breaks_the_write():
    from tutortrack.scheduling.models import LessonSeries

    broken = LessonSeries(id=SERIES_ID)  # no start date yet: its __str__ raises
    assert audit_labels.display_repr(broken) == "Lesson series #f8d864"


def test_record_uses_the_readable_repr(tenant):
    from tutortrack.billing.models import PaymentRequest

    with tenant_context(tenant):
        entry = audit.record(PaymentRequest(number="PR-0007"), "issue")
    assert entry.object_repr == "Payment request PR-0007"


def test_labels():
    assert audit_labels.action_label("status_change") == "Status changed"
    assert audit_labels.action_label("brand_new_thing") == "Brand new thing"
    assert audit_labels.record_type_label("scheduling.lessonseries") == "Lesson series"
    assert audit_labels.record_type_label("gone.oldmodel") == "Oldmodel"
    legacy = f"LessonSeries object ({SERIES_ID})"
    assert audit_labels.record_label("scheduling.lessonseries", SERIES_ID, legacy) == (
        "Lesson series #f8d864"
    )
    assert audit_labels.record_label("scheduling.lessonseries", SERIES_ID, "") == (
        "Lesson series #f8d864"
    )
    assert audit_labels.record_label("people.client", "1", "Patel family") == "Patel family"


def test_api_returns_labels_and_keeps_raw_fields(org):
    owner = MembershipFactory(organisation=org, role="owner").user
    widget = WidgetFactory(organisation=org, name="Maths lesson")
    with tenant_context(org):
        audit.record(widget, "status_change")
        AuditEntry.objects.create(
            organisation_id=org.pk,
            action="create",
            object_type="scheduling.lessonseries",
            object_id=SERIES_ID,
            object_repr=f"LessonSeries object ({SERIES_ID})",
        )
    rows = client_for(org, owner).get("/api/v1/audit").json()["results"]
    by_type = {row["object_type"]: row for row in rows}
    latest, legacy = by_type["testapp.widget"], by_type["scheduling.lessonseries"]
    assert latest["action"] == "status_change"
    assert latest["action_label"] == "Status changed"
    assert latest["record_label"] == "Maths lesson"
    assert latest["record_type_label"] == "Widget"
    assert legacy["object_repr"] == f"LessonSeries object ({SERIES_ID})"
    assert legacy["record_label"] == "Lesson series #f8d864"
    assert legacy["record_type_label"] == "Lesson series"
    assert legacy["action_label"] == "Created"


def _written_action_codes() -> dict[str, str]:
    """Constant action codes passed to ``audit.record``/``audit.track`` in app code
    (both branches of ``"a" if x else "b"`` too)."""
    root = pathlib.Path(audit.__file__).resolve().parents[1]
    codes: dict[str, str] = {}
    for path in root.rglob("*.py"):
        if "tests" in path.parts or "migrations" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in ("record", "track") or "audit" not in ast.unparse(
                node.func.value
            ):
                continue
            arg = node.args[1] if len(node.args) >= 2 else None
            for kw in node.keywords:
                if kw.arg == "action":
                    arg = kw.value
            values = [arg.body, arg.orelse] if isinstance(arg, ast.IfExp) else [arg]
            for value in values:
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    codes.setdefault(value.value, f"{path.relative_to(root)}:{node.lineno}")
    return codes


def test_every_written_action_has_a_label():
    codes = _written_action_codes()
    assert len(codes) > 100  # the scan found the services
    missing = {
        code: where for code, where in codes.items() if code not in audit_labels.ACTION_LABELS
    }
    assert not missing, f"Add these to core/audit_labels.py ACTION_LABELS: {missing}"
