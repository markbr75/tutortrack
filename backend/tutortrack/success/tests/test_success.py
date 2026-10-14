"""E30 Part 2 (tenant side): help panel content and search, product tours, "What's new",
the setup checklist, NPS/CSAT, support chat and consent-gated product analytics."""

from __future__ import annotations

import json
import uuid
from datetime import timedelta
from typing import Any
from urllib.parse import quote

import pytest

from tutortrack.core.context import tenant_context
from tutortrack.core.events import EventEnvelope, subscribers_for
from tutortrack.core.models import OutboxEvent
from tutortrack.core.testing import TenantIsolationTestMixin, client_for
from tutortrack.core.time import now
from tutortrack.identity.models import Membership
from tutortrack.identity.tests.factories import MembershipFactory, UserFactory
from tutortrack.people.tests.factories import StudentFactory
from tutortrack.success import analytics, help, services
from tutortrack.success.handlers import tick_setup_step
from tutortrack.success.models import (
    ProductEvent,
    SetupChecklistItem,
    SupportConversation,
    SurveyResponse,
)
from tutortrack.success.tests.factories import SupportConversationFactory
from tutortrack.tenancy import settings_service

pytestmark = pytest.mark.django_db


def member_api(org: Any, role: str = "owner", *, days: int = 30) -> tuple[Any, Any]:
    with tenant_context(org):
        membership = MembershipFactory(organisation=org, role=role)
        joined = now() - timedelta(days=days)
        Membership.objects.filter(pk=membership.pk).update(joined_at=joined, created_at=joined)
    return client_for(org, membership.user), membership.user


def consent_cookie(analytics_on: bool = True) -> str:
    return quote(
        json.dumps({"necessary": True, "analytics": analytics_on, "marketing": False, "version": 1})
    )


# --- help articles and "What's new" (FR-30-5) ---------------------------------------------------


def test_help_articles_are_markdown_with_front_matter():
    articles = help.articles()
    assert {"getting-started", "send-invoices", "contact-support"} <= set(articles)
    invoices = articles["send-invoices"]
    assert invoices.title == "Make and send invoices"
    assert "/billing" in invoices.routes
    assert invoices.tour == "billing"
    assert invoices.body.startswith("Completed lessons")


def test_search_ranks_title_matches_first_and_needs_every_word():
    found = [a.slug for a in help.search("invoice")]
    assert found[0] == "send-invoices"
    assert [a.slug for a in help.search("stripe payouts")] == ["connect-stripe"]
    assert help.search("stripe zebra") == []
    assert "send-invoices" in [a.slug for a in help.search("invo")]  # prefixes count


def test_help_panel_suggests_articles_for_the_page(org):
    api, _user = member_api(org)
    body = api.get("/api/v1/help/articles", {"route": "/billing"}).json()
    assert {"send-invoices", "connect-stripe"} <= {a["slug"] for a in body}
    found = api.get("/api/v1/help/articles", {"q": "pay run"}).json()
    assert found[0]["slug"] == "pay-tutors"
    fallback = api.get("/api/v1/help/articles", {"route": "/nowhere"}).json()
    assert "getting-started" in {a["slug"] for a in fallback}
    article = api.get("/api/v1/help/articles/schedule-lessons").json()
    assert article["tour"] == "calendar"
    assert "Calendar" in article["body"]
    assert api.get("/api/v1/help/articles/../secrets").status_code == 404
    assert api.get("/api/v1/help/articles/nope").status_code == 404


def test_whats_new_is_unread_until_seen(org):
    api, _user = member_api(org, days=60)
    entries = api.get("/api/v1/help/changelog").json()
    assert entries[0]["published_on"] >= entries[-1]["published_on"]
    unread = api.get("/api/v1/me/guidance").json()["changelog_unread"]
    assert unread >= 1
    assert api.post("/api/v1/help/changelog/seen").json()["changelog_unread"] == 0


# --- product tours ------------------------------------------------------------------------------


def test_tours_are_remembered_per_person(org):
    api, _user = member_api(org)
    body = api.post("/api/v1/me/guidance/tours/welcome", {"status": "completed"}).json()
    assert body["completed_tours"] == ["welcome"]
    body = api.post("/api/v1/me/guidance/tours/billing", {"status": "dismissed"}).json()
    assert body["dismissed_tours"] == ["billing"]
    body = api.post("/api/v1/me/guidance/tours/welcome", {"status": "restart"}).json()
    assert body["completed_tours"] == []
    other, _ = member_api(org)
    assert other.get("/api/v1/me/guidance").json()["dismissed_tours"] == []


