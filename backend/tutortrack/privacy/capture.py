"""Consent ticked outside the privacy screens becomes E29 consent records (FR-29-3, G6).

Public forms (E17/E24), class enrolment (E20), the review page (E25), the lesson-feedback
page (E09) and imports (E28) call ``record_ticked`` with the people the submission created
and the consent keys that were ticked. Each key is recorded for every person it applies to
(``ConsentType.applies_to``): a parent ticking "photos and video" records it for the child,
given by the parent (``on_behalf_of_child``).

Capture never blocks the submission that carries it: unknown or inactive keys are skipped
(a form may name a type the organisation later removed), and so is consent the rules
refuse (AADC: no marketing consent for children). What was skipped is returned for tests
and logs.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

import structlog

from tutortrack.core.exceptions import BusinessRuleViolation, NotFound

from .models import ConsentRecord, ConsentType

logger = structlog.get_logger(__name__)

# A plain "I agree" consent field on a form without its own key.
DEFAULT_FORM_KEY = "data-processing"


@dataclass
class Captured:
    records: list[ConsentRecord] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)  # (key, reason)


def _type_for(key: str) -> ConsentType | None:
    from .services import LAZY_DEFAULT_KEYS, ensure_default_types

    found = ConsentType.objects.filter(key=key, is_active=True).first()
    if found is None and key in LAZY_DEFAULT_KEYS:
        ensure_default_types()
        found = ConsentType.objects.filter(key=key, is_active=True).first()
    return found


def _already_current(
    consent_type: ConsentType, subject_type: str, subject_id: str, granted: bool
) -> bool:
    latest = (
        ConsentRecord.objects.filter(
            consent_type=consent_type, subject_type=subject_type, subject_id=subject_id
        )
        .order_by("-recorded_at", "-id")
        .first()
    )
    if latest is None:
        return False
    if not granted:
        return not latest.granted
    return latest.granted and latest.version >= consent_type.version


def record_ticked(
    *,
    people: dict[str, Iterable[Any]],
    keys: Iterable[str],
    method: str,
    source: str,
    given_by_name: str = "",
    given_by: Any = None,
    granted: bool = True,
    skip_if_current: bool = False,
) -> Captured:
    """Record ``keys`` for ``people`` (``{"people.contact": [id], "people.student": [...]}``).

    Students get the record "on behalf of a child" when the giver is someone else (a contact
    or a staff import). ``skip_if_current``: don't append a record when the latest one already
    says the same (granted at the current version, or withdrawn), e.g. re-running an import.
    """
    from .services import record_consent

    out = Captured()
    wanted = [k for k in dict.fromkeys(str(k).strip() for k in keys) if k]
    targets = {t: [str(i) for i in ids if i] for t, ids in people.items()}
    for key in wanted:
        consent_type = _type_for(key)
        if consent_type is None:
            out.skipped.append((key, "unknown"))
            continue
        matched = False
        for subject_type, ids in targets.items():
            if consent_type.applies_to and subject_type not in consent_type.applies_to:
                continue
            for subject_id in ids:
                matched = True
                if skip_if_current and _already_current(
                    consent_type, subject_type, subject_id, granted
                ):
                    out.skipped.append((key, "current"))
                    continue
                try:
                    out.records.append(
                        record_consent(
                            subject_type=subject_type,
                            subject_id=subject_id,
                            key=key,
                            granted=granted,
                            method=method,
                            given_by=given_by,
                            given_by_name=given_by_name,
                            on_behalf_of_child=subject_type == "people.student",
                            source=source,
                        )
                    )
                except (BusinessRuleViolation, NotFound) as exc:
                    out.skipped.append((key, getattr(exc, "extra", {}).get("code") or "refused"))
        if not matched:
            out.skipped.append((key, "not_applicable"))
    if out.skipped:
        logger.info("consent.capture_skipped", source=source, skipped=out.skipped)
    return out


def form_consent_keys(schema: dict[str, Any], answers: dict[str, Any]) -> list[str]:
    """The consent keys ticked on an E17 form: each ticked ``consent`` field records its
    ``consent_key`` (``data-processing`` when the field doesn't name one)."""
    from tutortrack.leads.forms import fields_of

    keys = []
    for f in fields_of(schema):
        if f.get("type") != "consent":
            continue
        if answers.get(f["key"]) in (True, "true", "on", "yes", "1", 1):
            keys.append(str(f.get("consent_key") or DEFAULT_FORM_KEY))
    return keys
