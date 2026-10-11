"""Outbox subscribers (E24): drive ``CustomDomainWorkflow`` and keep the CORS origin cache
fresh. Idempotent: workflow starts are keyed by id, signals to finished workflows are
ignored, cache invalidation is harmless to repeat."""

from __future__ import annotations

from tutortrack.core.events import EventEnvelope, subscribe
from tutortrack.core.workflows import bridge

from . import cors
from .processes import CustomDomainWorkflow, DomainInput, domain_workflow_id


def _wid(e: EventEnvelope) -> str:
    return domain_workflow_id(e.organisation_id, e.subject["id"])


bridge.on(
    "custom_domain.added",
    start=CustomDomainWorkflow,
    id=_wid,
    input=lambda e: DomainInput(
        organisation_id=str(e.organisation_id),
        domain_id=str(e.subject["id"]),
        hostname=str(e.data["hostname"]),
    ),
    subject=lambda e: ("custom_domain", e.subject["id"]),
)
bridge.on("custom_domain.check_requested", signal="check_now", id=_wid)
bridge.on("custom_domain.removed", signal="remove", id=_wid)


@subscribe(
    "widget.saved",
    "custom_domain.activated",
    "custom_domain.verified",
    "custom_domain.removed",
    name="sites.cors_cache",
)
def refresh_cors_origins(event: EventEnvelope) -> None:
    cors.forget(event.organisation_id)
