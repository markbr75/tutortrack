"""Reviews, referrals and affiliates (E25).

* **Reviews** (FR-25-1): a ``ReviewRequest`` asks a family to rate a tutor (or the business)
  after N completed lessons or a trial (``ReviewRequestWorkflow`` sends it and a reminder);
  the ``Review`` they submit goes to a moderation queue, can be published as an E24
  ``sites.Testimonial`` and feeds tutor ratings (matching E19, directory E24).
* **Client referrals** (FR-25-2): every client (and tutor, FR-25-4) has a ``ReferralCode``;
  an enquiry made with it creates a ``Referral``. ``ReferralRewardWorkflow`` waits for the
  referee's first payment (or N lessons), runs fraud checks and gives the referrer account
  credit (E10) and the referee a discount (E06).
* **Affiliates** (FR-25-3): ``Affiliate`` partners with tracking ``AffiliateLink``s; clients
  they bring are ``AffiliateReferral``s. ``CommissionRule``s turn collected payments into
  ``CommissionItem``s (refunds claw back), grouped into monthly ``AffiliateStatement``s and
  paid with E12's bank file or manually.
* **Tutor referrals** (FR-25-4): ``TutorReferral`` pays a tutor a bonus (E12 pay item) when the
  tutor or client they referred reaches a milestone.

Commission items and statements are financial records: never edited or deleted after they
are created; corrections are new (negative) items.
"""

from __future__ import annotations

from typing import Any, ClassVar

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from tutortrack.core.crypto import EncryptedField
from tutortrack.core.fields import CurrencyField, MoneyField
from tutortrack.core.models import TenantModel


class ImmutableRecord(Exception):
    """A financial record was about to be changed."""


# --- reviews (T01, T02) -------------------------------------------------------------------------


