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
        "application", "attendance", "availability", "branch", "charge", "client",
        "compliance", "contact", "cover_request", "credit_note", "document", "enquiry",
        "expense", "form", "invoice", "job", "job_offer", "job_posting", "lesson",
        "lesson_report", "lesson_series", "makeup_credit", "note", "online_meeting",
        "pay_item", "pay_run", "payment", "payment_request", "payout", "reference", "service",
        "student", "task", "trial_lesson", "tutor", "waitlist",
    }
)  # fmt: skip

TEST_EVENT = "webhook.test"


@dataclass(frozen=True)
class EventType:
    key: str
    aggregate: str
    subject_type: str
    description: str
    version: int


def _description(cls: type) -> str:
    doc = (cls.__doc__ or "").strip()
    if doc and not doc.startswith(cls.__name__ + "("):
        return doc.splitlines()[0]
    return ""


def event_types() -> list[EventType]:
    out = []
    for key, cls in sorted(EVENT_TYPES.items()):
        aggregate = key.split(".", 1)[0]
        if aggregate in PUBLIC_AGGREGATES:
            out.append(EventType(key, aggregate, cls.subject_type, _description(cls), cls.version))
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
    if cache is not None and key in cache:
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
            "data": data if data is not None else event.data,
            "event_data": event.data,
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
        }
    )
    return body
