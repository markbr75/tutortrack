"""E03 Phase 2: passkeys (T08), custom roles and the permission matrix (T11), and
enterprise SSO per organisation over OIDC and SAML (T12)."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import cbor2
import jwt
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import NameOID
from django.conf import settings

from tutortrack.core.context import tenant_context
from tutortrack.core.permissions import has_perm
from tutortrack.core.testing import TenantIsolationTestMixin, client_for
from tutortrack.identity import org_sso, rbac, services
from tutortrack.identity.models import (
    Membership,
    OrganisationSSO,
    Role,
    SocialAccount,
    User,
    WebAuthnCredential,
)
from tutortrack.identity.tests.factories import TEST_PASSWORD, MembershipFactory

pytestmark = pytest.mark.django_db


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64url(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


# --- custom roles (T11) -------------------------------------------------------------------------


def test_cloning_a_built_in_role_expands_its_patterns(org, tenant):
    matrix = services.builtin_matrix("coordinator")
    assert matrix["people.client.view"] == "all"
    assert "scheduling.edit_locked" not in matrix  # coordinator denies it
    tutor = services.builtin_matrix("tutor")
    assert tutor["scheduling.lesson.view"] == "own"


def test_custom_role_replaces_the_built_in_grants_and_unions(org):
    with tenant_context(org):
        coordinator = MembershipFactory(organisation=org, role="coordinator")
        viewer = services.create_custom_role(
            name="Read-only coordinator",
            clone_from="coordinator",
            grants={"people.client.edit": None, "people.client.create": "none"},
        )
        invoicer = services.create_custom_role(
            name="Invoicer", grants={"billing.invoice.issue": "branch"}
        )
        services.set_custom_roles(coordinator, [viewer, invoicer])
        user = coordinator.user
        rbac.clear_cache(user)
        assert has_perm(user, "people.client.view")
        assert not has_perm(user, "people.client.edit")
        assert has_perm(user, "billing.invoice.issue")  # from the second role
        services.archive_custom_role(viewer)
        rbac.clear_cache(user)
        assert not has_perm(user, "people.client.view")  # only the invoicer role is left
        services.set_custom_roles(coordinator, [])
        rbac.clear_cache(user)
        assert has_perm(user, "people.client.edit")  # back to the built-in coordinator


def test_custom_role_rules(org):
    with tenant_context(org):
        owner = MembershipFactory(organisation=org, role="owner")
        client = MembershipFactory(organisation=org, role="client")
        role = services.create_custom_role(name="Helper", clone_from="finance")
        with pytest.raises(services.BusinessRuleViolation):
            services.set_custom_roles(owner, [role])
        with pytest.raises(services.BusinessRuleViolation):
            services.set_custom_roles(client, [role])
        with pytest.raises(services.BusinessRuleViolation):
            services.create_custom_role(name="Bad", grants={"org.close": "all"})  # owner only
        with pytest.raises(services.BusinessRuleViolation):
            services.create_custom_role(name="helper")  # name taken
        with pytest.raises(services.BusinessRuleViolation):
            services.update_custom_role(role, grants={"nope.nothing": "all"})


def test_custom_roles_api_and_membership_assignment(org):
    admin = MembershipFactory(organisation=org, role="admin")
    member = MembershipFactory(organisation=org, role="coordinator")
    api = client_for(org, admin.user)
    response = api.post(
        "/api/v1/custom-roles",
        {"name": "Scheduler", "clone_from": "coordinator", "grants": {"leads.*": "all"}},
        format="json",
    )
    assert response.status_code == 422  # patterns aren't codenames in the matrix
    response = api.post(
        "/api/v1/custom-roles", {"name": "Scheduler", "clone_from": "coordinator"}, format="json"
    )
    assert response.status_code == 201, response.json()
    role_id = response.json()["id"]
    assert response.json()["grants"]["scheduling.lesson.edit"] == "all"
    response = api.patch(
        f"/api/v1/custom-roles/{role_id}",
        {"grants": {"scheduling.lesson.edit": "own", "comms.message.send": "none"}},
        format="json",
    )
    assert response.json()["grants"]["scheduling.lesson.edit"] == "own"
    response = api.patch(
        f"/api/v1/memberships/{member.pk}", {"custom_roles": [role_id]}, format="json"
    )
    assert response.status_code == 200, response.json()
    assert response.json()["custom_roles"] == [role_id]
    roles = api.get("/api/v1/roles").json()
    assert any(r["id"] == role_id and not r["is_builtin"] for r in roles)
    me = client_for(org, member.user).get("/api/v1/me").json()
    assert me["permissions"]["scheduling.lesson.edit"] == "own"
    coordinator_api = client_for(org, MembershipFactory(organisation=org, role="coordinator").user)
    assert (
        coordinator_api.post("/api/v1/custom-roles", {"name": "X"}, format="json").status_code
        == 403
    )


class TestCustomRoleIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/custom-roles"

    def make_object(self, organisation):
        with tenant_context(organisation):
            return Role.objects.create(name=f"Role {organisation.slug}")


# --- passkeys (T08) -----------------------------------------------------------------------------


class SoftAuthenticator:
    """A software authenticator producing ``none`` attestations and ES256 assertions."""

    def __init__(self, origin: str, rp_id: str):
        self.origin, self.rp_id = origin, rp_id
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = os.urandom(16)
        self.count = 0

    def _client_data(self, kind: str, challenge: str) -> bytes:
        return json.dumps(
            {"type": kind, "challenge": challenge, "origin": self.origin, "crossOrigin": False}
        ).encode()

    def create(self, options: dict) -> dict:
        numbers = self.key.public_key().public_numbers()
        cose = cbor2.dumps(
            {1: 2, 3: -7, -1: 1, -2: numbers.x.to_bytes(32, "big"),
             -3: numbers.y.to_bytes(32, "big")}
        )  # fmt: skip
        auth_data = (
            hashlib.sha256(self.rp_id.encode()).digest()
            + bytes([0x45])
            + (0).to_bytes(4, "big")
            + bytes(16)
            + len(self.credential_id).to_bytes(2, "big")
            + self.credential_id
            + cose
        )
        attestation = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data})
        return {
            "id": b64url(self.credential_id),
            "rawId": b64url(self.credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": b64url(
                    self._client_data("webauthn.create", options["challenge"])
                ),
                "attestationObject": b64url(attestation),
                "transports": ["internal"],
            },
            "clientExtensionResults": {},
        }

    def get(self, options: dict, *, user_handle: bytes | None = None) -> dict:
        self.count += 1
        auth_data = (
            hashlib.sha256(self.rp_id.encode()).digest()
            + bytes([0x05])
            + self.count.to_bytes(4, "big")
        )
        client_data = self._client_data("webauthn.get", options["challenge"])
        signature = self.key.sign(
            auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256())
        )
        return {
            "id": b64url(self.credential_id),
            "rawId": b64url(self.credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": b64url(client_data),
                "authenticatorData": b64url(auth_data),
                "signature": b64url(signature),
                "userHandle": b64url(user_handle) if user_handle else None,
            },
            "clientExtensionResults": {},
        }


@pytest.fixture
def passkey_user(org):
    member = MembershipFactory(organisation=org, role="tutor", user__email="sam@example.com")
    api = client_for(org, member.user)
    origin = f"http://{org.slug}.{settings.TENANT_BASE_DOMAIN}"
    device = SoftAuthenticator(origin, settings.TENANT_BASE_DOMAIN)
    options = api.post("/api/v1/me/passkeys/options").json()
    assert options["rp"]["id"] == settings.TENANT_BASE_DOMAIN
    response = api.post(
        "/api/v1/me/passkeys/register",
        {"credential": device.create(options), "name": "Laptop"},
        format="json",
    )
    assert response.status_code == 201, response.json()
    return member.user, device, response.json()


def test_registering_a_passkey_turns_on_mfa_with_recovery_codes(passkey_user):
    user, _device, body = passkey_user
    assert body["credential"]["name"] == "Laptop"
    assert len(body["recovery_codes"]) == 10
    assert User.objects.get(pk=user.pk).has_mfa


def test_passkey_only_sign_in(org, passkey_user):
    user, device, _body = passkey_user
    anonymous = client_for(org)
    options = anonymous.post("/api/v1/auth/passkey/options").json()
    assert options["allowCredentials"] == []
    assert options["userVerification"] == "required"
    response = anonymous.post(
        "/api/v1/auth/passkey/verify",
        {"credential": device.get(options, user_handle=user.pk.bytes)},
        format="json",
    )
    assert response.status_code == 200, response.json()
    assert response.json()["user"]["email"] == user.email
    assert anonymous.get("/api/v1/me").status_code == 200
    stored = WebAuthnCredential.objects.get(user=user)
    assert stored.sign_count == 1
    assert stored.last_used_at is not None


def test_passkey_as_second_factor_after_password(org, passkey_user):
    user, device, _body = passkey_user
    browser = client_for(org)
    response = browser.post(
        "/api/v1/auth/login", {"email": user.email, "password": TEST_PASSWORD}, format="json"
    )
    assert response.json()["mfa_required"] is True
    options = browser.post("/api/v1/auth/passkey/options").json()
    assert [c["id"] for c in options["allowCredentials"]] == [b64url(device.credential_id)]
    response = browser.post(
        "/api/v1/auth/passkey/verify", {"credential": device.get(options)}, format="json"
    )
    assert response.status_code == 200, response.json()
    assert browser.get("/api/v1/me").status_code == 200


def test_a_replayed_or_foreign_assertion_fails(org, passkey_user):
    _user, device, _body = passkey_user
    browser = client_for(org)
    options = browser.post("/api/v1/auth/passkey/options").json()
    assertion = device.get(options)
    stranger = SoftAuthenticator(device.origin, device.rp_id)
    forged = stranger.get(options)
    forged["id"] = forged["rawId"] = assertion["id"]
    assert browser.post("/api/v1/auth/passkey/verify", {"credential": forged},
                        format="json").status_code == 400  # fmt: skip
    # the challenge was used up by the failed attempt
    assert browser.post("/api/v1/auth/passkey/verify", {"credential": assertion},
                        format="json").status_code == 400  # fmt: skip


def test_removing_the_last_passkey_turns_mfa_off(org, passkey_user):
    user, _device, body = passkey_user
    api = client_for(org, user)
    assert len(api.get("/api/v1/me/passkeys").json()) == 1
    assert api.delete(f"/api/v1/me/passkeys/{body['credential']['id']}").status_code == 204
    assert not User.objects.get(pk=user.pk).has_mfa


# --- organisation SSO (T12) ---------------------------------------------------------------------

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
ISSUER = "https://idp.school.example"


@pytest.fixture
def oidc(org, monkeypatch):
    with tenant_context(org):
        cfg = OrganisationSSO.objects.create(
            protocol="oidc", enabled=True, name="School login", email_domains=["school.org"],
            issuer=ISSUER, client_id="tt-client", client_secret="s3cret", auto_provision=True,
            default_role="tutor",
        )  # fmt: skip
    public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(KEY.public_key()))
    public.update({"kid": "k1", "use": "sig", "alg": "RS256"})
    calls: list[tuple[str, dict | None]] = []

    def fake_http(url: str, data: dict | None = None) -> dict:
        calls.append((url, data))
        if url.endswith("/.well-known/openid-configuration"):
            return {
                "issuer": ISSUER,
                "authorization_endpoint": f"{ISSUER}/authorize",
                "token_endpoint": f"{ISSUER}/token",
                "jwks_uri": f"{ISSUER}/jwks",
            }
        if url.endswith("/jwks"):
            return {"keys": [public]}
        assert data is not None
        return {"id_token": fake_http.token}  # type: ignore[attr-defined]

    monkeypatch.setattr(org_sso, "_http_json", fake_http)
    return cfg, fake_http, calls


def oidc_token(nonce: str, **claims: object) -> str:
    payload = {
        "iss": ISSUER, "aud": "tt-client", "sub": "staff-42", "email": "ana@school.org",
        "given_name": "Ana", "iat": int(time.time()), "exp": int(time.time()) + 300,
        "nonce": nonce, **claims,
    }  # fmt: skip
    return jwt.encode(payload, KEY, algorithm="RS256", headers={"kid": "k1"})


def test_oidc_sign_in_provisions_a_member(org, oidc):
    _cfg, fake_http, calls = oidc
    browser = client_for(org)
    assert browser.get("/api/v1/auth/org-sso").json()["name"] == "School login"
    start = browser.get("/api/v1/auth/org-sso/start?next=/calendar")
    assert start.status_code == 302
    params = parse_qs(urlparse(start["Location"]).query)
    assert params["redirect_uri"] == [
        f"http://{org.slug}.{settings.TENANT_BASE_DOMAIN}/api/v1/auth/org-sso/callback"
    ]
    state_cookie = browser.cookies[org_sso.STATE_COOKIE].value
    nonce = org_sso.read_state(state_cookie, params["state"][0])["n"]
    fake_http.token = oidc_token(nonce)
    done = browser.get(f"/api/v1/auth/org-sso/callback?code=abc&state={params['state'][0]}")
    assert done.status_code == 302
    assert done["Location"] == "/calendar"
    assert calls[-2][1]["code_verifier"]  # PKCE
    user = User.objects.get(email="ana@school.org")
    with tenant_context(org):
        assert Membership.objects.get(user=user).role == "tutor"
    assert SocialAccount.objects.get(user=user).provider == "org_sso"
    assert browser.get("/api/v1/me").status_code == 200


def test_oidc_rejects_wrong_nonce_and_other_domains(org, oidc):
    _cfg, fake_http, _calls = oidc
    browser = client_for(org)
    start = browser.get("/api/v1/auth/org-sso/start")
    state = parse_qs(urlparse(start["Location"]).query)["state"][0]
    fake_http.token = oidc_token("wrong")
    done = browser.get(f"/api/v1/auth/org-sso/callback?code=abc&state={state}")
    assert done["Location"] == "/login?error=sso_nonce"
    start = browser.get("/api/v1/auth/org-sso/start")
    state = parse_qs(urlparse(start["Location"]).query)["state"][0]
    nonce = org_sso.read_state(browser.cookies[org_sso.STATE_COOKIE].value, state)["n"]
    fake_http.token = oidc_token(nonce, sub="other", email="eve@gmail.com")
    done = browser.get(f"/api/v1/auth/org-sso/callback?code=abc&state={state}")
    assert done["Location"] == "/login?error=sso_domain"


def test_enforced_sso_blocks_passwords_for_its_domains(org, oidc):
    cfg, _http, _calls = oidc
    with tenant_context(org):
        cfg.enforce = True
        cfg.save()
    member = MembershipFactory(organisation=org, user__email="bo@school.org")
    response = client_for(org).post(
        "/api/v1/auth/login", {"email": member.user.email, "password": TEST_PASSWORD},
        format="json",
    )  # fmt: skip
    assert response.status_code == 400
    assert response.json()["type"].endswith("sso-required")
    other = MembershipFactory(organisation=org, user__email="cy@example.com")
    response = client_for(org).post(
        "/api/v1/auth/login", {"email": other.user.email, "password": TEST_PASSWORD},
        format="json",
    )  # fmt: skip
    assert response.status_code == 200


def test_sso_settings_api(org):
    admin = MembershipFactory(organisation=org, role="owner")
    api = client_for(org, admin.user)
    response = api.put("/api/v1/security/sso", {"enabled": True, "protocol": "saml"}, format="json")
    assert response.status_code == 422  # incomplete
    response = api.put(
        "/api/v1/security/sso",
        {"protocol": "oidc", "issuer": ISSUER, "client_id": "c", "client_secret": "s",
         "email_domains": ["@School.org"], "enabled": True},
        format="json",
    )  # fmt: skip
    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["email_domains"] == ["school.org"]
    assert body["has_client_secret"] is True
    assert "client_secret" not in body
    tutor_api = client_for(org, MembershipFactory(organisation=org, role="tutor").user)
    assert tutor_api.get("/api/v1/security/sso").status_code == 403


def _certificate() -> tuple[str, str]:
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "idp.school.example")])
    moment = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(KEY.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(moment - timedelta(days=1))
        .not_valid_after(moment + timedelta(days=30))
        .sign(KEY, hashes.SHA256())
    )
    key_pem = KEY.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    return cert.public_bytes(serialization.Encoding.PEM).decode(), key_pem


CERT_PEM, KEY_PEM = _certificate()


def saml_response(
    *, request_id: str, acs: str, audience: str, email: str = "ana@school.org",
    issuer: str = "https://idp.school.example/saml", minutes: int = 5,
) -> str:  # fmt: skip
    from lxml import etree
    from signxml import XMLSigner

    moment = datetime.now(UTC)
    stamp = moment.strftime("%Y-%m-%dT%H:%M:%SZ")
    later = (moment + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assertion = f"""<saml:Assertion xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion"
 ID="_a1" Version="2.0" IssueInstant="{stamp}"><saml:Issuer>{issuer}</saml:Issuer>
