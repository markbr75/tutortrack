"""The webhook event catalogue and payloads (FR-27-3).

Event types come from the domain event registry, limited to the business aggregates
integrators care about; platform internals (organisation lifecycle, users, subscriptions,
automations, reporting, this app's own events) are never offered. Endpoints subscribe to
explicit types or a per-aggregate wildcard (``lesson.*``); there is no global wildcard.

The body follows the event envelope (docs/02-architecture.md §5); ``data`` is the public
API representation of the subject *as the endpoint's creator may see it* (field
permissions apply), falling back to the event's own data when the subject has no public
representation or no longer exists. ``event_data`` keeps the event's own fields.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import structlog
from django.utils.module_loading import import_string

from tutortrack.core.events import EVENT_TYPES, EventEnvelope
from tutortrack.core.events.base import to_json_safe

logger = structlog.get_logger(__name__)

PUBLIC_AGGREGATES = frozenset(
    {
        "application", "attendance", "availability", "branch", "charge", "class", "client",
        "compliance", "contact", "cover_request", "credit_note", "document", "enquiry", "enrolment",
        "expense", "form", "invoice", "job", "job_offer", "job_posting", "lesson",
        "lesson_report", "lesson_series", "makeup_credit", "note", "online_meeting",
        "pay_item", "pay_run", "payment", "payment_request", "payout", "reference", "service",
        "student", "task", "trial_lesson", "tutor", "waitlist",
        # G6: aggregates added after E27 (E09-E25 phases 2-3).
        "affiliate_statement", "assessment", "background_check", "billing_plan", "booking",
        "broadcast", "commission", "goal", "homework", "late_fee", "lesson_feedback", "loan",
        "mandate", "message", "onboarding", "package", "payment_method", "progress_report",
        "proposal", "public_profile", "quiz", "recording", "referral", "reschedule", "resource",
        "review", "self_billing_statement", "shortlist", "term", "thread", "time_off",
        "topic_mastery",
        # G5a: tutor probation reviews and offboarding (E18 FR-18-9).
        "offboarding", "probation",
    }
)  # fmt: skip

# Never webhook types, whatever aggregate lists say: safeguarding, privacy casework, security,
# the platform relationship and AI internals (docs/03-domain-model.md §5 notes).
NEVER_AGGREGATES = frozenset(
    {
        "safeguarding", "lone_working", "data_request", "data_subject", "legal_hold",
        "retention", "dpa", "consent", "setup_checklist", "survey", "support_conversation",
        "push_subscription", "api_key", "oauth_app", "webhook_endpoint", "webhook_delivery",
        "sandbox", "user", "impersonation", "membership", "role", "organisation",
        "subscription", "credits", "automation", "ai_feature", "ai_proposal",
        # G5a: staff notes on a tutor's performance stay inside TutorTrack.
        "performance",
    }
)  # fmt: skip
NEVER_EVENT_TYPES = frozenset({"thread.intent_classified"})
# Ids-only events: only these fields of the event leave TutorTrack (and no record
# representation is attached). Background-check results and safeguarding flags never do.
IDS_ONLY: dict[str, frozenset[str]] = {
    "background_check": frozenset({"tutor_id", "provider", "status"}),
    "message": frozenset({"thread_id", "channel", "author_type"}),
    "thread": frozenset({"assignee_id"}),
    "recording": frozenset({"provider", "restricted"}),
}

TEST_EVENT = "webhook.test"


@dataclass(frozen=True)
class EventType:
    key: str
    aggregate: str
    subject_type: str
    description: str
    version: int
    payload_fields: tuple[tuple[str, str], ...] = ()  # (name, JSON type) of ``event_data``


_JSON_TYPES = {"str": "string", "int": "integer", "bool": "boolean", "float": "number"}


def _json_type(annotation: Any) -> str:
    text = str(getattr(annotation, "__name__", annotation)).replace("typing.", "")
    nullable = "None" in text
    base = text.split("|")[0].strip()
    if base.startswith(("list", "tuple")):
        kind = "array"
    elif base.startswith("dict"):
        kind = "object"
    else:
        kind = _JSON_TYPES.get(base, "string")
    return f"{kind} | null" if nullable else kind


def payload_fields(cls: type) -> tuple[tuple[str, str], ...]:
    """The event's own fields (``event_data``) and their JSON types, minus redactions."""
    import dataclasses

    aggregate = cls.event_type.split(".", 1)[0]  # type: ignore[attr-defined]
    allowed = IDS_ONLY.get(aggregate)
    out = []
    for f in dataclasses.fields(cls):
        if f.name == "subject_id" or (allowed is not None and f.name not in allowed):
            continue
        out.append((f.name, _json_type(f.type)))
    return tuple(out)


