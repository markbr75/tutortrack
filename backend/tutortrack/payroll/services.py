"""Tutor pay (E12): pay profiles, pay items and holds, expenses, pay runs, statements,
payouts and exports.

Pay items follow what happened (lessons completed or cancelled, paid events, charge shares,
approved expenses) and are kept in sync idempotently, like billing's charges: open items
are replaced; once an item is in a pay run or paid, a change becomes an adjustment item.
"""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from collections.abc import Callable, Iterable
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

import structlog
from django.conf import settings
from django.db import transaction
from django.utils.translation import gettext as _

from tutortrack.core import audit
from tutortrack.core.context import require_organisation_id
from tutortrack.core.events import publish
from tutortrack.core.exceptions import BusinessRuleViolation, NotFound, PermissionDenied
from tutortrack.core.money import Money
from tutortrack.core.permissions import has_perm
from tutortrack.core.sequences import next_number
from tutortrack.core.time import now
from tutortrack.people.models import TutorProfile
from tutortrack.tenancy.models import Organisation
from tutortrack.tenancy.settings_service import get_setting

from . import banking, events
from .models import (
    BankFileExport,
    Expense,
    ExpenseCategory,
    PayItem,
    PayMethod,
    Payout,
    PayrollOriginator,
    PayRun,
    PayStatement,
    TutorPayProfile,
)

logger = structlog.get_logger(__name__)

OPEN = (PayItem.Status.READY, PayItem.Status.HELD)
LOCKED = (PayItem.Status.IN_PAY_RUN, PayItem.Status.APPROVED, PayItem.Status.PAID)
SELF_BILLING_VERSION = "2026-10"


def _org() -> Organisation:
    return Organisation.objects.get(pk=require_organisation_id())


def _decimal(value: Any, default: str = "0") -> Decimal:
    try:
        return Decimal(str(value or default))
    except InvalidOperation:
        return Decimal(default)


def _money_dict(amount: Money) -> dict[str, str]:
    return amount.to_dict()


# --- pay profiles (T01) ---------------------------------------------------------------------


def profile_for(tutor: TutorProfile) -> TutorPayProfile:
    profile, _created = TutorPayProfile.objects.get_or_create(tutor=tutor)
    return profile


def currency_for(tutor: TutorProfile) -> str:
    profile = TutorPayProfile.objects.filter(tutor=tutor).first()
    return (profile.currency if profile and profile.currency else "") or _org().default_currency


PROFILE_FIELDS = {"method", "currency", "payee_name", "vat_registered", "vat_number", "hourly_rate"}


@transaction.atomic
def update_profile(
    tutor: TutorProfile, *, bank: dict[str, Any] | None = None, **changes: Any
) -> TutorPayProfile:
    unknown = set(changes) - PROFILE_FIELDS
    if unknown:
        raise BusinessRuleViolation(f"Unknown pay profile fields: {', '.join(sorted(unknown))}")
    if "method" in changes and changes["method"] not in PayMethod.values:
        raise BusinessRuleViolation(_("Unknown pay method."))
    profile = profile_for(tutor)
    with audit.track(profile, action="update"):
        for key, value in changes.items():
            setattr(profile, key, value)
        if bank is not None:
            country = str(bank.get("country") or _org().country).upper()
            details = banking.clean(country, bank)
            profile.bank_country = country
            profile.bank_details = banking.dumps(details)
            profile.bank_hint = banking.hint(details)
        profile.save()
    return profile


def bank_details(profile: TutorPayProfile, *, full: bool) -> dict[str, str]:
    details = banking.loads(profile.bank_details)
    if not full:
        return banking.mask(details)
    audit.record_read(profile, reason="bank_details")
    return details


@transaction.atomic
def agree_self_billing(tutor: TutorProfile) -> TutorPayProfile:
    """The tutor accepts the self-billing agreement (HMRC: needed before we issue
    self-billing invoices on their behalf)."""
    profile = profile_for(tutor)
    with audit.track(profile, action="self_billing_agreed"):
        profile.self_billing_agreed_at = now()
        profile.self_billing_agreement_version = SELF_BILLING_VERSION
        profile.save(update_fields=["self_billing_agreed_at", "self_billing_agreement_version",
                                    "updated_at"])  # fmt: skip
    return profile


def stripe_onboarding_link(tutor: TutorProfile, *, return_url: str) -> str:
    from .payouts import PayoutError, get_provider

    profile = profile_for(tutor)
    provider = get_provider()
    try:
        if not profile.stripe_account_id:
            email = tutor.email or ""
            profile.stripe_account_id = provider.create_account(
                email=email, country=_org().country, ref=str(tutor.pk)
            )
            TutorPayProfile.objects.filter(pk=profile.pk).update(
                stripe_account_id=profile.stripe_account_id
            )
        return provider.onboarding_link(
            profile.stripe_account_id, return_url=return_url, refresh_url=return_url
        )
    except PayoutError as exc:
        raise BusinessRuleViolation(str(exc)) from exc


def refresh_stripe(tutor: TutorProfile) -> TutorPayProfile:
    from .payouts import get_provider

    profile = profile_for(tutor)
    if profile.stripe_account_id:
        enabled = get_provider().payouts_enabled(profile.stripe_account_id)
        TutorPayProfile.objects.filter(pk=profile.pk).update(stripe_payouts_enabled=enabled)
        profile.stripe_payouts_enabled = enabled
    return profile


@transaction.atomic
def save_originator(*, name: str, bank: dict[str, Any], extra: dict[str, str]) -> PayrollOriginator:
    org = _org()
    country = str(bank.get("country") or org.country).upper()
    details = {**banking.clean(country, {"account_name": name, **bank}),
               **{k: str(v)[:40] for k, v in extra.items()}}  # fmt: skip
    originator, _created = PayrollOriginator.objects.get_or_create(organisation=org)
    with audit.track(originator, action="update"):
        originator.name = name[:140]
        originator.bank_details = banking.dumps(details)
        originator.bank_hint = banking.hint(details)
        originator.save()
    return originator


# --- holds (T03) ----------------------------------------------------------------------------