class ReviewRequest(TenantModel):
    """An invitation to review (sent by email with a signed link)."""

    class Status(models.TextChoices):
        PENDING = "pending", _("Sent")
        REMINDED = "reminded", _("Reminded")
        SUBMITTED = "submitted", _("Reviewed")
        EXPIRED = "expired", _("Expired")
        CANCELLED = "cancelled", _("Cancelled")

    class Trigger(models.TextChoices):
        LESSONS = "lessons", _("After N lessons")
        TRIAL = "trial", _("After a trial lesson")
        AUTOMATION = "automation", _("Automation")
        MANUAL = "manual", _("Sent by staff")

    client = models.ForeignKey("people.Client", on_delete=models.CASCADE, related_name="+")
    contact = models.ForeignKey(
        "people.Contact", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    student = models.ForeignKey(
        "people.Student", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    tutor = models.ForeignKey(
        "people.TutorProfile", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    trigger = models.CharField(max_length=12, choices=Trigger.choices, default=Trigger.MANUAL)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    lesson_count = models.PositiveIntegerField(default=0)
    sent_at = models.DateTimeField(null=True, blank=True)
    reminded_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField()
    workflow_id = models.CharField(max_length=200, blank=True, default="")

    class Meta(TenantModel.Meta):
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["client", "tutor"], name="review_request_pair_idx")]

    def __str__(self) -> str:
        return f"Review request {self.pk}"


class Review(TenantModel):
    """A rating (1-5, with optional criteria) and comment from a family (FR-25-1)."""

    class Status(models.TextChoices):
        PENDING = "pending", _("Waiting for moderation")
        APPROVED = "approved", _("Approved")
        HIDDEN = "hidden", _("Hidden")

    class Source(models.TextChoices):
        REQUEST = "request", _("Review request")
        PORTAL = "portal", _("Portal")
        STAFF = "staff", _("Entered by staff")

    request = models.OneToOneField(
        ReviewRequest, null=True, blank=True, on_delete=models.SET_NULL, related_name="review"
    )
    client = models.ForeignKey("people.Client", on_delete=models.CASCADE, related_name="+")
    contact = models.ForeignKey(
        "people.Contact", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    student = models.ForeignKey(
        "people.Student", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    tutor = models.ForeignKey(
        "people.TutorProfile", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )  # null: a review of the business
    rating = models.PositiveSmallIntegerField()
    criteria = models.JSONField(default=dict, blank=True)  # {criterion key: 1-5}
    text = models.TextField(blank=True, default="")
    reviewer_name = models.CharField(max_length=120)  # as the reviewer agreed to be named
    publish_consent = models.BooleanField(default=False)
    source = models.CharField(max_length=8, choices=Source.choices, default=Source.REQUEST)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.PENDING)
    moderated_at = models.DateTimeField(null=True, blank=True)
    moderated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    response = models.TextField(blank=True, default="")
    responded_at = models.DateTimeField(null=True, blank=True)
    testimonial = models.ForeignKey(
        "sites.Testimonial", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    google_prompted = models.BooleanField(default=False)

    class Meta(TenantModel.Meta):
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(rating__gte=1, rating__lte=5), name="review_rating_1_5"
            )
        ]
        indexes = [models.Index(fields=["tutor", "status"], name="review_tutor_status_idx")]

    def __str__(self) -> str:
        return f"{self.rating}/5 by {self.reviewer_name}"

    @classmethod
    def own_scope_q(cls, user: Any) -> Q:
        """Tutors see approved reviews about them (if the organisation allows it)."""
        return Q(tutor__membership__user_id=getattr(user, "pk", None), status="approved")


# --- client referrals (T03) ---------------------------------------------------------------------


class ReferralProgram(TenantModel):
    """Give/get rules (FR-25-2). The newest active programme applies to new referrals."""

    class RewardKind(models.TextChoices):
        CREDIT = "credit", _("Account credit")
        FREE_LESSON = "free_lesson", _("A free lesson (as credit)")

    class Milestone(models.TextChoices):
        FIRST_PAYMENT = "first_payment", _("The new family pays their first invoice")
        LESSONS = "lessons", _("The new family completes a number of lessons")

    name = models.CharField(max_length=120)
    active = models.BooleanField(default=True)
    currency = CurrencyField()
    referrer_reward_kind = models.CharField(
        max_length=12, choices=RewardKind.choices, default=RewardKind.CREDIT
    )
    referrer_reward = MoneyField()
    milestone = models.CharField(
        max_length=14, choices=Milestone.choices, default=Milestone.FIRST_PAYMENT
    )
    milestone_lessons = models.PositiveIntegerField(default=1)
    referee_discount_percent = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )
    referee_discount_days = models.PositiveIntegerField(default=90)
    deadline_days = models.PositiveIntegerField(default=180)  # to reach the milestone
    max_rewards_per_period = models.PositiveIntegerField(null=True, blank=True)
    period_days = models.PositiveIntegerField(default=365)
    terms = models.TextField(blank=True, default="")

    class Meta(TenantModel.Meta):
        ordering = ["-active", "-created_at"]

    def __str__(self) -> str:
        return self.name


class ReferralCode(TenantModel):
    """A client's (or tutor's, FR-25-4) personal code, used in links as ``?ref=CODE``."""

    code = models.CharField(max_length=20)
    client = models.OneToOneField(
        "people.Client", null=True, blank=True, on_delete=models.CASCADE, related_name="+"
    )
    tutor = models.OneToOneField(
        "people.TutorProfile",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="+",
    )
    clicks = models.PositiveIntegerField(default=0)
    active = models.BooleanField(default=True)

    class Meta(TenantModel.Meta):
        ordering = ["code"]
        constraints = [
            models.UniqueConstraint(fields=["organisation", "code"], name="referral_code_unique"),
            models.CheckConstraint(
                condition=Q(client__isnull=False, tutor__isnull=True)
                | Q(client__isnull=True, tutor__isnull=False),
                name="referral_code_one_owner",
            ),
        ]

    def __str__(self) -> str:
        return self.code


