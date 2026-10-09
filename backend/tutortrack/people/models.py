"""Clients, contacts, students and tutors (E05). Glossary: docs/03-domain-model.md."""

from __future__ import annotations

from typing import Any, ClassVar

from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from tutortrack.core.crypto import EncryptedField
from tutortrack.core.fields import CurrencyField
from tutortrack.core.models import BranchScopedModel, TenantModel


class Address(TenantModel):
    """A postal address, geocoded asynchronously (FR-05-15) for matching and travel."""

    line1 = models.CharField(max_length=200, blank=True, default="")
    line2 = models.CharField(max_length=200, blank=True, default="")
    city = models.CharField(max_length=100, blank=True, default="")
    region = models.CharField(max_length=100, blank=True, default="")
    postcode = models.CharField(max_length=20, blank=True, default="")
    country = models.CharField(max_length=2, blank=True, default="")
    lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    geocoded_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return ", ".join(p for p in (self.line1, self.city, self.postcode) if p)

    def one_line(self) -> str:
        parts = (self.line1, self.line2, self.city, self.region, self.postcode, self.country)
        return ", ".join(p for p in parts if p)


class CustomisableModel(models.Model):
    """Shared by every 'customisable' entity (docs/03-domain-model.md §4)."""

    custom_fields = models.JSONField(default=dict, blank=True)

    class Meta:
        abstract = True


class NoOwnScopeMixin:
    """Tutors' ``own`` scope reaches people through their jobs (E07); until then, none."""

    @classmethod
    def own_scope_q(cls, user: Any) -> Q:
        return Q(pk__in=[])


