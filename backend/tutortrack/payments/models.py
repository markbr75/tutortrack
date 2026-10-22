"""Payments (E11): connected provider accounts, saved payment methods, payments and their
allocation to invoices, refunds, disputes, payouts and the raw webhook log."""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from tutortrack.core.crypto import EncryptedField
from tutortrack.core.fields import CurrencyField, MoneyField
from tutortrack.core.models import BranchScopedModel, TenantModel


class Provider(models.TextChoices):
    STRIPE = "stripe", _("Stripe")
    GOCARDLESS = "gocardless", _("GoCardless")
    PAYPAL = "paypal", _("PayPal")
    MANUAL = "manual", _("Manual")


class AccountRoute(models.Model):
    """Platform-level routing for webhooks: which organisation a connected account belongs
    to. Webhooks arrive on the platform host before any tenant is known; this is the only
    lookup they make outside a tenant (like resolving a subdomain)."""

    provider = models.CharField(max_length=10, choices=Provider.choices)
    account_ref = models.CharField(max_length=100)
    organisation_id = models.UUIDField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["provider", "account_ref"], name="account_route_unique")
        ]

    def __str__(self) -> str:
        return f"{self.provider}:{self.account_ref}"


class ProviderAccount(TenantModel):
    """A tenant's own connected account (Stripe Connect). ``branch`` empty = the default
    for every branch without its own account (FR-11-1)."""

    class Status(models.TextChoices):
        PENDING = "pending", _("Onboarding not finished")
        ACTIVE = "active", _("Active")
        RESTRICTED = "restricted", _("Action needed")
        DISCONNECTED = "disconnected", _("Disconnected")

    provider = models.CharField(max_length=10, choices=Provider.choices)
    branch = models.ForeignKey(
        "tenancy.Branch", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    account_ref = models.CharField(max_length=100)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    charges_enabled = models.BooleanField(default=False)
    payouts_enabled = models.BooleanField(default=False)
    requirements = models.JSONField(default=list, blank=True)  # fields the provider still needs
    default_currency = CurrencyField(blank=True, default="")
    connected_at = models.DateTimeField(null=True, blank=True)
    disconnected_at = models.DateTimeField(null=True, blank=True)
    # GoCardless partner OAuth token (Stripe and PayPal act with platform credentials).
    access_token = EncryptedField(blank=True, default="")
    connect_state = models.CharField(max_length=64, blank=True, default="")  # pending OAuth

    audit_sensitive_fields = frozenset({"access_token"})

    class Meta(TenantModel.Meta):
        ordering = ["provider", "created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "provider", "branch"],
                condition=~Q(status="disconnected"),
                name="provider_account_branch_unique",
            ),
            models.UniqueConstraint(
                fields=["organisation", "provider"],
                condition=Q(branch__isnull=True) & ~Q(status="disconnected"),
                name="provider_account_default_unique",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.get_provider_display()} {self.account_ref}"


class ProviderCustomer(TenantModel):
    client = models.ForeignKey("people.Client", on_delete=models.CASCADE, related_name="+")
    account = models.ForeignKey(ProviderAccount, on_delete=models.CASCADE, related_name="+")
    ref = models.CharField(max_length=100)

    class Meta(TenantModel.Meta):
        constraints = [
            models.UniqueConstraint(fields=["client", "account"], name="provider_customer_unique")
        ]


class PaymentMethod(TenantModel):
    """A saved card or debit mandate. Card numbers never reach us (SAQ-A): only the
    provider's reference, brand, last 4 and expiry."""

    class Status(models.TextChoices):
        ACTIVE = "active", _("Active")
        REMOVED = "removed", _("Removed")

    client = models.ForeignKey(
        "people.Client", on_delete=models.CASCADE, related_name="payment_methods"
    )
    account = models.ForeignKey(ProviderAccount, on_delete=models.PROTECT, related_name="+")
    provider_ref = models.CharField(max_length=100)
    type = models.CharField(max_length=30)  # card, bacs_debit, sepa_debit, us_bank_account...
    brand = models.CharField(max_length=30, blank=True, default="")
    last4 = models.CharField(max_length=4, blank=True, default="")
    exp_month = models.PositiveSmallIntegerField(null=True, blank=True)
    exp_year = models.PositiveSmallIntegerField(null=True, blank=True)
    mandate_status = models.CharField(max_length=20, blank=True, default="")
    is_default = models.BooleanField(default=False)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.ACTIVE)

    class Meta(TenantModel.Meta):
        ordering = ["-is_default", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["client"],
                condition=Q(is_default=True, status="active"),
                name="payment_method_one_default",
            )
        ]

    @property
    def is_debit(self) -> bool:
        return self.type.endswith("_debit") or self.type == "us_bank_account"


