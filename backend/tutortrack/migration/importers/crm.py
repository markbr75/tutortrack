"""Tags, notes, enquiries and tutor availability (E28-T02)."""

from __future__ import annotations

from datetime import time
from typing import Any

from django.utils.translation import gettext as _

from . import refs
from .base import Context, FieldSpec, Importer, Outcome, Plan, RowError, register
from .base import label as _l
from .common import apply_tags, not_found, ref
from .jobs import TUTOR_FIELDS

RECORD_FIELDS = [
    FieldSpec(
        "record_type",
        _l("Record type"),
        "choice",
        required=True,
        choices=tuple(refs.RECORD_TYPES),
        synonyms=("type", "record type", "entity"),
    ),
    FieldSpec("record_external_id", _l("Record ID"), synonyms=("id", "record id", "external id")),
    FieldSpec("record_email", _l("Record email"), "email", synonyms=("email",)),
    FieldSpec(
        "record_name", _l("Record name or reference"), synonyms=("name", "record", "reference")
    ),
]


def _record(values: dict[str, Any], ctx: Context) -> tuple[str, Any]:
    target_type, record = refs.find_record(ctx, values["record_type"], values)
    if record is None:
        raise RowError(not_found(_("Record")), "record_name")
    return target_type, record


@register
class TagImporter(Importer):
    key = "tags"
    label = _l("Tags")
    description = _l("Labels on clients, students, tutors, contacts, jobs or enquiries.")
    permissions = ("crm.tag.apply",)
    upsert_keys = ("none",)
    default_upsert = "none"
    fields = [
        *RECORD_FIELDS,
        FieldSpec(
            "tags",
            _l("Tags (separated by ;)"),
            "list",
            required=True,
            synonyms=("tags", "labels", "tag", "label"),
        ),
    ]
    example = {"record_type": "client", "record_external_id": "C-1001", "tags": "VIP; Referral"}

    def check(self, values: dict[str, Any], ctx: Context) -> Plan:
        try:
            target_type, record = _record(values, ctx)
        except RowError as exc:
            ctx.error(exc.field, str(exc))
            return Plan()
        return Plan(
            action="update",
            effects=[("crm.tag", "create")] * len(values.get("tags") or []),
            target_type=target_type,
            target_id=str(record.pk),
        )

    def apply(self, values: dict[str, Any], ctx: Context) -> Outcome:
        target_type, record = _record(values, ctx)
        created = apply_tags(target_type, record, values["tags"])
        return Outcome(
            action="update" if created else "skip",
            target_type=target_type,
            target_id=str(record.pk),
            created=created,
        )


@register
class NoteImporter(Importer):
    key = "notes"
    label = _l("Notes")
    description = _l("Notes on records, kept with their original date.")
    permissions = ("crm.note.create",)
    upsert_keys = ("none",)
    default_upsert = "none"
    fields = [
        *RECORD_FIELDS,
        FieldSpec(
            "body",
            _l("Note"),
            required=True,
            synonyms=("note", "notes", "body", "text", "comment"),
        ),
        FieldSpec("date", _l("Date"), "date", synonyms=("date", "created", "written on")),
        FieldSpec("author", _l("Written by"), synonyms=("author", "by", "created by")),
        FieldSpec("pinned", _l("Pinned"), "bool", synonyms=("pinned",)),
    ]
    example = {
        "record_type": "student",
        "record_name": "Tom Smith",
        "body": "Prefers afternoon lessons.",
        "date": "2026-05-04",
    }

    def check(self, values: dict[str, Any], ctx: Context) -> Plan:
        try:
            target_type, record = _record(values, ctx)
        except RowError as exc:
            ctx.error(exc.field, str(exc))
            return Plan()
        return Plan(
            effects=[("crm.note", "create")], target_type=target_type, target_id=str(record.pk)
        )

    def apply(self, values: dict[str, Any], ctx: Context) -> Outcome:
        from django.utils.html import escape

        from tutortrack.crm import services as crm

        target_type, record = _record(values, ctx)
        prefix = [values["date"].isoformat()] if values.get("date") else []
        if values.get("author"):
            prefix.append(str(values["author"]))
        body = escape(values["body"]).replace("\n", "<br>")
        if prefix:
            body = f"<p><em>{escape(' · '.join(prefix))}</em></p><p>{body}</p>"
        note = crm.create_note(
            target_type=target_type,
            target_id=str(record.pk),
            body=body,
            pinned=bool(values.get("pinned")),
        )
        return Outcome(
            action="create",
            target_type=target_type,
            target_id=str(record.pk),
            created=[ref(note)],
        )


