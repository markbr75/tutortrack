"""Domain events published by the success app (E30 Part 2). Internal: ids only, never
offered as webhook event types (their aggregates aren't public, see developer.catalogue)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from tutortrack.core.events import DomainEvent


@dataclass(frozen=True, kw_only=True)
class SetupItemCompleted(DomainEvent):
    event_type: ClassVar[str] = "setup_checklist.item_completed"
    subject_type: ClassVar[str] = "setup_checklist"
    key: str
    source: str


@dataclass(frozen=True, kw_only=True)
class SetupChecklistCompleted(DomainEvent):
    event_type: ClassVar[str] = "setup_checklist.completed"
    subject_type: ClassVar[str] = "setup_checklist"


@dataclass(frozen=True, kw_only=True)
class SurveyAnswered(DomainEvent):
    event_type: ClassVar[str] = "survey.answered"
    subject_type: ClassVar[str] = "survey_response"
    kind: str
    score: int | None


@dataclass(frozen=True, kw_only=True)
class SupportConversationOpened(DomainEvent):
    event_type: ClassVar[str] = "support_conversation.opened"
    subject_type: ClassVar[str] = "support_conversation"


@dataclass(frozen=True, kw_only=True)
class SupportConversationReplied(DomainEvent):
    event_type: ClassVar[str] = "support_conversation.replied"
    subject_type: ClassVar[str] = "support_conversation"
    from_support: bool


@dataclass(frozen=True, kw_only=True)
class SupportConversationClosed(DomainEvent):
    event_type: ClassVar[str] = "support_conversation.closed"
    subject_type: ClassVar[str] = "support_conversation"
