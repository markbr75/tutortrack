"""Domain events published by the AI assistant (E31)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from tutortrack.core.events import DomainEvent


@dataclass(frozen=True, kw_only=True)
class AIFeatureUpdated(DomainEvent):
    """An organisation turned an AI feature on or off, or changed its tone."""

    event_type: ClassVar[str] = "ai_feature.updated"
    subject_type: ClassVar[str] = "ai_feature_setting"
    feature: str
    enabled: bool


@dataclass(frozen=True, kw_only=True)
class AIProposalExecuted(DomainEvent):
    """A person confirmed an AI-proposed action and it ran (human in the loop)."""

    event_type: ClassVar[str] = "ai_proposal.executed"
    subject_type: ClassVar[str] = "ai_proposal"
    action: str
    feature: str


@dataclass(frozen=True, kw_only=True)
class ThreadIntentClassified(DomainEvent):
    """The AI classified an inbox conversation (automations can route on ``intent``)."""

    event_type: ClassVar[str] = "thread.intent_classified"
    subject_type: ClassVar[str] = "thread"
    intent: str
    confidence: int
