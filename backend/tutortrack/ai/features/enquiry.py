"""FR-31-4 Enquiry triage: extract students, subjects, levels, availability and location
from free text (fast model, structured output), then propose next steps, a priority and a
first reply (capable model). Changes to the enquiry are a proposal the person confirms."""

from __future__ import annotations

import json
from typing import Any

from django.utils.translation import gettext as _

from tutortrack.core.exceptions import BusinessRuleViolation, DomainError, PermissionDenied
from tutortrack.core.permissions import has_perm

from .. import engine, prompts
from ..redaction import Redactor
from . import quoted, scoped_get

MAX_TEXT = 12_000


def _extract(user: Any, text: str, redactor: Redactor) -> engine.Result:
    if not text.strip():
        raise BusinessRuleViolation(
            _("Paste the enquiry text first."), extra={"errors": {"text": [_("Required.")]}}
        )
    return engine.run(
        prompts.ENQUIRY_EXTRACT,
        user=user,
        content=f"Enquiry text:\n{quoted(text[:MAX_TEXT])}",
        redactor=redactor,
    )


def extract(user: Any, text: str) -> dict[str, Any]:
    """Structured fields for the new-enquiry form (the person reviews and saves them).
    Contact details found in the text come back restored, never sent in the clear."""
    if not has_perm(user, "leads.enquiry.create"):
        raise PermissionDenied()
    result = _extract(user, text, Redactor())
    return {"request": str(result.log.pk), "extracted": result.data or {}}


def _notes_from(extracted: dict[str, Any]) -> str:
    lines = []
    if extracted.get("availability"):
        lines.append(_("Availability: %(a)s") % {"a": "; ".join(extracted["availability"])})
    location = extracted.get("location") or {}
    where = ", ".join(v for v in (location.get("area"), location.get("postcode")) if v)
    if where or location.get("mode"):
        lines.append(
            _("Location: %(w)s (%(m)s)") % {"w": where or "-", "m": location.get("mode") or "-"}
        )
    return "\n".join(lines)


def triage(user: Any, enquiry_id: Any) -> dict[str, Any]:
    from tutortrack.leads.models import Enquiry

    from .. import services

    enquiry = scoped_get(
        user, Enquiry, "leads.enquiry.edit", enquiry_id, related=("contact", "client")
    )
    redactor = Redactor()
    if enquiry.contact_id:
        contact = enquiry.contact
        redactor.person(
            f"{contact.first_name} {contact.last_name}".strip(),
            kind="CONTACT",
            first_name=contact.first_name,
            last_name=contact.last_name,
        )
    redactor.value(enquiry.client.display_name, "CLIENT")
    for student in enquiry.students.all():
        redactor.person(
            student.full_name,
            kind="STUDENT",
            first_name=student.first_name,
            last_name=student.last_name,
        )
    text = "\n\n".join(p for p in (enquiry.title, enquiry.notes) if p)
    extraction = _extract(user, text, redactor)
    extracted = extraction.data or {}
    content = "\n".join(
        [
            f"Enquiry: {enquiry.title}",
            f"Source: {enquiry.source}; status: {enquiry.status}; stage: {enquiry.stage.name}",
            f"Subjects on record: {json.dumps(enquiry.subjects or [], sort_keys=True)}",
            "",
            "Enquiry notes:",
            quoted(enquiry.notes[:MAX_TEXT]),
            "",
            "Extracted details (JSON):",
            json.dumps(redactor.redact_data(extracted), sort_keys=True),
        ]
    )
    result = engine.run(prompts.ENQUIRY_TRIAGE, user=user, content=content, redactor=redactor)
    data = result.data or {}
    params: dict[str, Any] = {"enquiry_id": str(enquiry.pk)}
    if data.get("priority") and data["priority"] != enquiry.priority:
        params["priority"] = data["priority"]
    if extracted.get("subjects") and not enquiry.subjects:
        params["subjects"] = extracted["subjects"]
    notes = _notes_from(extracted)
    if notes and notes not in enquiry.notes:
        params["notes_append"] = notes
    proposal = None
    if len(params) > 1:
        try:
            proposal = services.propose(
                user,
                action="update_enquiry",
                params=params,
                feature="enquiry",
                request=result.log,
            )
        except DomainError:
            proposal = None
    return {
        "request": str(result.log.pk),
        "extracted": extracted,
        "next_steps": [str(s) for s in data.get("next_steps") or []],
        "priority": str(data.get("priority") or ""),
        "reply_subject": str(data.get("reply_subject") or ""),
        "reply_body": str(data.get("reply_body") or ""),
        "proposal": proposal,
    }