# --- setup checklist ----------------------------------------------------------------------------


def test_checklist_finds_existing_data(org):
    StudentFactory(organisation=org)
    api, _user = member_api(org)
    body = api.get("/api/v1/setup-checklist").json()
    steps = {s["key"]: s for s in body["steps"]}
    assert list(steps) == ["service", "student", "lesson", "payments", "invoice"]
    assert steps["student"]["done"]
    assert steps["student"]["link"] == "/students"
    assert not steps["invoice"]["done"]
    assert body["total"] == 5


def _envelope(org: Any, event_type: str) -> EventEnvelope:
    return EventEnvelope(
        id=uuid.uuid4(),
        type=event_type,
        version=1,
        occurred_at=now(),
        organisation_id=org.pk,
        branch_id=None,
        actor={},
        subject={"type": "x", "id": "1"},
        data={},
        changes={},
    )


def test_checklist_ticks_itself_from_domain_events(org):
    for event_type in [
        "service.created",
        "student.created",
        "lesson.scheduled",
        "provider_account.connected",
        "invoice.sent",
    ]:
        assert "success.setup_checklist" in {s.name for s in subscribers_for(event_type)}
    with tenant_context(org):
        services.checklist()
        for event_type in [
            "service.created",
            "student.created",
            "lesson.scheduled",
            "provider_account.connected",
            "invoice.issued",
            "invoice.sent",
        ]:
            tick_setup_step(_envelope(org, event_type))
        assert SetupChecklistItem.objects.count() == 5  # idempotent: invoice ticked once
        state = services.checklist()
        assert state.completed_at is not None
        types = list(
            OutboxEvent.objects.filter(event_type__startswith="setup_checklist.").values_list(
                "event_type", flat=True
            )
        )
    assert types.count("setup_checklist.item_completed") == 5
    assert types.count("setup_checklist.completed") == 1


def test_only_managers_hide_the_checklist(org):
    coordinator, _ = member_api(org, "coordinator")
    assert coordinator.patch("/api/v1/setup-checklist", {"dismissed": True}).status_code == 403
    owner, _ = member_api(org, "owner")
    body = owner.patch("/api/v1/setup-checklist", {"dismissed": True}, format="json").json()
    assert body["dismissed_at"] is not None
    assert coordinator.get("/api/v1/setup-checklist").json()["dismissed_at"] is not None


# --- NPS / CSAT (FR-30-6) -----------------------------------------------------------------------


def test_nps_is_asked_after_two_weeks_then_rests(org):
    newcomer, _ = member_api(org, days=3)
    assert newcomer.get("/api/v1/me/guidance").json()["nps_due"] is False
    api, user = member_api(org, days=30)
    assert api.get("/api/v1/me/guidance").json()["nps_due"] is True
    answer = api.post(
        "/api/v1/surveys/responses",
        {"kind": "nps", "score": 9, "comment": "Saves me hours"},
        format="json",
    )
    assert answer.status_code == 201, answer.content
    assert api.get("/api/v1/me/guidance").json()["nps_due"] is False
    with tenant_context(org):
        row = SurveyResponse.objects.get(user=user)
        assert (row.score, row.role) == (9, "owner")
        assert OutboxEvent.objects.filter(event_type="survey.answered").exists()


def test_nps_dismissal_snoozes_and_scores_are_checked(org):
    api, user = member_api(org)
    assert (
        api.post(
            "/api/v1/surveys/responses", {"kind": "nps", "score": 11}, format="json"
        ).status_code
        == 400
    )
    assert (
        api.post(
            "/api/v1/surveys/responses", {"kind": "csat", "score": 0}, format="json"
        ).status_code
        == 422
    )
    assert (
        api.post(
            "/api/v1/surveys/responses", {"kind": "nps", "score": None}, format="json"
        ).status_code
        == 201
    )
    assert api.get("/api/v1/me/guidance").json()["nps_due"] is False
    with tenant_context(org):
        state = services.guidance(user)
        assert state.nps_snoozed_until > now() + timedelta(days=29)


def test_nps_respects_the_organisation_setting_and_roles(org):
    api, _ = member_api(org)
    with tenant_context(org):
        settings_service.update_settings("privacy", {"privacy.satisfaction_surveys": False})
    assert api.get("/api/v1/me/guidance").json()["nps_due"] is False


