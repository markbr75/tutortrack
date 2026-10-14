"""Rolling an imported row back (FR-28-1): records it created are removed through their
owning app's services (newest first) while nobody has changed them since the import, and
records it updated get their previous values back. Financial records are never deleted:
ledger adjustments are reversed, imported invoices voided and payments refunded."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from django.apps import apps
from django.db import models, transaction
from django.utils.translation import gettext as _

from tutortrack.core.exceptions import BusinessRuleViolation

from .base import Context

GRACE = timedelta(seconds=2)
MODELS = {
    "people.client": "people.Client",
    "people.contact": "people.Contact",
    "people.student": "people.Student",
    "people.tutorprofile": "people.TutorProfile",
    "catalogue.service": "catalogue.Service",
    "jobs.job": "jobs.Job",
    "scheduling.lesson": "scheduling.Lesson",
    "scheduling.lessonseries": "scheduling.LessonSeries",
    "billing.invoice": "billing.Invoice",
    "billing.packagepurchase": "billing.PackagePurchase",
    "payments.payment": "payments.Payment",
    "crm.note": "crm.Note",
    "leads.enquiry": "leads.Enquiry",
    "growth.affiliate": "growth.Affiliate",
    "growth.commissionrule": "growth.CommissionRule",
    "growth.affiliatereferral": "growth.AffiliateReferral",
    "growth.review": "growth.Review",
    "billing.charge": "billing.Charge",
    "billing.paymentrequest": "billing.PaymentRequest",
}


class Kept(Exception):
    """The record was changed after the import (or is in use) and stays."""


def _load(kind: str, pk: str) -> Any:
    label = MODELS.get(kind)
    if label is None:
        return None
    model = apps.get_model(label)
    manager = getattr(model, "all_objects", None) or model._default_manager
    return manager.filter(pk=pk).first()


def _untouched(obj: Any, ctx: Context) -> bool:
    finished = ctx.batch.completed_at
    updated = getattr(obj, "updated_at", None)
    return finished is None or updated is None or updated <= finished + GRACE


def _discard(kind: str, obj: Any) -> Any:
    from tutortrack.billing import packages
    from tutortrack.billing import services as billing
    from tutortrack.catalogue import services as catalogue
    from tutortrack.crm import services as crm
    from tutortrack.growth import services as growth
    from tutortrack.jobs import services as jobs
    from tutortrack.leads import services as leads
    from tutortrack.people import services as people
    from tutortrack.scheduling import services as scheduling

    handlers: dict[str, Callable[[Any], Any]] = {
        "growth.affiliate": growth.discard_imported,
        "growth.commissionrule": growth.discard_imported,
        "growth.affiliatereferral": growth.discard_imported,
        "growth.review": growth.discard_imported,
        "billing.charge": billing.discard_imported_charge,
        "billing.paymentrequest": billing.discard_imported_payment_request,
        "people.client": people.discard_imported,
        "people.contact": people.discard_imported,
        "people.student": people.discard_imported,
        "people.tutorprofile": people.discard_imported,
        "catalogue.service": catalogue.discard_imported_service,
        "jobs.job": jobs.discard_imported_job,
        "scheduling.lesson": scheduling.discard_imported_lesson,
        "scheduling.lessonseries": scheduling.discard_imported_series,
        "billing.invoice": billing.discard_imported_invoice,
        "billing.packagepurchase": packages.discard_imported_package,
        "crm.note": crm.delete_note,
        "leads.enquiry": leads.discard_imported_enquiry,
    }
    return handlers[kind](obj)


def _undo_ref(item: dict[str, Any], ctx: Context) -> bool:
    """Undo one created record: True when reverted, False when partly kept; raises
    ``Kept`` when nothing could be done."""
    kind = item.get("type", "")
    if kind == "migration.externalref":
        from ..models import ExternalRef

        ExternalRef.objects.filter(pk=item["id"]).delete()
        return True
    if kind == "privacy.consentrecord":
        from tutortrack.privacy.services import discard_imported_consent

        discard_imported_consent(item["id"])
        return True
    if kind in ("catalogue.paytier", "catalogue.tutorpaytierassignment"):
        from tutortrack.catalogue import services as catalogue
        from tutortrack.catalogue.models import PayTier, TutorPayTierAssignment

        if kind == "catalogue.tutorpaytierassignment":
            assignment = TutorPayTierAssignment.objects.filter(pk=item["id"]).first()
            if assignment is not None:
                catalogue.remove_tier_assignment(assignment)
            return True
        tier = PayTier.objects.filter(pk=item["id"]).first()
        if tier is not None and not tier.assignments.exists():
            catalogue.delete_imported_tier(tier)
        return True
    if kind == "crm.tag":
        from tutortrack.crm import services as crm
        from tutortrack.crm.models import Tag

        tag = Tag.objects.filter(pk=item["id"]).first()
        if tag is not None:
            crm.apply_tag(tag, item["target_type"], [item["target_id"]], remove=True)
        return True
    if kind == "billing.ledgeradjustment":
        from tutortrack.billing import services as billing
        from tutortrack.core.money import Money
        from tutortrack.people.models import Client

        client = Client.objects.filter(pk=item["client"]).first()
        if client is not None:
            billing.reverse_import_adjustment(
                client, Money(Decimal(item["amount"]), item["currency"]), entry_id=item["id"]
            )
        return True
    if kind == "scheduling.availabilitywindow":
        from tutortrack.people.models import TutorProfile
        from tutortrack.scheduling import services as scheduling

        tutor = TutorProfile.objects.filter(pk=item["tutor"]).first()
        if tutor is not None:
            scheduling.remove_availability_window(
                tutor,
                int(item["weekday"]),
                time.fromisoformat(item["start_time"]),
                time.fromisoformat(item["end_time"]),
            )
        return True
    if kind == "payments.payment":
        from tutortrack.payments import services as payments

        payment = _load(kind, item["id"])
        if payment is None:
            return True
        if payment.status != "succeeded":
            raise Kept
        payments.refund_payment(payment, reason=_("Import rolled back"))
        return True
    obj = _load(kind, item["id"])
    if obj is None:
        return True  # already gone (e.g. deleted with its parent)
    if not _untouched(obj, ctx):
        raise Kept
    try:
        with transaction.atomic():
            result = _discard(kind, obj)
    except (BusinessRuleViolation, models.ProtectedError) as exc:
        raise Kept from exc
    return result is not False


def _revert(key: str, old: dict[str, Any], ctx: Context) -> None:
    from tutortrack.catalogue import services as catalogue
    from tutortrack.jobs import services as jobs
    from tutortrack.people import services as people

    kind, _sep, pk = key.partition(":")
    obj = _load("people.tutorprofile" if kind == "people.tutor" else kind, pk)
    if obj is None:
        return
    if not _untouched(obj, ctx):
        raise Kept
    values = {name: _restore(obj, name, value) for name, value in old.items()}
    status = values.pop("status", None)
    updaters: dict[str, Callable[..., Any]] = {
        "people.client": people.update_client,
        "people.contact": people.update_contact,
        "people.student": people.update_student,
        "people.tutorprofile": people.update_tutor,
        "people.tutor": people.update_tutor,
        "catalogue.service": catalogue.update_service,
        "jobs.job": jobs.update_job,
    }
    if status is not None and kind == "people.student":
        people.change_student_status(obj, status)
    elif status is not None and kind in ("people.tutor", "people.tutorprofile"):
        people.change_tutor_status(obj, status)
    elif status is not None:
        values["status"] = status
    if values:
        updaters[kind](obj, **values)


def _restore(obj: Any, name: str, value: Any) -> Any:
    """A JSON value back to what the model field holds."""
    from tutortrack.core.money import Money

    if isinstance(value, dict) and {"amount", "currency"} <= set(value):
        return Money(Decimal(value["amount"]), value["currency"])
    try:
        field = obj._meta.get_field(name)
    except Exception:
        return value
    if value is None:
        return None
    if isinstance(field, models.ForeignKey):
        return field.related_model._default_manager.filter(pk=value).first()
    if isinstance(field, models.DateTimeField):
        return datetime.fromisoformat(value)
    if isinstance(field, models.DateField):
        return date.fromisoformat(value)
    if isinstance(field, models.DecimalField):
        return Decimal(str(value))
    return value


def undo_row(importer: Any, row: Any, ctx: Context) -> bool:
    """True when everything the row did was reverted."""
    complete = True
    for item in reversed(row.created_refs or []):
        try:
            with transaction.atomic():
                done = _undo_ref(item, ctx)
        except Kept:
            done = False
        complete = complete and done
    for key, old in (row.previous or {}).items():
        try:
            with transaction.atomic():
                _revert(key, old, ctx)
        except Kept:
            complete = False
    return complete
