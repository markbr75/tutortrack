"""Recurring fixed fees (E10-T13, FR-10-8): billing plans, their periods and proration.

Periods run from the anchor date: every week, every calendar month on the anchor's day
(clamped to short months) or termly: each of the branch's terms (E20 term dates), or
every four months when the branch has no terms. A plan starting or ending part
way through a period is charged for the share of days it covers (``prorate``), rounded
half-up to the minor unit. ``BillingPlanWorkflow`` charges each period when it starts;
charges are idempotent per plan and period (``plan:{plan}:{start}``).
"""

from __future__ import annotations

import calendar
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils.translation import gettext as _

from tutortrack.core import audit
from tutortrack.core.events import publish
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.money import Money
from tutortrack.core.time import now
from tutortrack.tenancy.settings_service import get_setting

from . import events
from .models import BillingPlan, Charge

CHARGE_TIME = time(6, 0)
MONTHS: dict[str, int] = {BillingPlan.Interval.MONTHLY: 1, BillingPlan.Interval.TERMLY: 4}


def _invalid(field_name: str, message: str) -> BusinessRuleViolation:
    return BusinessRuleViolation(message, extra={"errors": {field_name: [message]}})


def add_months(day: date, months: int, anchor_day: int) -> date:
    index = day.year * 12 + (day.month - 1) + months
    year, month = divmod(index, 12)
    last = calendar.monthrange(year, month + 1)[1]
    return date(year, month + 1, min(anchor_day, last))


def boundary(interval: str, anchor: date, k: int) -> date:
    """The start of period ``k`` (``k`` may be negative: periods before the anchor)."""
    if interval == BillingPlan.Interval.WEEKLY:
        return anchor + timedelta(weeks=k)
    return add_months(anchor, MONTHS[interval] * k, anchor.day)


def _index_at(interval: str, anchor: date, day: date) -> int:
    """The period index containing ``day``."""
    if interval == BillingPlan.Interval.WEEKLY:
        return (day - anchor).days // 7
    step = MONTHS[interval]
    k = ((day.year - anchor.year) * 12 + (day.month - anchor.month)) // step
    while boundary(interval, anchor, k) > day:
        k -= 1
    while boundary(interval, anchor, k + 1) <= day:
        k += 1
    return k


@dataclass(frozen=True)
class Segment:
    """The part of one period a plan bills: ``start``..``end`` inclusive."""

    start: date
    end: date
    period_start: date
    period_end: date

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    @property
    def period_days(self) -> int:
        return (self.period_end - self.period_start).days + 1

    @property
    def fraction(self) -> Decimal:
        return Decimal(self.days) / Decimal(self.period_days)

    @property
    def partial(self) -> bool:
        return self.days < self.period_days


def segments(
    interval: str, anchor: date, start: date, end: date | None = None
) -> Iterator[Segment]:
    """The billed parts of each period from ``start`` to ``end`` (open-ended without)."""
    k = _index_at(interval, anchor, start)
    while True:
        period_start = boundary(interval, anchor, k)
        period_end = boundary(interval, anchor, k + 1) - timedelta(days=1)
        seg_start = max(period_start, start)
        seg_end = period_end if end is None else min(period_end, end)
        if seg_start > seg_end:
            return
        yield Segment(seg_start, seg_end, period_start, period_end)
        if end is not None and period_end >= end:
            return
        k += 1


def amount_for(amount: Money, segment: Segment, *, prorate: bool) -> Money:
    """The fee for a segment: the full amount, or its share of days (rounded half-up)."""
    if not prorate or not segment.partial:
        return amount.round_to_minor()
    return (amount * segment.fraction).round_to_minor()


TermCalendar = Callable[[Any], list[tuple[date, date]]]
_term_calendar: list[TermCalendar] = []


def register_term_calendar(provider: TermCalendar) -> TermCalendar:
    """E20 provides each branch's term dates; termly plans then follow them."""
    _term_calendar[:] = [provider]
    return provider