class Referral(TenantModel):
    """A family referred by another (FR-25-2)."""

    class Status(models.TextChoices):
        PENDING = "pending", _("Waiting for the milestone")
        CONVERTED = "converted", _("Milestone reached")
        REWARDED = "rewarded", _("Rewarded")
        BLOCKED = "blocked", _("Held by fraud checks")
        EXPIRED = "expired", _("Expired")
        CANCELLED = "cancelled", _("Cancelled")

    class Source(models.TextChoices):
        LINK = "link", _("Referral link")
        CODE = "code", _("Code entered")
        STAFF = "staff", _("Added by staff")

    program = models.ForeignKey(ReferralProgram, on_delete=models.PROTECT, related_name="+")
    code = models.ForeignKey(
        ReferralCode, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    referrer = models.ForeignKey("people.Client", on_delete=models.PROTECT, related_name="+")
    referee = models.ForeignKey("people.Client", on_delete=models.PROTECT, related_name="+")
    enquiry_id = models.CharField(max_length=64, blank=True, default="")
    source = models.CharField(max_length=6, choices=Source.choices, default=Source.LINK)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    deadline = models.DateTimeField()
    converted_at = models.DateTimeField(null=True, blank=True)
    rewarded_at = models.DateTimeField(null=True, blank=True)
    fraud_flags = models.JSONField(default=list, blank=True)
    currency = CurrencyField(blank=True, default="")
    referrer_credit = MoneyField(null=True, blank=True)
    referee_discount_id = models.CharField(max_length=64, blank=True, default="")
    note = models.CharField(max_length=300, blank=True, default="")
    workflow_id = models.CharField(max_length=200, blank=True, default="")

    class Meta(TenantModel.Meta):
        ordering = ["-created_at"]
        constraints = [
            # A family can only be referred once.
            models.UniqueConstraint(fields=["organisation", "referee"], name="referral_once")
        ]

    def __str__(self) -> str:
        return f"{self.referrer_id} → {self.referee_id}"


# --- affiliates (T04, T05) ----------------------------------------------------------------------


class Affiliate(TenantModel):
    """A partner (school, blogger, agency) earning commission on clients they bring."""

    class Kind(models.TextChoices):
        INDIVIDUAL = "individual", _("Individual")
        ORGANISATION = "organisation", _("Organisation")

    class Status(models.TextChoices):
        ACTIVE = "active", _("Active")
        PAUSED = "paused", _("Paused (no new commission)")
        ARCHIVED = "archived", _("Archived")

    class PayoutMethod(models.TextChoices):
        BANK_FILE = "bank_file", _("Bank transfer (payment file)")
        MANUAL = "manual", _("Paid manually")

    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.INDIVIDUAL)
    name = models.CharField(max_length=150)
    email = models.EmailField()
    phone = models.CharField(max_length=32, blank=True, default="")
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.ACTIVE)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    currency = CurrencyField()
    payout_method = models.CharField(
        max_length=10, choices=PayoutMethod.choices, default=PayoutMethod.MANUAL
    )
    payee_name = models.CharField(max_length=140, blank=True, default="")
    bank_country = models.CharField(max_length=2, blank=True, default="")
    bank_details = EncryptedField(blank=True, default="")  # JSON, see payroll.banking
    bank_hint = models.CharField(max_length=40, blank=True, default="")
    notes = models.TextField(blank=True, default="")

    audit_sensitive_fields: ClassVar[frozenset[str]] = frozenset({"bank_details"})

    class Meta(TenantModel.Meta):
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    @classmethod
    def own_scope_q(cls, user: Any) -> Q:
        return Q(user_id=getattr(user, "pk", None))


class AffiliateLink(TenantModel):
    """A tracking link (``?ref=CODE``) or code an affiliate shares."""

    affiliate = models.ForeignKey(Affiliate, on_delete=models.CASCADE, related_name="links")
    code = models.CharField(max_length=20)
    name = models.CharField(max_length=120, blank=True, default="")
    landing_path = models.CharField(max_length=200, blank=True, default="/")
    clicks = models.PositiveIntegerField(default=0)
    active = models.BooleanField(default=True)

    class Meta(TenantModel.Meta):
        ordering = ["code"]
        constraints = [
            models.UniqueConstraint(fields=["organisation", "code"], name="affiliate_link_unique")
        ]

    def __str__(self) -> str:
        return self.code

    @classmethod
    def own_scope_q(cls, user: Any) -> Q:
        return Q(affiliate__user_id=getattr(user, "pk", None))


