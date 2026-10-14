"""Notification types added by gap batch G4 (FR-13-2): card expiring, monthly statement,
low attendance, expense approved or rejected, booking declined and package running low.

Kept in one block so the concurrent billing/payments batch can see them. Event-driven
types are sent by the handlers at the bottom (keyed on the event, so redelivery never
sends twice); card expiry and statements are daily/monthly checks run by the 15-minute
comms task (``run_daily``), keyed on the card's expiry month and the statement month.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _l

from tutortrack.core.events import EventEnvelope, subscribe
from tutortrack.tenancy.settings_service import get_setting

from .catalogue import (
    SAMPLE_ALERT,
    SAMPLE_BASE,
    _billing_deliveries,
    contact_recipient,
    load_client,
    organisation,
    tenant_link,
    tutor_recipient,
)
from .defaults import DEFAULTS, SIGN
from .registry import Delivery, NotificationType, register

DAILY_CHECK_HOUR = 9  # organisation time
TUTOR_EXPENSES = "/portal/tutor/expenses"


def _none(pk: str) -> Any:
    return None


# --- card expiring (billing) ----------------------------------------------------------------------


def load_payment_method(pk: str) -> Any:
    from tutortrack.payments.models import PaymentMethod

    return PaymentMethod.objects.select_related("client").filter(pk=pk).first()


def _card_expiring(method: Any) -> list[Delivery]:
    card = {
        "brand": method.brand or _("Card"),
        "last4": method.last4,
        "expiry": f"{method.exp_month:02d}/{method.exp_year}",
        "link": tenant_link("/portal/billing"),
    }
    return _billing_deliveries(method.client, {"card": card})


# --- monthly statement (billing) ------------------------------------------------------------------


def _statement_period(today: date) -> tuple[date, date]:
    end = today.replace(day=1) - timedelta(days=1)
    return end.replace(day=1), end


def _statement(client: Any) -> list[Delivery]:
    from tutortrack.billing import selectors as billing

    today = _org_today()
    start, end = _statement_period(today)
    data = billing.statement(client, client.currency, start, end, organisation()["timezone"])
    statement = {
        "start": start,
        "end": end,
        "opening": data.opening.round_to_minor().to_dict(),
        "closing": data.closing.round_to_minor().to_dict(),
        "link": tenant_link("/portal/billing"),
    }
    return _billing_deliveries(client, {"statement": statement})


def _statement_pdf(client: Any) -> list[tuple[str, bytes, str]]:
    from tutortrack.billing import pdf
    from tutortrack.billing import selectors as billing

    start, end = _statement_period(_org_today())
    data = billing.statement(client, client.currency, start, end, organisation()["timezone"])
    return [(f"statement-{end:%Y-%m}.pdf", pdf.statement_pdf(client, data), "application/pdf")]


# --- low attendance (delivery) --------------------------------------------------------------------


def _low_attendance(payload: Any) -> list[Delivery]:
    student, rate, lessons = payload
    base = {
        "organisation": organisation(),
        "attendance": {
            "student": student.full_name,
            "percent": rate,
            "lessons": lessons,
            "link": tenant_link(f"/students/{student.pk}"),
        },
        "alert": {
            "title": _("%(name)s attended %(p)s%% of their last %(n)s lessons")
            % {"name": student.full_name, "p": rate, "n": lessons},
            "body": "",
            "link": f"/students/{student.pk}",
        },
    }
    return [
        Delivery(r, {**base, "recipient": {"name": r.name, "first_name": r.first_name}})
        for r in _staff("people.student.view")
    ]


def _staff(codename: str) -> list[Any]:
    from .catalogue import staff_with

    return staff_with(codename)


# --- expenses (payroll) ---------------------------------------------------------------------------


def load_expense(pk: str) -> Any:
    from tutortrack.payroll.models import Expense

    return Expense.objects.select_related("tutor__membership__user").filter(pk=pk).first()


def _expense(expense: Any) -> list[Delivery]:
    r = tutor_recipient(expense.tutor)
    context = {
        "organisation": organisation(),
        "recipient": {"name": r.name, "first_name": r.first_name},
        "expense": {
            "description": expense.description,
            "date": expense.date,
            "amount": expense.amount.round_to_minor().to_dict() if expense.amount else None,
            "comment": expense.decision_comment,
            "link": tenant_link(TUTOR_EXPENSES),
        },
    }
    return [Delivery(r, context)]


# --- booking declined (scheduling) ----------------------------------------------------------------


def load_hold(pk: str) -> Any:
    from tutortrack.scheduling.models import BookingHold

    return BookingHold.objects.select_related("service", "tutor", "client").filter(pk=pk).first()


def _booking_declined(payload: Any) -> list[Delivery]:
    from .registry import Recipient

    hold, reason = payload
    booking = {
        "service": hold.service.name,
        "start": hold.start,
        "timezone": hold.timezone,
        "reason": reason,
        "link": tenant_link("/book"),
    }
    base = {"organisation": {**organisation(), "timezone": hold.timezone}, "booking": booking}
    recipients = []
    if hold.client_id:
        from .catalogue import client_contacts

        recipients = [contact_recipient(c) for c in client_contacts(hold.client)]
    elif (hold.contact or {}).get("email"):
        details = hold.contact
        first = str(details.get("first_name") or details.get("name") or "").strip()
        recipients = [
            Recipient(
                kind="booker",
                id=str(hold.pk),
                name=" ".join(p for p in (first, str(details.get("last_name") or "")) if p).strip(),
                first_name=first,
                email=str(details["email"]),
            )
        ]
    return [
        Delivery(r, {**base, "recipient": {"name": r.name, "first_name": r.first_name}})
        for r in recipients
    ]


# --- package low (billing) ------------------------------------------------------------------------


def load_package(pk: str) -> Any:
    from tutortrack.billing.models import PackagePurchase

    return PackagePurchase.objects.select_related("client").filter(pk=pk).first()


def _package_low(purchase: Any) -> list[Delivery]:
    package = {
        "name": purchase.name,
        "units_remaining": str(purchase.units_remaining.normalize()),
        "unit": purchase.quantity_type,
        "link": tenant_link("/portal/billing"),
    }
    return _billing_deliveries(purchase.client, {"package": package})


# --- registration ---------------------------------------------------------------------------------

MONEY = {"amount": "45.00", "currency": "GBP"}
G4_TYPES = (
    (
        "card_expiring",
        _l("Card about to expire"),
        "billing",
        "client",
        ("email",),
        ("email",),
        _card_expiring,
        load_payment_method,
        "payments.paymentmethod",
        ("card.brand", "card.last4", "card.expiry", "card.link"),
        {"card": {"brand": "Visa", "last4": "4242", "expiry": "11/2026", "link": "https://x"}},
        True,
        False,
    ),
    (
        "client_statement",
        _l("Monthly statement"),
        "billing",
        "client",
        ("email",),
        ("email",),
        _statement,
        load_client,
        "people.client",
        (
            "statement.start",
            "statement.end",
            "statement.opening",
            "statement.closing",
            "statement.link",
        ),
        {
            "statement": {
                "start": "2026-10-01",
                "end": "2026-10-31",
                "opening": MONEY,
                "closing": MONEY,
                "link": "https://x",
            }
        },
        False,
        True,
    ),
    (
        "low_attendance",
        _l("Low attendance alert"),
        "staff",
        "staff",
        ("in_app", "email"),
        ("in_app",),
        _low_attendance,
        _none,
        "",
        (
            "attendance.student",
            "attendance.percent",
            "attendance.lessons",
            "attendance.link",
            "alert.title",
        ),
        {
            **SAMPLE_ALERT,
            "attendance": {
                "student": "Arjun Patel",
                "percent": 50,
                "lessons": 6,
                "link": "https://x",
            },
        },
        True,
        False,
    ),
    (
        "expense_approved",
        _l("Expense approved"),
        "billing",
        "tutor",
        ("email", "in_app"),
        ("email", "in_app"),
        _expense,
        load_expense,
        "payroll.expense",
        ("expense.description", "expense.date", "expense.amount", "expense.link"),
        {
            "expense": {
                "description": "Train to lesson",
                "date": "2026-10-01",
                "amount": MONEY,
                "comment": "",
                "link": "https://x",
            }
        },
        True,
        False,
    ),
    (
        "expense_rejected",
        _l("Expense rejected"),
        "billing",
        "tutor",
        ("email", "in_app"),
        ("email", "in_app"),
        _expense,
        load_expense,
        "payroll.expense",
        (
            "expense.description",
            "expense.date",
            "expense.amount",
            "expense.comment",
            "expense.link",
        ),
        {
            "expense": {
                "description": "Train to lesson",
                "date": "2026-10-01",
                "amount": MONEY,
                "comment": "No receipt",
                "link": "https://x",
            }
        },
        True,
        False,
    ),
    (
        "booking_declined",
        _l("Booking declined"),
        "scheduling",
        "client",
        ("email",),
        ("email",),
        _booking_declined,
        _none,
        "",
        ("booking.service", "booking.start", "booking.reason", "booking.link"),
        {
            "booking": {
                "service": "GCSE Maths 1:1",
                "start": "2026-11-02T16:30:00+00:00",
                "timezone": "Europe/London",
                "reason": "declined",
                "link": "https://x",
            }
        },
        True,
        False,
    ),
    (
        "package_low",
        _l("Package running low"),
        "billing",
        "client",
        ("email", "sms"),
        ("email",),
        _package_low,
        load_package,
        "billing.packagepurchase",
        ("package.name", "package.units_remaining", "package.unit", "package.link"),
        {
            "package": {
                "name": "10 hours of Maths",
                "units_remaining": "1",
                "unit": "hours",
                "link": "https://x",
            }
        },
        True,
        False,
    ),
)
for (
    _key,
    _label,
    _category,
    _audience,
    _channels,
    _defaults,
    _resolve,
    _load,
    _related,
    _vars,
    _sample,
    _enabled,
    _attach,
) in G4_TYPES:
    register(
        NotificationType(
            key=_key,
            label=str(_label),
            category=_category,
            audience=_audience,
            channels=_channels,
            default_channels=_defaults,
            resolve=_resolve,
            load=_load,
            related_type=_related,
            variables=_vars,
            sample={**SAMPLE_BASE, **_sample},
            default_enabled=_enabled,
            transactional=_key in {"card_expiring", "client_statement", "booking_declined"},
            attachments=_statement_pdf if _attach else None,
            link=(lambda obj: TUTOR_EXPENSES) if _audience == "tutor" else None,
        )
    )

DEFAULTS[("card_expiring", "email")] = (
    "Your card ending {{ card.last4 }} expires soon",
    "Hello {{ recipient.first_name }},\n\nThe {{ card.brand }} card ending {{ card.last4 }} "
    "that pays your lessons expires at the end of {{ card.expiry }}. Please add a new card "
    "so payments carry on: {{ card.link }}" + SIGN,
)
DEFAULTS[("client_statement", "email")] = (
    "Your statement for {{ statement.end|date }}",
    "Hello {{ recipient.first_name }},\n\nYour statement from {{ statement.start|date }} to "
    "{{ statement.end|date }} is attached. Balance: {{ statement.closing|money }}.\n\n"
    "See your account: {{ statement.link }}" + SIGN,
)
DEFAULTS[("low_attendance", "in_app")] = ("{{ alert.title }}", "{{ attendance.link }}")
DEFAULTS[("low_attendance", "email")] = (
    "{{ alert.title }}",
    "{{ attendance.student }} attended {{ attendance.percent }}% of their last "
    "{{ attendance.lessons }} lessons.\n\n{{ attendance.link }}",
)
DEFAULTS[("expense_approved", "email")] = (
    "Expense approved: {{ expense.description }}",
    "Hello {{ recipient.first_name }},\n\nYour expense \N{LEFT DOUBLE QUOTATION MARK}"
    "{{ expense.description }}\N{RIGHT DOUBLE QUOTATION MARK} ({{ expense.amount|money }}) "
    "was approved and will be paid with your next pay run." + SIGN,
)
DEFAULTS[("expense_approved", "in_app")] = (
    "Expense approved",
    "{{ expense.description }} ({{ expense.amount|money }})",
)
DEFAULTS[("expense_rejected", "email")] = (
    "Expense not approved: {{ expense.description }}",
    "Hello {{ recipient.first_name }},\n\nYour expense \N{LEFT DOUBLE QUOTATION MARK}"
    "{{ expense.description }}\N{RIGHT DOUBLE QUOTATION MARK} ({{ expense.amount|money }}) "
    "wasn't approved.{% if expense.comment %}\n\nReason: {{ expense.comment }}{% endif %}"
    "\n\n{{ expense.link }}" + SIGN,
)
DEFAULTS[("expense_rejected", "in_app")] = (
    "Expense not approved",
    "{{ expense.description }}{% if expense.comment %}: {{ expense.comment }}{% endif %}",
)
DEFAULTS[("booking_declined", "email")] = (
    "Your booking request: {{ booking.service }}",
    "Hello {{ recipient.first_name }},\n\nSorry, we can't confirm {{ booking.service }} on "
    '{{ booking.start|datetime("full") }}{% if booking.reason == "expired" %} because the '
    "booking wasn't completed in time{% endif %}. You can choose another time here: "
    "{{ booking.link }}" + SIGN,
)
DEFAULTS[("package_low", "email")] = (
    "{{ package.name }}: {{ package.units_remaining }} {{ package.unit }} left",
    "Hello {{ recipient.first_name }},\n\n{{ package.name }} has {{ package.units_remaining }} "
    "{{ package.unit }} left. You can buy more here: {{ package.link }}" + SIGN,
)
DEFAULTS[("package_low", "sms")] = (
    "",
    "{{ organisation.name }}: {{ package.name }} has {{ package.units_remaining }} "
    "{{ package.unit }} left. Top up: {{ package.link }}",
)


# --- event handlers -------------------------------------------------------------------------------


def _notify(type_key: str, subject: Any, key: str) -> None:
    from .services import notify

    notify(type_key, subject, key=key)


@subscribe("expense.approved")
def expense_approved(event: EventEnvelope) -> None:
    expense = load_expense(str(event.subject["id"]))
    if expense is not None:
        _notify("expense_approved", expense, str(event.id))


@subscribe("expense.rejected")
def expense_rejected(event: EventEnvelope) -> None:
    expense = load_expense(str(event.subject["id"]))
    if expense is not None:
        _notify("expense_rejected", expense, str(event.id))


@subscribe("booking.declined")
def booking_declined(event: EventEnvelope) -> None:
    reason = str(event.data.get("reason") or "declined")
    if reason == "cancelled":
        return  # the family cancelled it themselves
    hold = load_hold(str(event.subject["id"]))
    if hold is not None:
        _notify("booking_declined", (hold, reason), str(event.id))


@subscribe("package.low")
def package_low(event: EventEnvelope) -> None:
    purchase = load_package(str(event.subject["id"]))
    if purchase is not None:
        _notify("package_low", purchase, str(event.id))


def attendance_rate(student: Any, lessons: int) -> tuple[int, int] | None:
    """The student's attendance over their last ``lessons`` completed lessons as
    (percent, lessons counted), or None if they've had fewer than that."""
    from tutortrack.scheduling.models import Lesson, LessonAttendee

    rows = list(
        LessonAttendee.objects.filter(student=student, lesson__status=Lesson.Status.COMPLETED)
        .exclude(outcome="")
        .order_by("-lesson__start")
        .values_list("outcome", flat=True)[:lessons]
    )
    if len(rows) < lessons:
        return None
    attended = sum(1 for outcome in rows if outcome in {"present", "late"})
    return round(Decimal(attended * 100) / Decimal(len(rows))), len(rows)