class SetupLink(TenantModel):
    """A link (sent by staff, or opened from the portal) where a client adds a payment
    method and may opt in to auto-pay. Only the token hash is stored."""

    client = models.ForeignKey("people.Client", on_delete=models.CASCADE, related_name="+")
    token_hash = models.CharField(max_length=64, unique=True)
    provider = models.CharField(max_length=10, blank=True, default="")  # "" = any enabled
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta(TenantModel.Meta):
        ordering = ["-created_at"]


class AutoPayConsent(TenantModel):
    """Explicit consent to charge a saved method automatically (FR-11-3)."""

    client = models.ForeignKey("people.Client", on_delete=models.CASCADE, related_name="+")
    payment_method = models.ForeignKey(
        PaymentMethod, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    text_version = models.CharField(max_length=20)
    text = models.TextField()
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True, default="")
    given_at = models.DateTimeField()
    withdrawn_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        ordering = ["-given_at"]


class Payment(BranchScopedModel):
    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        SUCCEEDED = "succeeded", _("Succeeded")
        FAILED = "failed", _("Failed")
        REFUNDED = "refunded", _("Refunded")
        PARTIALLY_REFUNDED = "partially_refunded", _("Partly refunded")
        DISPUTED = "disputed", _("Disputed")

    class Method(models.TextChoices):
        CARD = "card", _("Card")
        DIRECT_DEBIT = "direct_debit", _("Direct debit")
        BANK_TRANSFER = "bank_transfer", _("Bank transfer")
        CASH = "cash", _("Cash")
        CHEQUE = "cheque", _("Cheque")
        PAYPAL = "paypal", _("PayPal")
        OTHER = "other", _("Other")

    class Source(models.TextChoices):
        AUTO_PAY = "auto_pay", _("Auto-pay")
        PAY_PAGE = "pay_page", _("Pay page")
        MANUAL = "manual", _("Recorded by staff")

    client = models.ForeignKey("people.Client", on_delete=models.PROTECT, related_name="payments")
    currency = CurrencyField()
    amount = MoneyField()
    refunded = MoneyField(default=0)
    fee = MoneyField(null=True, blank=True)
    net = MoneyField(null=True, blank=True)
    method = models.CharField(max_length=14, choices=Method.choices)
    provider = models.CharField(max_length=10, choices=Provider.choices, default=Provider.MANUAL)
    account = models.ForeignKey(
        ProviderAccount, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    provider_ref = models.CharField(max_length=100, blank=True, default="")
    payment_method = models.ForeignKey(
        PaymentMethod, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    status = models.CharField(max_length=18, choices=Status.choices, default=Status.PENDING)
    source = models.CharField(max_length=8, choices=Source.choices, default=Source.MANUAL)
    received_at = models.DateTimeField(null=True, blank=True)
    reference = models.CharField(max_length=120, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    payment_request = models.ForeignKey(
        "billing.PaymentRequest",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="payments",
    )
    failure_code = models.CharField(max_length=60, blank=True, default="")
    failure_message = models.CharField(max_length=300, blank=True, default="")
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    receipt_sent_at = models.DateTimeField(null=True, blank=True)
    group = models.ForeignKey(
        "PaymentGroup", null=True, blank=True, on_delete=models.PROTECT, related_name="payments"
    )  # one receipt split across clients (E11-T14)

    class Meta(BranchScopedModel.Meta):
        ordering = ["-received_at", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "provider", "provider_ref"],
                condition=~Q(provider_ref=""),
                name="payment_provider_ref_unique",
            )
        ]
        indexes = [models.Index(fields=["client", "status"], name="payment_client_idx")]

    def __str__(self) -> str:
        return f"{self.get_method_display()} {self.amount}"


class PaymentAllocation(TenantModel):
    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name="allocations")
    invoice = models.ForeignKey("billing.Invoice", on_delete=models.PROTECT, related_name="+")
    currency = CurrencyField()
    amount = MoneyField()  # negative rows record a re-allocation or refund

    class Meta(TenantModel.Meta):
        ordering = ["created_at"]


