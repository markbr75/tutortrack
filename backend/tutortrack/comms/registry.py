"""The notification type registry (FR-13-2). Types are defined in code (``catalogue.py``);
organisations choose per type whether it is sent, on which channels and (reminders) when."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any

CATEGORIES = ("scheduling", "reports", "billing", "account", "staff", "messages", "marketing")


@dataclass(frozen=True)
class Recipient:
    kind: str  # contact | tutor | user
    id: str
    name: str
    first_name: str
    email: str = ""
    phone: str = ""
    user_id: str | None = None
    target: tuple[str, str] = ("", "")  # the record whose timeline shows the message
    # G4 (FR-13-3): the person's language picks a per-locale template override.
    locale: str = ""

    def available(self) -> set[str]:
        out = set()
        if self.email:
            out.add("email")
        if self.phone:
            out.update({"sms", "whatsapp"})  # WhatsApp also needs the person's opt-in
        if self.user_id:
            out.update({"in_app", "push"})  # push needs a subscribed device (checked later)
        return out


@dataclass(frozen=True)
class Delivery:
    recipient: Recipient
    context: dict[str, Any]


Resolver = Callable[[Any], list[Delivery]]


@dataclass(frozen=True)
class NotificationType:
    key: str
    label: str
    category: str
    audience: str  # client | tutor | staff
    channels: tuple[str, ...]
    default_channels: tuple[str, ...]
    resolve: Resolver
    load: Callable[[str], Any]
    related_type: str
    variables: tuple[str, ...] = ()
    sample: dict[str, Any] = field(default_factory=dict)
    default_enabled: bool = True
    transactional: bool = False  # recipients can switch channel but not opt out
    default_timing: tuple[int, ...] = ()  # minutes before (reminders)
    attachments: Callable[[Any], list[tuple[str, bytes, str]]] | None = None
    link: Callable[[Any], str] | None = None
    # Internal types (broadcasts, inbox replies) send through the pipeline but aren't
    # configurable notifications: not listed in settings or preferences.
    hidden: bool = False
    # G4: account emails (password reset, verification...) can be edited but not switched
    # off: the sign-in flows depend on them.
    locked: bool = False


_types: dict[str, NotificationType] = {}


# Web Push (E16-T09) goes wherever an in-app notification can: it reaches the same signed-in
# user on their phone. These types (FR-16-9: lesson changes, job offers, report reminders,
# pay) push by default; organisations switch push on or off per type like any channel.
PUSH_BY_DEFAULT = frozenset(
    {
        "lesson_changed",
        "lesson_cancelled",
        "job_offer",
        "cover_request",
        "report_due",
        "report_overdue",
        "report_comment",
        "payout_paid",
        # G4 (FR-16-9): messages from families and the office reach the tutor's phone.
        "conversation_message_tutor",
        "conversation_message_family",
        "inbox_new_message",
    }
)


def register(t: NotificationType) -> NotificationType:
    if "sms" in t.channels and "whatsapp" not in t.channels and not t.hidden:
        # E13-T12: anything that can be texted can go by WhatsApp (off by default; needs an
        # approved template mapped to the type and the recipient's opt-in).
        t = replace(t, channels=(*t.channels, "whatsapp"))
    if "in_app" in t.channels and "push" not in t.channels:
        defaults = t.default_channels
        if t.key in PUSH_BY_DEFAULT:
            defaults = (*defaults, "push")
        t = replace(t, channels=(*t.channels, "push"), default_channels=defaults)
    _types[t.key] = t
    return t


def get(key: str) -> NotificationType:
    try:
        return _types[key]
    except KeyError:
        raise KeyError(f"Unknown notification type {key!r}") from None


def all_types() -> list[NotificationType]:
    return list(_types.values())


def visible_types() -> list[NotificationType]:
    """The configurable notification types (settings screen, preferences)."""
    return [t for t in _types.values() if not t.hidden]