def offered(event_type: str) -> bool:
    aggregate = event_type.split(".", 1)[0]
    return (
        aggregate in PUBLIC_AGGREGATES
        and aggregate not in NEVER_AGGREGATES
        and event_type not in NEVER_EVENT_TYPES
    )


def redact(event_type: str, data: dict[str, Any]) -> dict[str, Any]:
    allowed = IDS_ONLY.get(event_type.split(".", 1)[0])
    if allowed is None:
        return data
    return {k: v for k, v in data.items() if k in allowed}


def _description(cls: type) -> str:
    doc = (cls.__doc__ or "").strip()
    if doc and not doc.startswith(cls.__name__ + "("):
        return doc.splitlines()[0]
    return ""


def event_types() -> list[EventType]:
    out = []
    for key, cls in sorted(EVENT_TYPES.items()):
        aggregate = key.split(".", 1)[0]
        if offered(key):
            out.append(
                EventType(
                    key,
                    aggregate,
                    cls.subject_type,
                    _description(cls),
                    cls.version,
                    payload_fields(cls),
                )
            )
    return out


def public_event_keys() -> list[str]:
    return [e.key for e in event_types()]


def aggregates() -> list[str]:
    return sorted({e.aggregate for e in event_types()})


def validate_subscriptions(values: list[str]) -> list[str]:
    """Known event types or ``<aggregate>.*``; raises ``ValueError`` listing the bad ones."""
    known = set(public_event_keys())
    wildcards = {f"{a}.*" for a in aggregates()}
    bad = [v for v in values if v not in known and v not in wildcards]
    if bad:
        raise ValueError(", ".join(bad))
    if not values:
        raise ValueError("empty")
    return sorted(set(values))


def subscribed(subscriptions: list[str], event_type: str) -> bool:
    aggregate = event_type.split(".", 1)[0]
    return event_type in subscriptions or f"{aggregate}.*" in subscriptions


# --- public representations ---------------------------------------------------------------------

# subject type → (model, serializer, select_related, prefetch_related)
REPRESENTATIONS: dict[str, tuple[str, str, tuple[str, ...], tuple[str, ...]]] = {
    "client": ("people.models.Client", "people.api.serializers.ClientSerializer",
               ("billing_address",), ()),
    "contact": ("people.models.Contact", "people.api.serializers.ContactSerializer", (), ()),
    "student": ("people.models.Student", "people.api.serializers.StudentSerializer", (), ()),
    "tutor": ("people.models.Tutor", "people.api.serializers.TutorSerializer", (), ()),
    "service": ("catalogue.models.Service", "catalogue.api.serializers.ServiceSerializer",
                (), ()),
    "job": ("jobs.models.Job", "jobs.api.serializers.JobSerializer", (), ()),
    "lesson": ("scheduling.models.Lesson", "scheduling.api.serializers.LessonSerializer",
               ("service", "location"), ("tutors__tutor", "attendees__student")),
    "lesson_report": ("delivery.models.LessonReport",
                      "delivery.api.serializers.LessonReportSerializer", (), ()),
    "invoice": ("billing.models.Invoice", "billing.api.serializers.InvoiceSerializer", (), ()),
    "charge": ("billing.models.Charge", "billing.api.serializers.ChargeSerializer", (), ()),
    "credit_note": ("billing.models.CreditNote", "billing.api.serializers.CreditNoteSerializer",
                    (), ()),
    "payment_request": ("billing.models.PaymentRequest",
                        "billing.api.serializers.PaymentRequestSerializer", (), ()),
    "payment": ("payments.models.Payment", "payments.api.serializers.PaymentSerializer", (), ()),
    "pay_item": ("payroll.models.PayItem", "payroll.api.serializers.PayItemSerializer", (), ()),
    "enquiry": ("leads.models.Enquiry", "leads.api.serializers.EnquirySerializer", (), ()),
    "note": ("crm.models.Note", "crm.api.views.NoteSerializer", (), ()),
    "task": ("crm.models.Task", "crm.api.views.TaskSerializer", (), ()),
    "branch": ("tenancy.models.Branch", "tenancy.api.serializers.BranchSerializer", (), ()),
    "enrolment": ("courses.models.Enrolment", "courses.api.serializers.EnrolmentSerializer",
                  ("group_class__course", "student", "client"), ()),
    "group_class": ("courses.models.GroupClass", "courses.api.serializers.GroupClassSerializer",
                    ("course", "term"), ("teachers__tutor",)),
    # G6: resources that became public after E27.
    "review": ("growth.models.Review", "growth.api.serializers.ReviewSerializer", (), ()),
    "form_submission": ("leads.models.FormSubmission",
                        "leads.api.serializers.FormSubmissionSerializer", ("form",), ()),
}  # fmt: skip


