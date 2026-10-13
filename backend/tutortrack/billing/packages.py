"""Packages (E10-T12, FR-10-7): selling, activating, consuming, extending, cancelling and
expiring prepaid bundles of hours, lessons or credit.

* **Sale:** a ``package`` charge on its own invoice (issued at once, setting) - the money is
  an ordinary invoice, so it reaches the ledger, payments and accounting sync unchanged.
* **Activation:** when that invoice is paid (or issued, ``billing.package_activation``).
* **Consumption:** ``consume_for_attendee`` is called by charge sync for every delivered
  (or chargeable cancelled) lesson on a package job or a client-booked lesson. Units come
  from the oldest-expiring eligible package first (FIFO); a lesson only partly covered is
  charged for the rest (overage falls back to pay-as-you-go). Movements are append-only
  ``PackageConsumption`` rows; a changed lesson posts reversals.
* **Expiry:** ``PackageExpiryWorkflow`` reminds N days before and then writes off what is
  left (an ``expiry`` movement whose value is the revenue released).
"""

from __future__ import annotations

import secrets
from collections import defaultdict
from datetime import datetime, time, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from django.db import transaction
from django.db.models import Q, Sum
from django.utils.translation import gettext as _

from tutortrack.core import audit
from tutortrack.core.events import publish
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.money import Money
from tutortrack.core.time import now
from tutortrack.people.models import Client, Student
from tutortrack.tenancy.settings_service import get_setting

from . import events
from .models import Charge, Invoice, PackageConsumption, PackagePurchase

ZERO = Decimal(0)
UNIT = Decimal("0.0001")
HOURS = "hours"
LESSONS = "lessons"
CREDIT = "credit"
USING = (PackageConsumption.Kind.LESSON, PackageConsumption.Kind.REVERSAL)


def _invalid(field_name: str, message: str) -> BusinessRuleViolation:
    return BusinessRuleViolation(message, extra={"errors": {field_name: [message]}})


def unit_price(purchase: PackagePurchase) -> Money:
    if not purchase.units_total:
        return Money.zero(purchase.currency)
    return purchase.price / purchase.units_total


def value_of(purchase: PackagePurchase, units: Decimal) -> Money:
    return (unit_price(purchase) * units).round_to_minor()


def _payload(purchase: PackagePurchase, **extra: Any) -> dict[str, Any]:
    return {
        "subject_id": purchase.pk,
        "client_id": str(purchase.client_id),
        "units_remaining": str(purchase.units_remaining.quantize(Decimal("0.01"))),
        **extra,
    }


# --- sale ---------------------------------------------------------------------------------------


def _snapshot(template: Any) -> dict[str, Any]:
    return {
        "id": str(template.pk),
        "name": template.name,
        "quantity_type": template.quantity_type,
        "quantity": str(template.quantity),
        "price": template.price.to_dict(),
        "validity_days": template.validity_days,
        "valid_until": template.valid_until.isoformat() if template.valid_until else None,
        "refund_policy": template.refund_policy,
        "transferable_between_siblings": template.transferable_between_siblings,
        "auto_renew": template.auto_renew,
        "tax_rate_id": str(template.tax_rate_id) if template.tax_rate_id else None,
    }


