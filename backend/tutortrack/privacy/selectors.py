"""Privacy reads (E29 Part 2): scoped querysets and legal-hold lookups other apps use to
skip held records during retention purges."""

from __future__ import annotations

from typing import Any

from django.db.models import Q, QuerySet

from tutortrack.core.permissions import has_perm, permission_scope

from .models import (
    DataSubjectRequest,
    ErasureRecord,
    LegalHold,
    LoneWorkingVisit,
    RetentionPolicy,
    RetentionRun,
    SafeguardingConcern,
    SafeguardingFlag,
)
from .registry import Person


def _all_or_none(user: Any, qs: QuerySet[Any], codename: str) -> QuerySet[Any]:
    return qs if has_perm(user, codename) else qs.none()


# --- legal holds --------------------------------------------------------------------------------


def active_holds() -> QuerySet[LegalHold]:
    return LegalHold.objects.filter(released_at__isnull=True)


def held_ids(subject_type: str) -> set[str]:
    """Ids of ``subject_type`` records under an active legal hold (retention handlers skip
    them)."""
    return set(
        active_holds().filter(subject_type=subject_type).values_list("subject_id", flat=True)
    )


def holds_for(person: Person) -> list[LegalHold]:
    """Active holds on the person, anyone erased with them, or their context (a student's
    client)."""
    refs: dict[str, set[str]] = {}
    for bucket in (person.ids, person.context):
        for subject_type, ids in bucket.items():
            refs.setdefault(subject_type, set()).update(ids)
    if not refs:
        return []
    q = Q()
    for subject_type, ids in refs.items():
        q |= Q(subject_type=subject_type, subject_id__in=list(ids))
    return list(active_holds().filter(q))


def legal_holds(user: Any) -> QuerySet[LegalHold]:
    return _all_or_none(user, LegalHold.objects.all(), "privacy.legal_hold.manage")


# --- requests, erasures and retention -----------------------------------------------------------


def data_requests(user: Any) -> QuerySet[DataSubjectRequest]:
    return _all_or_none(user, DataSubjectRequest.objects.all(), "privacy.dsar.manage")


def my_data_requests(user: Any) -> QuerySet[DataSubjectRequest]:
    return DataSubjectRequest.objects.filter(requester_user=user)


def erasures(user: Any) -> QuerySet[ErasureRecord]:
    return _all_or_none(user, ErasureRecord.objects.all(), "privacy.dsar.manage")


def retention_policies(user: Any) -> QuerySet[RetentionPolicy]:
    return _all_or_none(user, RetentionPolicy.objects.all(), "privacy.retention.manage")


def retention_runs(user: Any) -> QuerySet[RetentionRun]:
    return _all_or_none(user, RetentionRun.objects.all(), "privacy.retention.manage")


def erased_ids(subject_type: str) -> set[str]:
    """Ids of ``subject_type`` covered by any erasure (planned, running or done), including
    people erased as part of someone else (a client's students)."""
    out: set[str] = set()
    for subjects in ErasureRecord.objects.exclude(status=ErasureRecord.Status.BLOCKED).values_list(
        "subjects", flat=True
    ):
        out.update((subjects or {}).get("ids", {}).get(subject_type, []))
    return out


def is_erased(subject_type: str, subject_id: Any) -> bool:
    return ErasureRecord.objects.filter(
        subject_type=subject_type,
        subject_id=str(subject_id),
        status=ErasureRecord.Status.COMPLETED,
    ).exists()


# --- safeguarding -------------------------------------------------------------------------------


def concerns(user: Any) -> QuerySet[SafeguardingConcern]:
    """DSLs see every case; nobody else sees any (raisers see only their references, via
    ``raised_concerns``)."""
    qs = SafeguardingConcern.objects.select_related("student", "lesson", "tutor")
    return _all_or_none(user, qs, "safeguarding.dsl")


def raised_concerns(user: Any) -> QuerySet[SafeguardingConcern]:
    return SafeguardingConcern.objects.filter(raised_by=user)


def flags(user: Any) -> QuerySet[SafeguardingFlag]:
    return _all_or_none(user, SafeguardingFlag.objects.all(), "safeguarding.dsl")


def visits(user: Any) -> QuerySet[LoneWorkingVisit]:
    qs = LoneWorkingVisit.objects.select_related("lesson", "tutor")
    if has_perm(user, "safeguarding.lone_working.monitor"):
        return qs
    if permission_scope(user, "safeguarding.checkin") is not None:
        return qs.filter(LoneWorkingVisit.own_scope_q(user))
    return qs.none()
