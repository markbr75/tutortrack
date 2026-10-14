"""FR-31-8 Content writing helpers: broadcasts (E13), tutor bios for public profiles (E24,
which still go through profile approval), website page copy (E24) and job adverts (E18).
Drafts are returned to the editor; nothing is saved here."""

from __future__ import annotations

from typing import Any

from django.utils.translation import gettext as _

from tutortrack.core.exceptions import BusinessRuleViolation, PermissionDenied
from tutortrack.core.permissions import has_perm

from .. import engine, prompts
from ..redaction import Redactor
from . import quoted, scoped_get

KINDS: dict[str, str] = {
    "broadcast": "comms.broadcast.send",
    "bio": "sites.profile.edit",
    "page": "sites.site.manage",
    "job_ad": "recruitment.pipeline.manage",
}
MAX_BRIEF = 4000


def _organisation() -> dict[str, str]:
    from tutortrack.core.context import require_organisation_id
    from tutortrack.tenancy.models import Organisation

    org = Organisation.objects.filter(pk=require_organisation_id()).first()
    return {"name": org.name if org else "", "country": getattr(org, "country", "") or ""}


def _tutor_facts(user: Any, tutor_id: Any, redactor: Redactor) -> list[str]:
    from tutortrack.people.models import TutorProfile, TutorSubject

    tutor = scoped_get(user, TutorProfile, "sites.profile.edit", tutor_id)
    redactor.person(
        tutor.full_name, kind="TUTOR", first_name=tutor.first_name, last_name=tutor.last_name
    )
    subjects = [
        f"{s.subject} {s.level}".strip()
        for s in TutorSubject.objects.filter(
            tutor=tutor, competency=TutorSubject.Competency.APPROVED
        )[:20]
    ]
    modes = [
        m
        for m, on in (("online", tutor.delivers_online), ("in person", tutor.delivers_in_person))
        if on
    ]
    return [
        f"Tutor: {tutor.full_name}",
        f"Headline: {tutor.headline or '-'}",
        f"Approved subjects: {', '.join(subjects) or '-'}",
        f"Languages: {', '.join(str(lang) for lang in tutor.languages or []) or '-'}",
        f"Years of experience: {tutor.years_experience or '-'}",
        f"Teaches: {', '.join(modes) or '-'}",
        "Current public bio:",
        quoted(tutor.bio_public[:3000]),
    ]


def write(
    user: Any,
    *,
    kind: str,
    brief: str,
    channel: str = "email",
    title: str = "",
    tutor_id: Any = None,
    subjects: list[str] | None = None,
    location: str = "",
) -> dict[str, Any]:
    codename = KINDS.get(kind)
    if codename is None:
        raise BusinessRuleViolation(_("Unknown kind of content."))
    if not has_perm(user, codename):
        raise PermissionDenied()
    redactor = Redactor()
    org = _organisation()
    lines = [f"Kind: {kind}", f"Business: {org['name']}"]
    if kind == "broadcast":
        lines.append(
            f"Channel: {channel} ("
            + (
                "short text message, under 300 characters, no subject"
                if channel == "sms"
                else "email"
            )
            + ")"
        )
    if kind == "bio":
        if not tutor_id:
            raise BusinessRuleViolation(
                _("Choose the tutor."), extra={"errors": {"tutor": [_("Required.")]}}
            )
        lines += _tutor_facts(user, tutor_id, redactor)
    if title:
        lines.append(f"Working title: {title[:200]}")
    if subjects:
        lines.append(f"Subjects: {', '.join(str(s)[:100] for s in subjects[:20])}")
    if location:
        lines.append(f"Location: {location[:150]}")
    lines += ["", "Brief:", quoted((brief or "")[:MAX_BRIEF])]
    result = engine.run(prompts.CONTENT, user=user, content="\n".join(lines), redactor=redactor)
    data = result.data or {}
    out: dict[str, Any] = {
        "request": str(result.log.pk),
        "kind": kind,
        "title": str(data.get("title") or ""),
        "subject": str(data.get("subject") or ""),
        "body": str(data.get("body") or ""),
        "meta_description": str(data.get("meta_description") or "")[:300],
        "warnings": [],
    }
    if kind == "broadcast":
        out["warnings"] = _check_merge_fields(out["subject"], out["body"])
    return out


def _check_merge_fields(subject: str, body: str) -> list[str]:
    """A draft broadcast must render with the broadcast template engine (E13)."""
    from tutortrack.comms import render

    context = {"organisation": {"name": "Org"}, "recipient": {"name": "A B", "first_name": "A"}}
    try:
        render.render(subject, context)
        render.render(body, context)
    except render.TemplateInvalid:
        return [_("The draft has a merge field the editor can't use; check the {{ }} parts.")]
    return []