@transaction.atomic
def sell_package(
    *,
    client: Client,
    template: Any,
    student: Student | None = None,
    user: Any = None,
    source: str = PackagePurchase.Source.SALE,
    invoice_now: bool | None = None,
) -> PackagePurchase:
    """Sell a package template to a client (FR-10-7): a ``package`` charge, invoiced at once
    (``billing.package_invoice_immediately``) or on the next run."""
    from . import services

    if not template.active:
        raise _invalid("template", _("This package isn't on sale."))
    if template.currency != client.currency:
        raise _invalid("template", _("This package is priced in another currency."))
    if student is not None and student.client_id != client.pk:
        raise _invalid("student", _("That student isn't in this client's account."))
    purchase = PackagePurchase.objects.create(
        client=client,
        branch_id=client.branch_id,
        student=student,
        template=template,
        template_snapshot=_snapshot(template),
        name=template.name,
        quantity_type=template.quantity_type,
        units_total=template.quantity,
        currency=template.currency,
        price=template.price,
        services=[str(pk) for pk in template.services.values_list("pk", flat=True)],
        shareable=template.transferable_between_siblings,
        auto_renew=template.auto_renew,
        source=source,
        created_by=user,
    )
    rate = template.tax_rate
    charge = services._create_charge(
        client=client,
        kind=Charge.Kind.PACKAGE,
        source_key=f"package:{purchase.pk}",
        description=_("Package: %(name)s") % {"name": template.name},
        day=services.org_today(),
        price=template.price,
        quantity=Decimal(1),
        unit="package",
        tax_percent=rate.percent if rate else ZERO,
        tax_rate_id=rate.pk if rate else None,
        student=student,
        category="package",
        user=user,
    )
    purchase.charge = charge
    purchase.save(update_fields=["charge", "updated_at"])
    audit.record_create(purchase)
    publish(
        events.PackagePurchased(
            **_payload(purchase, name=purchase.name, price=purchase.price.to_dict())
        ),
        branch_id=purchase.branch_id,
    )
    if (
        invoice_now
        if invoice_now is not None
        else get_setting("billing.package_invoice_immediately")
    ):
        for draft in services.build_drafts(Charge.objects.filter(pk=charge.pk), skip_small=False):
            invoice = services.issue_invoice(draft, user=user)
            activate_for_invoice(invoice.pk)
    elif template.price.is_zero():
        activate(purchase)
    purchase.refresh_from_db()
    return purchase


def activate_for_invoice(invoice_id: Any) -> list[PackagePurchase]:
    """``invoice.paid`` / ``invoice.issued``: activate the packages sold on it (setting)."""
    invoice = Invoice.objects.filter(pk=invoice_id).first()
    if invoice is None:
        return []
    when = str(get_setting("billing.package_activation"))
    ready = invoice.status == Invoice.Status.PAID or (
        when == "issue" and invoice.status in Invoice.OPEN
    )
    if not ready:
        return []
    out = []
    for purchase in PackagePurchase.objects.filter(
        charge__invoice=invoice, status=PackagePurchase.Status.PENDING
    ):
        out.append(activate(purchase))
    return out


def _expiry(purchase: PackagePurchase, start: datetime) -> datetime | None:
    from tutortrack.tenancy.models import Organisation

    snapshot = purchase.template_snapshot or {}
    candidates: list[datetime] = []
    if snapshot.get("validity_days"):
        candidates.append(start + timedelta(days=int(snapshot["validity_days"])))
    if snapshot.get("valid_until"):
        from datetime import date

        tz = ZoneInfo(Organisation.objects.get(pk=purchase.organisation_id).timezone)
        day = date.fromisoformat(snapshot["valid_until"]) + timedelta(days=1)
        candidates.append(datetime.combine(day, time.min, tzinfo=tz))
    return min(candidates) if candidates else None


@transaction.atomic
def activate(purchase: PackagePurchase, *, user: Any = None) -> PackagePurchase:
    purchase = PackagePurchase.objects.select_for_update().get(pk=purchase.pk)
    if purchase.status != PackagePurchase.Status.PENDING:
        return purchase
    moment = now()
    with audit.track(purchase, action="activate"):
        purchase.status = PackagePurchase.Status.ACTIVE
        purchase.activated_at = moment
        purchase.expires_at = purchase.expires_at or _expiry(purchase, moment)
        purchase.save()
    publish(
        events.PackageActivated(
            **_payload(
                purchase,
                expires_at=purchase.expires_at.isoformat() if purchase.expires_at else None,
            )
        ),
        branch_id=purchase.branch_id,
    )
    _track_expiry(purchase)
    return purchase


def _running(workflow_id: str) -> bool:
    from tutortrack.core.models import WorkflowLink

    return bool(workflow_id) and (
        WorkflowLink.objects.filter(workflow_id=workflow_id, status="running").exists()
    )


def _track_expiry(purchase: PackagePurchase) -> None:
    """Start ``PackageExpiryWorkflow`` (after commit) unless one is already following it."""
    if purchase.expires_at is None or _running(purchase.workflow_id):
        return
    from tutortrack.core.workflows import start

    from .processes import PackageExpiryWorkflow, PackageInput, package_workflow_id

    wid = package_workflow_id(purchase.organisation_id, purchase.pk, secrets.token_hex(3))
    PackagePurchase.objects.filter(pk=purchase.pk).update(workflow_id=wid)
    purchase.workflow_id = wid
    start(
        PackageExpiryWorkflow,
        PackageInput(
            organisation_id=str(purchase.organisation_id),
            purchase_id=str(purchase.pk),
            expires_at=purchase.expires_at.isoformat(),
        ),
        id=wid,
        subject=("package", str(purchase.pk)),
        branch_id=purchase.branch_id,
    )