class AffiliateReferral(TenantModel):
    """A client attributed to an affiliate (one affiliate per client)."""

    class Source(models.TextChoices):
        LINK = "link", _("Tracking link")
        STAFF = "staff", _("Added by staff")

    affiliate = models.ForeignKey(Affiliate, on_delete=models.PROTECT, related_name="referrals")
    client = models.ForeignKey("people.Client", on_delete=models.PROTECT, related_name="+")
    link = models.ForeignKey(
        AffiliateLink, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    source = models.CharField(max_length=5, choices=Source.choices, default=Source.LINK)
    attributed_at = models.DateTimeField()
    converted_at = models.DateTimeField(null=True, blank=True)  # first payment
    enquiry_id = models.CharField(max_length=64, blank=True, default="")

    class Meta(TenantModel.Meta):
        ordering = ["-attributed_at"]
        constraints = [
            models.UniqueConstraint(fields=["organisation", "client"], name="affiliate_client_once")
        ]

    def __str__(self) -> str:
        return f"{self.affiliate_id}: {self.client_id}"

    @classmethod
    def own_scope_q(cls, user: Any) -> Q:
        return Q(affiliate__user_id=getattr(user, "pk", None))


class CommissionRule(TenantModel):
    """How an affiliate earns (FR-25-3). ``affiliate`` null = the default for everyone;
    an affiliate's own active rules replace the defaults (per-affiliate overrides)."""

    class Kind(models.TextChoices):
        PERCENT = "percent", _("Percentage of collected revenue")
        BOUNTY = "bounty", _("Fixed bounty per converted client")

    affiliate = models.ForeignKey(
        Affiliate, null=True, blank=True, on_delete=models.CASCADE, related_name="rules"
    )
    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=8, choices=Kind.choices, default=Kind.PERCENT)
    active = models.BooleanField(default=True)
    percent = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    # [{"from_clients": 10, "percent": "15.00"}]: higher rate once the affiliate has
    # converted that many clients (tiered rates).
    tiers = models.JSONField(default=list, blank=True)
    currency = CurrencyField(blank=True, default="")
    bounty = MoneyField(null=True, blank=True)
    duration_months = models.PositiveIntegerField(null=True, blank=True)  # null: lifetime

    class Meta(TenantModel.Meta):
        ordering = ["affiliate", "kind", "name"]
        constraints = [
            models.CheckConstraint(
                condition=Q(kind="percent", percent__isnull=False)
                | Q(kind="bounty", bounty_amount__isnull=False),
                name="commission_rule_has_value",
            )
        ]

    def __str__(self) -> str:
        return self.name


class AffiliateStatement(TenantModel):
    """A monthly statement of an affiliate's commission items, paid as one payout."""

    class Status(models.TextChoices):
        ISSUED = "issued", _("Issued")
        PAID = "paid", _("Paid")

    affiliate = models.ForeignKey(Affiliate, on_delete=models.PROTECT, related_name="statements")
    number = models.CharField(max_length=30)
    period_start = models.DateField()
    period_end = models.DateField()
    currency = CurrencyField()
    total = MoneyField()
    status = models.CharField(max_length=6, choices=Status.choices, default=Status.ISSUED)
    issued_at = models.DateTimeField()
    paid_at = models.DateTimeField(null=True, blank=True)
    payout_method = models.CharField(max_length=10, blank=True, default="")
    payout_reference = models.CharField(max_length=100, blank=True, default="")

    class Meta(TenantModel.Meta):
        ordering = ["-period_end", "number"]
        constraints = [
            models.UniqueConstraint(fields=["organisation", "number"], name="statement_number")
        ]

    def __str__(self) -> str:
        return self.number

    @classmethod
    def own_scope_q(cls, user: Any) -> Q:
        return Q(affiliate__user_id=getattr(user, "pk", None))


