"""Group classes, courses, terms and enrolment (E20).

A **Course** is the product ("Year 6 11+ Prep"), a **GroupClass** one scheduled cohort of it
in a **Term** (Saturdays 10:00-11:30, room 2, 12 places). Each class runs on an E08 lesson
series; every session is a ``scheduling.Lesson`` linked by ``ClassSession``, and the class
roster (its active **Enrolments** plus makeup bookings) decides each future session's
attendees. Fees are E10 charges and plans; online enrolment holds the place until payment
(``EnrolmentPaymentWorkflow``) and term rollover asks families to confirm
(``TermRolloverWorkflow``).
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.db import models
from django.db.models import F, Q
from django.utils.translation import gettext_lazy as _

from tutortrack.core.fields import CurrencyField, MoneyField
from tutortrack.core.models import BranchScopedModel, TenantModel


class AcademicYear(BranchScopedModel):
    name = models.CharField(max_length=100)
    start_date = models.DateField()
    end_date = models.DateField()

    class Meta(BranchScopedModel.Meta):
        ordering = ["-start_date"]
        constraints = [
            models.CheckConstraint(
                condition=Q(end_date__gte=F("start_date")), name="academic_year_dates"
            ),
            models.UniqueConstraint(fields=["branch", "name"], name="academic_year_name_unique"),
        ]

    def __str__(self) -> str:
        return self.name


class Term(BranchScopedModel):
    """A date range for enrolment and billing (FR-20-1). Breaks (half term) are skipped by
    class sessions and left out of proration."""

    academic_year = models.ForeignKey(AcademicYear, on_delete=models.PROTECT, related_name="terms")
    name = models.CharField(max_length=100)
    start_date = models.DateField()
    end_date = models.DateField()
    enrolment_opens = models.DateField(null=True, blank=True)
    enrolment_closes = models.DateField(null=True, blank=True)

    class Meta(BranchScopedModel.Meta):
        ordering = ["start_date"]
        constraints = [
            models.CheckConstraint(condition=Q(end_date__gte=F("start_date")), name="term_dates")
        ]

    def __str__(self) -> str:
        return self.name


class TermBreak(TenantModel):
    term = models.ForeignKey(Term, on_delete=models.CASCADE, related_name="breaks")
    name = models.CharField(max_length=100)
    start_date = models.DateField()
    end_date = models.DateField()

    class Meta(TenantModel.Meta):
        ordering = ["start_date"]
        constraints = [
            models.CheckConstraint(
                condition=Q(end_date__gte=F("start_date")), name="term_break_dates"
            )
        ]


class Course(TenantModel):
    """A curriculum product (FR-20-2). ``price`` is per term, month, session or for the
    whole course, by ``pricing_model``."""

    class PricingModel(models.TextChoices):
        PER_TERM = "per_term", _("Per term")
        PER_MONTH = "per_month", _("Per month")
        PER_SESSION = "per_session", _("Per session (pay as you go)")
        FULL_COURSE = "full_course", _("Whole course up front")
        INSTALMENTS = "instalments", _("Whole course in instalments")

    class DeliveryMode(models.TextChoices):
        IN_PERSON = "in_person", _("In person")
        ONLINE = "online", _("Online")
        HYBRID = "hybrid", _("Hybrid")

    name = models.CharField(max_length=150)
    description = models.TextField(blank=True, default="")  # internal
    public_description = models.TextField(blank=True, default="")
    # The catalogue service sessions are scheduled as (E06 rates, tutor pay, tax).
    service = models.ForeignKey("catalogue.Service", on_delete=models.PROTECT, related_name="+")
    subject = models.ForeignKey(
        "catalogue.Subject", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    level = models.ForeignKey(
        "catalogue.Level", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    min_age = models.PositiveSmallIntegerField(null=True, blank=True)
    max_age = models.PositiveSmallIntegerField(null=True, blank=True)
    year_groups = models.JSONField(default=list, blank=True)  # e.g. ["Year 5", "Year 6"]
    prerequisites = models.TextField(blank=True, default="")
    duration_weeks = models.PositiveSmallIntegerField(null=True, blank=True)
    duration_sessions = models.PositiveSmallIntegerField(null=True, blank=True)
    delivery_mode = models.CharField(
        max_length=10, choices=DeliveryMode.choices, default=DeliveryMode.IN_PERSON
    )
    default_capacity = models.PositiveIntegerField(default=10)
    pricing_model = models.CharField(
        max_length=12, choices=PricingModel.choices, default=PricingModel.PER_TERM
    )
    currency = CurrencyField()
    price = MoneyField()
    instalments = models.PositiveSmallIntegerField(default=1)
    deposit = MoneyField(null=True, blank=True)
    registration_fee = MoneyField(null=True, blank=True)
    materials_fee = MoneyField(null=True, blank=True)
    tax_rate = models.ForeignKey(
        "catalogue.TaxRate", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    image = models.ForeignKey(
        "core.StoredFile", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    is_public = models.BooleanField(default=False)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(condition=Q(price_amount__gte=0), name="course_price_positive"),
            models.CheckConstraint(condition=Q(instalments__gte=1), name="course_instalments"),
        ]

    def __str__(self) -> str:
        return self.name


class GroupClass(BranchScopedModel):
    """A scheduled cohort of a course in a term (FR-20-3), called "class" in the API."""

    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        OPEN = "open", _("Open for enrolment")
        FULL = "full", _("Full")
        RUNNING = "running", _("Running")
        COMPLETED = "completed", _("Completed")
        CANCELLED = "cancelled", _("Cancelled")

    ENROLLABLE = ("open", "full", "running")

    class TeacherPay(models.TextChoices):
        SERVICE = "service", _("Usual tutor rates for the service")
        PER_SESSION = "per_session", _("A fixed amount per session")
        HEADCOUNT = "headcount", _("By number of students")
        FIXED = "fixed", _("A fixed amount for the whole class")

    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name="classes")
    term = models.ForeignKey(Term, on_delete=models.PROTECT, related_name="classes")
    name = models.CharField(max_length=150)
    rrule = models.CharField(max_length=300, default="FREQ=WEEKLY")
    start_date = models.DateField()
    end_date = models.DateField()
    start_time = models.TimeField()
    duration_minutes = models.PositiveIntegerField()
    timezone = models.CharField(max_length=64)
    series = models.ForeignKey(
        "scheduling.LessonSeries",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    location = models.ForeignKey(
        "catalogue.Location", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    room = models.ForeignKey(
        "catalogue.Room", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    online = models.BooleanField(default=False)
    capacity = models.PositiveIntegerField()
    min_size = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    waitlist_enabled = models.BooleanField(default=True)
    # Age/year gating for this class; empty uses the course's.
    min_age = models.PositiveSmallIntegerField(null=True, blank=True)
    max_age = models.PositiveSmallIntegerField(null=True, blank=True)
    year_groups = models.JSONField(default=list, blank=True)
    teacher_pay_mode = models.CharField(
        max_length=11, choices=TeacherPay.choices, default=TeacherPay.SERVICE
    )
    # {"amount": "25.00"} (per session / fixed total) or {"tiers": [{"from": 1, "amount":
    # "20.00"}, {"from": 8, "amount": "30.00"}]} (headcount), in the course currency.
    teacher_pay = models.JSONField(default=dict, blank=True)
    is_public = models.BooleanField(default=True)
    next_class = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )  # where its students roll over to next term
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.CharField(max_length=300, blank=True, default="")

    class Meta(BranchScopedModel.Meta):
        ordering = ["start_date", "start_time", "name"]
        verbose_name = "class"
        verbose_name_plural = "classes"
        constraints = [
            models.CheckConstraint(condition=Q(end_date__gte=F("start_date")), name="class_dates"),
            models.CheckConstraint(condition=Q(capacity__gte=1), name="class_capacity"),
        ]

    def __str__(self) -> str:
        return self.name

    @classmethod
    def own_scope_q(cls, user: Any) -> Q:
        return Q(
            pk__in=ClassTeacher.objects.filter(tutor__membership__user=user).values(
                "group_class_id"
            )
        )


class ClassTeacher(TenantModel):
    class Role(models.TextChoices):
        LEAD = "lead", _("Teacher")
        ASSISTANT = "assistant", _("Assistant")

    group_class = models.ForeignKey(GroupClass, on_delete=models.CASCADE, related_name="teachers")
    tutor = models.ForeignKey("people.TutorProfile", on_delete=models.PROTECT, related_name="+")
    role = models.CharField(max_length=9, choices=Role.choices, default=Role.LEAD)
    currency = CurrencyField(blank=True, default="")
    pay_per_session = MoneyField(null=True, blank=True)  # overrides the class pay rule

    class Meta(TenantModel.Meta):
        ordering = ["role", "created_at"]
        constraints = [
            models.UniqueConstraint(fields=["group_class", "tutor"], name="class_teacher_unique")
        ]


class ClassSession(TenantModel):
    """One session of a class: a lesson (E08) whose attendees follow the roster."""

    group_class = models.ForeignKey(GroupClass, on_delete=models.CASCADE, related_name="sessions")
    lesson = models.OneToOneField(
        "scheduling.Lesson", on_delete=models.CASCADE, related_name="class_session"
    )
    number = models.PositiveSmallIntegerField(default=1)
    date = models.DateField()
    absence_reasons = models.JSONField(default=dict, blank=True)  # {student id: reason}

    class Meta(TenantModel.Meta):
        ordering = ["date", "number"]

    @classmethod
    def own_scope_q(cls, user: Any) -> Q:
        return Q(group_class__in=GroupClass.objects.filter(GroupClass.own_scope_q(user)))


class Enrolment(BranchScopedModel):
    """A student's place in a class (FR-20-4)."""

    class Status(models.TextChoices):
        PENDING_PAYMENT = "pending_payment", _("Waiting for payment")
        ENROLLED = "enrolled", _("Enrolled")
        TRIAL = "trial", _("Trial")
        WITHDRAWN = "withdrawn", _("Withdrawn")
        COMPLETED = "completed", _("Completed")
        TRANSFERRED = "transferred", _("Transferred")

    ACTIVE = ("pending_payment", "enrolled", "trial")
    ATTENDING = ("enrolled", "trial")

    class Source(models.TextChoices):
        STAFF = "staff", _("Staff")
        PORTAL = "portal", _("Client portal")
        PUBLIC = "public", _("Website")
        WAITLIST = "waitlist", _("Waitlist offer")
        ROLLOVER = "rollover", _("Term rollover")
        TRANSFER = "transfer", _("Transfer")

    class Payment(models.TextChoices):
        NONE = "none", _("Invoice as usual")
        FULL = "full", _("Pay in full now")
        DEPOSIT = "deposit", _("Pay a deposit now")

    group_class = models.ForeignKey(GroupClass, on_delete=models.PROTECT, related_name="enrolments")
    student = models.ForeignKey("people.Student", on_delete=models.PROTECT, related_name="+")
    client = models.ForeignKey("people.Client", on_delete=models.PROTECT, related_name="+")
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.ENROLLED)
    source = models.CharField(max_length=8, choices=Source.choices, default=Source.STAFF)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    currency = CurrencyField()
    fee = MoneyField()  # the price after discounts, per the course's pricing model
    price_snapshot = models.JSONField(default=dict, blank=True)
    billing_plan_id = models.UUIDField(null=True, blank=True)  # billing.BillingPlan (monthly)
    payment = models.CharField(max_length=7, choices=Payment.choices, default=Payment.NONE)
    payment_request_id = models.UUIDField(null=True, blank=True)  # billing.PaymentRequest
    hold_expires_at = models.DateTimeField(null=True, blank=True)
    billed_at = models.DateTimeField(null=True, blank=True)
    terms_accepted_at = models.DateTimeField(null=True, blank=True)
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    withdrawal_reason = models.CharField(max_length=300, blank=True, default="")
    waitlist_entry_id = models.UUIDField(null=True, blank=True)  # leads.WaitlistEntry
    contact = models.JSONField(default=dict, blank=True)  # new families from the website
    token_hash = models.CharField(max_length=64, blank=True, default="")  # public status link
    workflow_id = models.CharField(max_length=255, blank=True, default="")
    created_by_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta(BranchScopedModel.Meta):
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["group_class", "student"],
                condition=Q(status__in=["pending_payment", "enrolled", "trial"]),
                name="enrolment_one_active_per_class",
            )
        ]
        indexes = [models.Index(fields=["group_class", "status"], name="enrolment_class_status")]

    @classmethod
    def own_scope_q(cls, user: Any) -> Q:
        return Q(group_class__in=GroupClass.objects.filter(GroupClass.own_scope_q(user)))