def cancel_for_charges(charges: list[Charge], *, reason: str) -> None:
    """The sale invoice was voided: its packages are cancelled and their charges voided."""
    from . import services

    for charge in charges:
        if charge.kind != Charge.Kind.PACKAGE:
            continue
        purchase = PackagePurchase.objects.filter(charge=charge).first()
        if purchase is None or purchase.units_used:
            continue
        with audit.track(purchase, action="cancel"):
            purchase.status = PackagePurchase.Status.CANCELLED
            purchase.closed_at = now()
            purchase.close_reason = reason[:300]
            purchase.save()
        charge.refresh_from_db()
        if charge.status == Charge.Status.UNINVOICED and charge.invoice_id is None:
            services.void_charge(charge, reason="package cancelled")
        _closed(purchase, "cancelled")


def _closed(purchase: PackagePurchase, why: str) -> None:
    if purchase.workflow_id and _running(purchase.workflow_id):
        from tutortrack.core.workflows import signal

        signal(purchase.workflow_id, "depleted")


# --- consumption --------------------------------------------------------------------------------


def uses_packages(lesson: Any) -> bool:
    """Package jobs, and lessons clients booked themselves (paid by package deduction)."""
    job = lesson.job if lesson.job_id else None
    if job is not None and job.billing_method == "package":
        return True
    return bool(lesson.created_via == "client_booking")


def _full_units(kind: str, lesson: Any, attendee: Any, price: Money) -> Decimal:
    """Units one attendee's lesson uses from a package of ``kind`` (its charge percentage
    applies: a half-charged late cancellation uses half a lesson)."""
    if kind == CREDIT:
        return price.amount
    percent = Decimal(attendee.charge_percent or 0) / Decimal(100)
    if kind == HOURS:
        hours = Decimal(int((lesson.end - lesson.start).total_seconds())) / Decimal(3600)
        return (hours * percent).quantize(UNIT)
    return percent.quantize(UNIT)


def _eligible(attendee: Any, lesson: Any) -> list[PackagePurchase]:
    qs = (
        PackagePurchase.objects.select_for_update()
        .filter(
            client_id=attendee.client_id,
            currency=attendee.currency,
            status=PackagePurchase.Status.ACTIVE,
        )
        .filter(Q(student__isnull=True) | Q(student_id=attendee.student_id) | Q(shareable=True))
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=lesson.start))
    )
    job = lesson.job if lesson.job_id else None
    if job is not None and job.package_template_id:
        qs = qs.filter(template_id=job.package_template_id)
    service = str(lesson.service_id)
    rows = [p for p in qs if not p.services or service in p.services]
    far = datetime.max.replace(tzinfo=ZoneInfo("UTC"))
    rows.sort(key=lambda p: (p.expires_at or far, p.activated_at or p.created_at))
    return rows


def _used_by(attendee: Any) -> dict[Any, Decimal]:
    out: dict[Any, Decimal] = defaultdict(Decimal)
    for row in PackageConsumption.objects.filter(lesson_attendee=attendee, kind__in=USING):
        out[row.purchase_id] += row.units
    return {k: v for k, v in out.items() if v}


def _move(
    purchase: PackagePurchase,
    units: Decimal,
    *,
    kind: str,
    lesson: Any = None,
    attendee: Any = None,
    note: str = "",
) -> PackageConsumption:
    row = PackageConsumption.objects.create(
        purchase=purchase,
        kind=kind,
        lesson=lesson,
        lesson_attendee=attendee,
        units=units,
        currency=purchase.currency,
        value=value_of(purchase, units),
        note=note[:300],
    )
    used = (
        PackageConsumption.objects.filter(purchase=purchase, kind__in=USING).aggregate(
            t=Sum("units")
        )["t"]
        or ZERO
    )
    purchase.units_used = used
    purchase.save(update_fields=["units_used", "updated_at"])
    _after_move(purchase)
    return row


