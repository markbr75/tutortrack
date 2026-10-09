"""E15-T01..T08: household scoping and isolation, dashboard, schedule and ICS, cancelling
and absences, reports and replies, billing and payment methods, profile edits,
announcements and portal settings."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from tutortrack.billing import services as billing
from tutortrack.catalogue.tests.factories import ServiceFactory
from tutortrack.core.context import tenant_context
from tutortrack.core.models import OutboxEvent
from tutortrack.core.money import Money
from tutortrack.core.testing import client_for
from tutortrack.core.time import now
from tutortrack.delivery import services as delivery
from tutortrack.identity.models import Invitation
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.people import services as people
from tutortrack.people.tests.factories import (
    ClientFactory,
    ContactFactory,
    StudentFactory,
    TutorProfileFactory,
)
from tutortrack.scheduling import services as scheduling
from tutortrack.tenancy import settings_service

pytestmark = pytest.mark.django_db


def snap(moment):
    return moment.replace(second=0, microsecond=0, minute=moment.minute - moment.minute % 5)


def make_household(org, name):
    client = ClientFactory(organisation=org, display_name=name)
    membership = MembershipFactory(organisation=org, role="client")
    contact = ContactFactory(
        organisation=org, client=client, first_name="Parent", email=membership.user.email
    )
    with tenant_context(org):
        people.link_portal_user("people.contact", str(contact.pk), membership.user)
    students = [
        StudentFactory(organisation=org, client=client, first_name=n) for n in ("Arjun", "Maya")
    ]
    return {
        "client": client,
        "contact": contact,
        "user": membership.user,
        "students": students,
        "api": client_for(org, membership.user),
    }


@pytest.fixture
def world(org):
    tutor = TutorProfileFactory(organisation=org, status="active", first_name="Nia")
    service = ServiceFactory(organisation=org, name="Maths 1:1")
    group = ServiceFactory(organisation=org, name="Maths group", format="small_group",
                           max_students=6)  # fmt: skip
    return {
        "a": make_household(org, "The Patels"),
        "b": make_household(org, "The Smiths"),
        "tutor": tutor,
        "service": service,
        "group": group,
    }


def lesson_for(org, world, students, *, hours=48, service=None):
    start = snap(now() + timedelta(hours=hours))
    with tenant_context(org):
        return scheduling.create_lesson(
            start=start, end=start + timedelta(hours=1),
            service=service or (world["group"] if len(students) > 1 else world["service"]),
            attendees=[{"student": s} for s in students], tutors=[{"tutor": world["tutor"]}],
            timezone="Europe/London", override_conflicts=True,
        ).lesson  # fmt: skip


def test_invite_links_the_login_to_the_contact(org):
    client = ClientFactory(organisation=org)
    contact = ContactFactory(organisation=org, client=client, email="mum@example.com")
    staff = client_for(org, MembershipFactory(organisation=org, role="admin").user)
    response = staff.post(f"/api/v1/contacts/{contact.pk}/portal-invite", {}, format="json")
    assert response.status_code == 201, response.json()
    with tenant_context(org):
        invitation = Invitation.objects.get(email="mum@example.com")
    assert (invitation.role, invitation.target_type) == ("client", "people.contact")
    student = StudentFactory(organisation=org, client=client)
    no_email = staff.post(f"/api/v1/students/{student.pk}/portal-invite", {}, format="json")
    assert no_email.status_code == 422
    ok = staff.post(
        f"/api/v1/students/{student.pk}/portal-invite", {"email": "kid@example.com"}, format="json"
    )
    assert ok.status_code == 201


def test_me_and_dashboard(org, world):
    a = world["a"]
    lesson = lesson_for(org, world, [a["students"][0]], hours=3)
    with tenant_context(org):
        billing.create_ad_hoc_charge(
            client=a["client"], description="Fee", unit_price=Money(Decimal("40"), "GBP")
        )
        billing.issue_invoice(billing.create_draft(a["client"]), send=False)
    me = a["api"].get("/api/v1/portal/me").json()
    assert me["role"] == "client"
    assert [s["name"] for s in me["students"]] == ["Arjun " + a["students"][0].last_name,
                                                  "Maya " + a["students"][1].last_name]  # fmt: skip
    assert me["features"]["cancellations"] is True
    dash = a["api"].get("/api/v1/portal/dashboard").json()
    assert dash["next_lesson"]["id"] == str(lesson.pk)
    assert dash["amount_due"] == {"amount": "40.00", "currency": "GBP"}
    assert "notes_internal" not in dash["next_lesson"]


def test_households_cannot_see_each_other(org, world):
    a, b = world["a"], world["b"]
    theirs = lesson_for(org, world, [b["students"][0]])
    mine = lesson_for(org, world, [a["students"][0]], hours=72)
    rows = a["api"].get("/api/v1/portal/schedule").json()
    assert [r["id"] for r in rows] == [str(mine.pk)]
    assert a["api"].get(f"/api/v1/portal/lessons/{theirs.pk}/ics").status_code == 404
    assert (
        a["api"].post(f"/api/v1/portal/lessons/{theirs.pk}/cancel", {}, format="json").status_code
        == 404
    )
    assert (
        a["api"].get(f"/api/v1/portal/payment-methods?client={b['client'].pk}").status_code == 404
    )
    assert a["api"].get(f"/api/v1/portal/statement?client={b['client'].pk}").status_code == 404
    ics = a["api"].get(f"/api/v1/portal/lessons/{mine.pk}/ics")
    assert b"BEGIN:VEVENT" in ics.content
    # Staff APIs stay closed to families.
    assert a["api"].get("/api/v1/lessons").status_code == 403
    assert a["api"].get(f"/api/v1/clients/{b['client'].pk}").status_code in {403, 404}


def test_cancel_with_policy_preview(org, world):
    a = world["a"]
    lesson = lesson_for(org, world, [a["students"][0]], hours=10)
    preview = (
        a["api"]
        .post(f"/api/v1/portal/lessons/{lesson.pk}/cancel?preview=true", {}, format="json")
        .json()
    )
    assert preview["kind"] == "late"
    assert "client charged 100%" in preview["message"]
    assert preview["cancelled"] is False
    done = (
        a["api"]
        .post(f"/api/v1/portal/lessons/{lesson.pk}/cancel", {"reason": "Ill"}, format="json")
        .json()
    )
    assert done["cancelled"] is True
    with tenant_context(org):
        lesson.refresh_from_db()
        assert (lesson.status, lesson.cancelled_by) == ("cancelled", "client")
        settings_service.update_settings("portal", {"portal.allow_cancellations": False})
    other = lesson_for(org, world, [a["students"][0]], hours=96)
    blocked = a["api"].post(f"/api/v1/portal/lessons/{other.pk}/cancel", {}, format="json")
    assert blocked.status_code == 403


def test_absence_in_a_group_lesson_carries_into_the_register(org, world):
    a = world["a"]
    arjun, maya = a["students"]
    group = lesson_for(org, world, [arjun, maya], hours=2)
    response = a["api"].post(
        f"/api/v1/portal/lessons/{group.pk}/absence",
        {"student": str(maya.pk), "note": "Dentist"},
        format="json",
    )
    assert response.status_code == 204
    with tenant_context(org):
        attendee = group.attendees.get(student=maya)
        assert (attendee.outcome, attendee.chargeable) == ("absent_notified", False)
        assert OutboxEvent.objects.filter(event_type="attendance.absence_notified").exists()
        from tutortrack.scheduling.models import Lesson

        Lesson.objects.filter(pk=group.pk).update(
            start=now() - timedelta(hours=2), end=now() - timedelta(hours=1)
        )
        group.refresh_from_db()
        delivery.complete_lesson(group)
        outcomes = {a.student_id: a.outcome for a in group.attendees.all()}
    assert outcomes == {arjun.pk: "present", maya.pk: "absent_notified"}
    solo = lesson_for(org, world, [arjun], hours=72)
    a["api"].post(
        f"/api/v1/portal/lessons/{solo.pk}/absence", {"student": str(arjun.pk)}, format="json"
    )
    with tenant_context(org):
        solo.refresh_from_db()
    assert solo.status == "cancelled"


def test_reports_feed_hides_staff_fields_and_takes_replies(org, world):
    a, b = world["a"], world["b"]
    lesson = lesson_for(org, world, [a["students"][0]], hours=-3)
    with tenant_context(org):
        report = delivery.open_report(lesson, world["tutor"])
        delivery.submit_report(
            report, answers={"covered": "Fractions", "private_notes": "Tired today"}
        )
    feed = a["api"].get("/api/v1/portal/reports").json()
    assert len(feed) == 1
    labels = {row["label"]: row["value"] for row in feed[0]["answers"]}
    assert labels == {"What we covered": "Fractions"}
    assert b["api"].get("/api/v1/portal/reports").json() == []
    reply = a["api"].post(
        f"/api/v1/portal/reports/{report.pk}/comments", {"body": "Thanks!"}, format="json"
    )
    assert reply.status_code == 201
    assert reply.json()["comments"][0]["body"] == "Thanks!"
    stolen = b["api"].post(
        f"/api/v1/portal/reports/{report.pk}/comments", {"body": "x"}, format="json"
    )
    assert stolen.status_code == 404


def test_billing_payment_methods_and_statement(org, world):
    a = world["a"]
    with tenant_context(org):
        billing.create_ad_hoc_charge(
            client=a["client"], description="Fee", unit_price=Money(Decimal("25"), "GBP")
        )
        issued = billing.issue_invoice(billing.create_draft(a["client"]), send=False)
        billing.create_ad_hoc_charge(
            client=a["client"], description="Draft", unit_price=Money(Decimal("5"), "GBP")
        )
        billing.create_draft(a["client"])
        from tutortrack.payments.models import AccountRoute, ProviderAccount

        ProviderAccount.objects.create(provider="stripe", account_ref="acct_p", status="active")
        AccountRoute.objects.create(provider="stripe", account_ref="acct_p", organisation_id=org.pk)
    data = a["api"].get("/api/v1/portal/billing").json()
    assert [i["number"] for i in data["invoices"]] == [issued.number]
    assert data["invoices"][0]["pay_token"] == issued.pay_token
    assert data["accounts"][0]["balances"]["invoice_balance"]["amount"] == "25.00"
    statement = a["api"].get(f"/api/v1/portal/statement?client={a['client'].pk}")
    assert statement.content.startswith(b"%PDF")
    link = (
        a["api"]
        .post(
            "/api/v1/portal/payment-methods",
            {"client": str(a["client"].pk), "action": "add"},
            format="json",
        )
        .json()
    )
    assert "/pay/setup/" in link["url"]
    methods = a["api"].get(f"/api/v1/portal/payment-methods?client={a['client'].pk}").json()
    assert methods == {"auto_pay": False, "consent_given_at": None, "methods": []}


def test_profile_edits_and_sensitive_alert(org, world):
    a = world["a"]
    profile = a["api"].get("/api/v1/portal/profile").json()
    assert profile["contacts"][0]["email"] == a["user"].email
    contact_url = f"/api/v1/portal/profile/contacts/{a['contact'].pk}"
    changed = (
        a["api"]
        .patch(contact_url, {"mobile": "07700900999", "email": "new@example.com"}, format="json")
        .json()
    )
    assert changed["mobile"] == "07700900999"
    assert changed["email"] == a["user"].email  # read-only here
    student = a["students"][0]
    a["api"].patch(
        f"/api/v1/portal/profile/students/{student.pk}",
        {"learning_needs": "Dyslexia: larger print please"},
        format="json",
    )
    with tenant_context(org):
        assert OutboxEvent.objects.filter(event_type="portal.sensitive_updated").exists()
    other = world["b"]["students"][0]
    assert (
        a["api"]
        .patch(f"/api/v1/portal/profile/students/{other.pk}", {"school": "x"}, format="json")
        .status_code
        == 404
    )


def test_student_logins_see_only_themselves(org, world):
    a = world["a"]
    membership = MembershipFactory(organisation=org, role="student")
    arjun, maya = a["students"]
    with tenant_context(org):
        people.link_portal_user("people.student", str(arjun.pk), membership.user)
    api = client_for(org, membership.user)
    mine = lesson_for(org, world, [arjun])
    lesson_for(org, world, [maya], hours=60)
    assert [r["id"] for r in api.get("/api/v1/portal/schedule").json()] == [str(mine.pk)]
    assert api.get("/api/v1/portal/billing").status_code == 403
    assert api.get("/api/v1/portal/me").json()["features"]["invoices"] is False


def test_announcements_and_portal_switch(org, world):
    staff = client_for(org, MembershipFactory(organisation=org, role="coordinator").user)
    for audience, title in (("clients", "Half term"), ("tutors", "Staff training")):
        response = staff.post(
            "/api/v1/announcements", {"title": title, "body": "...", "audience": audience},
            format="json",
        )  # fmt: skip
        assert response.status_code == 201, response.json()
    a = world["a"]
    titles = [n["title"] for n in a["api"].get("/api/v1/portal/announcements").json()]
    assert titles == ["Half term"]
    assert staff.get("/api/v1/portal/dashboard").status_code == 403  # staff aren't families
    with tenant_context(org):
        settings_service.update_settings("portal", {"portal.enabled": False})
    assert a["api"].get("/api/v1/portal/dashboard").status_code == 403