def term_dates(branch_id: Any) -> list[tuple[date, date]]:
    """The branch's terms as ``(first day, last day)``, oldest first ([] without E20 terms)."""
    return sorted(_term_calendar[0](branch_id)) if _term_calendar else []


def term_segments(
    terms: list[tuple[date, date]], start: date, end: date | None = None
) -> Iterator[Segment]:
    """Termly periods from real term dates (E20): each term is one period and the days
    between terms (the holidays) are not billed. A plan starting or ending inside a term
    is charged for its share of that term's days."""
    for term_start, term_end in sorted(terms):
        seg_start = max(term_start, start)
        seg_end = term_end if end is None else min(term_end, end)
        if seg_start > seg_end:
            continue
        yield Segment(seg_start, seg_end, term_start, term_end)


def _uses_terms(plan: BillingPlan) -> list[tuple[date, date]]:
    if plan.interval != BillingPlan.Interval.TERMLY:
        return []
    return term_dates(plan.branch_id)


def plan_segments(plan: BillingPlan) -> Iterator[Segment]:
    terms = _uses_terms(plan)
    if terms:
        return term_segments(terms, plan.start_date, plan.end_date)
    return segments(plan.interval, plan.anchor_date, plan.start_date, plan.end_date)


def term_dates_changed(branch_id: Any) -> int:
    """Terms were added or moved (E20): re-plan the branch's open termly plans."""
    plans = BillingPlan.objects.filter(
        branch_id=branch_id, interval=BillingPlan.Interval.TERMLY
    ).exclude(status=BillingPlan.Status.ENDED)
    count = 0
    for plan in plans:
        _changed(plan)
        count += 1
    return count


def source_key(plan: BillingPlan, segment: Segment) -> str:
    return f"plan:{plan.pk}:{segment.start.isoformat()}"


# --- writes -------------------------------------------------------------------------------------


def _validate(plan: BillingPlan) -> None:
    if not plan.amount.is_positive():
        raise _invalid("amount", _("The fee must be more than zero."))
    if plan.interval not in BillingPlan.Interval.values:
        raise _invalid("interval", _("Choose how often to charge."))
    if plan.end_date and plan.end_date < plan.start_date:
        raise _invalid("end_date", _("The plan ends before it starts."))
    if plan.student_id and plan.student.client_id != plan.client_id:  # type: ignore[union-attr]
        raise _invalid("student", _("That student isn't in this client's account."))
    if plan.job_id and plan.amount.currency != plan.job.currency:  # type: ignore[union-attr]
        raise _invalid("amount", _("Use the job's currency."))


@transaction.atomic
def create_plan(
    *,
    client: Any,
    description: str,
    amount: Money,
    interval: str,
    start_date: date,
    anchor_date: date | None = None,
    end_date: date | None = None,
    job: Any = None,
    student: Any = None,
    tax_rate: Any = None,
    prorate: bool = True,
    attendance_independent: bool = True,
    user: Any = None,
) -> BillingPlan:
    plan = BillingPlan(
        client=client,
        branch_id=(job.branch_id if job is not None else client.branch_id),
        job=job,
        student=student,
        description=description[:200],
        currency=amount.currency,
        tax_rate=tax_rate,
        interval=interval,
        anchor_date=anchor_date or start_date,
        start_date=start_date,
        end_date=end_date,
        prorate=prorate,
        attendance_independent=attendance_independent,
        created_by=user,
    )
    plan.amount = amount.round_to_minor()
    _validate(plan)
    plan.save()
    audit.record_create(plan)
    publish(
        events.BillingPlanCreated(
            subject_id=plan.pk, client_id=str(client.pk), amount=plan.amount.to_dict()
        ),
        branch_id=plan.branch_id,
    )
    from tutortrack.core.workflows import start

    from .processes import BillingPlanWorkflow, PlanInput, plan_workflow_id

    plan.workflow_id = plan_workflow_id(plan.organisation_id, plan.pk)
    plan.save(update_fields=["workflow_id", "updated_at"])
    start(
        BillingPlanWorkflow,
        PlanInput(organisation_id=str(plan.organisation_id), plan_id=str(plan.pk)),
        id=plan.workflow_id,
        subject=("billing_plan", str(plan.pk)),
        branch_id=plan.branch_id,
    )
    return plan


