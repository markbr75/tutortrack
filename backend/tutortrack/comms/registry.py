"""The notification type registry (FR-13-2). Types are defined in code (``catalogue.py``);
organisations choose per type whether it is sent, on which channels and (reminders) when."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

CATEGORIES = ("scheduling", "reports", "billing", "account", "staff")


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

    def available(self) -> set[str]:
        out = set()
        if self.email:
            out.add("email")
        if self.phone:
            out.add("sms")
        if self.user_id:
            out.add("in_app")
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


_types: dict[str, NotificationType] = {}


def register(t: NotificationType) -> NotificationType:
    _types[t.key] = t
    return t


def get(key: str) -> NotificationType:
    try:
        return _types[key]
    except KeyError:
        raise KeyError(f"Unknown notification type {key!r}") from None


def all_types() -> list[NotificationType]:
    return list(_types.values())