HoldRule = Callable[[PayItem], bool]
_hold_rules: dict[str, HoldRule] = {}


def register_hold_rule(reason: str, rule: HoldRule) -> None:
    """Other apps add hold reasons (E18 registers ``compliance``)."""
    _hold_rules[reason] = rule


def _report_overdue(item: PayItem) -> bool:
    if not item.lesson_id or not get_setting("payroll.hold_on_overdue_report"):
        return False
    from tutortrack.delivery.models import LessonReport

    return LessonReport.objects.filter(
        lesson_id=item.lesson_id, tutor_id=item.tutor_id, overdue_at__isnull=False,
        status__in=[LessonReport.Status.PENDING, LessonReport.Status.DRAFT,
                    LessonReport.Status.RETURNED],
    ).exists()  # fmt: skip


def _client_unpaid(item: PayItem) -> bool:
    if not item.lesson_id or not get_setting("payroll.pay_when_client_paid"):
        return False
    from tutortrack.billing.selectors import lesson_paid

    return not lesson_paid(item.lesson_id)


register_hold_rule("report_overdue", _report_overdue)
register_hold_rule("client_unpaid", _client_unpaid)


def evaluate_holds(item: PayItem, *, publish_changes: bool = True) -> PayItem:
    """Recompute automatic holds for an open item (manual holds stay until released)."""
    if item.status not in OPEN:
        return item
    reasons = [r for r in item.hold_reasons if r == "manual"]
    reasons += [reason for reason, rule in _hold_rules.items() if rule(item)]
    was_held = item.status == PayItem.Status.HELD
    item.hold_reasons = reasons
    item.status = PayItem.Status.HELD if reasons else PayItem.Status.READY
    item.save(update_fields=["hold_reasons", "status", "updated_at"])
    if publish_changes and reasons and not was_held:
        publish(events.PayItemHeld(**_item_event(item), reasons=reasons), branch_id=item.branch_id)
    elif publish_changes and was_held and not reasons:
        publish(events.PayItemReleased(**_item_event(item)), branch_id=item.branch_id)
    return item


def _item_event(item: PayItem) -> dict[str, Any]:
    return {"subject_id": item.pk, "tutor_id": str(item.tutor_id), "kind": item.kind,
            "amount": _money_dict(item.amount)}  # fmt: skip


@transaction.atomic
def hold(item: PayItem, *, note: str) -> PayItem:
    if item.status not in OPEN:
        raise BusinessRuleViolation(_("Only items not yet in a pay run can be held."))
    with audit.track(item, action="hold"):
        item.hold_reasons = sorted({*item.hold_reasons, "manual"})
        item.hold_note = note[:300]
        item.save(update_fields=["hold_reasons", "hold_note", "updated_at"])
    return evaluate_holds(item)


@transaction.atomic
def release(item: PayItem) -> PayItem:
    if item.status not in OPEN:
        raise BusinessRuleViolation(_("This item isn't on hold."))
    with audit.track(item, action="release"):
        item.hold_reasons = [r for r in item.hold_reasons if r != "manual"]
        item.hold_note = ""
        item.save(update_fields=["hold_reasons", "hold_note", "updated_at"])
    return evaluate_holds(item)


@transaction.atomic
def reevaluate_lessons(lesson_ids: Iterable[Any]) -> int:
    count = 0
    for item in PayItem.objects.select_for_update().filter(
        lesson_id__in=list(lesson_ids), status__in=OPEN
    ):
        evaluate_holds(item)
        count += 1
    return count


# --- pay items (T02) ------------------------------------------------------------------------


def _create_item(
    *, tutor: TutorProfile, kind: str, source_key: str, description: str, day: date,
    amount: Money, quantity: Decimal = Decimal(1), unit: str = "", branch_id: Any = None,
    **links: Any,
) -> PayItem:  # fmt: skip
    item = PayItem(
        tutor=tutor, kind=kind, source_key=source_key, description=description[:300], date=day,
        quantity=quantity, unit=unit, currency=amount.currency, branch_id=branch_id, **links,
    )  # fmt: skip
    item.amount = amount
    item.save()
    audit.record_create(item)
    publish(events.PayItemCreated(**_item_event(item)), branch_id=item.branch_id)
    return evaluate_holds(item)


def _void(item: PayItem, reason: str) -> None:
    with audit.track(item, action="void"):
        item.status = PayItem.Status.VOID
        item.hold_note = reason[:300]
        item.save(update_fields=["status", "hold_note", "updated_at"])


def lesson_pay(link: Any) -> Money | None:
    if link.pay_amount is None or not link.payable:
        return None
    return (link.pay_amount * link.pay_percent / Decimal(100)).round_to_minor()


@transaction.atomic
def sync_lesson_pay(lesson_id: Any) -> list[PayItem]:
    """Make the lesson's pay items match what each tutor should get (idempotent)."""
    from tutortrack.scheduling.models import Lesson

    lesson = Lesson.objects.filter(pk=lesson_id).first()
    if lesson is None:
        return []
    created = []
    for link in lesson.tutors.select_related("tutor"):
        item = _sync_link(lesson, link)
        if item is not None:
            created.append(item)
    return created


def _desired_lesson_pay(lesson: Any, link: Any) -> Money:
    from tutortrack.scheduling.models import Lesson

    zero = Money.zero(link.currency or currency_for(link.tutor))
    if lesson.status == Lesson.Status.COMPLETED:
        return lesson_pay(link) or zero
    if lesson.status == Lesson.Status.CANCELLED and get_setting("payroll.include_cancellations"):
        return lesson_pay(link) or zero
    return zero


