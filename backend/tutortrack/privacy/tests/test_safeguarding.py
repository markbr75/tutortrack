"""E29-T08/T09: safeguarding concerns, the DSL role and messaging safeguards (FR-29-6)."""

from __future__ import annotations

from datetime import date

import pytest
from django.db import connection, transaction

from tutortrack.comms import hooks
from tutortrack.comms.models import Message
from tutortrack.core.context import tenant_context
from tutortrack.core.models import AuditEntry
from tutortrack.core.testing import TenantIsolationTestMixin, client_for
from tutortrack.core.time import now
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.people.tests.factories import StudentFactory
from tutortrack.privacy import safeguarding, safeguards
from tutortrack.privacy.models import SafeguardingConcern, SafeguardingFlag
from tutortrack.tenancy import settings_service

pytestmark = pytest.mark.django_db


def _raise(api, family, **extra):
    return api.post(
        "/api/v1/safeguarding/concerns",
        {
            "category": "neglect",
            "description": "Arjun said he hadn't eaten since yesterday.",
            "immediate_risk": False,
            "student": str(family.student.pk),
            **extra,
        },
        format="json",
    )


def test_staff_raise_a_concern_and_get_only_the_reference(org, family, admin_member, owner):
    response = _raise(client_for(org, admin_member), family)
    assert response.status_code == 201, response.content
    body = response.json()
    assert body["reference"] == "SG-00001"
    assert "description" not in body
    with tenant_context(org):
        concern = SafeguardingConcern.objects.get()
        assert concern.raised_by == admin_member
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT description FROM privacy_safeguardingconcern WHERE id = %s", [concern.pk]
            )
            assert "eaten" not in cursor.fetchone()[0]  # encrypted at rest


def test_cases_are_restricted_to_safeguarding_leads(org, family, admin_member, tutor, owner):
    _raise(client_for(org, admin_member), family)
    # Admins and tutors can raise but not see cases; the owner is a DSL by default.
    assert client_for(org, admin_member).get("/api/v1/safeguarding/concerns").status_code == 403
    tutor_api = client_for(org, tutor.membership.user)
    assert tutor_api.get("/api/v1/safeguarding/concerns").status_code == 403
    listed = client_for(org, owner).get("/api/v1/safeguarding/concerns").json()["results"]
    assert [c["reference"] for c in listed] == ["SG-00001"]
    raised = client_for(org, admin_member).get("/api/v1/safeguarding/raised").json()["results"]
    assert raised[0]["status"] == "open"


def test_a_custom_role_makes_someone_a_dsl(org, family, admin_member):
    from tutortrack.identity import services as identity

    lead = MembershipFactory(organisation=org, role="coordinator")
    with tenant_context(org):
        role = identity.create_custom_role(
            name="Designated Safeguarding Lead",
            clone_from="coordinator",
            grants={"safeguarding.dsl": "all"},
        )
        identity.set_custom_roles(lead, [role])
    _raise(client_for(org, admin_member), family)
    assert client_for(org, lead.user).get("/api/v1/safeguarding/concerns").status_code == 200


def test_opening_a_case_is_audited_and_hidden_from_the_general_audit_log(
    org, family, admin_member, owner
):
    _raise(client_for(org, admin_member), family)
    with tenant_context(org):
        concern = SafeguardingConcern.objects.get()
    detail = client_for(org, owner).get(f"/api/v1/safeguarding/concerns/{concern.pk}")
    assert detail.status_code == 200
    assert detail.json()["description"].startswith("Arjun said")
    assert detail.json()["student_name"] == "Arjun Patel"
    with tenant_context(org):
        assert AuditEntry.objects.filter(object_id=str(concern.pk), action="read").exists()
    admin_audit = client_for(org, admin_member).get("/api/v1/audit").json()["results"]
    assert not [e for e in admin_audit if e["object_type"].startswith("privacy.safeguarding")]
    owner_audit = client_for(org, owner).get("/api/v1/audit").json()["results"]
    assert [e for e in owner_audit if e["object_type"] == "privacy.safeguardingconcern"]
    history = client_for(org, owner).get(f"/api/v1/safeguarding/concerns/{concern.pk}/history")
    assert {"create", "read"} <= {h["action"] for h in history.json()}


