"""Consent writes and reads (FR-29-3)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.db import transaction
from django.utils.translation import gettext as _

from tutortrack.core import audit
from tutortrack.core.context import get_request_context
from tutortrack.core.events import publish
from tutortrack.core.exceptions import BusinessRuleViolation, NotFound
from tutortrack.core.time import now

from . import subjects
from .events import ConsentGranted, ConsentWithdrawn
from .models import ConsentRecord, ConsentType

PEOPLE = ["people.contact", "people.student", "identity.user"]
DEFAULT_TYPES: list[dict[str, Any]] = [
    {"key": "terms", "name": "Terms of service", "category": "terms_of_service",
     "required": True, "applies_to": ["people.contact", "identity.user"]},
    {"key": "privacy-policy", "name": "Privacy policy", "category": "privacy_policy",
     "required": True, "applies_to": ["people.contact", "identity.user"]},
    {"key": "data-processing", "name": "Processing of personal data", "category": "data_processing",
     "required": True, "applies_to": PEOPLE},
    {"key": "marketing-email", "name": "News and offers by email", "category": "marketing_email",
     "applies_to": ["people.contact", "identity.user"]},
    {"key": "marketing-sms", "name": "News and offers by SMS", "category": "marketing_sms",
     "applies_to": ["people.contact", "identity.user"]},
    {"key": "photo-video", "name": "Photos and video", "category": "photo_video",
     "applies_to": ["people.student"]},
    {"key": "lesson-recording", "name": "Recording online lessons", "category": "lesson_recording",
     "applies_to": ["people.student", "people.contact"]},
]  # fmt: skip


def ensure_default_types() -> int:
    """Create the default consent types for the organisation in context (idempotent)."""
    created = 0
    for spec in DEFAULT_TYPES:
        _, was_created = ConsentType.objects.get_or_create(key=spec["key"], defaults=spec)
        created += int(was_created)
    return created


@transaction.atomic
def publish_new_version(consent_type: ConsentType) -> ConsentType:
    """A material change (e.g. updated privacy policy): everyone must consent again."""
    with audit.track(consent_type, action="new_version"):
        consent_type.version += 1
        consent_type.save(update_fields=["version", "updated_at"])
    return consent_type


@dataclass(frozen=True)
class ConsentStatus:
    key: str
    name: str
    category: str
    required: bool
    current_version: int
    granted: bool | None  # None: never asked
    version: int | None
    recorded_at: datetime | None
    needs_reconsent: bool


def status_for(subject_type: str, subject_id: str) -> list[ConsentStatus]:
    """Current consent state per active type for a person."""
    latest: dict[Any, ConsentRecord] = {}
    for record in ConsentRecord.objects.filter(
        subject_type=subject_type, subject_id=str(subject_id)
    ).order_by("consent_type_id", "-recorded_at", "-id"):
        latest.setdefault(record.consent_type_id, record)
    out = []
    for ct in ConsentType.objects.filter(is_active=True).order_by("name"):
        if ct.applies_to and subject_type not in ct.applies_to:
            continue
        rec = latest.get(ct.pk)
        out.append(
            ConsentStatus(
                key=ct.key,
                name=ct.name,
                category=ct.category,
                required=ct.required,
                current_version=ct.version,
                granted=rec.granted if rec else None,
                version=rec.version if rec else None,
                recorded_at=rec.recorded_at if rec else None,
                needs_reconsent=bool(rec and rec.granted and rec.version < ct.version)
                or (rec is None and ct.required),
            )
        )
    return out


def is_granted(subject_type: str, subject_id: str, key: str) -> bool:
    """Whether consent of type ``key`` is currently granted at the current version."""
    return any(
        s.key == key and s.granted and not s.needs_reconsent
        for s in status_for(subject_type, subject_id)
    )


@transaction.atomic
def record_consent(
    *,
    subject_type: str,
    subject_id: str,
    key: str,
    granted: bool,
    method: str,
    given_by: Any = None,
    given_by_name: str = "",
    on_behalf_of_child: bool = False,
) -> ConsentRecord:
    consent_type = ConsentType.objects.filter(key=key, is_active=True).first()
    if consent_type is None:
        raise NotFound(_("Unknown consent type."))
    if consent_type.applies_to and subject_type not in consent_type.applies_to:
        raise BusinessRuleViolation(_("This consent does not apply to this person."))
    if not subjects.is_valid(subject_type, str(subject_id)):
        raise NotFound(_("Person not found."))
    ctx = get_request_context()
    record = ConsentRecord.objects.create(
        consent_type=consent_type,
        version=consent_type.version,
        subject_type=subject_type,
        subject_id=str(subject_id),
        granted=granted,
        method=method,
        given_by=given_by,
        given_by_name=given_by_name or (given_by.get_full_name() if given_by else ""),
        on_behalf_of_child=on_behalf_of_child,
        ip=ctx.ip,
        user_agent=(ctx.user_agent or "")[:500],
        recorded_at=now(),
    )
    audit.record_create(record)
    event_cls = ConsentGranted if granted else ConsentWithdrawn
    data: dict[str, Any] = {
        "consent_type": consent_type.key,
        "category": consent_type.category,
        "person_type": subject_type,
        "person_id": str(subject_id),
    }
    if granted:
        data["consent_version"] = consent_type.version
    publish(event_cls(subject_id=record.pk, **data))
    return record


def withdraw_consent(
    *, subject_type: str, subject_id: str, key: str, **kwargs: Any
) -> ConsentRecord:
    return record_consent(
        subject_type=subject_type, subject_id=subject_id, key=key, granted=False, **kwargs
    )