def test_csat_rates_a_support_chat_once_by_its_author(org):
    api, user = member_api(org)
    other, _ = member_api(org)
    conversation = SupportConversationFactory(organisation=org, opened_by=user)
    context = f"support:{conversation.pk}"
    payload = {"kind": "csat", "score": 5, "topic": context}
    assert other.post("/api/v1/surveys/responses", payload, format="json").status_code == 422
    assert api.post("/api/v1/surveys/responses", payload, format="json").status_code == 201
    assert api.post("/api/v1/surveys/responses", payload, format="json").status_code == 422
    detail = api.get(f"/api/v1/support-conversations/{conversation.pk}").json()
    assert detail["csat_score"] == 5


# --- support chat (FR-30-5) ---------------------------------------------------------------------


def test_staff_open_and_continue_a_support_chat(org):
    api, _user = member_api(org, "coordinator")
    created = api.post(
        "/api/v1/support-conversations",
        {"subject": "Invoice run", "body": "How do I invoice everyone?", "page": "/billing"},
        format="json",
    )
    assert created.status_code == 201, created.content
    body = created.json()
    assert body["status"] == "open"
    assert body["messages"][0]["body"] == "How do I invoice everyone?"
    cid = body["id"]
    with tenant_context(org):
        conversation = SupportConversation.objects.get(pk=cid)
        staff = UserFactory(is_platform_staff=True, first_name="Pat")
        services.post_message(
            conversation, staff, body="Use Billing → Invoice run.", from_support=True
        )
    assert api.get("/api/v1/me/guidance").json()["support_unread"] == 1
    detail = api.get(f"/api/v1/support-conversations/{cid}").json()
    assert detail["status"] == "answered"
    assert detail["messages"][1]["author_name"] == "Pat (TutorTrack)"
    assert api.get("/api/v1/me/guidance").json()["support_unread"] == 0  # read on open
    reply = api.post(f"/api/v1/support-conversations/{cid}/messages", {"body": "Thanks!"})
    assert reply.json()["status"] == "open"
    closed = api.post(f"/api/v1/support-conversations/{cid}/close").json()
    assert closed["status"] == "closed"
    with tenant_context(org):
        types = set(OutboxEvent.objects.values_list("event_type", flat=True))
    assert {
        "support_conversation.opened",
        "support_conversation.replied",
        "support_conversation.closed",
    } <= types
    assert api.post("/api/v1/support-conversations", {"body": " "}).status_code == 400


def test_members_see_their_own_chats_and_owners_see_all(org):
    coordinator, coord_user = member_api(org, "coordinator")
    owner, _ = member_api(org, "owner")
    mine = SupportConversationFactory(organisation=org, opened_by=coord_user)
    theirs = SupportConversationFactory(organisation=org)
    ids = {r["id"] for r in coordinator.get("/api/v1/support-conversations").json()["results"]}
    assert ids == {str(mine.pk)}
    assert coordinator.get(f"/api/v1/support-conversations/{theirs.pk}").status_code == 404
    ids = {r["id"] for r in owner.get("/api/v1/support-conversations").json()["results"]}
    assert ids == {str(mine.pk), str(theirs.pk)}
    tutor, _ = member_api(org, "tutor")
    assert tutor.get("/api/v1/support-conversations").status_code == 403


class TestSupportConversationIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/support-conversations"

    def make_object(self, organisation):
        return SupportConversationFactory(organisation=organisation)


# --- product analytics (FR-30-6) ----------------------------------------------------------------


EVENTS = {
    "events": [
        {
            "name": "page.viewed",
            "route": "/clients/0190f2a4-1b2c-7d3e-8f40-123456789abc/billing?tab=x",
            "properties": {
                "tab": "billing",
                "email": "sam@example.com",
                "student_name": "Sam",
                "count": 3,
                "label": "sam@example.com",
                "ref": "07700 900123",
                "free": "this is a long sentence typed by someone",
            },
        },
        {"name": "Bad Name!", "route": "/x"},
    ]
}


def test_no_consent_no_tracking(org):
    api, _ = member_api(org)
    response = api.post("/api/v1/analytics/events", EVENTS, format="json")
    assert response.status_code == 202
    assert response.json()["accepted"] == 0
    api.cookies["tt_consent"] = consent_cookie(analytics_on=False)
    assert api.post("/api/v1/analytics/events", EVENTS, format="json").json()["accepted"] == 0
    with tenant_context(org):
        assert not ProductEvent.objects.exists()


