"""Communications (E13): per-organisation notification settings and templates, the message
log with delivery events, recipient preferences, suppressions and in-app notifications.

Phase 2 adds broadcasts to segments (T10), the conversations inbox (T11), WhatsApp
templates, organisation phone numbers, custom sender domains and the platform-level
inbound routes webhooks use to find the organisation (T12)."""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from tutortrack.core.crypto import EncryptedField
from tutortrack.core.models import BranchScopedModel, TenantModel


class Channel(models.TextChoices):
    EMAIL = "email", _("Email")
    SMS = "sms", _("Text message")
    IN_APP = "in_app", _("In the app")
    PUSH = "push", _("Push notification")
    WHATSAPP = "whatsapp", _("WhatsApp")


class OrgNotificationSetting(TenantModel):
    """An organisation's choice for one notification type (absent = the type's defaults)."""

    type_key = models.CharField(max_length=60)
    enabled = models.BooleanField(default=True)
    channels = models.JSONField(default=list)  # ["email", "sms"]
    timing = models.JSONField(default=list, blank=True)  # minutes before, for reminders

    class Meta(TenantModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "type_key"], name="notif_setting_unique"
            )
        ]


class MessageTemplate(TenantModel):
    """An organisation's override of a type's default template for one channel. Saving
    creates a new version; the previous one is kept (``is_active=False``) for revert."""

    type_key = models.CharField(max_length=60)
    channel = models.CharField(max_length=10, choices=Channel.choices)
    locale = models.CharField(max_length=10, default="en-GB")
    subject = models.CharField(max_length=300, blank=True, default="")
    body = models.TextField()
    version = models.PositiveIntegerField(default=1)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta(TenantModel.Meta):
        ordering = ["type_key", "channel", "-version"]
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "type_key", "channel", "locale"],
                condition=Q(is_active=True),
                name="message_template_active_unique",
            )
        ]


class Message(TenantModel):
    class Status(models.TextChoices):
        QUEUED = "queued", _("Queued")
        SENT = "sent", _("Sent")
        DELIVERED = "delivered", _("Delivered")
        OPENED = "opened", _("Opened")
        CLICKED = "clicked", _("Clicked")
        BOUNCED = "bounced", _("Bounced")
        COMPLAINED = "complained", _("Marked as spam")
        FAILED = "failed", _("Failed")
        SUPPRESSED = "suppressed", _("Not sent (suppressed)")

    type_key = models.CharField(max_length=60)
    channel = models.CharField(max_length=10, choices=Channel.choices)
    recipient_type = models.CharField(max_length=10)  # contact | student | tutor | user
    recipient_id = models.CharField(max_length=64)
    recipient_name = models.CharField(max_length=200, blank=True, default="")
    to = models.CharField(max_length=254)  # email address, phone number or user id
    subject = models.CharField(max_length=300, blank=True, default="")
    body = models.TextField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.QUEUED)
    error = models.CharField(max_length=500, blank=True, default="")
    provider_ref = models.CharField(max_length=120, blank=True, default="")
    related_type = models.CharField(max_length=40, blank=True, default="")  # the subject record
    related_id = models.CharField(max_length=64, blank=True, default="")
    target_type = models.CharField(max_length=40, blank=True, default="")  # timeline record
    target_id = models.CharField(max_length=64, blank=True, default="")
    dedupe_key = models.CharField(max_length=255)
    scheduled_for = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    segments = models.PositiveSmallIntegerField(default=0)  # SMS parts
    # Phase 2: the inbox thread a reply belongs to (its email reply-to is the thread's
    # address) and channel extras (WhatsApp template sid and variables, sender number).
    thread = models.ForeignKey(
        "Thread", null=True, blank=True, on_delete=models.SET_NULL, related_name="deliveries"
    )
    meta = models.JSONField(default=dict, blank=True)

    class Meta(TenantModel.Meta):
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["organisation", "dedupe_key"], name="message_dedupe")
        ]
        indexes = [
            models.Index(fields=["target_type", "target_id"], name="message_target_idx"),
            models.Index(fields=["related_type", "related_id"], name="message_related_idx"),
        ]