@register
class EnquiryImporter(Importer):
    """Open enquiries carried over to the pipeline. They don't send acknowledgements or
    start follow-up timers (source ``import``)."""

    key = "enquiries"
    label = _l("Enquiries")
    description = _l("Open leads, added to the first stage of your pipeline.")
    permissions = ("leads.enquiry.create",)
    target_type = "leads.enquiry"
    upsert_keys = ("external_id", "none")
    default_upsert = "external_id"
    fields = [
        FieldSpec("external_id", _l("Enquiry ID"), synonyms=("enquiry id", "lead id", "id")),
        FieldSpec(
            "first_name",
            _l("First name"),
            required=True,
            synonyms=("first name", "parent first name", "contact first name"),
        ),
        FieldSpec("last_name", _l("Last name"), synonyms=("last name", "surname")),
        FieldSpec("email", _l("Email"), "email", synonyms=("email", "email address")),
        FieldSpec("phone", _l("Phone"), synonyms=("phone", "mobile", "telephone")),
        FieldSpec(
            "student_first_name",
            _l("Student first name"),
            synonyms=("student", "student first name", "child"),
        ),
        FieldSpec("student_last_name", _l("Student last name"), synonyms=("student last name",)),
        FieldSpec(
            "subjects",
            _l("Subjects (Subject: Level; ...)"),
            "list",
            synonyms=("subjects", "subject"),
        ),
        FieldSpec("notes", _l("Notes"), synonyms=("notes", "message", "details")),
        FieldSpec(
            "source_detail",
            _l("Where it came from"),
            synonyms=("source", "lead source", "channel"),
        ),
        FieldSpec(
            "received_on", _l("Received on"), "date", synonyms=("date", "received", "created")
        ),
    ]
    example = {
        "first_name": "Sam",
        "email": "sam@example.com",
        "student_first_name": "Ava",
        "subjects": "English: KS3",
        "notes": "Wants weekly lessons.",
    }

    def check(self, values: dict[str, Any], ctx: Context) -> Plan:
        if not values.get("email") and not values.get("phone"):
            ctx.error("email", _("Give an email address or phone number."))
        if values.get("external_id"):
            if ctx.claim("enquiry", values["external_id"]):
                ctx.error("external_id", _("This enquiry id appears earlier in the file."))
            target = refs.ref_for(ctx, "leads.enquiry", values["external_id"])
            if target and ctx.upsert_key != "none":
                ctx.warn("external_id", _("Already imported; skipped."))
                return Plan(action="skip", target_type="leads.enquiry", target_id=target)
        effects = [("leads.enquiry", "create")]
        if not (values.get("email") and refs.find_client(ctx, {"client_email": values["email"]})):
            effects.insert(0, ("people.client", "create"))
        return Plan(effects=effects)

    def apply(self, values: dict[str, Any], ctx: Context) -> Outcome:
        from tutortrack.leads import services as leads
        from tutortrack.leads.models import Enquiry

        ext = values.get("external_id")
        if ext and ctx.upsert_key != "none" and refs.ref_for(ctx, "leads.enquiry", ext):
            return Outcome(action="skip")
        existing_client = (
            refs.find_client(ctx, {"client_email": values["email"]})
            if values.get("email")
            else None
        )
        subjects = []
        for item in values.get("subjects") or []:
            subject, _sep, level = str(item).partition(":")
            subjects.append({"subject": subject.strip(), "level": level.strip()})
        students = []
        if values.get("student_first_name"):
            students.append(
                {
                    "first_name": values["student_first_name"],
                    "last_name": values.get("student_last_name") or values.get("last_name") or "",
                    "subjects": subjects,
                }
            )
        notes = values.get("notes") or ""
        if values.get("received_on"):
            notes = _("Received %(date)s.") % {"date": values["received_on"].isoformat()} + (
                f"\n{notes}" if notes else ""
            )
        enquiry = leads.create_enquiry(
            contact={k: values.get(k) or "" for k in ("first_name", "last_name", "email", "phone")},
            students=students,
            source=Enquiry.Source.IMPORT,
            source_detail=values.get("source_detail") or "",
            subjects=subjects,
            notes=notes,
        )
        out = Outcome(action="create", target_type="leads.enquiry", target_id=str(enquiry.pk))
        if existing_client is None:
            out.created.append(ref(enquiry.client))
            out.created += [ref(s) for s in enquiry.students.all()]
            if enquiry.contact_id:
                out.created.append(ref(enquiry.contact))
        out.created.append(ref(enquiry))
        if values.get("external_id"):
            out.created.append(refs.remember(ctx, "leads.enquiry", values["external_id"], enquiry))
        return out