def _viewer(user: Any) -> Any:
    """A stand-in request so field permissions apply as for ``user`` (anonymous: none)."""
    from django.contrib.auth.models import AnonymousUser

    return SimpleNamespace(user=user or AnonymousUser(), query_params={}, method="GET")


def representation(subject_type: str, subject_id: str, user: Any) -> dict[str, Any] | None:
    spec = REPRESENTATIONS.get(subject_type)
    if spec is None:
        return None
    model_path, serializer_path, related, prefetch = spec
    try:
        model = import_string(f"tutortrack.{model_path}")
        serializer = import_string(f"tutortrack.{serializer_path}")
        obj = (
            model._default_manager.filter(pk=subject_id)  # tenant-scoped manager
            .select_related(*related)
            .prefetch_related(*prefetch)
            .first()
        )
        if obj is None:
            return None
        data: dict[str, Any] = to_json_safe(
            serializer(obj, context={"request": _viewer(user)}).data
        )
        return data
    except Exception:  # a representation must never block delivery
        logger.warning("webhooks.representation_failed", subject_type=subject_type)
        return None


def build_payload(
    event: EventEnvelope, *, api_version: str, user: Any, cache: dict[str, Any] | None = None
) -> dict[str, Any]:
    key = f"{event.subject.get('type')}:{event.subject.get('id')}:{getattr(user, 'pk', '')}"
    event_data = redact(event.type, dict(event.data))
    if event.type.split(".", 1)[0] in IDS_ONLY:
        data = None  # ids only: never the record itself
    elif cache is not None and key in cache:
        data = cache[key]
    else:
        data = representation(str(event.subject.get("type")), str(event.subject.get("id")), user)
        if cache is not None:
            cache[key] = data
    body: dict[str, Any] = to_json_safe(
        {
            "id": str(event.id),
            "type": event.type,
            "version": event.version,
            "api_version": api_version,
            "occurred_at": event.occurred_at,
            "organisation_id": event.organisation_id,
            "branch_id": event.branch_id,
            "actor": event.actor,
            "subject": event.subject,
            "data": data if data is not None else event_data,
            "event_data": event_data,
            "changes": event.changes,
        }
    )
    return body


def test_payload(organisation_id: Any, api_version: str) -> dict[str, Any]:
    from tutortrack.core.time import now

    event_id = uuid.uuid4()
    body: dict[str, Any] = to_json_safe(
        {
            "id": str(event_id),
            "type": TEST_EVENT,
            "version": 1,
            "api_version": api_version,
            "occurred_at": now(),
            "organisation_id": organisation_id,
            "branch_id": None,
            "actor": {"type": "system", "id": None},
            "subject": {"type": "webhook_endpoint", "id": None},
            "data": {"message": "This is a test event from TutorTrack."},
            "event_data": {},
            "changes": {},
        }
    )
    return body


def sample_payload(event_type: str, organisation_id: Any, api_version: str) -> dict[str, Any]:
    """A synthetic example for docs and Zapier/Make "perform list" before real data exists."""
    cls = EVENT_TYPES[event_type]
    body = test_payload(organisation_id, api_version)
    body.update(
        {
            "type": event_type,
            "version": cls.version,
            "subject": {"type": cls.subject_type, "id": str(uuid.UUID(int=0))},
            "data": {"id": str(uuid.UUID(int=0))},
            "event_data": {name: None for name, _type in payload_fields(cls)},
        }
    )
    return body
