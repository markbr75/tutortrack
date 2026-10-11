"""Opening balances, historic invoices, payments and package balances (E28-T04).

* **Opening balances** post one ledger adjustment per client as of the cutover date
  (positive: the client owes; negative: credit). They are the only ledger effect of a
  migration's history.
* **Invoices** are history: issued/paid documents with their original numbers and no
  ledger entry (``billing.services.import_invoice``). Open ones can still be paid.
* **Payments** are real money received after the cutover: recorded through
  ``payments.services.record_manual_payment`` (ledger + allocation to the named invoice).
* **Packages**: package purchases are Phase 2 (E10-T12), so a remaining package balance
  is carried over as client credit with the package details in its description.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.utils.translation import gettext as _

from . import refs
from .base import Context, FieldSpec, Importer, Outcome, Plan, RowError, register
from .base import label as _l
from .common import money_or_none, not_found
from .jobs import REFERENCE_FIELDS


def _client(values: dict[str, Any], ctx: Context) -> Any:
    client = refs.find_client(ctx, values)
    if client is None:
        raise RowError(not_found(_("Client")), "client_name")
    return client


def _currency(values: dict[str, Any], client: Any, ctx: Context) -> str:
    return str(values.get("currency") or getattr(client, "currency", "") or ctx.currency).upper()


@register
class OpeningBalanceImporter(Importer):
    key = "opening_balances"
    label = _l("Opening balances")
    description = _l(
        "Each client's balance at the cutover date: positive if they owe, negative for credit."
    )
    permissions = ("billing.ledger.adjust",)
    target_type = "people.client"
    upsert_keys = ("none",)
    default_upsert = "none"
    fields = [
        *REFERENCE_FIELDS,
        FieldSpec(
            "balance",
            _l("Balance (owed is positive, credit negative)"),
            "decimal",
            required=True,
            synonyms=("balance", "amount", "account balance", "outstanding", "opening balance"),
        ),
        FieldSpec(
            "direction",
            _l("Owed or credit"),
            "choice",
            choices=("owes", "credit"),
            synonyms=("type", "direction", "dr/cr"),
        ),
        FieldSpec("currency", _l("Currency"), max_length=3, synonyms=("currency",)),
        FieldSpec("as_of", _l("As of"), "date", synonyms=("as of", "date", "balance date")),
    ]
    example = {"client_external_id": "C-1001", "balance": "-120.00"}

    def _amount(self, values: dict[str, Any]) -> Decimal:
        amount = Decimal(values["balance"])
        if values.get("direction") == "credit":
            amount = -abs(amount)
        elif values.get("direction") == "owes":
            amount = abs(amount)
        return amount

    def check(self, values: dict[str, Any], ctx: Context) -> Plan:
        from tutortrack.billing.selectors import has_opening_balance

        try:
            client = _client(values, ctx)
        except RowError as exc:
            ctx.error(exc.field, str(exc))
            return Plan()
        if ctx.claim("balance", str(client.pk)):
            ctx.error("client_name", _("This client appears earlier in the file."))
        if values.get("balance") is not None and self._amount(values) == 0:
            ctx.warn("balance", _("Zero balance; nothing to post."))
            return Plan(action="skip", target_type="people.client", target_id=str(client.pk))
        if has_opening_balance(client):
            ctx.warn("balance", _("This client already has an opening balance; skipped."))
            return Plan(action="skip", target_type="people.client", target_id=str(client.pk))
        return Plan(
            action="update",
            effects=[("billing.opening_balance", "create")],
            target_type="people.client",
            target_id=str(client.pk),
        )

    def apply(self, values: dict[str, Any], ctx: Context) -> Outcome:
        from tutortrack.billing import services as billing
        from tutortrack.billing.selectors import has_opening_balance

        client = _client(values, ctx)
        if has_opening_balance(client):
            return Outcome(action="skip", target_type="people.client", target_id=str(client.pk))
        amount = money_or_none(self._amount(values), _currency(values, client, ctx))
        as_of = values.get("as_of") or ctx.cutover
        entry = billing.post_opening_balance(client, amount, as_of=as_of)
        return Outcome(
            action="update",
            target_type="people.client",
            target_id=str(client.pk),
            created=[_ledger_ref(entry, client, amount)],
        )


def _ledger_ref(entry: Any, client: Any, amount: Any) -> dict[str, Any]:
    return {
        "type": "billing.ledgeradjustment",
        "id": str(entry.pk),
        "client": str(client.pk),
        "amount": str(amount.amount),
        "currency": amount.currency,
    }


@register
class InvoiceImporter(Importer):
    key = "invoices"
    label = _l("Invoices (history)")
    description = _l(
        "Past invoices with their original numbers. They don't change balances; use "
        "opening balances for what is owed."
    )
    permissions = ("billing.invoice.create",)
    target_type = "billing.invoice"
    upsert_keys = ("number",)
    default_upsert = "number"
    fields = [
        FieldSpec(
            "number",
            _l("Invoice number"),
            required=True,
            synonyms=("number", "invoice number", "invoice no", "invoice #", "invoice"),
        ),
        *REFERENCE_FIELDS,
        FieldSpec(
            "issue_date",
            _l("Issue date"),
            "date",
            required=True,
            synonyms=("date", "issue date", "invoice date", "issued"),
        ),
        FieldSpec("due_date", _l("Due date"), "date", synonyms=("due", "due date")),
        FieldSpec(
            "status",
            _l("Status"),
            "choice",
            choices=("issued", "partially_paid", "paid", "void", "written_off"),
            synonyms=("status",),
        ),
        FieldSpec(
            "total",
            _l("Total"),
            "decimal",
            required=True,
            synonyms=("total", "amount", "gross", "invoice total"),
        ),
        FieldSpec("tax", _l("Tax"), "decimal", synonyms=("tax", "vat", "gst", "sales tax")),
        FieldSpec(
            "amount_paid",
            _l("Amount paid"),
            "decimal",
            synonyms=("paid", "amount paid", "payments"),
        ),
        FieldSpec("currency", _l("Currency"), max_length=3, synonyms=("currency",)),
        FieldSpec(
            "description",
            _l("Description"),
            synonyms=("description", "details", "memo", "items"),
        ),
    ]
    example = {
        "number": "INV-0042",
        "client_external_id": "C-1001",
        "issue_date": "2026-09-01",
        "total": "180.00",
        "amount_paid": "180.00",
        "status": "paid",
    }

    def check(self, values: dict[str, Any], ctx: Context) -> Plan:
        if ctx.claim("invoice", str(values.get("number") or "")):
            ctx.error("number", _("This invoice number appears earlier in the file."))
        existing = refs.find_invoice(values.get("number"))
        if existing is not None:
            ctx.warn("number", _("An invoice with this number exists; skipped."))
            return Plan(action="skip", target_type="billing.invoice", target_id=str(existing.pk))
        try:
            _client(values, ctx)
        except RowError as exc:
            ctx.error(exc.field, str(exc))
        total, paid = values.get("total"), values.get("amount_paid")
        if total is not None and total < 0:
            ctx.error("total", _("Import credit notes as negative opening balances instead."))
        if total is not None and paid is not None and paid > total:
            ctx.error("amount_paid", _("More paid than the invoice total."))
        return Plan(effects=[("billing.invoice", "create")])

    def apply(self, values: dict[str, Any], ctx: Context) -> Outcome:
        from tutortrack.billing import services as billing

        if refs.find_invoice(values["number"]) is not None:
            return Outcome(action="skip")
        client = _client(values, ctx)
        currency = _currency(values, client, ctx)
        total = Decimal(values["total"])
        paid = Decimal(values["amount_paid"]) if values.get("amount_paid") is not None else None
        status = values.get("status")
        if paid is None:
            paid = total if status == "paid" else Decimal(0)
        invoice = billing.import_invoice(
            client=client,
            number=values["number"],
            issue_date=values["issue_date"],
            due_date=values.get("due_date"),
            total=money_or_none(total, currency),
            tax=money_or_none(values.get("tax") or Decimal(0), currency),
            amount_paid=money_or_none(paid, currency),
            status=status,
            description=values.get("description") or "",
        )
        out = Outcome(action="create", target_type="billing.invoice", target_id=str(invoice.pk))
        out.created.append({"type": "billing.invoice", "id": str(invoice.pk)})
        return out


@register
class PaymentImporter(Importer):
    key = "payments"
    label = _l("Payments")
    description = _l(
        "Money received after the cutover (bank transfers, cash, cheques), allocated to "
        "an invoice when one is named."
    )
    permissions = ("payments.payment.record",)
    target_type = "payments.payment"
    upsert_keys = ("none",)
    default_upsert = "none"
    fields = [
        *REFERENCE_FIELDS,
        FieldSpec(
            "amount",
            _l("Amount"),
            "decimal",
            required=True,
            synonyms=("amount", "paid", "payment amount", "total"),
        ),
        FieldSpec(
            "date",
            _l("Date received"),
            "date",
            required=True,
            synonyms=("date", "payment date", "received", "paid on"),
        ),
        FieldSpec(
            "method",
            _l("Method"),
            "choice",
            choices=("bank_transfer", "cash", "cheque", "other", "direct_debit"),
            synonyms=("method", "payment method", "type"),
        ),
        FieldSpec("reference", _l("Reference"), synonyms=("reference", "ref", "transaction id")),
        FieldSpec(
            "invoice_number",
            _l("Invoice number"),
            synonyms=("invoice", "invoice number", "invoice no"),
        ),
        FieldSpec("currency", _l("Currency"), max_length=3, synonyms=("currency",)),
    ]
    example = {
        "client_external_id": "C-1001",
        "amount": "45.00",
        "date": "2026-10-05",
        "method": "bank_transfer",
        "invoice_number": "INV-0042",
    }

    def check(self, values: dict[str, Any], ctx: Context) -> Plan:
        from tutortrack.payments.selectors import similar_payment_exists

        try:
            client = _client(values, ctx)
        except RowError as exc:
            ctx.error(exc.field, str(exc))
            return Plan()
        if values.get("amount") is not None and values["amount"] <= 0:
            ctx.error("amount", _("Payments must be positive."))
            return Plan()
        if values.get("invoice_number"):
            invoice = refs.find_invoice(values["invoice_number"])
            if invoice is None:
                ctx.error("invoice_number", not_found(_("Invoice")))
            elif invoice.client_id != client.pk:
                ctx.error("invoice_number", _("That invoice belongs to another client."))
        if (
            values.get("amount") is not None
            and values.get("date")
            and similar_payment_exists(
                client, values["amount"], values["date"], values.get("reference") or ""
            )
        ):
            ctx.warn("amount", _("A payment like this is already recorded; skipped."))
            return Plan(action="skip")
        return Plan(effects=[("payments.payment", "create")])

    def apply(self, values: dict[str, Any], ctx: Context) -> Outcome:
        from datetime import datetime, time
        from zoneinfo import ZoneInfo

        from tutortrack.payments import services as payments
        from tutortrack.payments.selectors import similar_payment_exists

        client = _client(values, ctx)
        if similar_payment_exists(
            client, values["amount"], values["date"], values.get("reference") or ""
        ):
            return Outcome(action="skip")
        currency = _currency(values, client, ctx)
        amount = money_or_none(values["amount"], currency)
        allocations = None
        if values.get("invoice_number"):
            invoice = refs.find_invoice(values["invoice_number"])
            if invoice is not None and invoice.is_open and invoice.currency == currency:
                allocations = [(invoice, min(amount, invoice.balance_due))]
        payment = payments.record_manual_payment(
            client=client,
            amount=amount,
            method=values.get("method") or "bank_transfer",
            received_at=datetime.combine(values["date"], time(12), tzinfo=ZoneInfo(ctx.timezone)),
            reference=values.get("reference") or "",
            notes=_("Imported"),
            allocations=allocations,
        )
        out = Outcome(action="create", target_type="payments.payment", target_id=str(payment.pk))
        out.created.append({"type": "payments.payment", "id": str(payment.pk)})
        return out


@register
class PackageBalanceImporter(Importer):
    key = "packages"
    label = _l("Package balances")
    description = _l("Prepaid packages still being used: the unused value becomes client credit.")
    permissions = ("billing.ledger.adjust",)
    target_type = "people.client"
    upsert_keys = ("none",)
    default_upsert = "none"
    fields = [
        *REFERENCE_FIELDS,
        FieldSpec(
            "package",
            _l("Package"),
            required=True,
            synonyms=("package", "package name", "bundle", "product"),
        ),
        FieldSpec(
            "remaining_value",
            _l("Remaining value"),
            "decimal",
            required=True,
            synonyms=("remaining value", "balance", "remaining amount", "value"),
        ),
        FieldSpec(
            "remaining_hours",
            _l("Remaining hours or lessons"),
            "decimal",
            synonyms=("remaining hours", "hours left", "remaining lessons", "remaining"),
        ),
        FieldSpec("expires_on", _l("Expires on"), "date", synonyms=("expiry", "expires")),
        FieldSpec("student_name", _l("Student"), synonyms=("student",)),
        FieldSpec("currency", _l("Currency"), max_length=3, synonyms=("currency",)),
    ]
    example = {
        "client_external_id": "C-1001",
        "package": "10 hours GCSE Maths",
        "remaining_value": "135.00",
        "remaining_hours": "3",
    }

    def check(self, values: dict[str, Any], ctx: Context) -> Plan:
        try:
            client = _client(values, ctx)
        except RowError as exc:
            ctx.error(exc.field, str(exc))
            return Plan()
        if values.get("remaining_value") is not None and values["remaining_value"] <= 0:
            ctx.warn("remaining_value", _("Nothing left on the package; skipped."))
            return Plan(action="skip", target_type="people.client", target_id=str(client.pk))
        return Plan(
            action="update",
            effects=[("billing.package_credit", "create")],
            target_type="people.client",
            target_id=str(client.pk),
        )

    def apply(self, values: dict[str, Any], ctx: Context) -> Outcome:
        from tutortrack.billing import services as billing

        client = _client(values, ctx)
        if values["remaining_value"] <= 0:
            return Outcome(action="skip")
        amount = money_or_none(-Decimal(values["remaining_value"]), _currency(values, client, ctx))
        details = [str(values["package"])]
        if values.get("student_name"):
            details.append(str(values["student_name"]))
        if values.get("remaining_hours") is not None:
            details.append(_("%(n)s remaining") % {"n": values["remaining_hours"]})
        if values.get("expires_on"):
            details.append(_("expires %(date)s") % {"date": values["expires_on"].isoformat()})
        entry = billing.adjust_ledger(
            client,
            amount,
            reason=_("Package carried over: %(details)s") % {"details": ", ".join(details)},
        )
        return Outcome(
            action="update",
            target_type="people.client",
            target_id=str(client.pk),
            created=[_ledger_ref(entry, client, amount)],
        )