class EnrolmentTransfer(TenantModel):
    from_enrolment = models.ForeignKey(
        Enrolment, on_delete=models.PROTECT, related_name="transfers_out"
    )
    to_enrolment = models.ForeignKey(
        Enrolment, on_delete=models.PROTECT, related_name="transfers_in"
    )
    effective_date = models.DateField()
    reason = models.CharField(max_length=300, blank=True, default="")
    adjustment = models.JSONField(default=dict, blank=True)  # fees kept, credited and charged
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta(TenantModel.Meta):
        ordering = ["-created_at"]


class MakeupBooking(TenantModel):
    """A student catching up in another class of the same course (FR-20-6)."""

    class Status(models.TextChoices):
        BOOKED = "booked", _("Booked")
        CANCELLED = "cancelled", _("Cancelled")

    session = models.ForeignKey(ClassSession, on_delete=models.CASCADE, related_name="makeups")
    student = models.ForeignKey("people.Student", on_delete=models.PROTECT, related_name="+")
    client = models.ForeignKey("people.Client", on_delete=models.PROTECT, related_name="+")
    from_session = models.ForeignKey(
        ClassSession, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    makeup_credit_id = models.UUIDField(null=True, blank=True)  # delivery.MakeupCredit
    status = models.CharField(max_length=9, choices=Status.choices, default=Status.BOOKED)

    class Meta(TenantModel.Meta):
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["session", "student"],
                condition=Q(status="booked"),
                name="makeup_one_per_session",
            )
        ]


