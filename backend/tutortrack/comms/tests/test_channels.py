"""E13-T12: custom sending domains, organisation numbers, WhatsApp templates and
notifications by WhatsApp, and Mailchimp/Brevo audience sync."""

from __future__ import annotations

import pytest
from django.core import mail

from tutortrack.comms import handlers, marketing, providers, senders, services
from tutortrack.comms.marketing_providers import FAKE_AUDIENCES, mailchimp_base
from tutortrack.comms.models import InboundRoute
from tutortrack.core import entitlements
from tutortrack.core.context import tenant_context
from tutortrack.core.exceptions import BusinessRuleViolation, UpgradeRequired
from tutortrack.core.testing import TenantIsolationTestMixin, client_for
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.integrations.providers import AuthError
from tutortrack.people.tests.factories import ClientFactory, ContactFactory
from tutortrack.privacy import services as privacy

from .factories import PhoneNumberFactory, SenderDomainFactory, WhatsAppTemplateFactory
from .test_comms import family, lesson_at, run  # noqa: F401  (fixtures)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def fakes():
    providers.whatsapp_provider.cache_clear()
    providers.sender_domain_provider.cache_clear()
    FAKE_AUDIENCES.clear()
    yield providers.whatsapp_provider()
    providers.whatsapp_provider.cache_clear()
    providers.sender_domain_provider.cache_clear()


@pytest.fixture
def staff(org):
    return client_for(org, MembershipFactory(organisation=org, role="admin").user)


# --- sender domains -----------------------------------------------------------------------------


def test_sender_domain_wizard_and_from_address(org, staff):
    created = staff.post(
        "/api/v1/sender-domains", {"domain": "BrightMinds.co.uk", "local_part": "hello"},
        format="json",
    )  # fmt: skip
    assert created.status_code == 201, created.json()
    row = created.json()
    assert row["domain"] == "brightminds.co.uk"
    assert row["status"] == "pending"
    purposes = [r["purpose"] for r in row["dns_records"]]
    assert purposes == ["dkim", "return_path", "spf", "dmarc"]
    assert row["dns_records"][0]["record_type"] == "TXT"
    with tenant_context(org):
        assert senders.from_address() == ""  # not verified yet
    checked = staff.post(f"/api/v1/sender-domains/{row['id']}/check").json()
    assert checked["status"] == "verified"
    assert checked["is_default"] is True
    with tenant_context(org):
        assert senders.from_address() == "hello@brightminds.co.uk"
        services.test_send("lesson_booked", "email", user=MembershipFactory(organisation=org).user)
    assert mail.outbox[-1].from_email.endswith("<hello@brightminds.co.uk>")


def test_sender_domain_failures_and_validation(org, staff, monkeypatch):
    bad = staff.post("/api/v1/sender-domains", {"domain": "not a domain"}, format="json")
    assert bad.status_code == 422
    platform = staff.post("/api/v1/sender-domains", {"domain": "x.tutortrack.test"}, format="json")
    assert platform.status_code == 422
    row = staff.post("/api/v1/sender-domains", {"domain": "unverified.example"}, format="json")
    checked = staff.post(f"/api/v1/sender-domains/{row.json()['id']}/check").json()
    assert checked["status"] == "failed"
    assert checked["error"]
    default = staff.patch(
        f"/api/v1/sender-domains/{row.json()['id']}", {"is_default": True}, format="json"
    )
    assert default.status_code == 422  # only verified domains can send

    class NoCustomDomains:
        def has(self, key, organisation_id):
            return key != "custom_domain"

        def limit(self, key, organisation_id):
            return None

        def required_plan(self, key, needed=None):
            return "enterprise"

    monkeypatch.setattr(entitlements, "_resolver", NoCustomDomains())
    with tenant_context(org), pytest.raises(UpgradeRequired):
        senders.add_sender_domain(domain="other.example")


# --- numbers ------------------------------------------------------------------------------------


