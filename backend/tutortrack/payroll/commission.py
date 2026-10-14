"""Commission-based pay (E12-T12, FR-12-10).

A tutor whose pay profile has ``pay_basis = commission`` earns ``commission_percent`` of
the client revenue *collected* for each of their lessons, instead of the rate snapshot.

* Collected revenue is the net (tax-exclusive) amount of the lesson's charges times the
  share of each charge's invoice that has been paid (``billing.selectors``), so a part
  payment earns part commission and a refund claws it back.
* The amount is rounded half-up to the currency's minor unit once, at line level
  (CLAUDE.md rule 5). Earlier items that are already in a pay run or paid are never
  changed: the difference becomes an adjustment item (``services._sync_link``).
* It needs "pay tutors only when the client has paid" (``payroll.pay_when_client_paid``),
  so commission is computed after payment allocation and the item is held until the
  invoice is settled.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from tutortrack.core.money import Money

HUNDRED = Decimal(100)


def paid_share(invoice_total: Decimal, amount_paid: Decimal) -> Decimal:
    """The fraction of an invoice that has been paid, between 0 and 1."""
    if invoice_total <= 0 or amount_paid <= 0:
        return Decimal(0)
    return min(amount_paid / invoice_total, Decimal(1))


def collected(lines: list[tuple[Decimal, Decimal, Decimal]]) -> Decimal:
    """Collected net revenue from ``[(charge net, invoice total, invoice paid)]``
    (unrounded: rounding happens once, on the commission)."""
    return sum((net * paid_share(total, paid) for net, total, paid in lines), Decimal(0))


def amount(collected_net: Decimal, percent: Decimal, currency: str) -> Money:
    """``percent`` of ``collected_net``, rounded half-up to the minor unit (never
    negative: a refund larger than what was collected can't make the tutor owe more than
    the commission they were paid)."""
    if collected_net <= 0 or percent <= 0:
        return Money.zero(currency)
    return Money(collected_net * percent / HUNDRED, currency).round_to_minor()  # half-up


def validate_percent(value: Any) -> Decimal:
    from django.utils.translation import gettext as _

    from tutortrack.core.exceptions import BusinessRuleViolation

    try:
        percent = Decimal(str(value))
    except ArithmeticError:
        percent = Decimal(-1)
    if not (Decimal(0) < percent <= HUNDRED):
        message = _("Enter a commission between 0 and 100%.")
        raise BusinessRuleViolation(message, extra={"errors": {"commission_percent": [message]}})
    return percent.quantize(Decimal("0.01"))


def lesson_commission(lesson_id: Any, percent: Decimal, currency: str) -> Money:
    """What a commission-paid tutor earns for a lesson so far (in ``currency``; charges in
    other currencies are ignored, as tutors are paid in one currency)."""
    from tutortrack.billing.selectors import lesson_collection_lines

    lines = [
        (net, total, paid)
        for net, total, paid, line_currency in lesson_collection_lines(lesson_id)
        if line_currency == currency
    ]
    return amount(collected(lines), percent, currency)


def resync(lesson_ids: list[Any]) -> int:
    """Re-work commission pay for lessons whose invoices were paid, part paid, refunded or
    voided (idempotent: unchanged amounts leave the items alone)."""
    from tutortrack.scheduling.models import LessonTutor

    from . import services
    from .models import PayBasis, TutorPayProfile

    tutors = TutorPayProfile.objects.filter(pay_basis=PayBasis.COMMISSION).values("tutor_id")
    lessons = (
        LessonTutor.objects.filter(lesson_id__in=list(lesson_ids), tutor_id__in=tutors)
        .values_list("lesson_id", flat=True)
        .distinct()
    )
    count = 0
    for lesson_id in lessons:
        services.sync_lesson_pay(lesson_id)
        count += 1
    return count
