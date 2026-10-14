"""Gap batch G2 (FR-03-9): change email: verify the new address by link, notify the old one,
audit, and sign out other sessions."""

from __future__ import annotations

import re

import pytest
from django.core import mail
from rest_framework.test import APIClient

from tutortrack.core.context import tenant_context
from tutortrack.core.models import AuditEntry, OutboxEvent
from tutortrack.identity.models import User
from tutortrack.identity.tests.factories import TEST_PASSWORD, MembershipFactory, UserFactory

pytestmark = pytest.mark.django_db
HOST = "brightminds.tutortrack.test"


@pytest.fixture
def person(org):
    return MembershipFactory(organisation=org, role="admin", user__email="sam@example.com").user


def signed_in(email: str = "sam@example.com", agent: str = "Browser A") -> APIClient:
    client = APIClient(HTTP_HOST=HOST, HTTP_USER_AGENT=agent)
    response = client.post(
        "/api/v1/auth/login", {"email": email, "password": TEST_PASSWORD}, format="json"
    )
    assert response.status_code == 200
    return client


def ask(client: APIClient, new_email: str, password: str = TEST_PASSWORD):
    return client.post(
        "/api/v1/me/email", {"new_email": new_email, "password": password}, format="json"
    )


def test_change_email_end_to_end(org, person, django_capture_on_commit_callbacks):
    client, other_device = signed_in(), signed_in(agent="Browser B")
    with django_capture_on_commit_callbacks(execute=True):
        response = ask(client, "Sam.New@Example.com")
    assert response.status_code == 202
    assert response.json() == {"pending_email": "sam.new@example.com"}
    # Nothing has changed yet; the link went to the new address, a notice to the old one.
    person.refresh_from_db()
    assert person.email == "sam@example.com"
    by_recipient = {m.to[0]: m for m in mail.outbox}
    assert set(by_recipient) == {"sam.new@example.com", "sam@example.com"}
    assert "sam.new@example.com" in by_recipient["sam@example.com"].body
    token = re.search(r"confirm-email\?token=(\S+)", by_recipient["sam.new@example.com"].body)
    assert token is not None

    mail.outbox.clear()
    with django_capture_on_commit_callbacks(execute=True):
        confirmed = client.post(
            "/api/v1/auth/email-change/confirm", {"token": token.group(1)}, format="json"
        )
    assert confirmed.status_code == 200
    assert confirmed.json() == {"email": "sam.new@example.com"}
    person.refresh_from_db()
    assert person.email == "sam.new@example.com"
    assert person.email_verified_at is not None
    # This browser stays signed in, the other device is signed out.
    assert client.get("/api/v1/me").status_code == 200
    assert other_device.get("/api/v1/me").status_code == 403
    assert [m.to for m in mail.outbox] == [["sam@example.com"]]
    with tenant_context(org):  # audited in the organisation where it was done
        actions = set(
            AuditEntry.objects.filter(object_id=str(person.pk)).values_list("action", flat=True)
        )
    assert {"email_change_requested", "email_change"} <= actions
    assert OutboxEvent.objects.filter(event_type="user.email_changed").exists()
    # The link works once; the new address signs in.
    again = client.post(
        "/api/v1/auth/email-change/confirm", {"token": token.group(1)}, format="json"
    )
    assert again.status_code == 400
    signed_in("sam.new@example.com", agent="Browser C")


def test_password_and_free_address_are_required(person):
    client = signed_in()
    assert ask(client, "sam.new@example.com", password="wrong").status_code in (400, 401)
    UserFactory(email="taken@example.com")
    taken = ask(client, "taken@example.com")
    assert taken.status_code == 422
    assert ask(client, "sam@example.com").status_code == 422
    assert not mail.outbox


def test_signed_out_or_tampered_links_fail(person):
    assert (
        APIClient(HTTP_HOST=HOST)
        .post("/api/v1/me/email", {"new_email": "x@example.com"}, format="json")
        .status_code
        == 403
    )
    bad = APIClient(HTTP_HOST=HOST).post(
        "/api/v1/auth/email-change/confirm", {"token": "nope"}, format="json"
    )
    assert bad.status_code == 400
    assert User.objects.get(pk=person.pk).email == "sam@example.com"


def test_address_taken_meanwhile_is_refused(person, django_capture_on_commit_callbacks):
    client = signed_in()
    with django_capture_on_commit_callbacks(execute=True):
        ask(client, "late@example.com")
    token = re.search(
        r"token=(\S+)", next(m for m in mail.outbox if m.to == ["late@example.com"]).body
    ).group(1)
    UserFactory(email="late@example.com")
    response = client.post("/api/v1/auth/email-change/confirm", {"token": token}, format="json")
    assert response.status_code == 400