def test_consented_events_are_pseudonymous_and_stripped_of_pii(org):
    api, user = member_api(org)
    api.cookies["tt_consent"] = consent_cookie()
    assert api.post("/api/v1/analytics/events", EVENTS, format="json").json()["accepted"] == 1
    with tenant_context(org):
        event = ProductEvent.objects.get()
    assert event.name == "page.viewed"
    assert event.route == "/clients/$id/billing"
    assert event.properties == {"tab": "billing", "count": 3}
    assert event.actor == analytics.pseudonym(org.pk, user.pk)
    assert str(user.pk) not in event.actor
    assert user.email not in json.dumps(event.properties)


def test_tracking_needs_the_organisation_and_a_staff_role(org):
    api, _ = member_api(org)
    api.cookies["tt_consent"] = consent_cookie()
    with tenant_context(org):
        settings_service.update_settings("privacy", {"privacy.product_analytics": False})
    assert api.post("/api/v1/analytics/events", EVENTS, format="json").json()["accepted"] == 0
    assert api.get("/api/v1/me/guidance").json()["analytics_allowed"] is False
    with tenant_context(org):
        settings_service.update_settings("privacy", {"privacy.product_analytics": True})
    family, _ = member_api(org, "client")
    family.cookies["tt_consent"] = consent_cookie()
    assert family.post("/api/v1/analytics/events", EVENTS, format="json").json()["accepted"] == 0


def test_sinks_are_the_provider_seam(org, settings):
    settings.PRODUCT_ANALYTICS_SINKS = ["tutortrack.success.tests.test_success.RecorderSink"]
    RecorderSink.received = []
    analytics.emit(analytics.build(org.pk, uuid.uuid4(), [{"name": "tour.completed"}]))
    assert [e.name for e in RecorderSink.received] == ["tour.completed"]


class RecorderSink:
    received: list[Any] = []

    def emit(self, events: list[Any]) -> None:
        RecorderSink.received.extend(events)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("/students/123/lessons", "/students/$id/lessons"),
        ("/calendar?week=2026-10-12", "/calendar"),
        ("/clients/$id", "/clients/$id"),
        ("https://evil.example/x", ""),
        ("/inbox/sam@example.com", "/inbox/$id"),
    ],
)
def test_routes_become_patterns(raw, expected):
    assert analytics.clean_route(raw) == expected


def test_consent_cookie_parsing():
    assert analytics.consented({"tt_consent": consent_cookie()})
    assert not analytics.consented({"tt_consent": consent_cookie(False)})
    assert not analytics.consented({"tt_consent": "garbage"})
    assert not analytics.consented({})


# --- privacy (E29 registry) ---------------------------------------------------------------------


def test_erasure_removes_usage_and_anonymises_chats(org):
    from tutortrack.privacy.registry import ErasureContext, Person
    from tutortrack.success import privacy

    api, user = member_api(org)
    api.cookies["tt_consent"] = consent_cookie()
    api.post("/api/v1/analytics/events", EVENTS, format="json")
    api.post("/api/v1/support-conversations", {"body": f"I am {user.first_name}, help"})
    with tenant_context(org):
        person = Person("identity.user", str(user.pk))
        person.add("identity.user", user.pk)
        person.add_terms(names=[user.first_name])
        assert {s.key for s in privacy.export(person)} == {
            "support_chat",
            "surveys",
            "product_usage",
        }
        ctx = ErasureContext(labels={}, financial_cutoff=now())
        ctx.prepare_scrub(person, "[erased]")
        outcome = privacy.erase(person, ctx)
        assert outcome.deleted >= 1
        assert not ProductEvent.objects.exists()
        message = SupportConversation.objects.get().messages.get()
        assert user.first_name not in message.body
        assert message.author_id is None


def test_old_usage_events_are_purged(org):
    from tutortrack.privacy.registry import retention_category
    from tutortrack.success.tests.factories import ProductEventFactory

    ProductEventFactory(organisation=org, occurred_at=now() - timedelta(days=400))
    ProductEventFactory(organisation=org)
    category = retention_category("product_usage")
    assert category is not None
    assert category.purge is not None
    with tenant_context(org):
        assert category.purge(now() - timedelta(days=395), True, 100) == 1
        assert category.purge(now() - timedelta(days=395), False, 100) == 1
        assert ProductEvent.objects.count() == 1