@subscribe("lesson.completed", "attendance.recorded")
def low_attendance(event: EventEnvelope) -> None:
    from tutortrack.core.time import now
    from tutortrack.scheduling.models import LessonAttendee

    threshold = int(get_setting("comms.low_attendance_percent"))
    if not threshold:
        return
    lessons = int(get_setting("comms.low_attendance_lessons"))
    week = now().isocalendar()
    for attendee in LessonAttendee.objects.filter(lesson_id=event.subject["id"]).select_related(
        "student"
    ):
        found = attendance_rate(attendee.student, lessons)
        if found is None or found[0] >= threshold:
            continue
        key = f"{attendee.student_id}:{week[0]}-{week[1]}"  # at most one alert a week
        _notify("low_attendance", (attendee.student, found[0], found[1]), key)


# --- daily checks (the 15-minute comms task) ------------------------------------------------------


def _org_today() -> date:
    from tutortrack.core.time import now

    return now().astimezone(ZoneInfo(organisation()["timezone"] or "UTC")).date()


def _in_daily_window(moment: datetime, tz: str) -> date | None:
    zone = ZoneInfo(tz or "UTC")
    local = moment.astimezone(zone)
    start = datetime.combine(local.date(), time(DAILY_CHECK_HOUR), tzinfo=zone)
    return local.date() if start <= local < start + timedelta(hours=1) else None


