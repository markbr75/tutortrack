"""Broadcast segments (FR-13-6): who a broadcast goes to. Reads only.

A definition is a dict; every key is optional and they combine with AND::

    {
        "branches": [<branch id>],
        "tags": [<tag id>],                # tags on clients (contacts) or tutors
        "saved_view": <crm SavedView id>,  # a saved list of clients, students or tutors
        # client contacts
        "client_statuses": ["active"],
        "student_statuses": ["active", "trial"],
        "group_class": <class id>,         # families with a student in the class
        "job": <job id>,                   # the job's family
        "pipeline_stage": <stage id>,      # open enquiries in a pipeline stage
        "contacts": "all" | "primary",     # every contact, or the main one per family
        # tutors
        "tutor_statuses": ["active"],
        "subject": "Maths",
    }

``resolve`` returns ``SegmentMember`` rows (person, name, email, phone) without
duplicates; consent, preferences and suppressions are applied when sending.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from django.db.models import Q, QuerySet
from django.http import QueryDict
from django.utils.translation import gettext as _

from tutortrack.core.exceptions import BusinessRuleViolation

from .models import Audience

LIST_KEYS = ("branches", "tags", "client_statuses", "student_statuses", "tutor_statuses")
ID_KEYS = ("saved_view", "group_class", "job", "pipeline_stage")
CONTACT_ONLY = ("client_statuses", "student_statuses", "pipeline_stage", "contacts")
TUTOR_ONLY = ("tutor_statuses", "subject")
ENROLLED = ("enrolled", "trial", "pending_payment")


@dataclass(frozen=True)
class SegmentMember:
    kind: str  # contact | tutor
    id: str
    name: str
    first_name: str
    email: str
    phone: str
    user_id: str | None
    target: tuple[str, str]  # the record whose timeline shows the message


def _invalid(message: str) -> BusinessRuleViolation:
    return BusinessRuleViolation(message, extra={"errors": {"definition": [message]}})


def _uuid(value: Any) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError):
        raise _invalid(_("A segment filter refers to something that doesn't exist.")) from None


def clean(audience: str, definition: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalise a definition for ``audience``."""
    if audience not in Audience.values:
        raise BusinessRuleViolation(
            _("Choose who it's for."), extra={"errors": {"audience": [_("Choose who it's for.")]}}
        )
    if not isinstance(definition, dict):
        raise _invalid(_("The segment is not valid."))
    known = {*LIST_KEYS, *ID_KEYS, "contacts", "subject"}
    unknown = set(definition) - known
    if unknown:
        raise _invalid(_("Unknown segment filter: %(k)s") % {"k": ", ".join(sorted(unknown))})
    wrong = TUTOR_ONLY if audience == Audience.CONTACTS else CONTACT_ONLY
    out: dict[str, Any] = {}
    for key, value in definition.items():
        if value in (None, "", []):
            continue
        if key in wrong:
            raise _invalid(_("That filter doesn't apply to this audience."))
        if key in LIST_KEYS:
            if not isinstance(value, list):
                raise _invalid(_("The segment is not valid."))
            out[key] = [
                _uuid(v) if key in {"branches", "tags"} else str(v)[:30] for v in value[:100]
            ]
        elif key in ID_KEYS:
            out[key] = _uuid(value)
        elif key == "contacts":
            if value not in ("all", "primary"):
                raise _invalid(_("The segment is not valid."))
            out[key] = value
        elif key == "subject":
            out[key] = str(value)[:100]
    return out


# --- resolution ---------------------------------------------------------------------------------


def _ids_tagged(tag_ids: Iterable[str], entity_type: str) -> list[str]:
    from tutortrack.crm.models import TaggedItem

    return list(
        TaggedItem.objects.filter(tag_id__in=list(tag_ids), target_type=entity_type)
        .values_list("target_id", flat=True)
        .distinct()
    )


def _saved_view(view_id: str, entity_types: tuple[str, ...]) -> tuple[str, QueryDict] | None:
    """A shared (or the sender's) saved list view: its entity type and filters as query
    parameters, as the list screen would send them."""
    from tutortrack.crm.models import SavedView

    view = SavedView.objects.filter(pk=view_id, entity_type__in=entity_types).first()
    if view is None:
        raise _invalid(_("A segment filter refers to something that doesn't exist."))
    params = QueryDict(mutable=True)
    for key, value in (view.filters or {}).items():
        for item in value if isinstance(value, list) else [value]:
            if item not in (None, ""):
                params.appendlist(key, str(item))
    return view.entity_type, params


def _apply_view(qs: QuerySet[Any], entity_type: str, params: QueryDict) -> QuerySet[Any]:
    from tutortrack.crm.listing import apply_crm_filters

    qs = apply_crm_filters(qs, params, entity_type)
    statuses = params.getlist("status")
    if statuses:
        qs = qs.filter(status__in=statuses)
    if params.get("branch"):
        branch_field = "branches" if entity_type == "people.tutor" else "branch_id"
        qs = qs.filter(**{branch_field: params["branch"]})
    if params.get("type") and entity_type == "people.client":
        qs = qs.filter(type=params["type"])
    return qs