def test_phone_numbers_are_unique_and_route_replies(org, other_org, staff):
    created = staff.post(
        "/api/v1/phone-numbers", {"channel": "sms", "number": "+44 7700 900999"}, format="json"
    )
    assert created.status_code == 201, created.json()
    assert created.json()["number"] == "+447700900999"
    assert created.json()["is_default"] is True
    with tenant_context(other_org), pytest.raises(BusinessRuleViolation):
        senders.add_phone_number(channel="sms", number="+447700900999")
    assert senders.route_inbound("sms", to="+447700900999", sender="+1") == org.pk
    staff.delete(f"/api/v1/phone-numbers/{created.json()['id']}")
    assert not InboundRoute.objects.filter(address="+447700900999").exists()


# --- WhatsApp -----------------------------------------------------------------------------------


def test_whatsapp_templates_validate_placeholders(org, staff):
    bad = staff.post(
        "/api/v1/whatsapp-templates",
        {"name": "x", "body": "Hi {{1}} and {{3}}", "variables": ["a", "b"]},
        format="json",
    )
    assert bad.status_code == 422
    ok = staff.post(
        "/api/v1/whatsapp-templates",
        {"name": "lesson_reminder", "body": "Hi {{1}}, {{2}} soon.", "type_key": "lesson_reminder",
         "variables": ["{{ recipient.first_name }}", "{{ lesson.title }}"], "status": "approved"},
        format="json",
    )  # fmt: skip
    assert ok.status_code == 201, ok.json()
    unknown = staff.post(
        "/api/v1/whatsapp-templates",
        {"name": "y", "body": "Hi {{1}}", "variables": ["a"], "type_key": "nope"},
        format="json",
    )
    assert unknown.status_code == 422


def test_notifications_go_by_whatsapp_with_opt_in_and_a_template(org, family, fakes):  # noqa: F811
    from datetime import timedelta

    from tutortrack.comms.models import OrgNotificationSetting
    from tutortrack.core.time import now

    with tenant_context(org):
        OrgNotificationSetting.objects.create(
            type_key="lesson_booked", enabled=True, channels=["whatsapp"]
        )
    lesson = lesson_at(org, family, now() + timedelta(days=2))
    with tenant_context(org):
        # No opt-in: nothing goes by WhatsApp.
        assert services.notify("lesson_booked", lesson, key="a", immediate=True) == []
        services.set_preference("contact", str(family["contact"].pk), "scheduling", ["whatsapp"])
        # Opted in but no approved template: still nothing.
        assert services.notify("lesson_booked", lesson, key="b", immediate=True) == []
        WhatsAppTemplateFactory(
            organisation=org,
            type_key="lesson_booked",
            body="Hi {{1}}, {{2}} is booked.",
            variables=["{{ recipient.first_name }}", "{{ lesson.title }}"],
        )
        sent = services.notify("lesson_booked", lesson, key="c", immediate=True)
    assert [m.channel for m in sent] == ["whatsapp"]
    assert sent[0].status == "sent"
    assert fakes.outbox[-1]["content_sid"].startswith("HX")
    assert fakes.outbox[-1]["variables"]["1"] == "Priya"
    assert fakes.outbox[-1]["to"] == "whatsapp:+447700900123"
    assert sent[0].body == f"Hi Priya, {lesson.title} is booked."


def test_whatsapp_stop_suppresses(org):
    client_for(org).post(
        "/webhooks/twilio/inbound",
        {"From": "whatsapp:+447700900123", "Body": "STOP"},
        format="multipart",
        HTTP_X_TWILIO_SIGNATURE="fake-signature",
    )
    with tenant_context(org):
        assert services.suppressed("whatsapp", "+447700900123")
        assert not services.suppressed("sms", "+447700900123")


# --- marketing sync -----------------------------------------------------------------------------