class CommissionItem(TenantModel):
    """One commission line: earned on a payment, a bounty, or a clawback (negative)."""

    class Kind(models.TextChoices):
        COMMISSION = "commission", _("Commission")
        BOUNTY = "bounty", _("Bounty")
        CLAWBACK = "clawback", _("Clawback (refund)")
        ADJUSTMENT = "adjustment", _("Adjustment")

    affiliate = models.ForeignKey(Affiliate, on_delete=models.PROTECT, related_name="items")
    referral = models.ForeignKey(
        AffiliateReferral, null=True, blank=True, on_delete=models.PROTECT, related_name="items"
    )
    client = models.ForeignKey(
        "people.Client", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    rule = models.ForeignKey(
        CommissionRule, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    kind = models.CharField(max_length=10, choices=Kind.choices)
    source_key = models.CharField(max_length=120)  # payment:<id>, refund:<id>, bounty:<id>
    payment_id = models.CharField(max_length=64, blank=True, default="")
    currency = CurrencyField()
    base = MoneyField(null=True, blank=True)  # the revenue the rate applied to
    rate = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    amount = MoneyField()
    description = models.CharField(max_length=300, blank=True, default="")
    earned_at = models.DateTimeField()
    statement = models.ForeignKey(
        AffiliateStatement, null=True, blank=True, on_delete=models.PROTECT, related_name="items"
    )

    class Meta(TenantModel.Meta):
        ordering = ["-earned_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "source_key"], name="commission_item_source"
            )
        ]

    def __str__(self) -> str:
        return f"{self.kind} {self.amount}"

    @classmethod
    def own_scope_q(cls, user: Any) -> Q:
        return Q(affiliate__user_id=getattr(user, "pk", None))

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Only the statement link may change after creation (financial record)."""
        fields = kwargs.get("update_fields")
        if not self._state.adding and (fields is None or set(fields) - {"statement", "updated_at"}):
            raise ImmutableRecord("Commission items are never changed; add an adjustment.")
        super().save(*args, **kwargs)


# --- tutor referral bonuses (T06) ---------------------------------------------------------------


class TutorReferral(TenantModel):
    """A tutor who referred another tutor (E18 application) or a client (FR-25-4)."""

    class Kind(models.TextChoices):
        TUTOR = "tutor", _("Tutor referral")
        CLIENT = "client", _("Client referral")

    class Status(models.TextChoices):
        PENDING = "pending", _("Waiting for the milestone")
        PAID = "paid", _("Bonus added to pay")
        REJECTED = "rejected", _("Rejected")

    referrer = models.ForeignKey("people.TutorProfile", on_delete=models.PROTECT, related_name="+")
    kind = models.CharField(max_length=6, choices=Kind.choices)
    application_id = models.CharField(max_length=64, blank=True, default="")
    referred_tutor = models.ForeignKey(
        "people.TutorProfile", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    client = models.ForeignKey(
        "people.Client", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    referred_name = models.CharField(max_length=200, blank=True, default="")
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.PENDING)
    currency = CurrencyField(blank=True, default="")
    bonus = MoneyField(null=True, blank=True)
    pay_item_id = models.CharField(max_length=64, blank=True, default="")
    qualified_at = models.DateTimeField(null=True, blank=True)
    note = models.CharField(max_length=300, blank=True, default="")

    class Meta(TenantModel.Meta):
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "application_id"],
                condition=~Q(application_id=""),
                name="tutor_referral_application_once",
            ),
            models.UniqueConstraint(
                fields=["organisation", "client"],
                condition=Q(client__isnull=False),
                name="tutor_referral_client_once",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.referrer_id}: {self.kind}"

    @classmethod
    def own_scope_q(cls, user: Any) -> Q:
        return Q(referrer__membership__user_id=getattr(user, "pk", None))