def _sync_link(lesson: Any, link: Any) -> PayItem | None:
    from tutortrack.scheduling.models import Lesson

    items = list(
        PayItem.objects.select_for_update()
        .filter(lesson_tutor=link)
        .exclude(status=PayItem.Status.VOID)
    )
    open_items = [i for i in items if i.status in OPEN]
    locked = [i for i in items if i.status in LOCKED]
    desired = _desired_lesson_pay(lesson, link)
    paid = sum((i.amount.amount for i in locked), Decimal(0))
    delta = Money(desired.amount - paid, desired.currency)
    if len(open_items) == 1 and open_items[0].amount == delta:
        return evaluate_holds(open_items[0])
    for item in open_items:
        _void(item, "replaced")
    if delta.is_zero():
        return None
    count = PayItem.objects.filter(lesson_tutor=link).count()
    cancelled = lesson.status == Lesson.Status.CANCELLED
    kind = (
        PayItem.Kind.ADJUSTMENT if locked
        else PayItem.Kind.CANCELLATION if cancelled else PayItem.Kind.LESSON
    )  # fmt: skip
    zone = ZoneInfo(lesson.timezone)
    day = lesson.start.astimezone(zone).date()
    minutes = Decimal((lesson.end - lesson.start).total_seconds() / 60)
    label = {
        PayItem.Kind.LESSON: lesson.title,
        PayItem.Kind.CANCELLATION: _("%(title)s (cancelled)") % {"title": lesson.title},
        PayItem.Kind.ADJUSTMENT: _("%(title)s (change after payment)") % {"title": lesson.title},
    }[kind]
    return _create_item(
        tutor=link.tutor, kind=kind, source_key=f"lesson_tutor:{link.pk}:{count}",
        description=f"{label} · {day.isoformat()}", day=day, amount=delta,
        quantity=(minutes / 60).quantize(Decimal("0.01")), unit="hour",
        branch_id=lesson.branch_id, lesson=lesson, lesson_tutor=link,
    )  # fmt: skip


@transaction.atomic
def sync_charge_share(charge_id: Any) -> PayItem | None:
    """An ad hoc charge with a tutor share pays the tutor (FR-10-2); voiding reverses it."""
    from tutortrack.billing.models import Charge

    charge = Charge.objects.select_related("tutor").filter(pk=charge_id).first()
    if charge is None or charge.tutor_id is None or charge.tutor_share is None:
        return None
    key = f"charge:{charge.pk}"
    existing = (
        PayItem.objects.select_for_update()
        .filter(source_key__startswith=key)
        .exclude(status=PayItem.Status.VOID)
    )
    paid = sum((i.amount.amount for i in existing), Decimal(0))
    desired = Decimal(0) if charge.status == Charge.Status.VOID else charge.tutor_share.amount
    open_items = [i for i in existing if i.status in OPEN]
    if charge.status == Charge.Status.VOID and open_items:
        for item in open_items:
            _void(item, "charge voided")
        paid -= sum((i.amount.amount for i in open_items), Decimal(0))
    delta = desired - paid
    if delta == 0:
        return None
    count = PayItem.objects.filter(source_key__startswith=key).count()
    kind = PayItem.Kind.CHARGE_SHARE if count == 0 else PayItem.Kind.ADJUSTMENT
    return _create_item(
        tutor=charge.tutor, kind=kind,
        source_key=f"{key}:{count}", description=charge.description, day=charge.date,
        amount=Money(delta, charge.tutor_share.currency), branch_id=charge.branch_id,
    )  # fmt: skip


@transaction.atomic
def sync_event_pay(until: date) -> int:
    """Paid meetings and training that ended by ``until`` (at the hourly rate on the pay
    profile). Called when a pay run collects items."""
    from tutortrack.scheduling.models import CalendarEventParticipant

    zone = ZoneInfo(_org().timezone)
    end = datetime.combine(until + timedelta(days=1), time.min, tzinfo=zone)
    created = 0
    participants = CalendarEventParticipant.objects.filter(
        event__paid=True, event__end__lte=end, event__end__gte=end - timedelta(days=120)
    ).select_related("event", "tutor")
    for participant in participants:
        event = participant.event
        key = f"event:{event.pk}:{participant.tutor_id}"
        if PayItem.objects.filter(source_key=key).exists():
            continue
        profile = TutorPayProfile.objects.filter(tutor=participant.tutor).first()
        if profile is None or profile.hourly_rate is None:
            continue
        hours = Decimal((event.end - event.start).total_seconds() / 3600).quantize(Decimal("0.01"))
        amount = Money(
            profile.hourly_rate * hours, currency_for(participant.tutor)
        ).round_to_minor()
        _create_item(
            tutor=participant.tutor, kind=PayItem.Kind.EVENT, source_key=key,
            description=event.title, day=event.start.astimezone(zone).date(), amount=amount,
            quantity=hours, unit="hour", branch_id=event.branch_id,
        )  # fmt: skip
        created += 1
    return created


MANUAL_KINDS = {
    PayItem.Kind.BONUS, PayItem.Kind.REFERRAL, PayItem.Kind.ADJUSTMENT, PayItem.Kind.DEDUCTION,
    PayItem.Kind.SALARY,
}  # fmt: skip


@transaction.atomic
def create_manual_item(
    *, tutor: TutorProfile, kind: str, description: str, amount: Money, day: date
) -> PayItem:
    if kind not in MANUAL_KINDS:
        raise BusinessRuleViolation(_("Choose bonus, referral, adjustment, deduction or salary."))
    if amount.is_zero():
        raise BusinessRuleViolation(_("Enter an amount."))
    if kind == PayItem.Kind.DEDUCTION and amount.is_positive():
        amount = Money(-amount.amount, amount.currency)
    import secrets

    return _create_item(
        tutor=tutor, kind=kind, source_key=f"manual:{secrets.token_hex(8)}",
        description=description, day=day, amount=amount.round_to_minor(),
    )  # fmt: skip


@transaction.atomic
def void_item(item: PayItem) -> PayItem:
    if item.status not in OPEN:
        raise BusinessRuleViolation(
            _("Items in a pay run or paid can't be cancelled: add an adjustment instead.")
        )
    _void(item, "cancelled by staff")
    return item


# --- expenses and mileage (T04, T05) --------------------------------------------------------