class MessageEvent(TenantModel):
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name="events")
    type = models.CharField(max_length=20)
    occurred_at = models.DateTimeField()
    detail = models.JSONField(default=dict, blank=True)

    class Meta(TenantModel.Meta):
        ordering = ["occurred_at"]


class CommunicationPreference(TenantModel):
    """Which channels a person accepts for a category (no row = every channel)."""

    person_type = models.CharField(max_length=10)  # contact | student | tutor | user
    person_id = models.CharField(max_length=64)
    category = models.CharField(max_length=20)
    channels = models.JSONField(default=list)

    class Meta(TenantModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "person_type", "person_id", "category"],
                name="comm_preference_unique",
            )
        ]


class Suppression(TenantModel):
    """Addresses we must not send to (hard bounce, spam complaint, manual)."""

    channel = models.CharField(max_length=10, choices=Channel.choices)
    address = models.CharField(max_length=254)
    reason = models.CharField(max_length=40)

    class Meta(TenantModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "channel", "address"], name="suppression_unique"
            )
        ]


class SmsOptOut(models.Model):
    """Numbers that replied STOP to the platform's shared sender (platform-level, like
    ``payments.AccountRoute``): honoured for every organisation."""

    phone = models.CharField(max_length=32, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.phone


class InAppNotification(TenantModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    type_key = models.CharField(max_length=60)
    title = models.CharField(max_length=300)
    body = models.TextField(blank=True, default="")
    link = models.CharField(max_length=300, blank=True, default="")
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "read_at"], name="inapp_user_unread_idx")]

    @classmethod
    def own_scope_q(cls, user: object) -> Q:
        return Q(user=user)


