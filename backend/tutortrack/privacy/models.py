"""Privacy, safeguarding and compliance (E29): consent (FR-29-3), data subject requests and
erasure (FR-29-4), retention and legal holds (FR-29-5), safeguarding (FR-29-6) and the
data processing agreement (FR-29-8)."""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from tutortrack.core.crypto import EncryptedField
from tutortrack.core.models import TenantModel


class ConsentType(TenantModel):
    """Something an organisation asks consent for (configurable per org, versioned)."""

    class Category(models.TextChoices):
        DATA_PROCESSING = "data_processing", _("Data processing")
        PHOTO_VIDEO = "photo_video", _("Photos and video")
        MARKETING_EMAIL = "marketing_email", _("Marketing email")
        MARKETING_SMS = "marketing_sms", _("Marketing SMS")
        LESSON_RECORDING = "lesson_recording", _("Lesson recording")
        TERMS = "terms_of_service", _("Terms of service")
        PRIVACY_POLICY = "privacy_policy", _("Privacy policy")
        PARENTAL_CONSENT = "parental_consent", _("Parental consent for a child's login")
        OTHER = "other", _("Other")

    key = models.SlugField(max_length=60)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    category = models.CharField(max_length=30, choices=Category.choices)
    version = models.PositiveIntegerField(default=1)
    document_url = models.URLField(blank=True, default="")
    required = models.BooleanField(default=False)
    # Subject types it applies to, e.g. ["people.contact", "people.student", "identity.user"].
    applies_to = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta(TenantModel.Meta):
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["organisation", "key"], name="consent_type_key_unique")
        ]

    def __str__(self) -> str:
        return self.name


class ConsentRecord(TenantModel):
    """One grant or withdrawal. Append-only: the latest record per (subject, type) is the
    current state, and the history is the evidence."""

    class Method(models.TextChoices):
        FORM = "form", _("Public form")
        PORTAL = "portal", _("Portal")
        IMPORT = "import", _("Import")
        STAFF = "staff", _("Recorded by staff")
        SIGNUP = "signup", _("Signup")

    consent_type = models.ForeignKey(ConsentType, on_delete=models.PROTECT, related_name="records")
    version = models.PositiveIntegerField()
    subject_type = models.CharField(max_length=60)
    subject_id = models.CharField(max_length=64)
    granted = models.BooleanField()
    method = models.CharField(max_length=10, choices=Method.choices)
    given_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    given_by_name = models.CharField(max_length=200, blank=True, default="")
    on_behalf_of_child = models.BooleanField(default=False)  # a guardian consenting for a child
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True, default="")
    recorded_at = models.DateTimeField()

    class Meta(TenantModel.Meta):
        ordering = ["-recorded_at", "-id"]
        indexes = [
            models.Index(
                fields=[
                    "organisation",
                    "subject_type",
                    "subject_id",
                    "consent_type",
                    "-recorded_at",
                ],
                name="consent_record_subject",
            )
        ]

    def __str__(self) -> str:
        return f"{self.consent_type_id} {'granted' if self.granted else 'withdrawn'}"


# --- data subject requests (FR-29-4) ------------------------------------------------------------


def _user_fk() -> models.ForeignKey:
    return models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )


def _file_fk() -> models.ForeignKey:
    return models.ForeignKey(
        "core.StoredFile", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )


class DataSubjectRequest(TenantModel):
    """A DSAR: access (export) or erasure, with its statutory deadline. The process runs as
    ``DataSubjectRequestWorkflow`` (E29-TW1)."""

    class Kind(models.TextChoices):
        ACCESS = "access", _("Access (a copy of their data)")
        PORTABILITY = "portability", _("Portability (machine-readable copy)")
        ERASURE = "erasure", _("Erasure")

    class Status(models.TextChoices):
        RECEIVED = "received", _("Awaiting identity verification")
        IN_PROGRESS = "in_progress", _("In progress")
        IN_REVIEW = "in_review", _("Awaiting review")
        ERASING = "erasing", _("Erasing")
        DELIVERED = "delivered", _("Delivered")
        COMPLETED = "completed", _("Completed")
        BLOCKED = "blocked", _("Blocked by a legal hold")
        REJECTED = "rejected", _("Rejected")
        CANCELLED = "cancelled", _("Cancelled")

    class Channel(models.TextChoices):
        PORTAL = "portal", _("Portal")
        EMAIL = "email", _("Email")
        PHONE = "phone", _("Phone")
        LETTER = "letter", _("Letter")
        IN_PERSON = "in_person", _("In person")

    class Relationship(models.TextChoices):
        SELF = "self", _("The person themself")
        PARENT = "parent", _("Parent or guardian")
        REPRESENTATIVE = "representative", _("Authorised representative")

    reference = models.CharField(max_length=20)
    kind = models.CharField(max_length=12, choices=Kind.choices)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.RECEIVED)
    channel = models.CharField(max_length=10, choices=Channel.choices, default=Channel.EMAIL)
    subject_type = models.CharField(max_length=60)
    subject_id = models.CharField(max_length=64)
    subject_label = models.CharField(max_length=200, blank=True, default="")
    requester_user = _user_fk()
    requester_name = models.CharField(max_length=200)
    requester_email = models.EmailField(blank=True, default="")
    relationship = models.CharField(
        max_length=15, choices=Relationship.choices, default=Relationship.SELF
    )
    details = models.TextField(blank=True, default="")
    received_at = models.DateTimeField()
    due_at = models.DateTimeField()
    extended_at = models.DateTimeField(null=True, blank=True)
    extension_reason = models.CharField(max_length=500, blank=True, default="")
    checks = models.JSONField(default=dict, blank=True)  # {check key: bool}
    verified_at = models.DateTimeField(null=True, blank=True)
    verified_by = _user_fk()
    verification_note = models.CharField(max_length=500, blank=True, default="")
    # Access: the compiled draft (JSON) waits for redaction; the package is what is delivered.
    draft_file = _file_fk()
    package_file = _file_fk()
    summary = models.JSONField(default=dict, blank=True)  # counts per section, never data
    redactions = models.JSONField(default=list, blank=True)
    redactions_approved_at = models.DateTimeField(null=True, blank=True)
    redactions_approved_by = _user_fk()
    token_hash = models.CharField(max_length=64, blank=True, default="")
    delivered_at = models.DateTimeField(null=True, blank=True)
    link_expires_at = models.DateTimeField(null=True, blank=True)
    downloaded_at = models.DateTimeField(null=True, blank=True)
    download_count = models.PositiveIntegerField(default=0)
    erasure_approved_at = models.DateTimeField(null=True, blank=True)
    erasure_approved_by = _user_fk()
    reminders_sent = models.JSONField(default=list, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    close_reason = models.CharField(max_length=500, blank=True, default="")
    workflow_id = models.CharField(max_length=200, blank=True, default="")

    OPEN = ("received", "in_progress", "in_review", "erasing", "delivered")

    class Meta(TenantModel.Meta):
        ordering = ["-received_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "reference"], name="dsar_reference_unique"
            )
        ]
        indexes = [models.Index(fields=["organisation", "status", "due_at"], name="dsar_due")]

    def __str__(self) -> str:
        return self.reference

    @property
    def is_open(self) -> bool:
        return self.status in self.OPEN


class ErasureRecord(TenantModel):
    """One erasure (from a DSAR or a retention policy): the people it covered, the token
    labels it used, which providers ran and what each did. The personal search terms used
    to scrub free text are kept encrypted, and only while it runs."""

    class Status(models.TextChoices):
        PLANNED = "planned", _("Planned")
        ERASING = "erasing", _("Erasing")
        COMPLETED = "completed", _("Completed")
        BLOCKED = "blocked", _("Blocked by a legal hold")

    class Reason(models.TextChoices):
        REQUEST = "request", _("Data subject request")
        RETENTION = "retention", _("Retention policy")

    request = models.ForeignKey(
        DataSubjectRequest, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    reason = models.CharField(max_length=10, choices=Reason.choices)
    subject_type = models.CharField(max_length=60)
    subject_id = models.CharField(max_length=64)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PLANNED)
    subjects = models.JSONField(default=dict, blank=True)  # {subject type: [ids]}
    labels = models.JSONField(default=dict, blank=True)  # {"type:id": "Erased Student #12"}
    scrub_terms = EncryptedField(blank=True, default="")  # JSON; cleared when completed
    steps_done = models.JSONField(default=list, blank=True)
    report = models.JSONField(default=dict, blank=True)
    file_ids = models.JSONField(default=list, blank=True)
    financial_retained_until = models.DateTimeField(null=True, blank=True)
    financial_erased_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    audit_sensitive_fields = frozenset({"scrub_terms"})

    class Meta(TenantModel.Meta):
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["organisation", "subject_type", "subject_id"], name="erasure_subj")
        ]

    def __str__(self) -> str:
        return f"Erasure {self.subject_type}:{self.subject_id}"