def _changed(plan: BillingPlan) -> None:
    if plan.workflow_id:
        from tutortrack.core.workflows import signal

        signal(plan.workflow_id, "changed")


@transaction.atomic
def update_plan(plan: BillingPlan, *, user: Any = None, **changes: Any) -> BillingPlan:
    """Change the fee, description, end date or settings; periods already charged stay."""
    plan = BillingPlan.objects.select_for_update().get(pk=plan.pk)
    if plan.status == BillingPlan.Status.ENDED:
        raise BusinessRuleViolation(_("This plan has ended."))
    with audit.track(plan, action="update"):
        for key in ("description", "end_date", "prorate", "attendance_independent", "tax_rate"):
            if key in changes:
                setattr(plan, key, changes[key])
        if "amount" in changes:
            plan.amount = changes["amount"].round_to_minor()
        _validate(plan)
        plan.save()
    _changed(plan)
    return plan


@transaction.atomic
def set_plan_status(plan: BillingPlan, status: str, *, user: Any = None) -> BillingPlan:
    """Pause (periods starting while paused aren't charged), resume or end a plan."""
    plan = BillingPlan.objects.select_for_update().get(pk=plan.pk)
    if plan.status == BillingPlan.Status.ENDED:
        raise BusinessRuleViolation(_("This plan has ended."))
    if status not in BillingPlan.Status.values or status == plan.status:
        raise _invalid("status", _("Choose pause, resume or end."))
    with audit.track(plan, action=status):
        plan.status = status
        plan.paused_at = now() if status == BillingPlan.Status.PAUSED else None
        today = local_today(plan)
        if status == BillingPlan.Status.ENDED and (plan.end_date is None or plan.end_date > today):
            # Ending before it started bills nothing (an empty range).
            plan.end_date = today if today >= plan.start_date else plan.start_date - timedelta(1)
        plan.save()
    publish(
        events.BillingPlanStatusChanged(
            subject_id=plan.pk, client_id=str(plan.client_id), status=status
        ),
        branch_id=plan.branch_id,
    )
    _changed(plan)
    return plan


def _tz(plan: BillingPlan) -> ZoneInfo:
    from tutortrack.tenancy.models import Branch

    branch = Branch.objects.filter(pk=plan.branch_id).first()
    return ZoneInfo(str(branch.timezone)) if branch else ZoneInfo("UTC")


def local_today(plan: BillingPlan) -> date:
    return now().astimezone(_tz(plan)).date()


def next_period(plan_id: Any, after: str) -> dict[str, Any]:
    """For ``BillingPlanWorkflow``: the next segment starting after ``after`` (ISO date,
    '' for the first) that isn't charged yet, and when to charge it (06:00 local)."""
    plan = BillingPlan.objects.filter(pk=plan_id).first()
    if plan is None:
        return {"status": "ended"}
    today = local_today(plan).isoformat()
    if plan.status == BillingPlan.Status.PAUSED:
        return {"status": "paused", "today": today}
    floor = date.fromisoformat(after) if after else None
    charged = set(
        Charge.objects.filter(source_key__startswith=f"plan:{plan.pk}:").values_list(
            "source_key", flat=True
        )
    )
    for segment in plan_segments(plan):
        if floor is not None and segment.start <= floor:
            continue
        if source_key(plan, segment) in charged:
            continue
        moment = datetime.combine(segment.start, CHARGE_TIME, tzinfo=_tz(plan))
        return {
            "status": "due",
            "start": segment.start.isoformat(),
            "charge_at": moment.astimezone(ZoneInfo("UTC")).isoformat(),
            "today": today,
        }
    if plan.end_date is None and _uses_terms(plan):
        # An open-ended termly plan past the last term we know: wait for the next term's
        # dates (``term_dates_changed`` signals the workflow) instead of ending.
        return {"status": "paused", "today": today}
    return {"status": "ended"}