class PushSubscription(TenantModel):
    """A browser's Web Push subscription for a signed-in user (E16-T09).

    The endpoint is a capability URL (anyone holding it can push to the device) and the keys
    belong to the device, so all three are encrypted at rest and never logged;
    ``endpoint_hash`` (SHA-256) finds a subscription again. ``push_service`` is the host
    only, safe to show ("fcm.googleapis.com")."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="push_subscriptions"
    )
    endpoint = EncryptedField()
    endpoint_hash = models.CharField(max_length=64)
    p256dh = EncryptedField()
    auth = EncryptedField()
    device = models.CharField(max_length=120, blank=True, default="")
    push_service = models.CharField(max_length=120, blank=True, default="")
    last_sent_at = models.DateTimeField(null=True, blank=True)
    failures = models.PositiveSmallIntegerField(default=0)

    audit_sensitive_fields = frozenset({"endpoint", "p256dh", "auth"})

    class Meta(TenantModel.Meta):
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "endpoint_hash"], name="push_subscription_unique"
            )
        ]
        indexes = [models.Index(fields=["user"], name="push_subscription_user_idx")]

    def __str__(self) -> str:
        return self.device or self.push_service or "Push subscription"

    @classmethod
    def own_scope_q(cls, user: object) -> Q:
        return Q(user=user)


# --- broadcasts (E13-T10) -----------------------------------------------------------------------


class Audience(models.TextChoices):
    CONTACTS = "contacts", _("Client contacts")
    TUTORS = "tutors", _("Tutors")


class Segment(BranchScopedModel):
    """A saved recipient definition for broadcasts (FR-13-6): client contacts or tutors,
    narrowed by status, branch, tags, a saved list view, a class, a job or a pipeline
    stage. The definition is evaluated when a broadcast sends (``segments.resolve``)."""

    name = models.CharField(max_length=120)
    description = models.CharField(max_length=300, blank=True, default="")
    audience = models.CharField(max_length=10, choices=Audience.choices)
    definition = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta(TenantModel.Meta):
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["organisation", "name"], name="segment_name_unique")
        ]

    def __str__(self) -> str:
        return self.name


class Broadcast(BranchScopedModel):
    """A bulk email, text or WhatsApp message to a segment (FR-13-6), sent in throttled
    batches by ``BroadcastWorkflow`` (E13-TW1). Delivery, opens and clicks are tracked on
    each recipient's ``Message``."""

    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        SCHEDULED = "scheduled", _("Scheduled")
        SENDING = "sending", _("Sending")
        PAUSED = "paused", _("Paused")
        SENT = "sent", _("Sent")
        CANCELLED = "cancelled", _("Cancelled")
        FAILED = "failed", _("Failed")

    class Purpose(models.TextChoices):
        MARKETING = "marketing", _("Marketing (needs consent)")
        OPERATIONAL = "operational", _("Service announcement")

    name = models.CharField(max_length=150)
    channel = models.CharField(max_length=10, choices=Channel.choices, default=Channel.EMAIL)
    purpose = models.CharField(max_length=12, choices=Purpose.choices, default=Purpose.OPERATIONAL)
    subject = models.CharField(max_length=300, blank=True, default="")
    body = models.TextField(blank=True, default="")
    whatsapp_template = models.ForeignKey(
        "WhatsAppTemplate", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    segment = models.ForeignKey(
        Segment, null=True, blank=True, on_delete=models.SET_NULL, related_name="broadcasts"
    )
    audience = models.CharField(max_length=10, choices=Audience.choices, default=Audience.CONTACTS)
    definition = models.JSONField(default=dict, blank=True)  # the segment as sent
    attachment_ids = models.JSONField(default=list, blank=True)  # stored files (email)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    scheduled_for = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    stats = models.JSONField(default=dict, blank=True)

    class Meta(TenantModel.Meta):
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status"], name="broadcast_status_idx")]

    def __str__(self) -> str:
        return self.name


class BroadcastRecipient(TenantModel):
    """One person a broadcast resolved to, snapshotted when sending starts: queued (a
    ``Message`` exists), skipped (why) or still pending for a later batch."""

    class Status(models.TextChoices):
        PENDING = "pending", _("Waiting")
        QUEUED = "queued", _("Sent to the channel")
        SKIPPED = "skipped", _("Skipped")
        FAILED = "failed", _("Failed")

    broadcast = models.ForeignKey(Broadcast, on_delete=models.CASCADE, related_name="recipients")
    recipient_type = models.CharField(max_length=10)  # contact | tutor
    recipient_id = models.CharField(max_length=64)
    name = models.CharField(max_length=200, blank=True, default="")
    address = models.CharField(max_length=254, blank=True, default="")
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.PENDING)
    # no_address | no_consent | opted_out | suppressed | duplicate | no_opt_in
    skip_reason = models.CharField(max_length=20, blank=True, default="")
    message = models.ForeignKey(
        Message, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    batch = models.PositiveIntegerField(default=0)

    class Meta(TenantModel.Meta):
        ordering = ["name", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["broadcast", "recipient_type", "recipient_id"],
                name="broadcast_recipient_unique",
            )
        ]
        indexes = [
            models.Index(fields=["broadcast", "status"], name="broadcast_recipient_status_idx")
        ]


# --- conversations inbox (E13-T11) --------------------------------------------------------------