def _contact(org, email, *, consent=True):
    client = ClientFactory(organisation=org, display_name=email)
    contact = ContactFactory(organisation=org, client=client, first_name="Pat", email=email)
    if consent is not None:
        with tenant_context(org):
            privacy.ensure_default_types()
            privacy.record_consent(
                subject_type="people.contact",
                subject_id=str(contact.pk),
                key="marketing-email",
                granted=consent,
                method="staff",
            )
    return contact


def test_mailchimp_sync(org, staff, django_capture_on_commit_callbacks):
    yes = _contact(org, "yes@example.com")
    _contact(org, "no@example.com", consent=False)
    _contact(org, "never@example.com", consent=None)
    connected = staff.post(
        "/api/v1/integrations/connections",
        {"provider": "mailchimp", "level": "organisation", "api_key": "abc123-us21"},
        format="json",
    )
    assert connected.status_code == 201, connected.json()
    rows = staff.get("/api/v1/marketing-sync").json()
    assert [r["provider"] for r in rows] == ["mailchimp", "brevo"]
    assert rows[0]["connection"] == connected.json()["id"]
    audiences = staff.get("/api/v1/marketing-sync/mailchimp/audiences").json()
    assert [a["id"] for a in audiences] == ["aud1", "aud2"]
    assert (
        staff.put(
            "/api/v1/marketing-sync/mailchimp/audiences", {"audience_id": "nope"}, format="json"
        ).status_code
        == 422
    )
    chosen = staff.put(
        "/api/v1/marketing-sync/mailchimp/audiences", {"audience_id": "aud1"}, format="json"
    )
    assert chosen.json()["audience_name"] == "Families"
    result = staff.post("/api/v1/marketing-sync/mailchimp/sync").json()
    assert result == {"upserted": 1, "unsubscribed": 0, "failed": 0, "opted_out": 0}
    (audience,) = [a["aud1"] for a in FAKE_AUDIENCES.values()]
    assert set(audience) == {"yes@example.com"}
    assert "status:active" in audience["yes@example.com"]["tags"]
    # Withdrawing consent unsubscribes them there (consent.withdrawn → one-contact sync).
    with tenant_context(org), django_capture_on_commit_callbacks(execute=True):
        privacy.withdraw_consent(
            subject_type="people.contact", subject_id=str(yes.pk), key="marketing-email",
            method="portal",
        )  # fmt: skip
        run(org, "consent.withdrawn", handlers.marketing_consent_changed)
    assert audience["yes@example.com"]["status"] == "unsubscribed"


def test_brevo_sync_needs_an_audience(org, staff):
    staff.post(
        "/api/v1/integrations/connections",
        {"provider": "brevo", "level": "organisation", "api_key": "xkeysib-123"},
        format="json",
    )
    assert staff.post("/api/v1/marketing-sync/brevo/sync").status_code == 422
    assert staff.get("/api/v1/marketing-sync/brevo/audiences").status_code == 200
    with tenant_context(org):
        assert marketing.connection_for("brevo") is not None
        assert marketing.connection_for("zoom") is None


def test_mailchimp_host_comes_from_the_key_safely():
    with pytest.raises(AuthError):
        mailchimp_base("abc123")  # no data centre
    with pytest.raises(AuthError):
        mailchimp_base("abc-evil.example.com/x")
    assert mailchimp_base("abc-us21") == "https://us21.api.mailchimp.com/3.0"


def test_channel_settings_need_permission(org):
    tutor = client_for(org, MembershipFactory(organisation=org, role="tutor").user)
    for url in ("/api/v1/sender-domains", "/api/v1/phone-numbers", "/api/v1/marketing-sync"):
        assert tutor.get(url).status_code == 403


class TestSenderDomainIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/sender-domains"

    def make_object(self, organisation):
        return SenderDomainFactory(organisation=organisation)


class TestPhoneNumberIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/phone-numbers"

    def make_object(self, organisation):
        return PhoneNumberFactory(organisation=organisation)


class TestWhatsAppTemplateIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/whatsapp-templates"

    def make_object(self, organisation):
        return WhatsAppTemplateFactory(organisation=organisation)