class TermRollover(TenantModel):
    """Re-enrolment for the next term (FR-20-4) run by ``TermRolloverWorkflow``."""

    class Mode(models.TextChoices):
        CONFIRM = "confirm", _("Families confirm to keep their place")
        OPT_OUT = "opt_out", _("Places roll over unless families opt out")

    class Status(models.TextChoices):
        RUNNING = "running", _("Waiting for families")
        FINALISED = "finalised", _("Finished")
        CANCELLED = "cancelled", _("Cancelled")

    from_term = models.ForeignKey(Term, on_delete=models.PROTECT, related_name="+")
    to_term = models.ForeignKey(Term, on_delete=models.PROTECT, related_name="+")
    mode = models.CharField(max_length=7, choices=Mode.choices, default=Mode.CONFIRM)
    deadline = models.DateTimeField()
    status = models.CharField(max_length=9, choices=Status.choices, default=Status.RUNNING)
    stats = models.JSONField(default=dict, blank=True)
    workflow_id = models.CharField(max_length=255, blank=True, default="")
    finalised_at = models.DateTimeField(null=True, blank=True)
    started_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta(TenantModel.Meta):
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["from_term"],
                condition=Q(status="running"),
                name="rollover_one_running_per_term",
            )
        ]


class RolloverOffer(TenantModel):
    class Status(models.TextChoices):
        PENDING = "pending", _("Waiting for the family")
        CONFIRMED = "confirmed", _("Confirmed")
        DECLINED = "declined", _("Not continuing")
        ENROLLED = "enrolled", _("Enrolled")
        RELEASED = "released", _("Place released")
        FAILED = "failed", _("Couldn't enrol")

    rollover = models.ForeignKey(TermRollover, on_delete=models.CASCADE, related_name="offers")
    enrolment = models.ForeignKey(Enrolment, on_delete=models.PROTECT, related_name="+")
    to_class = models.ForeignKey(GroupClass, on_delete=models.PROTECT, related_name="+")
    student = models.ForeignKey("people.Student", on_delete=models.PROTECT, related_name="+")
    client = models.ForeignKey("people.Client", on_delete=models.PROTECT, related_name="+")
    status = models.CharField(max_length=9, choices=Status.choices, default=Status.PENDING)
    token_hash = models.CharField(max_length=64, blank=True, default="", db_index=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    reminded_at = models.DateTimeField(null=True, blank=True)
    new_enrolment = models.ForeignKey(
        Enrolment, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    note = models.CharField(max_length=300, blank=True, default="")

    class Meta(TenantModel.Meta):
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(fields=["rollover", "enrolment"], name="rollover_offer_unique")
        ]