@transaction.atomic
def submit_expense(
    *, tutor: TutorProfile, category: ExpenseCategory, day: date, description: str,
    amount: Money | None = None, tax: Money | None = None, distance: Decimal | None = None,
    receipt: Any = None, lesson: Any = None, job: Any = None, client: Any = None,
    rebillable: bool | None = None,
) -> Expense:  # fmt: skip
    if not category.active:
        raise BusinessRuleViolation(_("This category isn't available."))
    currency = currency_for(tutor)
    if category.kind == ExpenseCategory.Kind.MILEAGE:
        if distance is None or distance <= 0:
            raise BusinessRuleViolation(
                _("Enter the distance."), extra={"errors": {"distance": [_("Required.")]}}
            )
        rate = category.mileage_rate or Decimal(0)
        amount = Money(rate * distance, currency).round_to_minor()
    elif amount is None or not amount.is_positive():
        raise BusinessRuleViolation(
            _("Enter the amount."), extra={"errors": {"amount": [_("Required.")]}}
        )
    else:
        amount = Money(amount.amount, currency)  # claims are paid in the tutor's currency
    if category.limit_amount is not None and amount.amount > category.limit_amount:
        raise BusinessRuleViolation(
            _("The limit for %(category)s is %(limit)s.")
            % {"category": category.name, "limit": category.limit_amount},
            extra={"errors": {"amount": [_("Over the limit.")]}},
        )
    if (
        client is not None
        and lesson is not None
        and not lesson.attendees.filter(client=client).exists()
    ):
        raise BusinessRuleViolation(_("That client isn't on the lesson."))
    if client is None and lesson is not None:
        attendee = lesson.attendees.select_related("client").first()
        client = attendee.client if attendee else None
    expense = Expense.objects.create(
        tutor=tutor, category=category, status=Expense.Status.SUBMITTED, date=day,
        description=description[:300], currency=amount.currency, amount=amount,
        tax=tax or Money.zero(amount.currency), distance=distance, receipt=receipt,
        lesson=lesson, job=job, client=client,
        rebillable=category.rebillable_default if rebillable is None else rebillable,
        submitted_at=now(), branch_id=lesson.branch_id if lesson is not None else None,
    )  # fmt: skip
    audit.record_create(expense)
    publish(
        events.ExpenseSubmitted(subject_id=expense.pk, tutor_id=str(tutor.pk),
                                amount=_money_dict(amount)),
        branch_id=expense.branch_id,
    )  # fmt: skip
    return expense


def _check_decider(expense: Expense, user: Any) -> None:
    if not has_perm(user, "payroll.expense.approve"):
        raise PermissionDenied()
    membership = expense.tutor.membership
    if membership is not None and membership.user_id == getattr(user, "pk", None):
        raise PermissionDenied(_("You can't approve your own expenses."))
    if expense.status != Expense.Status.SUBMITTED:
        raise BusinessRuleViolation(_("This claim has already been decided."))


@transaction.atomic
def approve_expense(expense: Expense, *, user: Any, comment: str = "") -> Expense:
    """Approval creates the reimbursement pay item, and a client charge when rebillable
    (AC FR-12-4)."""
    expense = (
        Expense.objects.select_for_update().select_related("tutor", "category").get(pk=expense.pk)
    )
    _check_decider(expense, user)
    with audit.track(expense, action="approve"):
        expense.status = Expense.Status.APPROVED
        expense.decided_by = user
        expense.decided_at = now()
        expense.decision_comment = comment[:500]
        expense.save()
    kind = (
        PayItem.Kind.MILEAGE if expense.category.kind == ExpenseCategory.Kind.MILEAGE
        else PayItem.Kind.EXPENSE
    )  # fmt: skip
    _create_item(
        tutor=expense.tutor, kind=kind, source_key=f"expense:{expense.pk}",
        description=expense.description, day=expense.date, amount=expense.amount,
        branch_id=expense.branch_id, expense=expense,
    )  # fmt: skip
    if expense.rebillable and expense.client is not None:
        from tutortrack.billing.services import create_ad_hoc_charge

        markup = _decimal(get_setting("payroll.expense_markup_percent"))
        price = (expense.amount * (1 + markup / 100)).round_to_minor()
        charge = create_ad_hoc_charge(
            client=expense.client, description=expense.description, unit_price=price,
            day=expense.date, job=expense.job, category="expense", user=user,
        )  # fmt: skip
        Expense.objects.filter(pk=expense.pk).update(charge_id=charge.pk)
        expense.charge_id = charge.pk
    publish(
        events.ExpenseApproved(subject_id=expense.pk, tutor_id=str(expense.tutor_id),
                               amount=_money_dict(expense.amount)),
        branch_id=expense.branch_id,
    )  # fmt: skip
    return expense


@transaction.atomic
def reject_expense(expense: Expense, *, user: Any, comment: str) -> Expense:
    expense = Expense.objects.select_for_update().select_related("tutor").get(pk=expense.pk)
    _check_decider(expense, user)
    if not comment.strip():
        raise BusinessRuleViolation(
            _("Say why the claim is rejected."), extra={"errors": {"comment": [_("Required.")]}}
        )
    with audit.track(expense, action="reject"):
        expense.status = Expense.Status.REJECTED
        expense.decided_by = user
        expense.decided_at = now()
        expense.decision_comment = comment[:500]
        expense.save()
    publish(
        events.ExpenseRejected(subject_id=expense.pk, tutor_id=str(expense.tutor_id),
                               amount=_money_dict(expense.amount), comment=comment[:500]),
        branch_id=expense.branch_id,
    )  # fmt: skip
    return expense


def expense_reminder(expense_id: Any) -> bool:
    """Approvers are reminded about a claim still waiting (ExpenseApprovalWorkflow)."""
    from tutortrack.comms import services as comms

    expense = Expense.objects.select_related("tutor").filter(pk=expense_id).first()
    if expense is None or expense.status != Expense.Status.SUBMITTED:
        return False
    title = _("Expense claim waiting: %(name)s") % {"name": expense.tutor.full_name}
    body = f"{expense.description} ({expense.amount.amount} {expense.currency})"
    comms.notify("staff_expense_submitted", (title, body, "/payroll/expenses"),
                 key=f"expense:{expense.pk}:{now():%Y%m%d}")  # fmt: skip
    return True


# --- pay runs (T06) -------------------------------------------------------------------------


def _items_in_scope(pay_run: PayRun) -> Any:
    qs = PayItem.objects.filter(date__lte=pay_run.period_end)
    if not pay_run.all_branches:
        qs = qs.filter(branch_id=pay_run.branch_id)
    return qs


