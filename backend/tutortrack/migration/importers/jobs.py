"""Jobs: who is taught what by whom at which rates (E28-T03)."""

from __future__ import annotations

from typing import Any

from django.utils.translation import gettext as _

from . import refs
from .base import Context, FieldSpec, Importer, Outcome, Plan, RowError, register
from .base import label as _l
from .common import custom_values, money_or_none, not_found, ref

JOB_STATUSES = ("draft", "seeking_tutor", "active", "paused", "completed", "cancelled")
BILLING = ("pay_as_you_go", "invoice_in_advance", "prepaid_credit")

REFERENCE_FIELDS = [
    FieldSpec(
        "client_external_id",
        _l("Client ID"),
        synonyms=("client id", "family id", "customer id", "account id"),
    ),
    FieldSpec(
        "client_email", _l("Client email"), "email", synonyms=("client email", "parent email")
    ),
    FieldSpec(
        "client_name",
        _l("Client name"),
        synonyms=("client", "client name", "family", "customer"),
    ),
]
TUTOR_FIELDS = [
    FieldSpec(
        "tutor_external_id",
        _l("Tutor ID"),
        synonyms=("tutor id", "contractor id", "teacher id", "employee id"),
    ),
    FieldSpec(
        "tutor_email",
        _l("Tutor email"),
        "email",
        synonyms=("tutor email", "teacher email", "contractor email"),
    ),
    FieldSpec(
        "tutor_name",
        _l("Tutor name"),
        synonyms=("tutor", "teacher", "contractor", "tutor name", "employee"),
    ),
]


def resolve_students(ctx: Context, values: dict[str, Any], client: Any) -> list[Any]:
    from tutortrack.people.models import Student

    found = []
    for ext in values.get("student_external_ids") or []:
        target = refs.ref_for(ctx, "people.student", ext)
        student = Student.objects.filter(pk=target).first() if target else None
        if student is None:
            raise RowError(_("Student %(id)s not found.") % {"id": ext}, "student_external_ids")
        found.append(student)
    for name in values.get("student_names") or []:
        student = refs.find_student_by_name(name, client)
        if student is None:
            raise RowError(_("Student %(name)s not found.") % {"name": name}, "student_names")
        found.append(student)
    if not found and client is not None:
        found = list(Student.objects.filter(client=client, archived_at__isnull=True)[:2])
        if len(found) != 1:
            raise RowError(_("Name the students (the client has several)."), "student_names")
    return list({s.pk: s for s in found}.values())