@register
class AvailabilityImporter(Importer):
    """One row per weekly window; windows are added to the tutor's current availability."""

    key = "availability"
    label = _l("Tutor availability")
    description = _l("Weekly windows when each tutor can teach.")
    permissions = ("scheduling.availability.manage_others",)
    target_type = "people.tutor"
    upsert_keys = ("none",)
    default_upsert = "none"
    fields = [
        *TUTOR_FIELDS,
        FieldSpec(
            "weekday",
            _l("Day"),
            "weekday",
            required=True,
            synonyms=("day", "weekday", "day of week"),
        ),
        FieldSpec(
            "start_time",
            _l("From"),
            "time",
            required=True,
            synonyms=("start", "from", "start time"),
        ),
        FieldSpec(
            "end_time",
            _l("Until"),
            "time",
            required=True,
            synonyms=("end", "to", "until", "end time"),
        ),
        FieldSpec(
            "mode",
            _l("Online or in person"),
            "choice",
            choices=("any", "online", "in_person"),
            synonyms=("mode", "delivery"),
        ),
    ]
    example = {
        "tutor_email": "alex@example.com",
        "weekday": "Monday",
        "start_time": "15:00",
        "end_time": "19:00",
    }

    def check(self, values: dict[str, Any], ctx: Context) -> Plan:
        tutor = refs.find_tutor(ctx, values)
        if tutor is None:
            ctx.error("tutor_email", not_found(_("Tutor")))
            return Plan()
        start, end = values.get("start_time"), values.get("end_time")
        if isinstance(start, time) and isinstance(end, time) and end <= start:
            ctx.error("end_time", _("The window ends before it starts."))
        return Plan(
            action="update",
            effects=[("scheduling.availability", "create")],
            target_type="people.tutor",
            target_id=str(tutor.pk),
        )

    def apply(self, values: dict[str, Any], ctx: Context) -> Outcome:
        from tutortrack.scheduling import services as scheduling

        tutor = refs.find_tutor(ctx, values)
        if tutor is None:
            raise RowError(not_found(_("Tutor")), "tutor_email")
        window = {
            "weekday": values["weekday"],
            "start_time": values["start_time"],
            "end_time": values["end_time"],
            "mode": values.get("mode") or "any",
        }
        added = scheduling.add_availability_window(tutor, window, timezone=ctx.timezone)
        out = Outcome(
            action="update" if added else "skip",
            target_type="people.tutor",
            target_id=str(tutor.pk),
        )
        if added:
            out.created.append(
                {
                    "type": "scheduling.availabilitywindow",
                    "tutor": str(tutor.pk),
                    "weekday": window["weekday"],
                    "start_time": window["start_time"].strftime("%H:%M"),
                    "end_time": window["end_time"].strftime("%H:%M"),
                    "id": str(tutor.pk),
                }
            )
        return out
