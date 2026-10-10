"""Domain events published by the developer platform (E27).

None of these are offered as webhook event types (see ``catalogue.PUBLIC_AGGREGATES``), so
webhook activity can never trigger more webhooks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from tutortrack.core.events import DomainEvent


@dataclass(frozen=True, kw_only=True)
class ApiKeyCreated(DomainEvent):
    event_type: ClassVar[str] = "api_key.created"
    subject_type: ClassVar[str] = "api_key"
    name: str
    scopes: list[str]
    rotated_from: str | None = None


@dataclass(frozen=True, kw_only=True)
class ApiKeyRevoked(DomainEvent):
    event_type: ClassVar[str] = "api_key.revoked"
    subject_type: ClassVar[str] = "api_key"
    name: str


@dataclass(frozen=True, kw_only=True)
class OAuthAppConnected(DomainEvent):
    event_type: ClassVar[str] = "oauth_app.connected"
    subject_type: ClassVar[str] = "oauth_grant"
    application_id: str
    application: str
    scopes: list[str]


@dataclass(frozen=True, kw_only=True)
class OAuthAppDisconnected(DomainEvent):
    event_type: ClassVar[str] = "oauth_app.disconnected"
    subject_type: ClassVar[str] = "oauth_grant"
    application_id: str
    application: str


@dataclass(frozen=True, kw_only=True)
class WebhookEndpointCreated(DomainEvent):
    event_type: ClassVar[str] = "webhook_endpoint.created"
    subject_type: ClassVar[str] = "webhook_endpoint"
    url: str
    events: list[str]


@dataclass(frozen=True, kw_only=True)
class WebhookEndpointDisabled(DomainEvent):
    """An endpoint failed continuously for the configured period and was switched off."""

    event_type: ClassVar[str] = "webhook_endpoint.disabled"
    subject_type: ClassVar[str] = "webhook_endpoint"
    url: str
    failing_since: str


@dataclass(frozen=True, kw_only=True)
class WebhookDeliveryFailed(DomainEvent):
    """A delivery used up its retries (about 72 hours)."""

    event_type: ClassVar[str] = "webhook_delivery.failed"
    subject_type: ClassVar[str] = "webhook_delivery"
    endpoint_id: str
    event_type_name: str
    attempts: int


@dataclass(frozen=True, kw_only=True)
class SandboxCreated(DomainEvent):
    event_type: ClassVar[str] = "sandbox.created"
    subject_type: ClassVar[str] = "sandbox"
    sandbox_organisation_id: str
    slug: str