class Thread(BranchScopedModel):
    """A two-way conversation (FR-13-7) with a family, a tutor, a tutor and a family, or
    an unknown sender. Email, text, WhatsApp and portal chat all land in it; staff reply,
    add internal notes, assign and snooze. Snoozed threads count as open again once
    ``snoozed_until`` passes (worked out when read, no sweeper)."""

    class Kind(models.TextChoices):
        CLIENT = "client", _("Family")
        TUTOR = "tutor", _("Tutor")
        TUTOR_FAMILY = "tutor_family", _("Tutor and family")
        OTHER = "other", _("Other")

    class Status(models.TextChoices):
        OPEN = "open", _("Open")
        SNOOZED = "snoozed", _("Snoozed")
        CLOSED = "closed", _("Closed")

    subject = models.CharField(max_length=200, blank=True, default="")
    kind = models.CharField(max_length=14, choices=Kind.choices)
    client = models.ForeignKey(
        "people.Client", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    tutor = models.ForeignKey(
        "people.TutorProfile", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    contact_name = models.CharField(max_length=200, blank=True, default="")
    contact_email = models.CharField(max_length=254, blank=True, default="")
    contact_phone = models.CharField(max_length=32, blank=True, default="")
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.OPEN)
    snoozed_until = models.DateTimeField(null=True, blank=True)
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    channel = models.CharField(max_length=10, default="chat")  # where replies go by default
    last_message_at = models.DateTimeField(null=True, blank=True)
    last_message_preview = models.CharField(max_length=200, blank=True, default="")
    awaiting_reply_since = models.DateTimeField(null=True, blank=True)  # SLA timer start
    closed_at = models.DateTimeField(null=True, blank=True)
    flagged = models.BooleanField(default=False)  # safeguarding detection (E29)

    class Meta(TenantModel.Meta):
        ordering = ["-last_message_at", "-created_at"]
        indexes = [
            models.Index(fields=["status", "last_message_at"], name="thread_status_idx"),
            models.Index(fields=["assignee", "status"], name="thread_assignee_idx"),
        ]

    def __str__(self) -> str:
        return self.subject or self.contact_name or str(self.pk)

    @classmethod
    def own_scope_q(cls, user: object) -> Q:
        """Tutors (``comms.inbox.*:own``): threads they take part in or are assigned."""
        mine = ThreadParticipant.objects.filter(user=user).values("thread_id")
        return Q(pk__in=mine) | Q(assignee=user)


class ThreadParticipant(TenantModel):
    class Role(models.TextChoices):
        FAMILY = "family", _("Family")
        TUTOR = "tutor", _("Tutor")
        STAFF = "staff", _("Staff")
        EXTERNAL = "external", _("Other")

    thread = models.ForeignKey(Thread, on_delete=models.CASCADE, related_name="participants")
    role = models.CharField(max_length=8, choices=Role.choices)
    person_type = models.CharField(max_length=10)  # contact | student | tutor | user | external
    person_id = models.CharField(max_length=64)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    name = models.CharField(max_length=200, blank=True, default="")
    email = models.CharField(max_length=254, blank=True, default="")
    phone = models.CharField(max_length=32, blank=True, default="")
    last_read_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["thread", "person_type", "person_id"], name="thread_participant_unique"
            )
        ]
        indexes = [models.Index(fields=["user"], name="thread_participant_user_idx")]


class ThreadMessage(TenantModel):
    """One entry in a thread: an inbound message, a reply, or an internal note (staff
    only). Outbound email/text/WhatsApp replies link the ``Message`` that delivered them."""

    class Direction(models.TextChoices):
        INBOUND = "inbound", _("Received")
        OUTBOUND = "outbound", _("Sent")
        INTERNAL = "internal", _("Internal note")

    class Via(models.TextChoices):
        EMAIL = "email", _("Email")
        SMS = "sms", _("Text message")
        WHATSAPP = "whatsapp", _("WhatsApp")
        CHAT = "chat", _("Portal message")
        NOTE = "note", _("Note")

    thread = models.ForeignKey(Thread, on_delete=models.CASCADE, related_name="messages")
    direction = models.CharField(max_length=8, choices=Direction.choices)
    channel = models.CharField(max_length=10, choices=Via.choices)
    author_type = models.CharField(max_length=10)  # contact | student | tutor | user | external
    author_id = models.CharField(max_length=64, blank=True, default="")
    author_name = models.CharField(max_length=200, blank=True, default="")
    author_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    subject = models.CharField(max_length=300, blank=True, default="")
    body = models.TextField()
    message = models.ForeignKey(
        Message, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    provider_ref = models.CharField(max_length=255, blank=True, default="")
    attachments = models.JSONField(default=list, blank=True)  # [{id, filename, ...}]
    flags = models.JSONField(default=list, blank=True)  # contact_details | profanity

    class Meta(TenantModel.Meta):
        ordering = ["created_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "provider_ref"],
                condition=~Q(provider_ref=""),
                name="thread_message_provider_ref_unique",
            )
        ]
        indexes = [models.Index(fields=["thread", "created_at"], name="thread_message_idx")]