@transaction.atomic
def create_pay_run(
    *, period_start: date, period_end: date, branch: Any = None, start_workflow: bool = True
) -> tuple[PayRun, bool]:
    if period_end < period_start:
        raise BusinessRuleViolation(_("The period ends before it starts."))
    existing = PayRun.objects.filter(
        period_start=period_start, period_end=period_end, all_branches=branch is None,
        **({"branch": branch} if branch is not None else {}),
        status__in=[PayRun.Status.DRAFT, PayRun.Status.REVIEW, PayRun.Status.APPROVED,
                    PayRun.Status.PAYING],
    ).first()  # fmt: skip
    if existing is not None:
        return existing, False
    pay_run = PayRun.objects.create(
        number=next_number("pay_run", prefix="PR-"), period_start=period_start,
        period_end=period_end, all_branches=branch is None,
        branch_id=getattr(branch, "pk", None),
    )  # fmt: skip
    audit.record_create(pay_run)
    publish(events.PayRunCreated(subject_id=pay_run.pk, number=pay_run.number))
    if start_workflow:
        from tutortrack.core.workflows import start

        from .processes import PayRunInput, PayRunWorkflow, pay_run_workflow_id

        wid = pay_run_workflow_id(pay_run.organisation_id, pay_run.pk)
        PayRun.objects.filter(pk=pay_run.pk).update(workflow_id=wid)
        start(PayRunWorkflow,
              PayRunInput(organisation_id=str(pay_run.organisation_id), pay_run_id=str(pay_run.pk)),
              id=wid, subject=("pay_run", str(pay_run.pk)))  # fmt: skip
    return pay_run, True


@transaction.atomic
def assemble(pay_run_id: Any) -> dict[str, Any]:
    """Collect ready items up to the period end into the run and work out each payout."""
    pay_run = PayRun.objects.select_for_update().get(pk=pay_run_id)
    if pay_run.status not in (PayRun.Status.DRAFT, PayRun.Status.REVIEW):
        return {"status": pay_run.status}
    sync_event_pay(pay_run.period_end)
    for item in _items_in_scope(pay_run).filter(status=PayItem.Status.HELD):
        evaluate_holds(item)
    _items_in_scope(pay_run).filter(status=PayItem.Status.READY, pay_run__isnull=True).update(
        status=PayItem.Status.IN_PAY_RUN, pay_run=pay_run, updated_at=now()
    )
    _recompute(pay_run)
    pay_run.status = PayRun.Status.REVIEW
    pay_run.save(update_fields=["status", "updated_at"])
    return {"status": pay_run.status, "totals": pay_run.totals}


def _recompute(pay_run: PayRun) -> None:
    """Payout per tutor and currency, totals, warnings and how many approvals it needs."""
    sums: dict[tuple[Any, str], Decimal] = defaultdict(Decimal)
    items = list(pay_run.items.filter(status=PayItem.Status.IN_PAY_RUN).select_related("tutor"))
    tutors = {i.tutor_id: i.tutor for i in items}
    for item in items:
        sums[(item.tutor_id, item.currency)] += item.amount.amount
    minimum = _decimal(get_setting("payroll.min_payout"))
    warnings: list[dict[str, str]] = []
    pay_run.payouts.filter(status=Payout.Status.PENDING).delete()
    totals: dict[str, Decimal] = defaultdict(Decimal)
    for (tutor_id, currency), amount in sorted(sums.items(), key=lambda kv: str(kv[0])):
        tutor = tutors[tutor_id]
        if amount <= 0 or amount < minimum:
            pay_run.items.filter(tutor_id=tutor_id, currency=currency).update(
                status=PayItem.Status.READY, pay_run=None
            )
            reason = "negative" if amount <= 0 else "below_minimum"
            warnings.append({"tutor": tutor.full_name, "code": reason,
                             "message": _("%(name)s: %(amount)s %(currency)s carried forward.")
                             % {"name": tutor.full_name, "amount": amount,
                                "currency": currency}})  # fmt: skip
            continue
        profile = profile_for(tutor)
        payout = Payout.objects.create(
            pay_run=pay_run,
            tutor=tutor,
            currency=currency,
            amount=Money(amount, currency),
            method=profile.method,
        )
        pay_run.items.filter(tutor_id=tutor_id, currency=currency).update(payout=payout)
        totals[currency] += amount
        problem = _payout_problem(profile)
        if problem:
            warnings.append({"tutor": tutor.full_name, "code": problem[0], "message": problem[1]})
    held = PayItem.objects.filter(status=PayItem.Status.HELD, date__lte=pay_run.period_end)
    if held.exists():
        warnings.append({"tutor": "", "code": "held",
                         "message": _("%(count)s items are on hold and not included.")
                         % {"count": held.count()}})  # fmt: skip
    pay_run.totals = {c: str(v) for c, v in totals.items()}
    pay_run.warnings = warnings
    threshold = _decimal(get_setting("payroll.dual_approval_threshold"), "0")
    pay_run.approvals_required = (
        2 if threshold and any(v > threshold for v in totals.values()) else 1
    )
    pay_run.save(update_fields=["totals", "warnings", "approvals_required", "updated_at"])


def _payout_problem(profile: TutorPayProfile) -> tuple[str, str] | None:
    name = profile.tutor.full_name
    if profile.method == PayMethod.BANK_FILE and not profile.bank_details:
        return "no_bank_details", _("%(name)s has no bank details.") % {"name": name}
    if profile.method == PayMethod.STRIPE_CONNECT and not profile.stripe_payouts_enabled:
        return "no_stripe", _("%(name)s hasn't finished Stripe setup.") % {"name": name}
    return None


def _editable(pay_run: PayRun) -> None:
    if pay_run.status != PayRun.Status.REVIEW:
        raise BusinessRuleViolation(_("Only pay runs under review can be changed."))
    if pay_run.approvals:
        raise BusinessRuleViolation(_("Someone has approved this run: cancel it to change it."))


