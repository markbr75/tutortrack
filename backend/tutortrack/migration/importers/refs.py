"""Finding the records a row refers to (by external id, email, name or number) and
remembering the external ids of records an import creates."""

from __future__ import annotations

from typing import Any

from django.db.models import Q, QuerySet
from django.utils.translation import gettext as _

from ..models import ExternalRef
from .base import Context, RowError, first


def ref_for(ctx: Context, target_type: str, external_id: Any) -> str | None:
    if external_id in (None, ""):
        return None
    key = (target_type, str(external_id))
    cached = ctx.cache.get(("ref", *key))
    if cached:
        return str(cached)
    found = (
        ExternalRef.objects.filter(
            system=ctx.system, target_type=target_type, external_id=str(external_id)[:120]
        )
        .values_list("target_id", flat=True)
        .first()
    )
    return str(found) if found else None


def remember(ctx: Context, target_type: str, external_id: Any, target: Any) -> dict[str, Any]:
    """Record ``external_id`` → ``target`` (idempotent); returns the created-ref entry."""
    ref, _created = ExternalRef.objects.update_or_create(
        system=ctx.system,
        target_type=target_type,
        external_id=str(external_id)[:120],
        defaults={"target_id": str(target.pk), "batch": ctx.batch},
    )
    ctx.cache[("ref", target_type, str(external_id))] = str(target.pk)
    return {"type": "migration.externalref", "id": str(ref.pk)}


def _one(qs: QuerySet[Any], what: str, value: str) -> Any:
    found = list(qs[:2])
    if len(found) > 1:
        raise RowError(
            _("More than one %(what)s matches “%(value)s”; use an id or email.")
            % {"what": what, "value": value}
        )
    return found[0] if found else None


# --- people -------------------------------------------------------------------------------------


def find_client(ctx: Context, values: dict[str, Any], prefix: str = "client_") -> Any:
    from tutortrack.people.models import Client, Contact

    ext = values.get(f"{prefix}external_id")
    if ext:
        target = ref_for(ctx, "people.client", ext)
        if target:
            return Client.objects.filter(pk=target).first()
    email = values.get(f"{prefix}email")
    if email:
        contact = (
            Contact.objects.filter(email=str(email).lower())
            .select_related("client")
            .order_by("-is_primary", "created_at")
            .first()
        )
        if contact is not None:
            return contact.client
    name = values.get(f"{prefix}name")
    if name:
        return _one(
            Client.objects.filter(display_name__iexact=str(name).strip(), archived_at__isnull=True),
            _("client"),
            str(name),
        )
    return None


def client_key(values: dict[str, Any], prefix: str = "client_") -> str:
    """A key identifying the client a row refers to, for rows not yet created."""
    return str(first(values, f"{prefix}external_id", f"{prefix}email", f"{prefix}name") or "")


def find_student(ctx: Context, values: dict[str, Any], client: Any = None) -> Any:
    from tutortrack.people.models import Student

    ext = values.get("student_external_id")
    if ext:
        target = ref_for(ctx, "people.student", ext)
        if target:
            return Student.objects.filter(pk=target).first()
    name = values.get("student_name")
    if name:
        return find_student_by_name(str(name), client)
    return None


def find_student_by_name(name: str, client: Any = None) -> Any:
    from tutortrack.people.models import Student

    parts = name.strip().split()
    qs = Student.objects.filter(archived_at__isnull=True)
    if client is not None:
        qs = qs.filter(client=client)
    if len(parts) > 1:
        qs = qs.filter(first_name__iexact=" ".join(parts[:-1]), last_name__iexact=parts[-1]) | (
            qs.filter(first_name__iexact=parts[0], last_name__iexact=" ".join(parts[1:]))
        )
    else:
        qs = qs.filter(Q(first_name__iexact=name.strip()) | Q(preferred_name__iexact=name.strip()))
    return _one(qs.distinct(), _("student"), name)


def find_tutor(ctx: Context, values: dict[str, Any], prefix: str = "tutor_") -> Any:
    from tutortrack.people.models import TutorProfile

    ext = values.get(f"{prefix}external_id")
    if ext:
        target = ref_for(ctx, "people.tutor", ext)
        if target:
            return TutorProfile.objects.filter(pk=target).first()
    email = values.get(f"{prefix}email")
    if email:
        return TutorProfile.objects.filter(email=str(email).lower()).first()
    name = values.get(f"{prefix}name")
    if name:
        parts = str(name).strip().split()
        qs = TutorProfile.objects.filter(archived_at__isnull=True)
        if len(parts) > 1:
            qs = qs.filter(first_name__iexact=" ".join(parts[:-1]), last_name__iexact=parts[-1])
        else:
            qs = qs.filter(Q(first_name__iexact=parts[0]) | Q(display_name__iexact=parts[0]))
        return _one(qs, _("tutor"), str(name))
    return None


def find_service(ctx: Context, values: dict[str, Any], key: str = "service") -> Any:
    from tutortrack.catalogue.models import Service

    ext = values.get(f"{key}_external_id")
    if ext:
        target = ref_for(ctx, "catalogue.service", ext)
        if target:
            return Service.objects.filter(pk=target).first()
    name = values.get(key)
    if name:
        return _one(Service.objects.filter(name__iexact=str(name).strip()), _("service"), name)
    return None


def find_job(ctx: Context, values: dict[str, Any]) -> Any:
    from tutortrack.jobs.models import Job

    ext = values.get("job_external_id")
    if ext:
        target = ref_for(ctx, "jobs.job", ext)
        if target:
            return Job.objects.filter(pk=target).first()
    reference = values.get("job_reference")
    if reference:
        return Job.objects.filter(reference__iexact=str(reference).strip()).first()
    return None


def find_invoice(number: Any) -> Any:
    from tutortrack.billing.models import Invoice

    if not number:
        return None
    return Invoice.objects.filter(number__iexact=str(number).strip()).first()


RECORD_TYPES = {
    "client": "people.client",
    "contact": "people.contact",
    "student": "people.student",
    "tutor": "people.tutor",
    "job": "jobs.job",
    "enquiry": "leads.enquiry",
}


def find_record(ctx: Context, record_type: str, values: dict[str, Any]) -> tuple[str, Any]:
    """For tags and notes: ``record_type`` plus ``record_external_id``/``record_email``/
    ``record_name``."""
    target_type = RECORD_TYPES.get(record_type, "")
    if not target_type:
        raise RowError(_("Unknown record type."), "record_type")
    ext, email, name = (values.get(f"record_{k}") for k in ("external_id", "email", "name"))
    found: Any = None
    if ext:
        target = ref_for(ctx, target_type, ext)
        if target:
            from tutortrack.crm import targets

            spec = targets.get(target_type)
            found = spec.model._default_manager.filter(pk=target).first() if spec else None
    if found is None and record_type == "client":
        found = find_client(ctx, {"client_email": email, "client_name": name})
    elif found is None and record_type == "student" and name:
        found = find_student_by_name(str(name))
    elif found is None and record_type == "tutor":
        found = find_tutor(ctx, {"tutor_email": email, "tutor_name": name})
    elif found is None and record_type == "contact" and email:
        from tutortrack.people.models import Contact

        found = Contact.objects.filter(email=str(email).lower()).first()
    elif found is None and record_type == "job" and name:
        from tutortrack.jobs.models import Job

        found = Job.objects.filter(reference__iexact=str(name)).first()
    return target_type, found
