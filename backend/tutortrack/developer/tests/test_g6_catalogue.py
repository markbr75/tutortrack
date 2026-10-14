"""G6: the webhook catalogue offers the event types added after E27 (FR-27-3), with payload
schemas and redactions, and the marketplace reports live integration status (FR-27-5)."""

from __future__ import annotations

import pytest

from tutortrack.core.context import tenant_context
from tutortrack.core.events import EVENT_TYPES
from tutortrack.developer import catalogue, marketplace
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.integrations.models import IntegrationConnection

from .test_webhooks import envelope

pytestmark = pytest.mark.django_db

ADDED = [
    "review.submitted", "review.published", "referral.created", "commission.earned",
    "affiliate_statement.issued", "proposal.accepted", "shortlist.tutor_chosen",
    "package.purchased", "booking.confirmed", "broadcast.sent", "thread.assigned",
    "message.received", "homework.assigned", "lesson_feedback.received",
    "background_check.completed", "recording.available", "enrolment.created", "class.full",
]  # fmt: skip


def test_event_types_added_after_e27_are_offered(api):
    rows = {r["key"]: r for r in api.get("/api/v1/webhook-event-types").json()}
    for key in ADDED:
        assert key in rows, key
    review = {f["name"]: f["json_type"] for f in rows["review.submitted"]["payload_fields"]}
    assert review["rating"] == "integer"
    assert review["tutor_id"].startswith("string")


def test_never_types_are_never_offered():
    keys = set(catalogue.public_event_keys())
    for key in EVENT_TYPES:
        aggregate = key.split(".", 1)[0]
        if aggregate in catalogue.NEVER_AGGREGATES or key in catalogue.NEVER_EVENT_TYPES:
            assert key not in keys, key
    assert not any(k.startswith(("safeguarding.", "data_subject.", "consent.")) for k in keys)
    assert "thread.intent_classified" not in keys


def test_background_check_results_and_safeguarding_flags_never_leave(org):
    fields = dict(catalogue.payload_fields(EVENT_TYPES["background_check.completed"]))
    assert "result" not in fields
    assert "tutor_id" in fields
    event = envelope(
        org, "background_check.completed", ("background_check", None),
        tutor_id="t1", provider="ucheck", result="consider",
    )  # fmt: skip
    body = catalogue.build_payload(event, api_version="2026-10-01", user=None)
    assert "consider" not in str(body)
    assert body["event_data"] == {"tutor_id": "t1", "provider": "ucheck"}
    message = envelope(
        org, "message.received", ("thread_message", None),
        thread_id="th1", channel="email", author_type="contact", flagged=True,
    )  # fmt: skip
    body = catalogue.build_payload(message, api_version="2026-10-01", user=None)
    assert "flagged" not in body["event_data"]
    assert body["data"] == body["event_data"]


def test_sample_payload_lists_the_event_fields(org):
    sample = catalogue.sample_payload("homework.assigned", org.pk, "2026-10-01")
    assert set(sample["event_data"]) >= {"homework_id", "student_id", "due_at"}


def test_subscribing_to_a_new_aggregate_wildcard(org):
    assert catalogue.validate_subscriptions(["review.*", "homework.assigned"]) == [
        "homework.assigned",
        "review.*",
    ]
    with pytest.raises(ValueError, match="safeguarding"):
        catalogue.validate_subscriptions(["safeguarding.*"])


# --- marketplace live status ----------------------------------------------------------------------


def connection(org, provider, *, status="active", level="organisation", user=None):
    with tenant_context(org):
        return IntegrationConnection.objects.create(
            provider=provider, status=status, level=level, user=user
        )


def test_marketplace_reports_live_status(api, org):
    connection(org, "xero")
    tutor = MembershipFactory(organisation=org, role="tutor").user
    connection(org, "google", level="user", user=tutor)
    connection(org, "zoom", status="error")
    connection(org, "sage", status="disconnected")
    rows = {r["key"]: r for r in api.get("/api/v1/developer/marketplace").json()}
    assert rows["xero"]["status"] == "connected"
    assert rows["google_calendar"]["status"] == "connected"
    assert rows["google_calendar"]["detail"] == "1 person connected"
    assert rows["google_meet"]["status"] == "connected"
    assert rows["zoom"]["status"] == "needs_attention"
    assert rows["sage"]["status"] == "available"
    for key in ("quickbooks", "freeagent", "xero_payroll", "outlook", "teams", "lessonspace",
                "caldav", "mailchimp", "brevo", "whatsapp", "open_banking", "wise", "ucheck",
                "checkr"):  # fmt: skip
        assert rows[key]["status"] == "available", key
    assert {r["category"] for r in rows.values()} >= set(marketplace.CATEGORIES) - {"automation"}