@transaction.atomic
def remove_item(pay_run: PayRun, item: PayItem) -> PayRun:
    pay_run = PayRun.objects.select_for_update().get(pk=pay_run.pk)
    _editable(pay_run)
    if item.pay_run_id != pay_run.pk:
        raise NotFound()
    with audit.track(item, action="remove_from_pay_run"):
        item.status = PayItem.Status.READY
        item.pay_run = None
        item.payout = None
        item.hold_reasons = sorted({*item.hold_reasons, "manual"})
        item.hold_note = _("Removed from %(run)s") % {"run": pay_run.number}
        item.save()
    evaluate_holds(item)
    _recompute(pay_run)
    return pay_run


@transaction.atomic
def add_adjustment(
    pay_run: PayRun, *, tutor: TutorProfile, description: str, amount: Money
) -> PayRun:
    pay_run = PayRun.objects.select_for_update().get(pk=pay_run.pk)
    _editable(pay_run)
    item = create_manual_item(
        tutor=tutor, kind=PayItem.Kind.ADJUSTMENT, description=description, amount=amount,
        day=pay_run.period_end,
    )  # fmt: skip
    if item.status == PayItem.Status.READY:
        PayItem.objects.filter(pk=item.pk).update(status=PayItem.Status.IN_PAY_RUN, pay_run=pay_run)
    _recompute(pay_run)
    return pay_run


@transaction.atomic
def approve(pay_run: PayRun, *, user: Any) -> PayRun:
    """Record an approval; the run is approved once enough different people agree."""
    if not has_perm(user, "payroll.payrun.approve"):
        raise PermissionDenied()
    pay_run = PayRun.objects.select_for_update().get(pk=pay_run.pk)
    if pay_run.status != PayRun.Status.REVIEW:
        raise BusinessRuleViolation(_("Only pay runs under review can be approved."))
    if any(a["user"] == str(user.pk) for a in pay_run.approvals):
        raise BusinessRuleViolation(_("A second approval must come from someone else."))
    if not pay_run.payouts.exists():
        raise BusinessRuleViolation(_("There's nothing to pay in this run."))
    with audit.track(pay_run, action="approve"):
        pay_run.approvals = [*pay_run.approvals, {"user": str(user.pk),
                             "name": user.get_full_name() or user.email,
                             "at": now().isoformat()}]  # fmt: skip
        if len(pay_run.approvals) >= pay_run.approvals_required:
            pay_run.status = PayRun.Status.APPROVED
            pay_run.approved_at = now()
        pay_run.save()
    if pay_run.status == PayRun.Status.APPROVED:
        pay_run.items.filter(status=PayItem.Status.IN_PAY_RUN).update(
            status=PayItem.Status.APPROVED
        )
        publish(events.PayRunApproved(subject_id=pay_run.pk, number=pay_run.number))
        _signal(pay_run, "approved")
    return pay_run


def _signal(pay_run: PayRun, name: str) -> None:
    from tutortrack.core.models import WorkflowLink
    from tutortrack.core.workflows import signal_now

    wid = pay_run.workflow_id

    def send() -> None:
        if wid and WorkflowLink.objects.filter(workflow_id=wid, status="running").exists():
            signal_now(wid, name)

    transaction.on_commit(send)


@transaction.atomic
def cancel_pay_run(pay_run: PayRun) -> PayRun:
    pay_run = PayRun.objects.select_for_update().get(pk=pay_run.pk)
    if pay_run.status not in (PayRun.Status.DRAFT, PayRun.Status.REVIEW, PayRun.Status.APPROVED):
        raise BusinessRuleViolation(_("Payouts have started: this run can't be cancelled."))
    with audit.track(pay_run, action="cancel"):
        pay_run.items.exclude(status=PayItem.Status.VOID).update(
            status=PayItem.Status.READY, pay_run=None, payout=None
        )
        pay_run.payouts.all().delete()
        pay_run.status = PayRun.Status.CANCELLED
        pay_run.save()
    for item in PayItem.objects.filter(status=PayItem.Status.READY).exclude(hold_reasons=[]):
        evaluate_holds(item)
    _signal(pay_run, "cancelled")
    return pay_run


# --- statements (T07) -----------------------------------------------------------------------


def _tutor_code(tutor: TutorProfile) -> str:
    return str(tutor.pk).replace("-", "")[-6:].upper()


@transaction.atomic
def issue_statements(pay_run_id: Any) -> int:
    """A self-billing invoice for self-employed tutors who agreed to self-billing, a
    remittance advice for everyone else (FR-12-6)."""
    pay_run = PayRun.objects.get(pk=pay_run_id)
    org = _org()
    issued = 0
    vat_percent = _decimal(get_setting("payroll.self_billing_vat_percent"), "20")
    for payout in pay_run.payouts.select_related("tutor").exclude(status=Payout.Status.CARRIED):
        if PayStatement.objects.filter(payout=payout).exists():
            continue
        tutor = payout.tutor
        profile = profile_for(tutor)
        self_billing = (
            tutor.employment_type == TutorProfile.Employment.SELF_EMPLOYED
            and profile.self_billing_agreed_at is not None
        )
        net = payout.amount
        vat = Money.zero(net.currency)
        if self_billing and profile.vat_registered:
            vat = (net * vat_percent / Decimal(100)).round_to_minor()
        if self_billing:
            number = next_number(f"self_billing:{tutor.pk}", prefix=f"SB-{_tutor_code(tutor)}-",
                                 padding=4)  # fmt: skip
        else:
            number = next_number("remittance", prefix="RA-")
        statement = PayStatement.objects.create(
            payout=payout, tutor=tutor,
            kind=PayStatement.Kind.SELF_BILLING if self_billing else PayStatement.Kind.REMITTANCE,
            number=number, issued_at=now(), currency=net.currency, net=net, vat=vat,
            total=net + vat,
            snapshot={
                "organisation": {"name": org.legal_name or org.name, "address": org.address,
                                 "vat_number": org.vat_number},
                "tutor": {"name": profile.payee_name or tutor.full_name,
                          "vat_number": profile.vat_number if profile.vat_registered else "",
                          "agreement": profile.self_billing_agreement_version},
                "period": [pay_run.period_start.isoformat(), pay_run.period_end.isoformat()],
                "pay_run": pay_run.number,
            },
        )  # fmt: skip
        if self_billing:
            issued_event = events.SelfBillingStatementIssued(
                subject_id=statement.pk, tutor_id=str(tutor.pk), number=number
            )
            publish(issued_event)
        issued += 1
    return issued


