"""Incremental refresh of the fact tables (E26-T01, FR-26-7).

Each ``refresh_*`` re-reads one source record (read-only) and upserts or deletes its fact
row(s), then recomputes the daily aggregates of the days it touched. They are idempotent,
so event handlers can call them as often as they like; ``rebuild()`` recomputes everything
for the organisation in context (backfill, repair).
"""

from __future__ import annotations

from collections.abc import Iterable
from contextvars import ContextVar
from datetime import date
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.db.models import Count, Q, Sum

from tutortrack.core.context import branch_scope

from .models import DailyAggregate, FactCharge, FactLesson, FactPayItem, FactPayment
from .periods import local_date, org_timezone

ZERO = Decimal("0.00")
Day = tuple[Any, date]  # (branch id, date)


def _amount(value: Any) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(value or 0)


# --- lessons ------------------------------------------------------------------------------------


def _lesson_rows(lesson: Any, tz: str) -> list[dict[str, Any]]:
    tutors = list(lesson.tutors.all().order_by("created_at"))
    attendees = list(lesson.attendees.all())
    service = lesson.service
    subject_id = (
        lesson.job.subject_id if lesson.job_id and lesson.job and lesson.job.subject_id else None
    ) or service.subject_id
    minutes = int((lesson.end - lesson.start).total_seconds() // 60)
    delivered = 0
    if lesson.status == "completed":
        if lesson.actual_start and lesson.actual_end:
            delivered = int((lesson.actual_end - lesson.actual_start).total_seconds() // 60)
        else:
            delivered = minutes
    currency = (
        (tutors[0].currency if tutors and tutors[0].currency else "")
        or next((a.currency for a in attendees if a.currency), "")
        or (lesson.job.currency if lesson.job_id and lesson.job else service.currency)
    )
    revenue = sum((_amount(a.charge_amount_amount) for a in attendees if a.chargeable), Decimal(0))
    common = {
        "branch_id": lesson.branch_id,
        "lesson_id": lesson.pk,
        "job_id": lesson.job_id,
        "service_id": lesson.service_id,
        "subject_id": subject_id,
        "location_id": lesson.location_id,
        "date": local_date(lesson.start, tz),
        "start": lesson.start,
        "end": lesson.end,
        "status": lesson.status,
        "cancelled_by": lesson.cancelled_by or "",
        "minutes": minutes,
        "delivered_minutes": delivered,
        "attendees": len(attendees),
        "present": sum(1 for a in attendees if a.outcome in ("present", "late")),
        "absent": sum(1 for a in attendees if a.outcome in ("no_show", "absent_notified")),
        "unconfirmed": lesson.status == "planned" and lesson.unconfirmed_at is not None,
        "currency": currency,
    }
    if not tutors:
        return [
            {
                **common,
                "key": f"{lesson.pk}:-",
                "tutor_id": None,
                "primary": True,
                "revenue_amount": revenue,
                "pay_amount": ZERO,
            }
        ]
    return [
        {
            **common,
            "key": f"{lesson.pk}:{t.tutor_id}",
            "tutor_id": t.tutor_id,
            "primary": index == 0,
            "revenue_amount": revenue if index == 0 else ZERO,
            "pay_amount": _amount(t.pay_amount_amount) if t.payable else ZERO,
        }
        for index, t in enumerate(tutors)
    ]


def refresh_lesson(lesson_id: Any) -> int:
    """Upsert the lesson's fact rows; returns how many rows it now has."""
    from tutortrack.scheduling.models import Lesson

    with branch_scope(None), transaction.atomic():
        old = list(FactLesson.objects.filter(lesson_id=lesson_id).values("branch_id", "date"))
        lesson = Lesson.objects.filter(pk=lesson_id).select_related("service", "job").first()
        rows = _lesson_rows(lesson, org_timezone()) if lesson is not None else []
        keys = [r["key"] for r in rows]
        FactLesson.objects.filter(lesson_id=lesson_id).exclude(key__in=keys).delete()
        for row in rows:
            key = row.pop("key")
            FactLesson.objects.update_or_create(key=key, defaults=row)
        days = {(o["branch_id"], o["date"]) for o in old}
        days |= {(r["branch_id"], r["date"]) for r in rows}
        refresh_days(days)
    return len(rows)


# --- charges ------------------------------------------------------------------------------------


def refresh_charge(charge_id: Any) -> bool:
    from tutortrack.billing.models import Charge

    with branch_scope(None), transaction.atomic():
        old = FactCharge.objects.filter(charge_id=charge_id).values("branch_id", "date").first()
        charge = (
            Charge.objects.filter(pk=charge_id)
            .select_related("lesson__service", "job__service")
            .first()
        )
        days: set[Day] = {(old["branch_id"], old["date"])} if old else set()
        if charge is None:
            FactCharge.objects.filter(charge_id=charge_id).delete()
            refresh_days(days)
            return False
        service = (charge.lesson.service if charge.lesson_id else None) or (
            charge.job.service if charge.job_id else None
        )
        subject_id = (charge.job.subject_id if charge.job_id else None) or (
            service.subject_id if service else None
        )
        tutor_id = charge.tutor_id
        if tutor_id is None and charge.lesson_id:
            first = charge.lesson.tutors.order_by("created_at").first()
            tutor_id = first.tutor_id if first else None
        FactCharge.objects.update_or_create(
            charge_id=charge.pk,
            defaults={
                "branch_id": charge.branch_id,
                "invoice_id": charge.invoice_id,
                "client_id": charge.client_id,
                "student_id": charge.student_id,
                "tutor_id": tutor_id,
                "job_id": charge.job_id,
                "lesson_id": charge.lesson_id,
                "service_id": service.pk if service else None,
                "subject_id": subject_id,
                "date": charge.date,
                "kind": charge.kind,
                "status": charge.status,
                "currency": charge.currency,
                "net_amount": charge.net_amount,
                "tax_amount": charge.tax_amount,
                "gross_amount": charge.gross_amount,
            },
        )
        days.add((charge.branch_id, charge.date))
        refresh_days(days)
    return True


# --- payments -----------------------------------------------------------------------------------


def refresh_payment(payment_id: Any) -> bool:
    from tutortrack.payments.models import Payment

    with branch_scope(None), transaction.atomic():
        old = FactPayment.objects.filter(payment_id=payment_id).values("branch_id", "date").first()
        payment = Payment.objects.filter(pk=payment_id).first()
        days: set[Day] = {(old["branch_id"], old["date"])} if old else set()
        if payment is None:
            FactPayment.objects.filter(payment_id=payment_id).delete()
            refresh_days(days)
            return False
        day = local_date(payment.received_at or payment.created_at, org_timezone())
        FactPayment.objects.update_or_create(
            payment_id=payment.pk,
            defaults={
                "branch_id": payment.branch_id,
                "client_id": payment.client_id,
                "date": day,
                "method": payment.method,
                "provider": payment.provider,
                "status": payment.status,
                "currency": payment.currency,
                "amount_amount": payment.amount_amount,
                "refunded_amount": payment.refunded_amount or ZERO,
                "fee_amount": payment.fee_amount or ZERO,
            },
        )
        days.add((payment.branch_id, day))
        refresh_days(days)
    return True


# --- pay items ----------------------------------------------------------------------------------


def refresh_pay_item(pay_item_id: Any) -> bool:
    from tutortrack.payroll.models import PayItem

    with branch_scope(None), transaction.atomic():
        old = (
            FactPayItem.objects.filter(pay_item_id=pay_item_id).values("branch_id", "date").first()
        )
        item = PayItem.objects.filter(pk=pay_item_id).select_related("lesson").first()
        days: set[Day] = {(old["branch_id"], old["date"])} if old else set()
        if item is None:
            FactPayItem.objects.filter(pay_item_id=pay_item_id).delete()
            refresh_days(days)
            return False
        FactPayItem.objects.update_or_create(
            pay_item_id=item.pk,
            defaults={
                "branch_id": item.branch_id,
                "tutor_id": item.tutor_id,
                "lesson_id": item.lesson_id,
                "job_id": item.lesson.job_id if item.lesson_id else None,
                "service_id": item.lesson.service_id if item.lesson_id else None,
                "pay_run_id": item.pay_run_id,
                "date": item.date,
                "kind": item.kind,
                "status": item.status,
                "currency": item.currency,
                "amount_amount": item.amount_amount,
                "quantity": item.quantity,
            },
        )
        days.add((item.branch_id, item.date))
        refresh_days(days)
    return True


# --- daily aggregates ---------------------------------------------------------------------------


# rebuild() collects the days it touches and refreshes each one once at the end.
_deferred: ContextVar[set[Day] | None] = ContextVar("reporting_deferred_days", default=None)


def refresh_days(days: Iterable[Day]) -> None:
    """Recompute ``DailyAggregate`` rows for each (branch, date)."""
    pending = _deferred.get()
    if pending is not None:
        pending.update(days)
        return
    for branch_id, day in set(days):
        _refresh_day(branch_id, day)


def _refresh_day(branch_id: Any, day: date) -> None:
    lessons = FactLesson.objects.filter(branch_id=branch_id, date=day)
    counts = lessons.filter(primary=True).aggregate(
        completed=Count("pk", filter=Q(status="completed")),
        cancelled=Count("pk", filter=Q(status="cancelled")),
        planned=Count("pk", filter=Q(status="planned")),
    )
    minutes = lessons.aggregate(m=Sum("delivered_minutes"))["m"] or 0
    money: dict[str, dict[str, Decimal]] = {}

    def add(currency: str, field: str, value: Any) -> None:
        if currency:
            row = money.setdefault(currency, {"revenue": ZERO, "collected": ZERO, "pay_cost": ZERO})
            row[field] += _amount(value)

    charges = (
        FactCharge.objects.filter(branch_id=branch_id, date=day)
        .exclude(status="void")
        .values("currency")
        .annotate(v=Sum("net_amount"))
    )
    for r in charges:
        add(r["currency"], "revenue", r["v"])
    payments = (
        FactPayment.objects.filter(
            branch_id=branch_id,
            date=day,
            status__in=("succeeded", "partially_refunded", "refunded", "disputed"),
        )
        .values("currency")
        .annotate(v=Sum("amount_amount"), r=Sum("refunded_amount"))
    )
    for r in payments:
        add(r["currency"], "collected", _amount(r["v"]) - _amount(r["r"]))
    pay = (
        FactPayItem.objects.filter(branch_id=branch_id, date=day)
        .exclude(status="void")
        .exclude(kind__in=("expense", "mileage"))
        .values("currency")
        .annotate(v=Sum("amount_amount"))
    )
    for r in pay:
        add(r["currency"], "pay_cost", r["v"])

    keep = {""} | set(money)
    DailyAggregate.objects.filter(branch_id=branch_id, date=day).exclude(currency__in=keep).delete()
    DailyAggregate.objects.update_or_create(
        branch_id=branch_id,
        date=day,
        currency="",
        defaults={
            "lessons_completed": counts["completed"],
            "lessons_cancelled": counts["cancelled"],
            "lessons_planned": counts["planned"],
            "delivered_minutes": minutes,
        },
    )
    for currency, values in money.items():
        DailyAggregate.objects.update_or_create(
            branch_id=branch_id, date=day, currency=currency, defaults=values
        )


# --- full rebuild -------------------------------------------------------------------------------


def rebuild() -> dict[str, int]:
    """Recompute every fact for the organisation in context (backfill and repair)."""
    counts = {"lessons": 0, "charges": 0, "payments": 0, "pay_items": 0}
    days: set[Day] = set()
    token = _deferred.set(days)
    try:
        _rebuild_facts(counts)
    finally:
        _deferred.reset(token)
    with branch_scope(None):
        refresh_days(days)
        days_with_facts = set(DailyAggregate.objects.values_list("branch_id", "date"))
        refresh_days(days_with_facts - days)  # days whose facts have all gone
    return counts


def _rebuild_facts(counts: dict[str, int]) -> None:
    from tutortrack.billing.models import Charge
    from tutortrack.payments.models import Payment
    from tutortrack.payroll.models import PayItem
    from tutortrack.scheduling.models import Lesson

    with branch_scope(None):
        lesson_ids = set(Lesson.objects.values_list("pk", flat=True))
        lesson_ids |= set(FactLesson.objects.values_list("lesson_id", flat=True))
        for lesson_id in lesson_ids:
            counts["lessons"] += 1 if refresh_lesson(lesson_id) else 0
        for model, fact, field, fn, key in (
            (Charge, FactCharge, "charge_id", refresh_charge, "charges"),
            (Payment, FactPayment, "payment_id", refresh_payment, "payments"),
            (PayItem, FactPayItem, "pay_item_id", refresh_pay_item, "pay_items"),
        ):
            ids = set(model.objects.values_list("pk", flat=True))
            ids |= set(fact.objects.values_list(field, flat=True))
            for pk in ids:
                counts[key] += 1 if fn(pk) else 0