def expiring_cards(today: date) -> list[Any]:
    """Active cards that expire at the end of this month or next month."""
    from tutortrack.payments.models import PaymentMethod

    this_month = (today.year, today.month)
    next_month = (today.year + (today.month == 12), today.month % 12 + 1)
    out = []
    for method in PaymentMethod.objects.filter(
        status="active", exp_month__isnull=False, exp_year__isnull=False
    ).select_related("client"):
        if (method.exp_year, method.exp_month) in {this_month, next_month}:
            out.append(method)
    return out


def send_card_notices(today: date) -> int:
    from .services import effective, notify

    if not effective("card_expiring").enabled:
        return 0
    sent = 0
    for method in expiring_cards(today):
        key = f"{method.pk}:{method.exp_year}-{method.exp_month:02d}"
        sent += len(notify("card_expiring", method, key=key))
    return sent


def send_statements(today: date) -> int:
    """On the 1st of the month: last month's statement to clients who owe something."""
    from tutortrack.billing import selectors as billing
    from tutortrack.people.models import Client

    from .services import effective, notify

    if today.day != 1 or not effective("client_statement").enabled:
        return 0
    sent = 0
    _start, end = _statement_period(today)
    for client in Client.objects.filter(status="active"):
        if billing.balance_due(client.pk) <= 0:
            continue
        sent += len(notify("client_statement", client, key=f"{client.pk}:{end:%Y-%m}"))
    return sent


def run_daily(moment: datetime) -> dict[str, int]:
    """The once-a-day part of the 15-minute task: from 09:00 organisation time."""
    tz = organisation()["timezone"]
    today = _in_daily_window(moment, tz)
    if today is None:
        return {"cards": 0, "statements": 0}
    return {"cards": send_card_notices(today), "statements": send_statements(today)}