# --- payouts (T08, T09) ---------------------------------------------------------------------


@transaction.atomic
def send_payouts(pay_run_id: Any) -> int:
    """Stripe transfers go now; bank file, manual and payroll-provider payouts wait for
    staff to mark them paid. Returns how many payouts are still outstanding."""
    from .payouts import get_provider

    pay_run = PayRun.objects.select_for_update().get(pk=pay_run_id)
    if pay_run.status == PayRun.Status.APPROVED:
        pay_run.status = PayRun.Status.PAYING
        pay_run.save(update_fields=["status", "updated_at"])
    provider = get_provider()
    for payout in pay_run.payouts.select_related("tutor").filter(
        status=Payout.Status.PENDING, method=PayMethod.STRIPE_CONNECT
    ):
        profile = profile_for(payout.tutor)
        if not profile.stripe_account_id:
            fail_payout(payout, reason=_("No Stripe account."))
            continue
        result = provider.transfer(
            profile.stripe_account_id, amount=payout.amount,
            description=f"{pay_run.number}", idempotency_key=f"payout-{payout.pk}",
        )  # fmt: skip
        if result.status == "failed":
            fail_payout(payout, reason=result.message)
        elif result.status == "paid":
            _mark_payout_paid(payout, reference=result.ref, provider_ref=result.ref)
        else:
            Payout.objects.filter(pk=payout.pk).update(
                status=Payout.Status.PROCESSING, provider_ref=result.ref
            )
    return outstanding(pay_run)


def outstanding(pay_run: PayRun) -> int:
    return pay_run.payouts.filter(
        status__in=[Payout.Status.PENDING, Payout.Status.PROCESSING]
    ).count()


def _mark_payout_paid(payout: Payout, *, reference: str = "", provider_ref: str = "") -> None:
    with audit.track(payout, action="paid"):
        payout.status = Payout.Status.PAID
        payout.paid_at = now()
        payout.reference = reference[:100]
        payout.provider_ref = provider_ref[:100] or payout.provider_ref
        payout.save()
    payout.items.filter(status=PayItem.Status.APPROVED).update(status=PayItem.Status.PAID)
    publish(
        events.PayoutPaid(subject_id=payout.pk, tutor_id=str(payout.tutor_id),
                          pay_run_id=str(payout.pay_run_id), amount=_money_dict(payout.amount)),
    )  # fmt: skip


@transaction.atomic
def fail_payout(payout: Payout, *, reason: str) -> Payout:
    """Failed payouts send their items back for the next run (FR-12-7)."""
    with audit.track(payout, action="failed"):
        payout.status = Payout.Status.FAILED
        payout.failure_reason = reason[:500]
        payout.save()
    payout.items.exclude(status=PayItem.Status.PAID).update(
        status=PayItem.Status.READY, pay_run=None, payout=None
    )
    publish(
        events.PayoutFailed(subject_id=payout.pk, tutor_id=str(payout.tutor_id),
                            pay_run_id=str(payout.pay_run_id),
                            amount=_money_dict(payout.amount), reason=reason[:500]),
    )  # fmt: skip
    from tutortrack.comms import services as comms

    title = _("Payout to %(name)s failed") % {"name": payout.tutor.full_name}
    comms.notify("staff_payout_failed", (title, reason[:300], f"/payroll/runs/{payout.pay_run_id}"),
                 key=f"payout:{payout.pk}")  # fmt: skip
    return payout


@transaction.atomic
def mark_paid(
    pay_run: PayRun, *, payout_ids: list[Any] | None = None, reference: str = ""
) -> PayRun:
    pay_run = PayRun.objects.select_for_update().get(pk=pay_run.pk)
    if pay_run.status not in (PayRun.Status.APPROVED, PayRun.Status.PAYING):
        raise BusinessRuleViolation(_("Approve the pay run first."))
    payouts = pay_run.payouts.filter(status__in=[Payout.Status.PENDING, Payout.Status.PROCESSING])
    if payout_ids:
        payouts = payouts.filter(pk__in=payout_ids)
    for payout in payouts:
        _mark_payout_paid(payout, reference=reference)
    if pay_run.status == PayRun.Status.APPROVED:
        pay_run.status = PayRun.Status.PAYING
        pay_run.save(update_fields=["status", "updated_at"])
    _signal(pay_run, "settled")
    return pay_run


@transaction.atomic
def finalise(pay_run_id: Any) -> str:
    pay_run = PayRun.objects.select_for_update().get(pk=pay_run_id)
    if pay_run.status in (PayRun.Status.PAID, PayRun.Status.PARTIALLY_FAILED):
        return pay_run.status
    if outstanding(pay_run):
        return "outstanding"
    failed = pay_run.payouts.filter(status=Payout.Status.FAILED).count()
    pay_run.status = PayRun.Status.PARTIALLY_FAILED if failed else PayRun.Status.PAID
    pay_run.paid_at = now()
    pay_run.save(update_fields=["status", "paid_at", "updated_at"])
    if failed:
        publish(events.PayRunPartiallyFailed(subject_id=pay_run.pk, number=pay_run.number,
                                             failed=failed))  # fmt: skip
    else:
        publish(events.PayRunPaid(subject_id=pay_run.pk, number=pay_run.number))
    return pay_run.status


def remind_approvers(pay_run_id: Any) -> bool:
    from tutortrack.comms import services as comms

    pay_run = PayRun.objects.filter(pk=pay_run_id).first()
    if pay_run is None or pay_run.status != PayRun.Status.REVIEW:
        return False
    title = _("Pay run %(number)s is waiting for approval") % {"number": pay_run.number}
    body = ", ".join(f"{v} {c}" for c, v in pay_run.totals.items())
    comms.notify("staff_pay_run_review", (title, body, f"/payroll/runs/{pay_run.pk}"),
                 key=f"pay_run:{pay_run.pk}:{now():%Y%m%d}")  # fmt: skip
    return True


