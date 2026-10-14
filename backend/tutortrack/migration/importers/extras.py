"""Affiliates and reviews (E25) and ad hoc charges and proformas (E10) (G6, FR-28-3).

TutorCruncher's agents, reviews, ad hoc charges and proformas were counted but not imported
before E25 and E10 Phase 2 existed. Every write goes through the owning app's services:

* **Affiliates** (TutorCruncher agents) become E25 affiliates with a percentage commission
  rule when the agent had a rate, and the clients they introduced are attributed to them.
* **Reviews** become E25 reviews (source *import*), approved when the old system had them
  published; nothing is sent to the family.
* **Charges** (ad hoc charges dated on or after the cutover) become uninvoiced E10 charges;
  earlier ones are part of the invoice history and the opening balance.
* **Payment requests** (unpaid proformas) become E10 payment requests; paid proformas are
  already part of the client's balance and are skipped.

Rolling back removes what was created while nobody has used it (an affiliate with
commission, a moderated review, an invoiced charge or a paid request is kept).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.utils.translation import gettext as _

from . import refs
from .base import Context, FieldSpec, Importer, Outcome, Plan, RowError, register
from .base import label as _l
from .common import money_or_none, not_found
from .jobs import REFERENCE_FIELDS, TUTOR_FIELDS


def _client(values: dict[str, Any], ctx: Context) -> Any:
    client = refs.find_client(ctx, values)
    if client is None:
        raise RowError(not_found(_("Client")), "client_name")
    return client


def _currency(values: dict[str, Any], client: Any, ctx: Context) -> str:
    return str(values.get("currency") or getattr(client, "currency", "") or ctx.currency).upper()


# --- affiliates (E25) ----------------------------------------------------------------------------


@register
class AffiliateImporter(Importer):
    key = "affiliates"
    label = _l("Affiliates and agents")
    description = _l(
        "Partners who introduce clients (TutorCruncher agents), with their commission rate "
        "and the clients they introduced."
    )
    permissions = ("growth.affiliate.manage",)
    target_type = "growth.affiliate"
    upsert_keys = ("external_id", "email")
    default_upsert = "external_id"
    fields = [
        FieldSpec("external_id", _l("Agent ID"), synonyms=("agent id", "affiliate id", "id")),
        FieldSpec("name", _l("Name"), required=True, synonyms=("name", "agent", "affiliate")),
        FieldSpec("email", _l("Email"), "email", required=True, synonyms=("email",)),
        FieldSpec("phone", _l("Phone"), synonyms=("phone", "mobile")),
        FieldSpec(
            "commission_percent",
            _l("Commission (%)"),
            "decimal",
            synonyms=("commission", "commission rate", "rate"),
        ),
        FieldSpec(
            "client_external_ids",
            _l("Clients introduced (IDs)"),
            "list",
            synonyms=("clients", "client ids"),
        ),
    ]
    example = {
        "external_id": "A-12",
        "name": "Hill Street School PTA",
        "email": "pta@example.com",
        "commission_percent": "10",
    }

    def _existing(self, values: dict[str, Any], ctx: Context) -> Any:
        from tutortrack.growth.models import Affiliate

        target = refs.ref_for(ctx, "growth.affiliate", values.get("external_id"))
        if target:
            return Affiliate.objects.filter(pk=target).first()
        if values.get("email"):
            return Affiliate.objects.filter(email=str(values["email"]).lower()).first()
        return None

    def check(self, values: dict[str, Any], ctx: Context) -> Plan:
        percent = values.get("commission_percent")
        if percent is not None and not Decimal(0) <= percent <= Decimal(100):
            ctx.error("commission_percent", _("Percentages run from 0 to 100."))
        existing = self._existing(values, ctx)
        if existing is not None:
            return Plan(
                action="update",
                target_type="growth.affiliate",
                target_id=str(existing.pk),
                effects=[("growth.affiliate", "update")],
            )
        return Plan(effects=[("growth.affiliate", "create")])

    def apply(self, values: dict[str, Any], ctx: Context) -> Outcome:
        from tutortrack.growth import services as growth
        from tutortrack.growth.models import AffiliateReferral

        affiliate = self._existing(values, ctx)
        out = Outcome(action="update" if affiliate else "create", target_type="growth.affiliate")
        if affiliate is None:
            affiliate = growth.save_affiliate(
                None,
                name=str(values["name"])[:200],
                email=str(values["email"]),
                phone=str(values.get("phone") or "")[:30],
            )
            out.created.append({"type": "growth.affiliate", "id": str(affiliate.pk)})
            percent = values.get("commission_percent")
            if percent:
                rule = growth.save_rule(
                    None,
                    affiliate=affiliate,
                    name=_("Imported commission"),
                    kind="percent",
                    percent=Decimal(percent),
                )
                out.created.append({"type": "growth.commissionrule", "id": str(rule.pk)})
            if values.get("external_id"):
                out.created.append(
                    refs.remember(ctx, "growth.affiliate", values["external_id"], affiliate)
                )
        out.target_id = str(affiliate.pk)
        for ext in values.get("client_external_ids") or []:
            client = refs.find_client(ctx, {"client_external_id": ext})
            if client is None:
                out.warnings.append(_("Client %(id)s not found; not attributed.") % {"id": ext})
                continue
            if AffiliateReferral.objects.filter(client=client).exists():
                continue
            referral = growth.assign_client(affiliate, client)
            out.created.append({"type": "growth.affiliatereferral", "id": str(referral.pk)})
        return out


# --- reviews (E25) -------------------------------------------------------------------------------


@register
class ReviewImporter(Importer):
    key = "reviews"
    label = _l("Reviews")
    description = _l("Reviews families left about your tutors (nothing is sent to them).")
    permissions = ("growth.review.manage",)
    target_type = "growth.review"
    upsert_keys = ("external_id", "none")
    default_upsert = "external_id"
    fields = [
        FieldSpec("external_id", _l("Review ID"), synonyms=("review id", "id")),
        *REFERENCE_FIELDS,
        *TUTOR_FIELDS,
        FieldSpec("rating", _l("Rating (1-5)"), "int", required=True, synonyms=("rating", "stars")),
        FieldSpec("text", _l("Review"), synonyms=("review", "comment", "text", "feedback")),
        FieldSpec("reviewer_name", _l("Reviewer name"), synonyms=("reviewer", "name")),
        FieldSpec("published", _l("Published"), "bool", synonyms=("published", "public")),
        FieldSpec("date", _l("Date"), "date", synonyms=("date", "created")),
    ]
    example = {
        "client_external_id": "C-1001",
        "tutor_email": "alex@example.com",
        "rating": "5",
        "text": "Patient and clear.",
        "reviewer_name": "Jane S.",
    }

    def check(self, values: dict[str, Any], ctx: Context) -> Plan:
        if values.get("rating") is not None and not 1 <= int(values["rating"]) <= 5:
            ctx.error("rating", _("Ratings run from 1 to 5."))
        try:
            client = _client(values, ctx)
        except RowError as exc:
            ctx.error(exc.field, str(exc))
            return Plan()
        if refs.ref_for(ctx, "growth.review", values.get("external_id")):
            return Plan(action="skip", target_type="people.client", target_id=str(client.pk))
        return Plan(effects=[("growth.review", "create")])

    def apply(self, values: dict[str, Any], ctx: Context) -> Outcome:
        from tutortrack.growth import services as growth
        from tutortrack.growth.models import Review

        if refs.ref_for(ctx, "growth.review", values.get("external_id")):
            return Outcome(action="skip")
        client = _client(values, ctx)
        tutor = refs.find_tutor(ctx, values)
        name = str(values.get("reviewer_name") or "").strip() or client.display_name
        review = growth.create_review(
            client=client,
            tutor=tutor,
            rating=int(values["rating"]),
            text=str(values.get("text") or ""),
            reviewer_name=name,
            publish_consent=bool(values.get("published")),
            source=Review.Source.IMPORT,
        )
        if values.get("published"):
            growth.moderate(review, action="approve")
        out = Outcome(action="create", target_type="growth.review", target_id=str(review.pk))
        out.created.append({"type": "growth.review", "id": str(review.pk)})
        if values.get("external_id"):
            out.created.append(refs.remember(ctx, "growth.review", values["external_id"], review))
        return out


# --- ad hoc charges and proformas (E10) ----------------------------------------------------------


@register
class ChargeImporter(Importer):
    key = "charges"
    label = _l("Ad hoc charges")
    description = _l(
        "One-off charges not invoiced yet (books, exam fees...); they go on the next invoice."
    )
    permissions = ("billing.charge.create",)
    target_type = "billing.charge"
    upsert_keys = ("external_id", "none")
    default_upsert = "external_id"
    fields = [
        FieldSpec("external_id", _l("Charge ID"), synonyms=("charge id", "id")),
        *REFERENCE_FIELDS,
        FieldSpec(
            "description",
            _l("Description"),
            required=True,
            synonyms=("description", "item", "name"),
        ),
        FieldSpec(
            "amount",
            _l("Amount"),
            "decimal",
            required=True,
            synonyms=("amount", "charge", "price", "charge client"),
        ),
        FieldSpec("date", _l("Date"), "date", synonyms=("date",)),
        FieldSpec("currency", _l("Currency"), max_length=3, synonyms=("currency",)),
    ]
    example = {"client_external_id": "C-1001", "description": "Exam entry fee", "amount": "45"}

    def check(self, values: dict[str, Any], ctx: Context) -> Plan:
        try:
            client = _client(values, ctx)
        except RowError as exc:
            ctx.error(exc.field, str(exc))
            return Plan()
        if values.get("amount") is not None and values["amount"] == 0:
            ctx.error("amount", _("Enter an amount."))
        if refs.ref_for(ctx, "billing.charge", values.get("external_id")):
            return Plan(action="skip", target_type="people.client", target_id=str(client.pk))
        return Plan(effects=[("billing.charge", "create")])

    def apply(self, values: dict[str, Any], ctx: Context) -> Outcome:
        from tutortrack.billing import services as billing

        if refs.ref_for(ctx, "billing.charge", values.get("external_id")):
            return Outcome(action="skip")
        client = _client(values, ctx)
        price = money_or_none(Decimal(values["amount"]), _currency(values, client, ctx))
        charge = billing.create_ad_hoc_charge(
            client=client,
            description=str(values["description"])[:300],
            unit_price=price,
            day=values.get("date") or ctx.cutover,
        )
        out = Outcome(action="create", target_type="billing.charge", target_id=str(charge.pk))
        out.created.append({"type": "billing.charge", "id": str(charge.pk)})
        if values.get("external_id"):
            out.created.append(refs.remember(ctx, "billing.charge", values["external_id"], charge))
        return out


@register
class PaymentRequestImporter(Importer):
    key = "payment_requests"
    label = _l("Payment requests (proformas)")
    description = _l("Unpaid requests for payment in advance; paid ones are in the balance.")
    permissions = ("billing.payment_request.manage",)
    target_type = "billing.paymentrequest"
    upsert_keys = ("external_id", "none")
    default_upsert = "external_id"
    fields = [
        FieldSpec("external_id", _l("Proforma ID"), synonyms=("proforma id", "id", "number")),
        *REFERENCE_FIELDS,
        FieldSpec("amount", _l("Amount"), "decimal", required=True, synonyms=("amount", "total")),
        FieldSpec("description", _l("Description"), synonyms=("description",)),
        FieldSpec("due_date", _l("Due date"), "date", synonyms=("due", "due date")),
        FieldSpec(
            "status",
            _l("Status"),
            "choice",
            choices=("unpaid", "paid", "void"),
            synonyms=("status",),
        ),
        FieldSpec("currency", _l("Currency"), max_length=3, synonyms=("currency",)),
    ]
    example = {"client_external_id": "C-1001", "amount": "300", "status": "unpaid"}

    def check(self, values: dict[str, Any], ctx: Context) -> Plan:
        try:
            client = _client(values, ctx)
        except RowError as exc:
            ctx.error(exc.field, str(exc))
            return Plan()
        if (values.get("status") or "unpaid") != "unpaid":
            ctx.warn("status", _("Paid or void proformas are already in the balance; skipped."))
            return Plan(action="skip", target_type="people.client", target_id=str(client.pk))
        if values.get("amount") is not None and values["amount"] <= 0:
            ctx.error("amount", _("Enter an amount."))
        if refs.ref_for(ctx, "billing.paymentrequest", values.get("external_id")):
            return Plan(action="skip", target_type="people.client", target_id=str(client.pk))
        return Plan(effects=[("billing.paymentrequest", "create")])

    def apply(self, values: dict[str, Any], ctx: Context) -> Outcome:
        from tutortrack.billing import services as billing

        if (values.get("status") or "unpaid") != "unpaid" or refs.ref_for(
            ctx, "billing.paymentrequest", values.get("external_id")
        ):
            return Outcome(action="skip")
        client = _client(values, ctx)
        request = billing.create_payment_request(
            client=client,
            amount=money_or_none(Decimal(values["amount"]), _currency(values, client, ctx)),
            description=str(values.get("description") or _("Payment in advance"))[:300],
            due_date=values.get("due_date"),
        )
        out = Outcome(
            action="create", target_type="billing.paymentrequest", target_id=str(request.pk)
        )
        out.created.append({"type": "billing.paymentrequest", "id": str(request.pk)})
        if values.get("external_id"):
            out.created.append(
                refs.remember(ctx, "billing.paymentrequest", values["external_id"], request)
            )
        return out