def _after_move(purchase: PackagePurchase) -> None:
    remaining = purchase.units_remaining
    if purchase.status == PackagePurchase.Status.ACTIVE and remaining <= 0:
        purchase.status = PackagePurchase.Status.DEPLETED
        purchase.closed_at = now()
        purchase.save(update_fields=["status", "closed_at", "updated_at"])
        publish(
            events.PackageDepleted(**_payload(purchase, auto_renew=purchase.auto_renew)),
            branch_id=purchase.branch_id,
        )
        _closed(purchase, "depleted")
        return
    if purchase.status == PackagePurchase.Status.DEPLETED and remaining > 0:
        purchase.status = PackagePurchase.Status.ACTIVE  # a lesson gave units back
        purchase.closed_at = None
        purchase.save(update_fields=["status", "closed_at", "updated_at"])
        _track_expiry(purchase)
    low = Decimal(int(get_setting("billing.package_low_units")))
    if (
        purchase.status == PackagePurchase.Status.ACTIVE
        and low
        and 0 < remaining <= low
        and purchase.low_notified_at is None
    ):
        purchase.low_notified_at = now()
        purchase.save(update_fields=["low_notified_at", "updated_at"])
        publish(events.PackageLow(**_payload(purchase)), branch_id=purchase.branch_id)


def consume_for_attendee(attendee: Any, lesson: Any, price: Money) -> Money:
    """Make the attendee's package use match the lesson and return the part of ``price``
    the packages cover (the rest is charged). Idempotent: re-syncing changes nothing;
    a lesson that no longer uses units gives them back (``reversal``)."""
    from tutortrack.scheduling.models import Lesson

    zero = Money.zero(price.currency)
    wanted = (
        price.is_positive()
        and lesson.status in {Lesson.Status.COMPLETED, Lesson.Status.CANCELLED}
        and uses_packages(lesson)
    )
    used = _used_by(attendee)
    purchases = {
        p.pk: p for p in PackagePurchase.objects.select_for_update().filter(pk__in=list(used))
    }

    def covered_fraction() -> Decimal:
        total = ZERO
        for pk, units in used.items():
            purchase = purchases[pk]
            full = _full_units(purchase.quantity_type, lesson, attendee, price)
            if full:
                total += units / full
        return total

    fraction = covered_fraction() if wanted else ZERO
    if used and (not wanted or fraction > 1):
        for pk, units in list(used.items()):  # give everything back, then (maybe) redo
            _move(purchases[pk], -units, kind=PackageConsumption.Kind.REVERSAL,
                  lesson=lesson, attendee=attendee, note=_("Lesson changed"))  # fmt: skip
        used, fraction = {}, ZERO
    if not wanted:
        return zero
    if fraction < 1:
        for purchase in _eligible(attendee, lesson):
            full = _full_units(purchase.quantity_type, lesson, attendee, price)
            if not full:
                continue
            need = (full * (1 - fraction)).quantize(UNIT)
            take = min(need, purchase.units_remaining)
            if take <= 0:
                continue
            _move(purchase, take, kind=PackageConsumption.Kind.LESSON, lesson=lesson,
                  attendee=attendee, note=lesson.title)  # fmt: skip
            fraction += take / full
            if fraction >= 1:
                break
    fraction = min(fraction, Decimal(1))
    if fraction >= 1:
        return price
    return (price * fraction).round_to_minor()


# --- management ---------------------------------------------------------------------------------


@transaction.atomic
def extend_package(purchase: PackagePurchase, *, until: datetime, user: Any = None) -> Any:
    """Move the expiry date (admin, FR-10-7). The expiry workflow follows the new date."""
    purchase = PackagePurchase.objects.select_for_update().get(pk=purchase.pk)
    if purchase.status not in {PackagePurchase.Status.ACTIVE, PackagePurchase.Status.PENDING}:
        raise BusinessRuleViolation(_("Only active packages can be extended."))
    if until <= now():
        raise _invalid("until", _("Choose a date in the future."))
    with audit.track(purchase, action="extend"):
        purchase.expires_at = until
        purchase.save(update_fields=["expires_at", "updated_at"])
    publish(
        events.PackageExtended(**_payload(purchase, expires_at=until.isoformat())),
        branch_id=purchase.branch_id,
    )
    if purchase.status == PackagePurchase.Status.ACTIVE:
        if _running(purchase.workflow_id):
            from tutortrack.core.workflows import signal

            signal(purchase.workflow_id, "extended", until.isoformat())
        else:
            _track_expiry(purchase)
    return purchase


