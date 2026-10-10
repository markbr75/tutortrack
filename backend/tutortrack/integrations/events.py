"""Domain events published by the integration framework (E22 §5)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

from tutortrack.core.events import DomainEvent


@dataclass(frozen=True, kw_only=True)
class _ConnectionEvent(DomainEvent):
    subject_type: ClassVar[str] = "integration_connection"
    provider: str
    level: str
    user_id: str | None = None
    capabilities: list[str] = field(default_factory=list)


@dataclass(frozen=True, kw_only=True)
class IntegrationConnected(_ConnectionEvent):
    """Starts ``CalendarConnectionWorkflow`` for calendar providers; ``reconnected`` when
    an existing connection was re-authorised (signals the running workflow)."""

    event_type: ClassVar[str] = "integration.connected"
    reconnected: bool = False


@dataclass(frozen=True, kw_only=True)
class IntegrationDisconnected(_ConnectionEvent):
    """Signals ``disconnect`` to the connection's workflow."""

    event_type: ClassVar[str] = "integration.disconnected"


@dataclass(frozen=True, kw_only=True)
class IntegrationError(_ConnectionEvent):
    event_type: ClassVar[str] = "integration.error"
    status: str = "error"
    error: str = ""
