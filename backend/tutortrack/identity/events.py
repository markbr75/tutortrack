"""Domain events emitted by identity (docs/03-domain-model.md §5)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

from tutortrack.core.events import DomainEvent


@dataclass(frozen=True, kw_only=True)
class UserLoggedIn(DomainEvent):
    event_type: ClassVar[str] = "user.logged_in"
    subject_type: ClassVar[str] = "user"

    method: str


@dataclass(frozen=True, kw_only=True)
class UserMFAEnabled(DomainEvent):
    event_type: ClassVar[str] = "user.mfa_enabled"
    subject_type: ClassVar[str] = "user"

    method: str


@dataclass(frozen=True, kw_only=True)
class UserInvited(DomainEvent):
    event_type: ClassVar[str] = "user.invited"
    subject_type: ClassVar[str] = "invitation"

    email: str
    role: str


@dataclass(frozen=True, kw_only=True)
class UserJoined(DomainEvent):
    event_type: ClassVar[str] = "user.joined"
    subject_type: ClassVar[str] = "membership"

    user_id: str
    role: str


@dataclass(frozen=True, kw_only=True)
class MembershipRoleChanged(DomainEvent):
    event_type: ClassVar[str] = "membership.role_changed"
    subject_type: ClassVar[str] = "membership"

    user_id: str
    old_role: str
    new_role: str


@dataclass(frozen=True, kw_only=True)
class MembershipDeactivated(DomainEvent):
    event_type: ClassVar[str] = "membership.deactivated"
    subject_type: ClassVar[str] = "membership"

    user_id: str
    status: str


@dataclass(frozen=True, kw_only=True)
class ImpersonationStarted(DomainEvent):
    event_type: ClassVar[str] = "impersonation.started"
    subject_type: ClassVar[str] = "membership"

    impersonator_id: str
    target_user_id: str
    write: bool


@dataclass(frozen=True, kw_only=True)
class ImpersonationEnded(DomainEvent):
    event_type: ClassVar[str] = "impersonation.ended"
    subject_type: ClassVar[str] = "membership"

    impersonator_id: str
    target_user_id: str
    extra: dict[str, str] = field(default_factory=dict)