@transaction.atomic
def cancel_package(
    purchase: PackagePurchase, *, reason: str, refund: bool | None = None, user: Any = None
) -> PackagePurchase:
    """Cancel a package. Unused value is credited back by a credit note on its invoice
    (never by editing it), as the template's refund policy allows (or ``refund``)."""
    from . import services

    purchase = PackagePurchase.objects.select_for_update().get(pk=purchase.pk)
    if purchase.status in {PackagePurchase.Status.CANCELLED, PackagePurchase.Status.EXPIRED}:
        raise BusinessRuleViolation(_("This package is already closed."))
    if not reason.strip():
        raise _invalid("reason", _("Give a reason."))
    remaining = max(purchase.units_remaining, ZERO)
    policy = (purchase.template_snapshot or {}).get("refund_policy", "none")
    if refund is None:
        refund = policy == "unused_pro_rata" or (policy == "full" and not purchase.units_used)
    charge = Charge.objects.filter(pk=purchase.charge_id).select_related("invoice").first()
    note = None
    if charge is not None and charge.status == Charge.Status.UNINVOICED:
        if charge.invoice_id:  # on a draft
            services.remove_line(charge.invoice, charge.line)
            charge.refresh_from_db()
        services.void_charge(charge, reason="package cancelled")
    elif refund and charge is not None and charge.invoice_id and remaining > 0:
        line = charge.line
        share = remaining / purchase.units_total if purchase.units_total else ZERO
        amount = min((line.gross * share).round_to_minor(), line.gross - line.credited)
        if amount.is_positive():
            note = services.create_credit_note(
                charge.invoice,
                reason=reason,
                application="invoice" if charge.invoice.is_open else "credit",
                lines=[{"line": line, "amount": amount}],
                user=user,
            )
    if remaining > 0 and purchase.status != PackagePurchase.Status.PENDING:
        PackageConsumption.objects.create(
            purchase=purchase,
            kind=PackageConsumption.Kind.ADJUSTMENT,
            units=remaining,
            currency=purchase.currency,
            value=value_of(purchase, remaining),
            note=_("Cancelled: %(reason)s") % {"reason": reason[:250]},
        )
        purchase.units_expired = purchase.units_expired + remaining
    with audit.track(purchase, action="cancel"):
        purchase.status = PackagePurchase.Status.CANCELLED
        purchase.closed_at = now()
        purchase.close_reason = reason[:300]
        purchase.save()
    publish(
        events.PackageCancelled(
            **_payload(purchase, credit_note_id=str(note.pk) if note else None, reason=reason)
        ),
        branch_id=purchase.branch_id,
    )
    _closed(purchase, "cancelled")
    return purchase


# --- expiry (PackageExpiryWorkflow activities) -------------------------------------------------


def expiry_of(purchase_id: Any) -> str:
    """The package's current expiry while it is active ('' when it no longer expires)."""
    purchase = PackagePurchase.objects.filter(pk=purchase_id).first()
    if purchase is None or purchase.status != PackagePurchase.Status.ACTIVE:
        return ""
    return purchase.expires_at.isoformat() if purchase.expires_at else ""


@transaction.atomic
def remind_expiry(purchase_id: Any, *, dedupe_key: str | None = None) -> bool:
    purchase = PackagePurchase.objects.filter(pk=purchase_id).first()
    if purchase is None or purchase.status != PackagePurchase.Status.ACTIVE:
        return False
    if purchase.units_remaining <= 0 or purchase.expires_at is None:
        return False
    publish(
        events.PackageExpiring(**_payload(purchase, expires_at=purchase.expires_at.isoformat())),
        branch_id=purchase.branch_id,
        dedupe_key=dedupe_key,
    )
    return True