# --- bank files (T08) -----------------------------------------------------------------------


@transaction.atomic
def generate_bank_file(
    pay_run: PayRun, *, fmt: str | None = None, user: Any = None
) -> BankFileExport:
    from . import bankfiles

    pay_run = PayRun.objects.select_for_update().get(pk=pay_run.pk)
    if pay_run.status not in (PayRun.Status.APPROVED, PayRun.Status.PAYING):
        raise BusinessRuleViolation(_("Approve the pay run first."))
    fmt = fmt or str(get_setting("payroll.bank_file_format"))
    originator = PayrollOriginator.objects.first()
    if fmt != "csv" and originator is None:
        raise BusinessRuleViolation(_("Add the account you pay from in pay settings."))
    payouts = list(
        pay_run.payouts.select_related("tutor").filter(
            method=PayMethod.BANK_FILE, status=Payout.Status.PENDING
        )
    )
    if not payouts:
        raise BusinessRuleViolation(_("No bank transfers are waiting in this run."))
    lines = []
    for payout in payouts:
        profile = profile_for(payout.tutor)
        details = banking.loads(profile.bank_details)
        if not details:
            raise BusinessRuleViolation(
                _("%(name)s has no bank details.") % {"name": payout.tutor.full_name}
            )
        lines.append(bankfiles.Line(profile.payee_name or payout.tutor.full_name, details,
                                    payout.amount, pay_run.number))  # fmt: skip
    origin_details = banking.loads(originator.bank_details) if originator else {}
    extra = {k: origin_details.pop(k) for k in list(origin_details)
             if k in ("company_id", "immediate_destination", "destination_name", "apca_id",
                      "bank")}  # fmt: skip
    org = _org()
    payer = bankfiles.Originator(originator.name if originator else org.name, origin_details, extra)
    filename, content = bankfiles.write(
        fmt, payer, lines, when=now(), file_id=f"{pay_run.number}-{fmt}"
    )
    totals: dict[str, Decimal] = defaultdict(Decimal)
    for line in lines:
        totals[line.amount.currency] += line.amount.amount
    export = BankFileExport.objects.create(
        pay_run=pay_run, format=fmt, filename=filename, content=content,
        payout_count=len(lines), total={c: str(v) for c, v in totals.items()},
        generated_by=user,
    )  # fmt: skip
    audit.record(export, "generate", {"format": [None, fmt], "payouts": [None, len(lines)]})
    return export


# --- external payroll exports (T10) ---------------------------------------------------------

EXPORT_FORMATS = {
    "generic": ["employee", "email", "hours", "amount", "currency", "period_start", "period_end"],
    "xero": ["Employee", "Earnings Rate", "Units", "Amount", "Period Start", "Period End"],
    "quickbooks": ["Employee Name", "Pay Item", "Hours", "Amount", "Pay Period End"],
    "brightpay": ["Employee", "Payment", "Hours", "Amount"],
    "gusto": ["employee_email", "regular_hours", "bonus", "reimbursement"],
}


def payroll_export(pay_run: PayRun, fmt: str) -> tuple[str, str]:
    """Hours and amounts for employed tutors, for the organisation's payroll provider."""
    if fmt not in EXPORT_FORMATS:
        raise NotFound()
    rows: dict[Any, dict[str, Any]] = {}
    items = (
        pay_run.items.select_related("tutor")
        .filter(payout__method=PayMethod.EXTERNAL_PAYROLL)
        .exclude(status=PayItem.Status.VOID)
    )
    for item in items:
        row = rows.setdefault(item.tutor_id, {"tutor": item.tutor, "hours": Decimal(0),
                                              "pay": Decimal(0), "bonus": Decimal(0),
                                              "expenses": Decimal(0),
                                              "currency": item.currency})  # fmt: skip
        if item.unit == "hour":
            row["hours"] += item.quantity
        if item.kind in (PayItem.Kind.EXPENSE, PayItem.Kind.MILEAGE):
            row["expenses"] += item.amount.amount
        elif item.kind in (PayItem.Kind.BONUS, PayItem.Kind.REFERRAL):
            row["bonus"] += item.amount.amount
        else:
            row["pay"] += item.amount.amount
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(EXPORT_FORMATS[fmt])
    start, end = pay_run.period_start.isoformat(), pay_run.period_end.isoformat()
    for row in rows.values():
        t = row["tutor"]
        total = row["pay"] + row["bonus"] + row["expenses"]
        writer.writerow({
            "generic": [t.full_name, t.email, row["hours"], total, row["currency"], start, end],
            "xero": [t.full_name, "Ordinary Hours", row["hours"], total, start, end],
            "quickbooks": [t.full_name, "Hourly", row["hours"], total, end],
            "brightpay": [t.full_name, "Basic", row["hours"], total],
            "gusto": [t.email, row["hours"], row["bonus"], row["expenses"]],
        }[fmt])  # fmt: skip
    return f"{pay_run.number}-{fmt}.csv", out.getvalue()


# --- schedules ------------------------------------------------------------------------------


def scheduled_period(cadence: str, today: date) -> tuple[date, date]:
    """The period that ended yesterday for a run opened on ``today``."""
    end = today - timedelta(days=1)
    if cadence == "weekly":
        return end - timedelta(days=6), end
    if cadence == "fortnightly":
        return end - timedelta(days=13), end
    if cadence == "semi_monthly":
        if end.day <= 15:
            return end.replace(day=1), end
        return end.replace(day=16), end
    previous = (today.replace(day=1) - timedelta(days=1)).replace(day=min(today.day, 28))
    return previous, end


def org_today() -> date:
    return now().astimezone(ZoneInfo(_org().timezone)).date()


def statement_pdf(statement: PayStatement) -> bytes:
    from django.template.loader import render_to_string
    from weasyprint import HTML

    items = list(statement.payout.items.order_by("date"))
    html = render_to_string(
        "payroll/statement.html", {"statement": statement, "items": items,
                                   "settings": settings},
    )  # fmt: skip
    return bytes(HTML(string=html).write_pdf())