def _clients(definition: dict[str, Any]) -> QuerySet[Any]:
    from tutortrack.people.models import Client, Student

    qs = Client.objects.filter(archived_at__isnull=True)
    if definition.get("client_statuses"):
        qs = qs.filter(status__in=definition["client_statuses"])
    else:
        qs = qs.exclude(status=Client.Status.ARCHIVED)
    if definition.get("branches"):
        qs = qs.filter(branch_id__in=definition["branches"])
    if definition.get("tags"):
        qs = qs.filter(pk__in=_ids_tagged(definition["tags"], "people.client"))
    if definition.get("student_statuses"):
        qs = qs.filter(
            pk__in=Student.objects.filter(
                status__in=definition["student_statuses"], archived_at__isnull=True
            ).values("client_id")
        )
    if definition.get("saved_view"):
        found = _saved_view(definition["saved_view"], ("people.client", "people.student"))
        if found:
            entity_type, params = found
            if entity_type == "people.client":
                qs = _apply_view(qs, entity_type, params)
            else:
                students = _apply_view(Student.objects.all(), entity_type, params)
                qs = qs.filter(pk__in=students.values("client_id"))
    if definition.get("group_class"):
        from tutortrack.courses.models import Enrolment

        qs = qs.filter(
            pk__in=Enrolment.objects.filter(
                group_class_id=definition["group_class"], status__in=ENROLLED
            ).values("client_id")
        )
    if definition.get("job"):
        from tutortrack.jobs.models import Job

        qs = qs.filter(pk__in=Job.objects.filter(pk=definition["job"]).values("client_id"))
    return qs


def _contacts(definition: dict[str, Any]) -> list[SegmentMember]:
    from tutortrack.people.models import Contact

    clients = _clients(definition)
    contacts = Contact.objects.filter(client__in=clients, archived_at__isnull=True)
    if definition.get("pipeline_stage"):
        from tutortrack.leads.models import Enquiry

        enquiries = Enquiry.objects.filter(stage_id=definition["pipeline_stage"], status="open")
        contacts = contacts.filter(
            Q(pk__in=enquiries.exclude(contact=None).values("contact_id"))
            | Q(client_id__in=enquiries.filter(contact=None).values("client_id"))
        )
    contacts = contacts.select_related("client").order_by("client_id", "-is_primary", "created_at")
    primary_only = definition.get("contacts") == "primary"
    out: list[SegmentMember] = []
    seen_clients: set[Any] = set()
    for contact in contacts:
        if primary_only:
            if contact.client_id in seen_clients:
                continue
            seen_clients.add(contact.client_id)
        out.append(
            SegmentMember(
                kind="contact",
                id=str(contact.pk),
                name=contact.full_name,
                first_name=contact.first_name,
                email=contact.email,
                phone=contact.mobile,
                user_id=str(contact.user_id) if contact.user_id else None,
                target=("people.client", str(contact.client_id)),
            )
        )
    return out


def _tutors(definition: dict[str, Any]) -> list[SegmentMember]:
    from tutortrack.people.models import TutorProfile

    qs = TutorProfile.objects.filter(archived_at__isnull=True)
    if definition.get("tutor_statuses"):
        qs = qs.filter(status__in=definition["tutor_statuses"])
    else:
        qs = qs.exclude(status__in=["archived", "applicant"])
    if definition.get("branches"):
        qs = qs.filter(branches__in=definition["branches"])
    if definition.get("tags"):
        qs = qs.filter(pk__in=_ids_tagged(definition["tags"], "people.tutor"))
    if definition.get("subject"):
        qs = qs.filter(subjects__subject__iexact=definition["subject"])
    if definition.get("saved_view"):
        found = _saved_view(definition["saved_view"], ("people.tutor",))
        if found:
            qs = _apply_view(qs, *found)
    if definition.get("group_class"):
        from tutortrack.courses.models import ClassTeacher

        qs = qs.filter(
            pk__in=ClassTeacher.objects.filter(group_class_id=definition["group_class"]).values(
                "tutor_id"
            )
        )
    if definition.get("job"):
        from tutortrack.jobs.models import JobTutor

        qs = qs.filter(
            pk__in=JobTutor.objects.filter(job_id=definition["job"], status="active").values(
                "tutor_id"
            )
        )
    out = []
    for tutor in qs.select_related("membership").distinct().order_by("first_name", "last_name"):
        membership = tutor.membership
        active = membership is not None and membership.status == "active"
        out.append(
            SegmentMember(
                kind="tutor",
                id=str(tutor.pk),
                name=tutor.full_name,
                first_name=tutor.display_name or tutor.first_name,
                email=tutor.email,
                phone=tutor.phone,
                user_id=str(membership.user_id) if active and membership else None,
                target=("people.tutor", str(tutor.pk)),
            )
        )
    return out


def resolve(audience: str, definition: dict[str, Any]) -> list[SegmentMember]:
    definition = clean(audience, definition)
    if audience == Audience.TUTORS:
        return _tutors(definition)
    return _contacts(definition)