class PaymentAttempt(TenantModel):
    """One try at collecting an invoice with a saved method (auto-pay or "collect")."""

    class Status(models.TextChoices):
        SUCCEEDED = "succeeded", _("Succeeded")
        PROCESSING = "processing", _("Processing")
        ACTION_REQUIRED = "action_required", _("Customer action needed")
        FAILED = "failed", _("Failed")

    invoice = models.ForeignKey("billing.Invoice", on_delete=models.CASCADE, related_name="+")
    payment_method = models.ForeignKey(
        PaymentMethod, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    payment = models.ForeignKey(
        Payment, null=True, blank=True, on_delete=models.SET_NULL, related_name="attempts"
    )
    number = models.PositiveSmallIntegerField()
    idempotency_key = models.CharField(max_length=200, unique=True)
    status = models.CharField(max_length=15, choices=Status.choices)
    provider_ref = models.CharField(max_length=100, blank=True, default="")
    failure_code = models.CharField(max_length=60, blank=True, default="")
    failure_message = models.CharField(max_length=300, blank=True, default="")

    class Meta(TenantModel.Meta):
        ordering = ["invoice", "number"]


class Refund(TenantModel):
    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        SUCCEEDED = "succeeded", _("Refunded")
        FAILED = "failed", _("Failed")

    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name="refunds")
    currency = CurrencyField()
    amount = MoneyField()
    reason = models.CharField(max_length=300)
    status = models.CharField(max_length=9, choices=Status.choices, default=Status.PENDING)
    provider_ref = models.CharField(max_length=100, blank=True, default="")
    credit_note = models.ForeignKey(
        "billing.CreditNote", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta(TenantModel.Meta):
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Refund {self.amount}"


class Dispute(TenantModel):
    class Status(models.TextChoices):
        NEEDS_RESPONSE = "needs_response", _("Needs a response")
        UNDER_REVIEW = "under_review", _("Under review")
        WON = "won", _("Won")
        LOST = "lost", _("Lost")

    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name="disputes")
    provider_ref = models.CharField(max_length=100)
    currency = CurrencyField()
    amount = MoneyField()
    reason = models.CharField(max_length=60, blank=True, default="")
    status = models.CharField(max_length=14, choices=Status.choices)
    evidence_due_by = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "provider_ref"], name="dispute_ref_unique"
            )
        ]


class ProviderPayout(TenantModel):
    account = models.ForeignKey(ProviderAccount, on_delete=models.PROTECT, related_name="+")
    provider_ref = models.CharField(max_length=100)
    currency = CurrencyField()
    amount = MoneyField()
    status = models.CharField(max_length=20)
    arrival_date = models.DateField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        ordering = ["-arrival_date"]
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "provider_ref"], name="payout_ref_unique"
            )
        ]


class ProviderWebhookEvent(TenantModel):
    """Raw provider events, stored before processing; processed idempotently (FR-11 §2)."""

    provider = models.CharField(max_length=10, choices=Provider.choices)
    event_id = models.CharField(max_length=100)
    type = models.CharField(max_length=80)
    account_ref = models.CharField(max_length=100, blank=True, default="")
    payload = models.JSONField()
    processed_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    last_error = models.TextField(blank=True, default="")

    class Meta(TenantModel.Meta):
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "event_id"], name="provider_webhook_event_unique"
            )
        ]


# --- Phase 2 (E11-T11..T14) ---------------------------------------------------------------------