def _has_lessons(plan: BillingPlan, segment: Segment) -> bool:
    from tutortrack.scheduling.models import Lesson

    tz = _tz(plan)
    lessons = Lesson.objects.filter(
        start__gte=datetime.combine(segment.start, time.min, tzinfo=tz),
        start__lt=datetime.combine(segment.end + timedelta(days=1), time.min, tzinfo=tz),
    ).exclude(status=Lesson.Status.CANCELLED)
    if plan.job_id:
        lessons = lessons.filter(job_id=plan.job_id)
    elif plan.student_id:
        lessons = lessons.filter(attendees__student_id=plan.student_id)
    else:
        lessons = lessons.filter(attendees__client_id=plan.client_id)
    return lessons.exists()


@transaction.atomic
def charge_period(plan_id: Any, start: str) -> str:
    """Charge one period (idempotent): ``charged``, ``skipped`` (no lessons and the plan
    isn't attendance-independent), ``exists`` or ``ended``."""
    from . import services
    from .splits import payers_for

    plan_row = (
        BillingPlan.objects.select_for_update().select_related("client").filter(pk=plan_id).first()
    )
    if plan_row is None or plan_row.status == BillingPlan.Status.PAUSED:
        return "ended" if plan_row is None else "paused"
    day = date.fromisoformat(start)
    segment = next((s for s in plan_segments(plan_row) if s.start == day), None)
    if segment is None:
        return "ended"
    key = source_key(plan_row, segment)
    if Charge.objects.filter(source_key__startswith=key).exclude(status="void").exists():
        return "exists"
    if not plan_row.attendance_independent and not _has_lessons(plan_row, segment):
        publish(
            events.BillingPlanPeriodSkipped(
                subject_id=plan_row.pk, client_id=str(plan_row.client_id), start=start
            ),
            branch_id=plan_row.branch_id,
            dedupe_key=key,
        )
        return "skipped"
    fee = amount_for(plan_row.amount, segment, prorate=plan_row.prorate)
    description = plan_row.description
    if segment.partial and plan_row.prorate:
        description = _("%(what)s (%(start)s to %(end)s, part period)") % {
            "what": plan_row.description,
            "start": segment.start.isoformat(),
            "end": segment.end.isoformat(),
        }
    rate = plan_row.tax_rate
    payers = payers_for(job=plan_row.job, student=plan_row.student, client=plan_row.client)
    shares = fee.allocate([p for _c, p in payers]) if len(payers) > 1 else [fee]
    created = []
    for index, ((client, _percent), share) in enumerate(zip(payers, shares, strict=True)):
        if share.is_zero():
            continue
        created.append(
            services._create_charge(
                client=client,
                kind=Charge.Kind.PLAN,
                source_key=key if len(payers) == 1 else f"{key}:{index}",
                description=description,
                day=segment.start,
                price=share,
                quantity=Decimal(1),
                unit="period",
                tax_percent=rate.percent if rate else Decimal(0),
                tax_rate_id=rate.pk if rate else None,
                branch_id=plan_row.branch_id,
                student=plan_row.student,
                job=plan_row.job,
                category="plan",
            )
        )
    if created and get_setting("billing.plan_invoice_immediately"):
        drafts = services.build_drafts(
            Charge.objects.filter(pk__in=[c.pk for c in created]), skip_small=False
        )
        for draft in drafts:
            services.issue_invoice(draft)
    return "charged"