class CannedReply(TenantModel):
    title = models.CharField(max_length=100)
    body = models.TextField()
    shortcut = models.CharField(max_length=30, blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta(TenantModel.Meta):
        ordering = ["title"]
        constraints = [
            models.UniqueConstraint(fields=["organisation", "title"], name="canned_reply_unique")
        ]

    def __str__(self) -> str:
        return self.title


# --- channels and senders (E13-T12) -------------------------------------------------------------


class WhatsAppTemplate(TenantModel):
    """A WhatsApp Business message template approved by Meta (through Twilio Content).
    Outside a 24-hour customer service window WhatsApp only delivers approved templates,
    so notifications and broadcasts map to one; ``variables`` are sandboxed Jinja
    expressions filling ``{{1}}``, ``{{2}}``..."""

    class Status(models.TextChoices):
        PENDING = "pending", _("Waiting for approval")
        APPROVED = "approved", _("Approved")
        REJECTED = "rejected", _("Rejected")

    class Category(models.TextChoices):
        UTILITY = "utility", _("Utility")
        MARKETING = "marketing", _("Marketing")

    name = models.CharField(max_length=100)
    language = models.CharField(max_length=10, default="en_GB")
    category = models.CharField(max_length=10, choices=Category.choices, default=Category.UTILITY)
    content_sid = models.CharField(max_length=64, blank=True, default="")
    body = models.TextField()
    variables = models.JSONField(default=list, blank=True)
    type_key = models.CharField(max_length=60, blank=True, default="")
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.PENDING)

    class Meta(TenantModel.Meta):
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "name", "language"], name="whatsapp_template_unique"
            )
        ]

    def __str__(self) -> str:
        return self.name


class PhoneNumber(TenantModel):
    """An organisation's own texting or WhatsApp number (FR-13-7: replies come back to
    it). Without one, texts use the platform's shared sender."""

    channel = models.CharField(max_length=10, choices=Channel.choices, default=Channel.SMS)
    number = models.CharField(max_length=32)  # E.164
    label = models.CharField(max_length=100, blank=True, default="")
    branch = models.ForeignKey(
        "tenancy.Branch", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    is_default = models.BooleanField(default=False)
    active = models.BooleanField(default=True)

    class Meta(TenantModel.Meta):
        ordering = ["channel", "number"]
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "channel", "number"], name="phone_number_unique"
            )
        ]

    def __str__(self) -> str:
        return self.number


class SenderDomain(TenantModel):
    """A custom sending domain (FR-13-1, plan-gated): mail comes from
    ``<local_part>@<domain>`` once its DKIM and return-path records verify."""

    class Status(models.TextChoices):
        PENDING = "pending", _("Waiting for DNS")
        VERIFIED = "verified", _("Verified")
        FAILED = "failed", _("Not verified")

    domain = models.CharField(max_length=253)
    local_part = models.CharField(max_length=64, default="hello")
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.PENDING)
    dns_records = models.JSONField(default=list, blank=True)
    provider_ref = models.CharField(max_length=64, blank=True, default="")
    verified_at = models.DateTimeField(null=True, blank=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    error = models.CharField(max_length=300, blank=True, default="")
    is_default = models.BooleanField(default=False)

    class Meta(TenantModel.Meta):
        ordering = ["domain"]
        constraints = [
            models.UniqueConstraint(fields=["organisation", "domain"], name="sender_domain_unique")
        ]

    def __str__(self) -> str:
        return self.domain

    @property
    def from_address(self) -> str:
        return f"{self.local_part}@{self.domain}"


class InboundRoute(models.Model):
    """Platform-level routing for inbound texts and WhatsApp messages (like
    ``payments.AccountRoute``): webhooks arrive before any tenant is known.

    * ``number``: an organisation's own number (``To``).
    * ``reply``: the organisation that last texted this phone from the shared sender
      (``From``), so replies to the shared number reach the right inbox."""

    class Kind(models.TextChoices):
        NUMBER = "number", _("Organisation number")
        REPLY = "reply", _("Reply to the shared sender")

    channel = models.CharField(max_length=10)
    kind = models.CharField(max_length=6, choices=Kind.choices)
    address = models.CharField(max_length=64)
    organisation_id = models.UUIDField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["channel", "kind", "address"], name="inbound_route_unique"
            )
        ]

    def __str__(self) -> str:
        return f"{self.channel}:{self.kind}:{self.address}"
