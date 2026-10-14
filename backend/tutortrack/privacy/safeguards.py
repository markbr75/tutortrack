"""Messaging safeguards (E29-T09, FR-29-6) and the children's marketing block (FR-29-7).

Registered as a comms pre-send hook (``comms.hooks``), so every message the platform sends
passes through ``check_outgoing``:

* marketing messages to under-18s are blocked (AADC defaults);
* for messages people write (``sender_user_id`` set, e.g. the inbox):
  - tutors can't message a student under 18 directly (``safeguarding.block_tutor_student_direct``),
  - a parent must be on any conversation with a student under 18
    (``safeguarding.require_parent_on_threads``),
  - personal contact details (phone numbers, emails, social handles) are blocked or flagged
    (``safeguarding.contact_details``),
  - flagged words (``safeguarding.flag_keywords``) create a flag for DSL review.

Text that is already shared (lesson report comments) is screened after the fact by
``screen_text`` and flagged, never blocked.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from django.db import transaction

from tutortrack.comms.hooks import OutgoingMessage, register_pre_send
from tutortrack.core import audit
from tutortrack.core.events import publish
from tutortrack.tenancy.settings_service import get_setting

from . import children, notifications
from .events import SafeguardingMessageFlagged
from .models import SafeguardingFlag

PHONE = re.compile(r"(?<!\w)\+?\d[\d\s().-]{6,}\d(?!\w)")
MIN_PHONE_DIGITS = 10
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
HANDLE = re.compile(
    r"(?:(?<!\w)@[A-Za-z0-9_.]{3,}|\b(?:snap(?:chat)?|insta(?:gram)?|whats\s?app|telegram|"
    r"discord|tiktok|kik)\b)",
    re.IGNORECASE,
)
MARKETING = "marketing"


@dataclass
class Screening:
    contact_details: list[str] = field(default_factory=list)  # phone | email | social
    keywords: list[str] = field(default_factory=list)

    @property
    def flagged(self) -> bool:
        return bool(self.contact_details or self.keywords)


def keywords() -> list[str]:
    raw = str(get_setting("safeguarding.flag_keywords") or "")
    return [k.strip().lower() for k in raw.split(",") if k.strip()]


def screen(text: str) -> Screening:
    result = Screening()
    if not text:
        return result
    if any(sum(c.isdigit() for c in m.group()) >= MIN_PHONE_DIGITS for m in PHONE.finditer(text)):
        result.contact_details.append("phone")
    if EMAIL.search(text):
        result.contact_details.append("email")
    if HANDLE.search(EMAIL.sub("", text)):
        result.contact_details.append("social")
    lowered = text.lower()
    result.keywords = [k for k in keywords() if re.search(rf"(?<!\w){re.escape(k)}(?!\w)", lowered)]
    return result


def _excerpt(text: str) -> str:
    return text.strip()[:500]


def record_flag(
    *,
    source_type: str,
    source_id: str,
    sender_id: str | None,
    reasons: list[str],
    found: list[str],
    excerpt: str,
    blocked: bool,
) -> SafeguardingFlag:
    """One flag per source (a message sent to several people is reviewed once)."""
    with transaction.atomic():
        if source_id:
            existing = SafeguardingFlag.objects.filter(
                source_type=source_type, source_id=source_id
            ).first()
            if existing is not None:
                return existing
        flag = SafeguardingFlag.objects.create(
            source_type=source_type,
            source_id=source_id,
            sender_id=sender_id,
            reasons=reasons,
            keywords=found,
            excerpt=_excerpt(excerpt),
            blocked=blocked,
        )
        audit.record_create(flag)
        publish(
            SafeguardingMessageFlagged(subject_id=flag.pk, source_type=source_type, blocked=blocked)
        )
        from django.utils.translation import gettext as _

        notifications.send(
            "safeguarding_alert",
            (
                _("A message was flagged for safeguarding review"),
                ", ".join(reasons),
                notifications.admin_link("/safeguarding?tab=flags"),
            ),
            key=f"flag:{flag.pk}",
        )
    return flag


def _is_tutor(user_id: str) -> bool:
    from tutortrack.identity.models import Membership

    return Membership.objects.filter(
        user_id=user_id, role=Membership.Role.TUTOR, status=Membership.Status.ACTIVE
    ).exists()


def _child_of(kind: str, ref: str) -> Any:
    """The under-18 student a recipient/participant is, if any."""
    from tutortrack.people.models import Student

    if kind == "student":
        student = Student.objects.filter(pk=ref).first()
        return student if student is not None and children.is_child(student) else None
    if kind == "user":
        return children.child_for_user(ref)
    return None


def check_outgoing(message: OutgoingMessage) -> str:
    """The comms pre-send hook: a block reason, or ``""``."""
    recipient_child = _child_of(message.recipient_kind, message.recipient_id) or (
        children.child_for_user(message.recipient_user_id)
    )
    if message.category == MARKETING and recipient_child and children.child_defaults_on():
        return "aadc:no_marketing_to_children"
    if not message.sender_user_id:
        return ""  # system notifications: templates, not people writing
    reasons: list[str] = []
    blocked = False
    participants = list(message.participants) or [(message.recipient_kind, message.recipient_id)]
    child_on_thread = any(_child_of(kind, ref) for kind, ref in participants) or recipient_child
    has_parent = any(kind == "contact" for kind, _ref in participants)
    if child_on_thread:
        if (
            get_setting("safeguarding.block_tutor_student_direct")
            and _is_tutor(message.sender_user_id)
            and not has_parent
        ):
            reasons.append("policy:tutor_student_direct")
            blocked = True
        elif get_setting("safeguarding.require_parent_on_threads") and not has_parent:
            reasons.append("policy:parent_required")
            blocked = True
    screening = screen(f"{message.subject}\n{message.body}")
    mode = get_setting("safeguarding.contact_details")
    if screening.contact_details and mode != "off":
        reasons.append("contact_details")
        blocked = blocked or mode == "block"
    if screening.keywords:
        reasons.append("keyword")
    if reasons:
        record_flag(
            source_type=message.source_type,
            source_id=message.source_id,
            sender_id=message.sender_user_id,
            reasons=reasons,
            found=[*screening.contact_details, *screening.keywords],
            excerpt=message.body,
            blocked=blocked,
        )
    return ",".join(r for r in reasons if r != "keyword") if blocked else ""


def screen_text(
    *, text: str, source_type: str, source_id: str, sender_id: str | None
) -> SafeguardingFlag | None:
    """Flag (never block) text people already shared, e.g. a lesson report comment."""
    screening = screen(text)
    mode = get_setting("safeguarding.contact_details")
    reasons = []
    if screening.contact_details and mode != "off":
        reasons.append("contact_details")
    if screening.keywords:
        reasons.append("keyword")
    if not reasons:
        return None
    return record_flag(
        source_type=source_type,
        source_id=source_id,
        sender_id=sender_id,
        reasons=reasons,
        found=[*screening.contact_details, *screening.keywords],
        excerpt=text,
        blocked=False,
    )


register_pre_send(check_outgoing)