class LegalHold(TenantModel):
    """Blocks erasure and retention purges for a person or record (FR-29-5)."""

    subject_type = models.CharField(max_length=60)
    subject_id = models.CharField(max_length=64)
    subject_label = models.CharField(max_length=200, blank=True, default="")
    reason = models.CharField(max_length=500)
    placed_by = _user_fk()
    placed_at = models.DateTimeField()
    released_at = models.DateTimeField(null=True, blank=True)
    released_by = _user_fk()
    release_reason = models.CharField(max_length=500, blank=True, default="")

    class Meta(TenantModel.Meta):
        ordering = ["-placed_at", "-id"]
        indexes = [
            models.Index(fields=["organisation", "subject_type", "subject_id"], name="hold_subj")
        ]

    def __str__(self) -> str:
        return f"Hold {self.subject_type}:{self.subject_id}"

    @property
    def active(self) -> bool:
        return self.released_at is None


# --- retention (FR-29-5) ------------------------------------------------------------------------


class RetentionPolicy(TenantModel):
    """How long one category of data is kept (the categories are defined in code)."""

    category = models.CharField(max_length=40)
    period_days = models.PositiveIntegerField()
    enabled = models.BooleanField(default=True)

    class Meta(TenantModel.Meta):
        ordering = ["category"]
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "category"], name="retention_policy_unique"
            )
        ]

    def __str__(self) -> str:
        return f"{self.category}: {self.period_days} days"


class RetentionRun(TenantModel):
    """One purge run (nightly schedule or manual): the dry-run report and what was done."""

    class Status(models.TextChoices):
        RUNNING = "running", _("Running")
        COMPLETED = "completed", _("Completed")
        FAILED = "failed", _("Failed")

    dry_run = models.BooleanField(default=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.RUNNING)
    trigger = models.CharField(max_length=10, default="schedule")  # schedule | manual
    report = models.JSONField(default=dict, blank=True)  # {category: {"due": n, "done": n}}
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)
    requested_by = _user_fk()
    workflow_id = models.CharField(max_length=200, blank=True, default="")

    class Meta(TenantModel.Meta):
        ordering = ["-started_at", "-id"]

    def __str__(self) -> str:
        return f"Retention run {self.started_at:%Y-%m-%d}"


# --- safeguarding (FR-29-6) ---------------------------------------------------------------------