def test_dsls_are_alerted_without_personal_details(
    org, family, admin_member, owner, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        _raise(client_for(org, admin_member), family, immediate_risk=True)
    with tenant_context(org):
        alerts = Message.objects.filter(type_key="safeguarding_alert")
        assert alerts.exists()
        assert {m.recipient_id for m in alerts} == {str(owner.pk)}
        for message in alerts:
            assert "URGENT" in message.subject or "URGENT" in message.body
            assert "Arjun" not in message.subject + message.body
            assert "eaten" not in message.subject + message.body


def test_tutors_raise_concerns_only_about_their_own_students(org, family, tutor):
    response = _raise(client_for(org, tutor.membership.user), family)
    assert response.status_code == 404  # not one of their students
    free = client_for(org, tutor.membership.user).post(
        "/api/v1/safeguarding/concerns",
        {"category": "allegation", "description": "A parent shouted at a child at the door"},
        format="json",
    )
    assert free.status_code == 201


def test_case_management(org, family, admin_member, owner):
    _raise(client_for(org, admin_member), family)
    api = client_for(org, owner)
    with tenant_context(org):
        concern = SafeguardingConcern.objects.get()
    url = f"/api/v1/safeguarding/concerns/{concern.pk}"
    noted = api.post(f"{url}/actions", {"kind": "note", "note": "Spoke to mum"}, format="json")
    assert noted.status_code == 201
    referred = api.post(
        f"{url}/actions", {"kind": "referred_social_care", "note": "MASH ref 123"}, format="json"
    )
    assert referred.status_code == 201
    assert api.get(url).json()["status"] == "referred"
    cannot_close = api.patch(url, {"status": "closed"}, format="json")
    assert cannot_close.status_code == 422
    closed = api.patch(url, {"status": "closed", "outcome": "Family supported"}, format="json")
    assert closed.json()["status"] == "closed"
    kinds = [a["kind"] for a in closed.json()["actions"]]
    assert kinds == ["note", "referred_social_care", "status_changed", "status_changed"]
    not_dsl = api.patch(url, {"assigned_to": str(admin_member.pk)}, format="json")
    assert not_dsl.status_code == 422


# --- messaging safeguards (T09) -----------------------------------------------------------------


def test_screening_finds_contact_details_and_flagged_words(org):
    with tenant_context(org):
        found = safeguards.screen("Call me on 07700 900123 or add me on snapchat, don't tell mum")
        clean = safeguards.screen("Homework: page 12, questions 1-10 by 2026-11-03")
    assert found.contact_details == ["phone", "social"]
    assert "don't tell" in found.keywords
    assert "snapchat" in found.keywords
    assert not clean.flagged
    with tenant_context(org):
        assert safeguards.screen("email me at tutor@example.com").contact_details == ["email"]


def _outgoing(sender, recipient_kind, recipient_id, body, participants=(), category="scheduling"):
    return hooks.OutgoingMessage(
        type_key="inbox_message",
        category=category,
        channel="in_app",
        recipient_kind=recipient_kind,
        recipient_id=recipient_id,
        recipient_user_id=None,
        subject="",
        body=body,
        sender_user_id=str(sender.pk) if sender else None,
        participants=tuple(participants),
        source_type="comms.thread_message",
        source_id="m1",
    )


def test_tutors_cannot_message_children_directly(org, family, tutor):
    with tenant_context(org):
        direct = hooks.run_pre_send(
            _outgoing(tutor.membership.user, "student", str(family.student.pk), "See you Monday")
        )
        with_parent = hooks.run_pre_send(
            _outgoing(
                tutor.membership.user,
                "student",
                str(family.student.pk),
                "See you Monday",
                participants=[
                    ("student", str(family.student.pk)),
                    ("contact", str(family.contact.pk)),
                ],
            )
        )
        flag = SafeguardingFlag.objects.get()
    assert direct == "policy:tutor_student_direct"
    assert with_parent == ""
    assert flag.blocked
    assert flag.reasons == ["policy:tutor_student_direct"]


def test_adult_learners_can_be_messaged_directly(org, tutor):
    adult = StudentFactory(organisation=org, date_of_birth=date(1990, 1, 1))
    with tenant_context(org):
        assert (
            hooks.run_pre_send(_outgoing(tutor.membership.user, "student", str(adult.pk), "Hi"))
            == ""
        )


def test_contact_details_are_blocked_and_flagged(org, family, tutor):
    with tenant_context(org):
        blocked = hooks.run_pre_send(
            _outgoing(
                tutor.membership.user, "contact", str(family.contact.pk), "Text me on 07700900999"
            )
        )
        settings_service.update_settings("safeguarding", {"safeguarding.contact_details": "flag"})
        flagged_only = hooks.run_pre_send(
            hooks.OutgoingMessage(
                **{
                    **_outgoing(
                        tutor.membership.user,
                        "contact",
                        str(family.contact.pk),
                        "Text me on 07700900999",
                    ).__dict__,
                    "source_id": "m2",
                }
            )
        )
        assert SafeguardingFlag.objects.count() == 2
    assert blocked == "contact_details"
    assert flagged_only == ""


def test_system_notifications_are_not_screened(org, family):
    with tenant_context(org):
        assert (
            hooks.run_pre_send(
                _outgoing(None, "contact", str(family.contact.pk), "Call 07700900123")
            )
            == ""
        )
        assert not SafeguardingFlag.objects.exists()


def test_marketing_to_children_is_blocked(org, family):
    child_user = MembershipFactory(organisation=org, role="student").user
    with tenant_context(org):
        family.student.user = child_user
        family.student.save()
        reason = hooks.run_pre_send(
            _outgoing(None, "user", str(child_user.pk), "Summer offer", category="marketing")
        )
    assert reason == "aadc:no_marketing_to_children"


def test_the_comms_pipeline_suppresses_blocked_messages(org, family, monkeypatch):
    from tutortrack.comms import services as comms

    monkeypatch.setattr(hooks, "_hooks", [lambda m: "test:blocked" if m.channel == "email" else ""])
    with tenant_context(org), transaction.atomic():
        comms.update_setting("enquiry_acknowledgement", enabled=True, channels=["email"])
        recipient = comms.registry.Recipient(
            kind="contact",
            id=str(family.contact.pk),
            name="Priya",
            first_name="Priya",
            email="priya@example.com",
        )
        delivery = comms.registry.Delivery(recipient, {"organisation": {"name": "X"}})
        t = comms.registry.get("enquiry_acknowledgement")
        messages = comms._deliver(t, None, delivery, ("email",), key="k", immediate=False)
    assert messages[0].status == "suppressed"
    assert messages[0].error == "test:blocked"


def test_shared_text_is_flagged_but_never_blocked(org, tutor):
    with tenant_context(org):
        flag = safeguards.screen_text(
            text="Add me on whatsapp me 07700900123",
            source_type="delivery.lessonreportcomment",
            source_id="c1",
            sender_id=str(tutor.membership.user_id),
        )
        assert (
            safeguards.screen_text(
                text="Great progress today", source_type="x", source_id="c2", sender_id=None
            )
            is None
        )
    assert flag is not None
    assert not flag.blocked
    assert set(flag.reasons) == {"contact_details", "keyword"}


def test_dsls_review_flags(org, family, tutor, owner):
    with tenant_context(org):
        flag = safeguards.screen_text(
            text="our secret", source_type="x", source_id="1", sender_id=None
        )
    api = client_for(org, owner)
    listed = api.get("/api/v1/safeguarding/flags?status=open").json()["results"]
    assert listed[0]["excerpt"] == "our secret"
    escalated = api.post(
        f"/api/v1/safeguarding/flags/{flag.pk}/review", {"decision": "escalate"}, format="json"
    )
    assert escalated.json()["status"] == "escalated"
    assert escalated.json()["concern"] is not None
    again = api.post(
        f"/api/v1/safeguarding/flags/{flag.pk}/review", {"decision": "dismiss"}, format="json"
    )
    assert again.status_code == 422


class TestConcernIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/safeguarding/concerns"

    def make_object(self, organisation):
        user = MembershipFactory(organisation=organisation, role="admin").user
        with tenant_context(organisation), transaction.atomic():
            return safeguarding.raise_concern(user=user, category="other", description="x")


class TestFlagIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/safeguarding/flags"

    def make_object(self, organisation):
        with tenant_context(organisation):
            return SafeguardingFlag.objects.create(source_type="x", reasons=["keyword"])


def test_concerns_carry_a_timestamp(org, admin_member):
    with tenant_context(org), transaction.atomic():
        concern = safeguarding.raise_concern(user=admin_member, category="online", description="x")
    assert concern.raised_at <= now()