class PaymentGroup(BranchScopedModel):
    """One receipt split across several clients (FR-11-6 split payments, e.g. a school
    paying for many students). Each client's share is an ordinary ``Payment`` in the group,
    so ledgers, allocations, refunds and accounting sync work per client."""

    payer_name = models.CharField(max_length=200)
    currency = CurrencyField()
    amount = MoneyField()
    method = models.CharField(max_length=14, choices=Payment.Method.choices)
    received_at = models.DateTimeField()
    reference = models.CharField(max_length=120, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta(BranchScopedModel.Meta):
        ordering = ["-received_at", "-created_at"]


class BankStatementImport(TenantModel):
    """A bank statement file (CSV, OFX, CAMT.053) or an Open Banking feed sync (FR-11-5)."""

    class Source(models.TextChoices):
        CSV = "csv", _("CSV")
        OFX = "ofx", _("OFX / QFX")
        CAMT = "camt", _("CAMT.053 (ISO 20022)")
        OPEN_BANKING = "open_banking", _("Open Banking feed")

    source = models.CharField(max_length=12, choices=Source.choices)
    filename = models.CharField(max_length=255, blank=True, default="")
    account_name = models.CharField(max_length=120, blank=True, default="")
    currency = CurrencyField()
    connection_id = models.CharField(max_length=64, blank=True, default="")  # Open Banking
    stats = models.JSONField(default=dict, blank=True)  # rows, new, duplicates, suggested
    imported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta(TenantModel.Meta):
        ordering = ["-created_at"]


class BankTransaction(TenantModel):
    """A line on the bank statement, waiting to be matched (the reconciliation queue)."""

    class Status(models.TextChoices):
        UNMATCHED = "unmatched", _("No match found")
        SUGGESTED = "suggested", _("Suggested match")
        MATCHED = "matched", _("Matched")
        IGNORED = "ignored", _("Ignored")

    statement = models.ForeignKey(
        BankStatementImport, on_delete=models.PROTECT, related_name="transactions"
    )
    external_id = models.CharField(max_length=128)  # FITID / entry ref / hash: dedupes imports
    booked_on = models.DateField()
    currency = CurrencyField()
    amount = MoneyField()  # credits positive, debits negative
    description = models.CharField(max_length=500, blank=True, default="")
    reference = models.CharField(max_length=200, blank=True, default="")
    counterparty = models.CharField(max_length=200, blank=True, default="")
    status = models.CharField(max_length=9, choices=Status.choices, default=Status.UNMATCHED)
    payment = models.ForeignKey(
        Payment, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    payment_group = models.ForeignKey(
        PaymentGroup, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    payout = models.ForeignKey(
        ProviderPayout, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    matched_at = models.DateTimeField(null=True, blank=True)
    matched_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta(TenantModel.Meta):
        ordering = ["-booked_on", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "external_id"], name="bank_transaction_unique"
            )
        ]
        indexes = [models.Index(fields=["organisation", "status"], name="bank_txn_status_idx")]


class ReconciliationMatch(TenantModel):
    """A suggested (or confirmed) match for a bank transaction."""

    class Kind(models.TextChoices):
        INVOICE = "invoice", _("Invoice")
        PAYMENT_REQUEST = "payment_request", _("Payment request")
        CLIENT = "client", _("Client account")
        PAYMENT = "payment", _("Payment already recorded")
        PAYOUT = "payout", _("Provider payout")

    class Status(models.TextChoices):
        SUGGESTED = "suggested", _("Suggested")
        CONFIRMED = "confirmed", _("Confirmed")
        REJECTED = "rejected", _("Rejected")

    transaction = models.ForeignKey(
        BankTransaction, on_delete=models.CASCADE, related_name="matches"
    )
    kind = models.CharField(max_length=15, choices=Kind.choices)
    invoice = models.ForeignKey(
        "billing.Invoice", null=True, blank=True, on_delete=models.CASCADE, related_name="+"
    )
    payment_request = models.ForeignKey(
        "billing.PaymentRequest", null=True, blank=True, on_delete=models.CASCADE, related_name="+"
    )
    client = models.ForeignKey(
        "people.Client", null=True, blank=True, on_delete=models.CASCADE, related_name="+"
    )
    payment = models.ForeignKey(
        Payment, null=True, blank=True, on_delete=models.CASCADE, related_name="+"
    )
    payout = models.ForeignKey(
        ProviderPayout, null=True, blank=True, on_delete=models.CASCADE, related_name="+"
    )
    score = models.PositiveSmallIntegerField()
    reason = models.CharField(max_length=200)
    status = models.CharField(max_length=9, choices=Status.choices, default=Status.SUGGESTED)

    class Meta(TenantModel.Meta):
        ordering = ["-score", "created_at"]


class ProviderMigration(TenantModel):
    """Moving a client to another provider (FR-11-2): a setup link for the new provider,
    switch the default when a method is added, then cancel the old mandate once nothing is
    being collected with it (``ProviderMigrationWorkflow``)."""

    class Status(models.TextChoices):
        WAITING = "waiting", _("Waiting for the client")
        SWITCHED = "switched", _("Switched; old method still settling")
        COMPLETED = "completed", _("Completed")
        CANCELLED = "cancelled", _("Cancelled")
        EXPIRED = "expired", _("Client didn't set up the new method")

    client = models.ForeignKey("people.Client", on_delete=models.CASCADE, related_name="+")
    from_method = models.ForeignKey(
        PaymentMethod, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    to_provider = models.CharField(max_length=10, choices=Provider.choices)
    new_method = models.ForeignKey(
        PaymentMethod, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    status = models.CharField(max_length=9, choices=Status.choices, default=Status.WAITING)
    workflow_id = models.CharField(max_length=255, blank=True, default="")
    completed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta(TenantModel.Meta):
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["client"],
                condition=Q(status__in=["waiting", "switched"]),
                name="provider_migration_one_open",
            )
        ]
