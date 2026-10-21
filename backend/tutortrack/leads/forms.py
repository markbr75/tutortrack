"""Form schemas: validation of the definition and of submissions, and mapping answers onto
the client, contact, students and enquiry (FR-17-1).

A field's ``maps_to`` is one of ``MAPPINGS``; unmapped answers are kept on the submission
and summarised in the enquiry notes. A ``students`` field collects several students
(``[{"first_name", "last_name", "subjects"}]``). ``show_if = {"field": key, "equals": v}``
hides a field (and its requirement) unless another answer matches.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from django.utils.translation import gettext as _

from tutortrack.core.exceptions import BusinessRuleViolation

FIELD_TYPES = (
    "text",
    "textarea",
    "email",
    "phone",
    "number",
    "date",
    "select",
    "multiselect",
    "checkbox",
    "consent",
    "subjects",
    "availability",
    "postcode",
    "students",
    "file",
    "referees",
)
MAPPINGS = (
    "contact.first_name",
    "contact.last_name",
    "contact.email",
    "contact.phone",
    "client.postcode",
    "student.first_name",
    "student.last_name",
    "student.date_of_birth",
    "student.subjects",
    "student.school",
    "students",
    "enquiry.subjects",
    "enquiry.notes",
    "enquiry.budget",
    "enquiry.expected_start",
    "enquiry.availability",
    "enquiry.how_heard",
)
# Tutor application forms (E18 FR-18-1) map onto the applicant instead.
APPLICATION_MAPPINGS = (
    "applicant.first_name",
    "applicant.last_name",
    "applicant.email",
    "applicant.phone",
    "applicant.postcode",
    "applicant.subjects",
    "applicant.qualifications",
    "applicant.experience",
    "applicant.right_to_work",
    "applicant.video_url",
    "applicant.cv",
    "applicant.video",
    "referees",
)
FILE_MAPPINGS = {"applicant.cv": "cv", "applicant.video": "video"}
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def fields_of(schema: dict[str, Any]) -> list[dict[str, Any]]:
    return [f for step in schema.get("steps", []) for f in step.get("fields", [])]


def clean_schema(schema: Any, form_type: str = "enquiry") -> dict[str, Any]:
    from tutortrack.core.storage.public import KINDS

    if not isinstance(schema, dict) or not isinstance(schema.get("steps"), list):
        raise BusinessRuleViolation(_("A form needs at least one step."))
    allowed = (*MAPPINGS, *APPLICATION_MAPPINGS) if form_type == "application" else MAPPINGS
    keys: set[str] = set()
    for step in schema["steps"]:
        for f in step.get("fields", []):
            key = str(f.get("key", ""))
            if not re.fullmatch(r"[a-z][a-z0-9_]{0,39}", key) or key in keys:
                raise BusinessRuleViolation(_("Field keys must be unique, lower-case words."))
            keys.add(key)
            if f.get("type") not in FIELD_TYPES:
                raise BusinessRuleViolation(_("Unknown field type: %(t)s") % {"t": f.get("type")})
            if f.get("consent_key") and not re.fullmatch(r"[a-z0-9-]{1,60}", str(f["consent_key"])):
                raise BusinessRuleViolation(_("Consent fields name a consent type by its key."))
            if f.get("maps_to") and f["maps_to"] not in allowed:
                raise BusinessRuleViolation(_("Unknown mapping: %(m)s") % {"m": f["maps_to"]})
            if f.get("type") == "file":
                kind = f.setdefault("file_kind", "document")
                if kind not in KINDS:
                    raise BusinessRuleViolation(_("Unknown kind of file: %(k)s") % {"k": kind})
                wanted = FILE_MAPPINGS.get(str(f.get("maps_to", "")))
                if wanted and (kind != wanted or f.get("multiple")):
                    raise BusinessRuleViolation(
                        _("Map a single %(kind)s upload onto %(target)s.")
                        % {"kind": wanted, "target": f["maps_to"]}
                    )
            elif f.get("maps_to") in FILE_MAPPINGS:
                raise BusinessRuleViolation(_("Only a file upload field can hold a file."))
    mapped = {f.get("maps_to") for f in fields_of(schema)}
    if not mapped & {"contact.email", "contact.phone", "applicant.email"}:
        raise BusinessRuleViolation(_("Ask for an email address or phone number."))
    return schema


def _visible(f: dict[str, Any], data: dict[str, Any]) -> bool:
    rule = f.get("show_if")
    if not rule:
        return True
    return data.get(rule.get("field")) == rule.get("equals")


def clean_submission(schema: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    """Required, typed and only-known answers; field errors keyed by field key."""
    errors: dict[str, list[str]] = {}
    out: dict[str, Any] = {}
    for f in fields_of(schema):
        key = f["key"]
        if not _visible(f, data):
            continue
        value = data.get(key)
        empty = value in (None, "", [], False)
        if empty:
            if f.get("required"):
                errors[key] = [_("Required.")]
            continue
        kind = f["type"]
        if kind == "email" and not EMAIL.match(str(value).strip()):
            errors[key] = [_("Enter a valid email address.")]
        elif kind in ("select",) and f.get("options") and value not in f["options"]:
            errors[key] = [_("Choose one of the options.")]
        elif kind == "referees":
            if not isinstance(value, list) or not all(
                isinstance(r, dict) and EMAIL.match(str(r.get("email", "")).strip()) for r in value
            ):
                errors[key] = [_("Give each referee's name and email address.")]
        elif kind == "file":
            from tutortrack.core.storage.public import MAX_FILES_PER_FIELD, tokens_of

            tokens = tokens_of(value)
            limit = MAX_FILES_PER_FIELD if f.get("multiple") else 1
            if not tokens:
                errors[key] = [_("Upload the file again.")]
            elif len(tokens) > limit:
                errors[key] = [_("Add at most %(n)s files.") % {"n": limit}]
            else:
                value = tokens
        elif kind == "students":
            if not isinstance(value, list) or not all(isinstance(s, dict) for s in value):
                errors[key] = [_("Add each student.")]
            elif any(not str(s.get("first_name", "")).strip() for s in value):
                errors[key] = [_("Every student needs a first name.")]
        out[key] = value.strip() if isinstance(value, str) else value
    if errors:
        raise BusinessRuleViolation(_("Check the form."), extra={"errors": errors})
    return out


@dataclass
class Mapped:
    contact: dict[str, Any] = field(default_factory=dict)
    client: dict[str, Any] = field(default_factory=dict)
    students: list[dict[str, Any]] = field(default_factory=list)
    enquiry: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)
    files: dict[str, list[str]] = field(default_factory=dict)  # field key -> upload tokens


def map_answers(schema: dict[str, Any], answers: dict[str, Any]) -> Mapped:
    mapped = Mapped()
    first_student: dict[str, Any] = {}
    labels = {f["key"]: f.get("label", f["key"]) for f in fields_of(schema)}
    for f in fields_of(schema):
        key = f["key"]
        if key not in answers:
            continue
        value = answers[key]
        target = f.get("maps_to", "")
        if f.get("type") == "file":
            mapped.files[key] = list(value)
        elif target == "students":
            mapped.students += [
                {
                    "first_name": str(s.get("first_name", "")).strip()[:100],
                    "last_name": str(s.get("last_name", "")).strip()[:100],
                    "subjects": _subjects(s.get("subjects")),
                }
                for s in value
            ]
        elif target.startswith("contact."):
            mapped.contact[target.split(".", 1)[1]] = str(value)[:200]
        elif target == "client.postcode":
            mapped.client["postcode"] = str(value)[:20]
        elif target.startswith("student."):
            name = target.split(".", 1)[1]
            first_student[name] = _subjects(value) if name == "subjects" else str(value)[:100]
        elif target.startswith("enquiry."):
            mapped.enquiry[target.split(".", 1)[1]] = value
        else:
            mapped.extra[labels.get(key, key)] = value
    if first_student.get("first_name"):
        mapped.students.insert(0, first_student)
    return mapped


def _subjects(value: Any) -> list[dict[str, str]]:
    if isinstance(value, str):
        value = [v.strip() for v in value.split(",") if v.strip()]
    out = []
    for item in value or []:
        if isinstance(item, dict):
            out.append(
                {
                    "subject": str(item.get("subject", ""))[:100],
                    "level": str(item.get("level", ""))[:100],
                }
            )
        else:
            out.append({"subject": str(item)[:100], "level": ""})
    return [s for s in out if s["subject"]]


# --- file uploads (G5a) ----------------------------------------------------------------------


def upload_kinds_for_form(slug: str) -> set[str] | None:
    """Upload context ``form``: a published enquiry or registration form with file fields."""
    from tutortrack.core.storage.public import file_kinds

    from .models import Form

    form = Form.objects.filter(slug=slug, published=True).exclude(type=Form.Type.APPLICATION)
    found = form.first()
    return file_kinds(fields_of(found.schema)) if found else None


def claim_files(
    schema: dict[str, Any], files: dict[str, list[str]], *, owner: Any, context: str
) -> dict[str, list[Any]]:
    """Attach each file field's uploads to ``owner``; returns the stored files per field."""
    from tutortrack.core.storage.public import claim

    by_key = {f["key"]: f for f in fields_of(schema)}
    out: dict[str, list[Any]] = {}
    for key, tokens in files.items():
        f = by_key.get(key)
        if f is None or not tokens:
            continue
        try:
            out[key] = claim(
                tokens, owner=owner, kinds=[f.get("file_kind") or "document"], context=context
            )
        except BusinessRuleViolation as exc:
            raise BusinessRuleViolation(
                _("Check the form."), extra={"errors": {key: [str(exc.detail)]}}
            ) from exc
    return out


def file_answers(stored: dict[str, list[Any]]) -> dict[str, list[dict[str, str]]]:
    """What the submission keeps instead of the upload tokens."""
    return {
        key: [{"file": str(s.pk), "filename": s.filename} for s in files]
        for key, files in stored.items()
    }