@register
class JobImporter(Importer):
    key = "jobs"
    label = _l("Jobs")
    description = _l("Ongoing arrangements: client, students, service, tutor and rates.")
    permissions = ("jobs.job.create",)
    target_type = "jobs.job"
    upsert_keys = ("external_id", "none")
    default_upsert = "external_id"
    fields = [
        FieldSpec("external_id", _l("Job ID"), synonyms=("job id", "service id", "id")),
        FieldSpec("name", _l("Job name"), synonyms=("name", "job name", "job", "title")),
        *REFERENCE_FIELDS,
        FieldSpec(
            "student_names",
            _l("Students (names, separated by ;)"),
            "list",
            synonyms=("students", "student", "recipients", "student names"),
        ),
        FieldSpec(
            "student_external_ids",
            _l("Student IDs (separated by ;)"),
            "list",
            synonyms=("student ids", "student id", "recipient ids"),
        ),
        FieldSpec(
            "service",
            _l("Service"),
            synonyms=("service", "service name", "lesson type", "subject"),
        ),
        FieldSpec("service_external_id", _l("Service ID"), synonyms=("service id",)),
        *TUTOR_FIELDS,
        FieldSpec(
            "charge_rate",
            _l("Charge rate"),
            "decimal",
            synonyms=("charge rate", "price", "client rate"),
        ),
        FieldSpec(
            "pay_rate",
            _l("Tutor pay rate"),
            "decimal",
            synonyms=("pay rate", "tutor rate", "wage"),
        ),
        FieldSpec(
            "status",
            _l("Status"),
            "choice",
            choices=JOB_STATUSES,
            synonyms=("status", "job status"),
        ),
        FieldSpec(
            "billing_method",
            _l("Billing"),
            "choice",
            choices=BILLING,
            synonyms=("billing", "billing method"),
        ),
        FieldSpec("start_date", _l("Start date"), "date", synonyms=("start", "start date")),
        FieldSpec("notes_internal", _l("Notes"), synonyms=("notes", "description")),
    ]
    example = {
        "external_id": "J-12",
        "client_external_id": "C-1001",
        "student_names": "Tom Smith",
        "service": "GCSE Maths 1:1",
        "tutor_email": "alex@example.com",
        "charge_rate": "45.00",
        "pay_rate": "25.00",
        "status": "active",
    }

    def _existing(self, values: dict[str, Any], ctx: Context) -> Any:
        if ctx.upsert_key == "none" or not values.get("external_id"):
            return None
        return refs.find_job(ctx, {"job_external_id": values["external_id"]})

    def check(self, values: dict[str, Any], ctx: Context) -> Plan:
        if values.get("external_id") and ctx.claim("job", values["external_id"]):
            ctx.error("external_id", _("This job id appears earlier in the file."))
        existing = self._existing(values, ctx)
        if existing is not None:
            ctx.warn("external_id", _("Already imported; skipped."))
            return Plan(action="skip", target_type="jobs.job", target_id=str(existing.pk))
        try:
            client = refs.find_client(ctx, values)
            if client is None:
                ctx.error("client_name", not_found(_("Client")))
            else:
                resolve_students(ctx, values, client)
            if refs.find_service(ctx, values) is None:
                ctx.error("service", not_found(_("Service")))
            if (
                any(values.get(f.key) for f in TUTOR_FIELDS)
                and refs.find_tutor(ctx, values) is None
            ):
                ctx.error("tutor_email", not_found(_("Tutor")))
        except RowError as exc:
            ctx.error(exc.field, str(exc))
        return Plan(effects=[("jobs.job", "create")])

    def apply(self, values: dict[str, Any], ctx: Context) -> Outcome:
        from tutortrack.jobs import services as jobs

        client = refs.find_client(ctx, values)
        service = refs.find_service(ctx, values)
        if client is None or service is None:
            raise RowError(not_found(_("Client") if client is None else _("Service")))
        students = resolve_students(ctx, values, client)
        tutor = (
            refs.find_tutor(ctx, values) if any(values.get(f.key) for f in TUTOR_FIELDS) else None
        )
        currency = service.currency
        fields: dict[str, Any] = {
            k: values[k]
            for k in ("name", "billing_method", "start_date", "notes_internal")
            if values.get(k) not in (None, "")
        }
        if values.get("charge_rate") is not None:
            fields["charge_rate"] = money_or_none(values["charge_rate"], currency)
        tutors = []
        if tutor is not None:
            tutors.append(
                {
                    "tutor": tutor,
                    "pay_rate_override": money_or_none(values.get("pay_rate"), currency),
                }
            )
        status = values.get("status") or ("active" if tutor is not None else "seeking_tutor")
        # Paused and completed jobs are reached through active (the job's state machine).
        initial = "active" if status in ("paused", "completed") else status
        job = jobs.create_job(
            client=client,
            service=service,
            students=[{"student": s} for s in students],
            tutors=tutors,
            status=initial,
            custom_fields=custom_values(values) or None,
            **fields,
        )
        if status != job.status:
            jobs.change_status(job, status, reason=_("Imported"))
        out = Outcome(action="create", target_type="jobs.job", target_id=str(job.pk))
        out.created.append(ref(job))
        if values.get("external_id"):
            out.created.append(refs.remember(ctx, "jobs.job", values["external_id"], job))
        return out