@transaction.atomic
def expire_package(purchase_id: Any, deadline: datetime | None = None) -> str:
    """Write off the unused units: ``expired``, ``moved:<iso>`` (the expiry moved later
    than ``deadline``, the one the workflow waited for; keep waiting) or ``skipped`` (not
    active any more). Without ``deadline`` the current time is used."""
    purchase = PackagePurchase.objects.select_for_update().filter(pk=purchase_id).first()
    if purchase is None or purchase.status != PackagePurchase.Status.ACTIVE:
        return "skipped"
    if purchase.expires_at is None:
        return "skipped"
    if purchase.expires_at > (deadline or now()) + timedelta(seconds=1):
        return f"moved:{purchase.expires_at.isoformat()}"
    remaining = max(purchase.units_remaining, ZERO)
    value = value_of(purchase, remaining)
    if remaining > 0:
        PackageConsumption.objects.create(
            purchase=purchase,
            kind=PackageConsumption.Kind.EXPIRY,
            units=remaining,
            currency=purchase.currency,
            value=value,
            note=_("Expired unused"),
        )
    with audit.track(purchase, action="expire"):
        purchase.units_expired = purchase.units_expired + remaining
        purchase.status = PackagePurchase.Status.EXPIRED
        purchase.closed_at = now()
        purchase.save()
    publish(
        events.PackageExpired(
            **_payload(purchase, units_expired=str(remaining), value=value.to_dict())
        ),
        branch_id=purchase.branch_id,
    )
    return "expired"


def renew(purchase_id: Any) -> PackagePurchase | None:
    """``package.depleted`` with auto-renew: sell the same template again."""
    purchase = (
        PackagePurchase.objects.select_related("client", "template", "student")
        .filter(pk=purchase_id)
        .first()
    )
    if purchase is None or not purchase.auto_renew or purchase.template is None:
        return None
    if PackagePurchase.objects.filter(
        client=purchase.client,
        template=purchase.template,
        source=PackagePurchase.Source.RENEWAL,
        created_at__gt=purchase.closed_at or purchase.created_at,
    ).exists():
        return None  # already renewed
    if not purchase.template.active:
        return None
    return sell_package(
        client=purchase.client,
        template=purchase.template,
        student=purchase.student,
        source=PackagePurchase.Source.RENEWAL,
    )


# --- imports (E28) ------------------------------------------------------------------------------


@transaction.atomic
def import_package(
    *,
    client: Client,
    name: str,
    quantity_type: str,
    units_total: Decimal,
    units_remaining: Decimal,
    value_remaining: Money,
    expires_at: datetime | None = None,
    template: Any = None,
    student: Student | None = None,
) -> PackagePurchase:
    """A package still being used at cutover (E28): active, with what is left. It has no
    invoice here (the money was taken in the old system); the price is the remaining value
    so consumption values stay right."""
    if quantity_type not in {HOURS, LESSONS, CREDIT}:
        raise _invalid("quantity_type", _("Use hours, lessons or credit."))
    if units_remaining <= 0 or units_total <= 0 or units_remaining > units_total:
        raise _invalid("units_remaining", _("Check the units left on the package."))
    purchase = PackagePurchase.objects.create(
        client=client,
        branch_id=client.branch_id,
        student=student,
        template=template,
        template_snapshot={
            "imported": True,
            "refund_policy": "none",
            "original_units": str(units_total),
        },
        name=name[:150],
        quantity_type=quantity_type,
        units_total=units_remaining,
        currency=value_remaining.currency,
        price=value_remaining.round_to_minor(),
        services=(
            [str(pk) for pk in template.services.values_list("pk", flat=True)] if template else []
        ),
        status=PackagePurchase.Status.PENDING,
        source=PackagePurchase.Source.IMPORT,
        expires_at=expires_at,
        close_reason="",
    )
    audit.record_create(purchase)
    activate(purchase)
    purchase.refresh_from_db()
    return purchase


@transaction.atomic
def discard_imported_package(purchase: PackagePurchase) -> bool:
    """An import is rolled back: an unused imported package is cancelled (kept, never
    deleted). One already used is kept as it is."""
    purchase = PackagePurchase.objects.select_for_update().get(pk=purchase.pk)
    if purchase.units_used or purchase.status != PackagePurchase.Status.ACTIVE:
        return False
    with audit.track(purchase, action="cancel"):
        purchase.status = PackagePurchase.Status.CANCELLED
        purchase.closed_at = now()
        purchase.close_reason = _("Import rolled back")
        purchase.save()
    _closed(purchase, "cancelled")
    return True