class Client(NoOwnScopeMixin, BranchScopedModel, CustomisableModel):
    """The billing account: a household, an adult learner, or an organisation."""

    class Type(models.TextChoices):
        HOUSEHOLD = "household", _("Household")
        INDIVIDUAL = "individual", _("Individual learner")
        ORGANISATION = "organisation", _("Organisation")

    class Status(models.TextChoices):
        PROSPECT = "prospect", _("Prospect")
        ACTIVE = "active", _("Active")
        DORMANT = "dormant", _("Dormant")
        ARCHIVED = "archived", _("Archived")

    class InvoiceDelivery(models.TextChoices):
        EMAIL = "email", _("Email")
        PORTAL = "portal", _("Portal only")
        POST = "post", _("Post")

    class InvoiceGrouping(models.TextChoices):
        CLIENT = "client", _("One invoice per client")
        STUDENT = "student", _("One per student")
        JOB = "job", _("One per job")

    type = models.CharField(max_length=15, choices=Type.choices, default=Type.HOUSEHOLD)
    display_name = models.CharField(max_length=200)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    primary_contact = models.ForeignKey(
        "Contact", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    billing_contact = models.ForeignKey(
        "Contact", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    billing_address = models.ForeignKey(
        Address, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    currency = CurrencyField()
    payment_terms_days = models.PositiveSmallIntegerField(default=14)
    invoice_delivery = models.CharField(
        max_length=10, choices=InvoiceDelivery.choices, default=InvoiceDelivery.EMAIL
    )
    invoice_grouping = models.CharField(
        max_length=10, choices=InvoiceGrouping.choices, default=InvoiceGrouping.CLIENT
    )
    preferred_payment_method = models.CharField(max_length=30, blank=True, default="")
    auto_pay = models.BooleanField(default=False)
    credit_limit_amount = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True
    )
    prevent_negative_balance = models.BooleanField(null=True, blank=True)  # None: org default
    tax_exempt = models.BooleanField(default=False)
    tax_id = EncryptedField(blank=True, default="")
    po_number = models.CharField(max_length=60, blank=True, default="")
    referral_source = models.CharField(max_length=100, blank=True, default="")
    account_manager = models.ForeignKey(
        "identity.Membership", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    archived_at = models.DateTimeField(null=True, blank=True, db_index=True)

    audit_sensitive_fields: ClassVar[frozenset[str]] = frozenset({"tax_id"})

    class Meta(BranchScopedModel.Meta):
        ordering = ["display_name"]
        indexes = [
            models.Index(fields=["organisation", "status"], name="client_status_idx"),
            GinIndex(fields=["display_name"], name="client_name_trgm", opclasses=["gin_trgm_ops"]),
        ]

    def __str__(self) -> str:
        return self.display_name


class Contact(NoOwnScopeMixin, TenantModel, CustomisableModel):
    """A person attached to a client (parent, guardian, payer...)."""

    class Relationship(models.TextChoices):
        PARENT = "parent", _("Parent")
        GUARDIAN = "guardian", _("Guardian")
        CARER = "carer", _("Carer")
        SELF = "self", _("Self (adult learner)")
        FINANCE = "finance", _("Finance contact")
        OTHER = "other", _("Other")

    class ContactMethod(models.TextChoices):
        EMAIL = "email", _("Email")
        SMS = "sms", _("SMS")
        PHONE = "phone", _("Phone")

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="contacts")
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100, blank=True, default="")
    relationship = models.CharField(
        max_length=10, choices=Relationship.choices, default=Relationship.PARENT
    )
    email = models.EmailField(blank=True, default="", db_index=True)
    phone = models.CharField(max_length=32, blank=True, default="")
    mobile = models.CharField(max_length=32, blank=True, default="")
    preferred_contact_method = models.CharField(
        max_length=10, choices=ContactMethod.choices, default=ContactMethod.EMAIL
    )
    address = models.ForeignKey(
        Address, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    use_client_address = models.BooleanField(default=True)
    is_primary = models.BooleanField(default=False)
    is_bill_payer = models.BooleanField(default=False)
    receives_reminders = models.BooleanField(default=True)
    receives_invoices = models.BooleanField(default=True)
    receives_reports = models.BooleanField(default=True)
    receives_marketing = models.BooleanField(default=False)
    is_emergency_contact = models.BooleanField(default=False)
    language = models.CharField(max_length=10, blank=True, default="")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
    )  # fmt: skip
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        ordering = ["last_name", "first_name"]
        indexes = [
            GinIndex(
                fields=["first_name", "last_name"], name="contact_name_trgm",
                opclasses=["gin_trgm_ops", "gin_trgm_ops"],
            ),
            GinIndex(fields=["email"], name="contact_email_trgm", opclasses=["gin_trgm_ops"]),
            GinIndex(
                fields=["phone", "mobile"], name="contact_phone_trgm",
                opclasses=["gin_trgm_ops", "gin_trgm_ops"],
            ),
        ]  # fmt: skip

    def __str__(self) -> str:
        return self.full_name

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


class Student(NoOwnScopeMixin, BranchScopedModel, CustomisableModel):
    class Status(models.TextChoices):
        LEAD = "lead", _("Lead")
        TRIAL = "trial", _("Trial")
        ACTIVE = "active", _("Active")
        WAITING = "waiting", _("Waiting list")
        PAUSED = "paused", _("Paused")
        FINISHED = "finished", _("Finished")
        ARCHIVED = "archived", _("Archived")

    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="students")
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100, blank=True, default="")
    preferred_name = models.CharField(max_length=100, blank=True, default="")
    date_of_birth = models.DateField(null=True, blank=True)  # sensitive (field permission)
    year_group = models.CharField(max_length=40, blank=True, default="")
    school = models.CharField(max_length=200, blank=True, default="")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    status_changed_at = models.DateTimeField(null=True, blank=True)
    # [{"subject": "Maths", "level": "GCSE"}]: free text until E06 links the catalogue.
    subjects = models.JSONField(default=list, blank=True)
    goals = models.TextField(blank=True, default="")
    learning_needs = EncryptedField(blank=True, default="")  # SEN / medical: encrypted
    exam_boards = models.JSONField(default=list, blank=True)
    target_grades = models.JSONField(default=dict, blank=True)
    availability = models.JSONField(default=dict, blank=True)
    lesson_address = models.ForeignKey(
        Address, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    preferred_tutors: models.ManyToManyField[Any, Any] = models.ManyToManyField(
        "TutorProfile", blank=True, related_name="+"
    )
    excluded_tutors: models.ManyToManyField[Any, Any] = models.ManyToManyField(
        "TutorProfile", blank=True, related_name="+"
    )
    contact = models.ForeignKey(  # adult learners: the contact who *is* the student
        Contact, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
    )  # fmt: skip
    archived_at = models.DateTimeField(null=True, blank=True, db_index=True)

    audit_sensitive_fields: ClassVar[frozenset[str]] = frozenset(
        {"learning_needs", "date_of_birth"}
    )

    class Meta(BranchScopedModel.Meta):
        ordering = ["last_name", "first_name"]
        indexes = [
            models.Index(fields=["organisation", "status"], name="student_status_idx"),
            GinIndex(
                fields=["first_name", "last_name"], name="student_name_trgm",
                opclasses=["gin_trgm_ops", "gin_trgm_ops"],
            ),
        ]  # fmt: skip

    def __str__(self) -> str:
        return self.full_name

    @property
    def full_name(self) -> str:
        return f"{self.preferred_name or self.first_name} {self.last_name}".strip()


class TutorProfile(TenantModel, CustomisableModel):
    """A person who delivers lessons, linked to their membership once they join."""

    class Status(models.TextChoices):
        APPLICANT = "applicant", _("Applicant")
        ONBOARDING = "onboarding", _("Onboarding")
        ACTIVE = "active", _("Active")
        RESTRICTED = "restricted", _("Restricted")
        INACTIVE = "inactive", _("Inactive")
        ARCHIVED = "archived", _("Archived")

    class Employment(models.TextChoices):
        SELF_EMPLOYED = "self_employed", _("Self-employed")
        EMPLOYEE = "employee", _("Employee")
        OTHER = "other", _("Other")

    membership = models.OneToOneField(
        "identity.Membership", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="tutor_profile",
    )  # fmt: skip
    email = models.EmailField(db_index=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100, blank=True, default="")
    display_name = models.CharField(max_length=200, blank=True, default="")
    phone = models.CharField(max_length=32, blank=True, default="")
    headline = models.CharField(max_length=200, blank=True, default="")
    bio_public = models.TextField(blank=True, default="")
    bio_private = models.TextField(blank=True, default="")
    languages = models.JSONField(default=list, blank=True)
    years_experience = models.PositiveSmallIntegerField(null=True, blank=True)
    employment_type = models.CharField(
        max_length=15, choices=Employment.choices, default=Employment.SELF_EMPLOYED
    )
    pay_rate_amount = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    address = models.ForeignKey(
        Address, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    travel_radius_km = models.PositiveSmallIntegerField(null=True, blank=True)
    delivers_online = models.BooleanField(default=True)
    delivers_in_person = models.BooleanField(default=True)
    max_weekly_hours = models.PositiveSmallIntegerField(null=True, blank=True)
    min_lesson_minutes = models.PositiveSmallIntegerField(null=True, blank=True)
    branches = models.ManyToManyField("tenancy.Branch", blank=True, related_name="+")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ONBOARDING)
    status_changed_at = models.DateTimeField(null=True, blank=True)
    public_profile = models.BooleanField(default=False)
    tax_reference = EncryptedField(blank=True, default="")  # UTR / SSN last 4 / ABN
    date_of_birth = models.DateField(null=True, blank=True)
    emergency_contact = models.JSONField(default=dict, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True, db_index=True)

    audit_sensitive_fields: ClassVar[frozenset[str]] = frozenset(
        {"tax_reference", "date_of_birth", "pay_rate_amount"}
    )

    class Meta(TenantModel.Meta):
        ordering = ["last_name", "first_name"]
        constraints = [
            models.UniqueConstraint(fields=["organisation", "email"], name="tutor_email_unique")
        ]
        indexes = [
            GinIndex(
                fields=["first_name", "last_name"], name="tutor_name_trgm",
                opclasses=["gin_trgm_ops", "gin_trgm_ops"],
            ),
            GinIndex(fields=["email"], name="tutor_email_trgm", opclasses=["gin_trgm_ops"]),
        ]  # fmt: skip

    def __str__(self) -> str:
        return self.full_name

    @property
    def full_name(self) -> str:
        return self.display_name or f"{self.first_name} {self.last_name}".strip()

    @classmethod
    def own_scope_q(cls, user: Any) -> Q:
        return Q(membership__user_id=getattr(user, "pk", None))


class TutorSubject(TenantModel):
    """What a tutor teaches (subject/level are free text until E06 links the catalogue)."""

    class Proficiency(models.TextChoices):
        GOOD = "good", _("Good")
        STRONG = "strong", _("Strong")
        EXPERT = "expert", _("Expert")

    tutor = models.ForeignKey(TutorProfile, on_delete=models.CASCADE, related_name="subjects")
    subject = models.CharField(max_length=100)
    level = models.CharField(max_length=100, blank=True, default="")
    proficiency = models.CharField(
        max_length=10, choices=Proficiency.choices, default=Proficiency.STRONG
    )
    approved = models.BooleanField(default=False)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
    )  # fmt: skip

    class Meta(TenantModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["tutor", "subject", "level"], name="tutor_subject_unique"
            )
        ]

    def __str__(self) -> str:
        return f"{self.subject} {self.level}".strip()


class TutorQualification(TenantModel):
    tutor = models.ForeignKey(TutorProfile, on_delete=models.CASCADE, related_name="qualifications")
    title = models.CharField(max_length=200)
    institution = models.CharField(max_length=200, blank=True, default="")
    year = models.PositiveSmallIntegerField(null=True, blank=True)
    document = models.ForeignKey(
        "core.StoredFile", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    def __str__(self) -> str:
        return self.title