<saml:Subject><saml:NameID>{email}</saml:NameID><saml:SubjectConfirmation
 Method="urn:oasis:names:tc:SAML:2.0:cm:bearer"><saml:SubjectConfirmationData
 InResponseTo="{request_id}" Recipient="{acs}" NotOnOrAfter="{later}"/></saml:SubjectConfirmation>
</saml:Subject><saml:Conditions NotBefore="{stamp}" NotOnOrAfter="{later}">
<saml:AudienceRestriction><saml:Audience>{audience}</saml:Audience></saml:AudienceRestriction>
</saml:Conditions><saml:AttributeStatement><saml:Attribute Name="givenName"><saml:AttributeValue>Ana
</saml:AttributeValue></saml:Attribute></saml:AttributeStatement></saml:Assertion>"""
    signer = XMLSigner(c14n_algorithm="http://www.w3.org/2001/10/xml-exc-c14n#")
    signed = signer.sign(etree.fromstring(assertion.encode()), key=KEY_PEM, cert=CERT_PEM)
    response = etree.fromstring(
        b'<samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol" ID="_r1" '
        b'Version="2.0"><samlp:Status><samlp:StatusCode '
        b'Value="urn:oasis:names:tc:SAML:2.0:status:Success"/></samlp:Status></samlp:Response>'
    )
    response.append(signed)
    return base64.b64encode(etree.tostring(response)).decode()


@pytest.fixture
def saml(org):
    with tenant_context(org):
        return OrganisationSSO.objects.create(
            protocol="saml", enabled=True, email_domains=["school.org"],
            idp_entity_id="https://idp.school.example/saml",
            idp_sso_url="https://idp.school.example/sso", idp_certificate=CERT_PEM,
        )  # fmt: skip


def _saml_start(org, browser):
    start = browser.get("/api/v1/auth/org-sso/start")
    params = parse_qs(urlparse(start["Location"]).query)
    state = org_sso.read_state(browser.cookies[org_sso.STATE_COOKIE].value, params["RelayState"][0])
    host = f"http://{org.slug}.{settings.TENANT_BASE_DOMAIN}"
    return params, state, f"{host}/api/v1/auth/org-sso/acs", f"{host}/api/v1/auth/org-sso/metadata"


def test_saml_sign_in_for_an_existing_member(org, saml):
    member = MembershipFactory(organisation=org, role="coordinator", user__email="ana@school.org")
    browser = client_for(org)
    params, state, acs, audience = _saml_start(org, browser)
    assert "SAMLRequest" in params
    body = saml_response(request_id=state["r"], acs=acs, audience=audience)
    done = browser.post(
        "/api/v1/auth/org-sso/acs",
        {"SAMLResponse": body, "RelayState": params["RelayState"][0]},
        format="multipart",
    )
    assert done.status_code == 302, done.content
    assert done["Location"] == "/"
    assert browser.get("/api/v1/me").json()["user"]["email"] == member.user.email
    metadata = client_for(org).get("/api/v1/auth/org-sso/metadata").content.decode()
    assert acs in metadata


@pytest.mark.parametrize(
    ("change", "error"),
    [
        ({"audience": "https://elsewhere"}, "audience"),
        ({"issuer": "https://evil.example"}, "issuer"),
        ({"request_id": "_other"}, "state"),
        ({"minutes": -10}, "expired"),
    ],
)
def test_saml_checks(org, saml, change, error):
    MembershipFactory(organisation=org, user__email="ana@school.org")
    browser = client_for(org)
    params, state, acs, audience = _saml_start(org, browser)
    values = {"request_id": state["r"], "acs": acs, "audience": audience, **change}
    done = browser.post(
        "/api/v1/auth/org-sso/acs",
        {"SAMLResponse": saml_response(**values), "RelayState": params["RelayState"][0]},
        format="multipart",
    )
    assert done["Location"] == f"/login?error=sso_{error}"


def test_saml_tampered_assertion_fails_the_signature(org, saml):
    MembershipFactory(organisation=org, user__email="ana@school.org")
    browser = client_for(org)
    params, state, acs, audience = _saml_start(org, browser)
    body = base64.b64decode(saml_response(request_id=state["r"], acs=acs, audience=audience))
    tampered = base64.b64encode(body.replace(b"ana@school.org", b"boss@school.org")).decode()
    done = browser.post(
        "/api/v1/auth/org-sso/acs", {"SAMLResponse": tampered,
                                     "RelayState": params["RelayState"][0]},
        format="multipart",
    )  # fmt: skip
    assert done["Location"] == "/login?error=sso_saml_signature"


def test_unb64_helper():
    assert unb64url(b64url(b"abc")) == b"abc"