class SafeguardingConcern(TenantModel):
    """A concern about a child's welfare. Restricted to Designated Safeguarding Leads,
    encrypted, audited on every read and never shown on the general timeline."""

    class Category(models.TextChoices):
        PHYSICAL = "physical", _("Physical abuse")
        EMOTIONAL = "emotional", _("Emotional abuse")
        SEXUAL = "sexual", _("Sexual abuse or exploitation")
        NEGLECT = "neglect", _("Neglect")
        ONLINE = "online", _("Online safety")
        SELF_HARM = "self_harm", _("Self-harm or mental health")
        BULLYING = "bullying", _("Bullying")
        RADICALISATION = "radicalisation", _("Radicalisation")
        ALLEGATION = "allegation", _("Allegation about an adult")
        CONDUCT = "conduct", _("Messaging or conduct concern")
        OTHER = "other", _("Other")

    class Status(models.TextChoices):
        OPEN = "open", _("Open")
        IN_REVIEW = "in_review", _("In review")
        REFERRED = "referred", _("Referred externally")
        CLOSED = "closed", _("Closed")

    reference = models.CharField(max_length=20)
    student = models.ForeignKey(
        "people.Student", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    lesson = models.ForeignKey(
        "scheduling.Lesson", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    tutor = models.ForeignKey(
        "people.TutorProfile", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    category = models.CharField(max_length=20, choices=Category.choices)
    description = EncryptedField()
    immediate_risk = models.BooleanField(default=False)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    raised_by = _user_fk()
    raised_at = models.DateTimeField()
    assigned_to = _user_fk()
    outcome = EncryptedField(blank=True, default="")
    closed_at = models.DateTimeField(null=True, blank=True)
    attachments = models.ManyToManyField("core.StoredFile", blank=True, related_name="+")

    audit_sensitive_fields = frozenset({"description", "outcome"})

    class Meta(TenantModel.Meta):
        ordering = ["-raised_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "reference"], name="safeguarding_reference_unique"
            )
        ]

    def __str__(self) -> str:
        return self.reference


class SafeguardingAction(TenantModel):
    """The case timeline: notes, contacts, referrals and status changes."""

    class Kind(models.TextChoices):
        NOTE = "note", _("Note")
        CONTACTED_FAMILY = "contacted_family", _("Contacted the family")
        REFERRED_SOCIAL_CARE = "referred_social_care", _("Referred to children's social care")
        REFERRED_LADO = "referred_lado", _("Referred to the LADO")
        REFERRED_POLICE = "referred_police", _("Referred to the police")
        STATUS_CHANGED = "status_changed", _("Status changed")
        ASSIGNED = "assigned", _("Assigned")

    concern = models.ForeignKey(
        SafeguardingConcern, on_delete=models.CASCADE, related_name="actions"
    )
    kind = models.CharField(max_length=25, choices=Kind.choices)
    note = EncryptedField(blank=True, default="")
    actor = _user_fk()
    occurred_at = models.DateTimeField()

    audit_sensitive_fields = frozenset({"note"})

    class Meta(TenantModel.Meta):
        ordering = ["occurred_at", "id"]

    def __str__(self) -> str:
        return self.kind


class SafeguardingFlag(TenantModel):
    """Something the messaging safeguards caught (contact details, flagged words or a
    blocked message) for a DSL to review."""

    class Status(models.TextChoices):
        OPEN = "open", _("To review")
        DISMISSED = "dismissed", _("Dismissed")
        ESCALATED = "escalated", _("Escalated to a concern")

    source_type = models.CharField(max_length=60)
    source_id = models.CharField(max_length=64, blank=True, default="")
    sender = _user_fk()
    reasons = models.JSONField(default=list)  # keyword | contact_details | policy:<rule>
    keywords = models.JSONField(default=list, blank=True)
    excerpt = EncryptedField(blank=True, default="")
    blocked = models.BooleanField(default=False)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    reviewed_by = _user_fk()
    reviewed_at = models.DateTimeField(null=True, blank=True)
    concern = models.ForeignKey(
        SafeguardingConcern, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    audit_sensitive_fields = frozenset({"excerpt"})

    class Meta(TenantModel.Meta):
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return f"Flag {self.source_type}"


class LoneWorkingVisit(TenantModel):
    """A tutor's check-in and check-out for an in-person lesson (FR-29-6 lone working). The
    overdue alert is a Temporal timer (``LoneWorkingWorkflow``), not a sweeper."""

    class Status(models.TextChoices):
        CHECKED_IN = "checked_in", _("Checked in")
        CHECKED_OUT = "checked_out", _("Checked out")
        OVERDUE = "overdue", _("Overdue")
        RESOLVED = "resolved", _("Resolved by staff")

    lesson = models.ForeignKey("scheduling.Lesson", on_delete=models.CASCADE, related_name="+")
    tutor = models.ForeignKey("people.TutorProfile", on_delete=models.CASCADE, related_name="+")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.CHECKED_IN)
    checked_in_at = models.DateTimeField()
    expected_end = models.DateTimeField()
    checked_out_at = models.DateTimeField(null=True, blank=True)
    alerted_at = models.DateTimeField(null=True, blank=True)
    escalated_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = _user_fk()
    note = models.CharField(max_length=500, blank=True, default="")
    workflow_id = models.CharField(max_length=200, blank=True, default="")

    class Meta(TenantModel.Meta):
        ordering = ["-checked_in_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "lesson", "tutor"], name="lone_working_visit_unique"
            )
        ]

    def __str__(self) -> str:
        return f"Visit {self.lesson_id}"

    @classmethod
    def own_scope_q(cls, user: object) -> models.Q:
        return models.Q(tutor__membership__user_id=getattr(user, "pk", None))


# --- data processing agreement and sub-processors (FR-29-8) -------------------------------------


class DPAAcceptance(TenantModel):
    """The organisation accepted a version of TutorTrack's Data Processing Agreement."""

    version = models.CharField(max_length=20)
    accepted_by = _user_fk()
    signer_name = models.CharField(max_length=200)
    signer_title = models.CharField(max_length=200, blank=True, default="")
    company_name = models.CharField(max_length=200)
    accepted_at = models.DateTimeField()
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True, default="")

    class Meta(TenantModel.Meta):
        ordering = ["-accepted_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["organisation", "version"], name="dpa_version_unique")
        ]

    def __str__(self) -> str:
        return f"DPA {self.version}"


class SubprocessorNotice(TenantModel):
    """The organisation was told about this version of the sub-processor list."""

    version = models.CharField(max_length=20)
    notified_at = models.DateTimeField()

    class Meta(TenantModel.Meta):
        ordering = ["-notified_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "version"], name="subprocessor_notice_unique"
            )
        ]

    def __str__(self) -> str:
        return f"Sub-processors {self.version}"
