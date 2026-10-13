"""Enterprise single sign-on per organisation (FR-03-2, E03-T12): OpenID Connect or
SAML 2.0 with the organisation's own identity provider.

Flow (on the organisation's address, so the session belongs to that tenant):
1. ``GET /api/v1/auth/org-sso/start`` stores ``{state, nonce, verifier | request id, next}``
   in a signed, short-lived cookie and redirects to the IdP.
2. OIDC returns to ``/auth/org-sso/callback`` (authorization code + PKCE; the ID token's
   signature, issuer, audience, expiry and nonce are checked against the IdP's discovery
   document and JWKS, all fetched through ``core.net.safe_urlopen`` because the URLs come
   from the organisation). SAML posts to ``/auth/org-sso/acs`` (HTTP-POST binding): the
   XML signature is checked with the configured IdP certificate (``signxml``; only the
   signed element is read, which defeats signature wrapping), then issuer, audience,
   recipient, validity window and ``InResponseTo``.
3. People are matched by their IdP subject (``SocialAccount`` ``org_sso``), then by an
   email in ``email_domains`` (the IdP is authoritative for its domains). With
   ``auto_provision`` a new person gets a membership with ``default_role``.

``enforce`` stops people with those email domains signing in here with a password or a
magic link. Unsupported: encrypted SAML assertions, IdP-initiated SAML (no
``InResponseTo``), single logout.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import urllib.parse
import zlib
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from django.core import signing
from django.core.cache import cache
from django.http import HttpRequest

from tutortrack.core.time import now

from .models import Membership, OrganisationSSO, SocialAccount, User

STATE_COOKIE = "tt_org_sso"
STATE_SALT = "tutortrack.identity.org-sso-state"
STATE_MAX_AGE = 600
PROVIDER = "org_sso"
NS = {
    "samlp": "urn:oasis:names:tc:SAML:2.0:protocol",
    "saml": "urn:oasis:names:tc:SAML:2.0:assertion",
}
EMAIL_ATTRIBUTES = (
    "email",
    "mail",
    "emailaddress",
    "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress",
    "urn:oid:0.9.2342.19200300.100.1.3",
)
CLOCK_SKEW = timedelta(minutes=3)


class SSOError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def config() -> OrganisationSSO | None:
    found = OrganisationSSO.objects.filter(enabled=True).first()
    return found if found is not None and is_complete(found) else None


def is_complete(cfg: OrganisationSSO) -> bool:
    if not cfg.email_domains:
        return False
    if cfg.protocol == OrganisationSSO.Protocol.OIDC:
        return bool(cfg.issuer and cfg.client_id and cfg.client_secret)
    return bool(cfg.idp_entity_id and cfg.idp_sso_url and cfg.idp_certificate)


def _origin(request: HttpRequest) -> str:
    return f"{request.scheme}://{request.get_host()}"


def callback_url(request: HttpRequest) -> str:
    return f"{_origin(request)}/api/v1/auth/org-sso/callback"


def acs_url(request: HttpRequest) -> str:
    return f"{_origin(request)}/api/v1/auth/org-sso/acs"


def sp_entity_id(request: HttpRequest) -> str:
    return f"{_origin(request)}/api/v1/auth/org-sso/metadata"


def domain_of(email: str) -> str:
    return email.rsplit("@", 1)[-1].strip().lower()


def covers(cfg: OrganisationSSO, email: str) -> bool:
    return domain_of(email) in {d.strip().lower().lstrip("@") for d in cfg.email_domains or []}


def password_blocked(request: HttpRequest, email: str) -> bool:
    """Enforced SSO: these addresses must use the organisation's identity provider here."""
    if getattr(request, "organisation", None) is None:
        return False
    cfg = config()
    return bool(cfg and cfg.enforce and covers(cfg, email))


# --- HTTP (organisation-supplied URLs go through the SSRF guard) ---------------------------------


def _http_json(url: str, data: dict[str, str] | None = None) -> dict[str, Any]:
    from tutortrack.core.net import UnsafeURL, safe_urlopen

    try:
        response = safe_urlopen(
            url,
            data=urllib.parse.urlencode(data).encode() if data is not None else None,
            method="POST" if data is not None else "GET",
            headers={"Accept": "application/json"},
        )
        with response:
            body: dict[str, Any] = json.loads(response.read(1_000_000))
            return body
    except (OSError, ValueError, UnsafeURL) as exc:
        raise SSOError("idp_unreachable") from exc


def discover(cfg: OrganisationSSO) -> dict[str, Any]:
    key = f"org-sso:discovery:{hashlib.sha256(cfg.issuer.encode()).hexdigest()}"
    doc: dict[str, Any] | None = cache.get(key)
    if doc is None:
        doc = _http_json(cfg.issuer.rstrip("/") + "/.well-known/openid-configuration")
        if doc.get("issuer", "").rstrip("/") != cfg.issuer.rstrip("/"):
            raise SSOError("issuer")
        cache.set(key, doc, 3600)
    return doc


# --- state ---------------------------------------------------------------------------------------


def _safe_next(path: str) -> str:
    return path if path.startswith("/") and not path.startswith("//") else "/"


def read_state(cookie: str, state: str) -> dict[str, Any]:
    try:
        data: dict[str, Any] = signing.loads(cookie, salt=STATE_SALT, max_age=STATE_MAX_AGE)
    except signing.BadSignature as exc:
        raise SSOError("state") from exc
    if not secrets.compare_digest(str(data.get("s", "")), state):
        raise SSOError("state")
    return data


def begin(request: HttpRequest, cfg: OrganisationSSO, *, next_path: str = "/") -> tuple[str, str]:
    """(IdP URL, signed state cookie)."""
    state = secrets.token_urlsafe(24)
    if cfg.protocol == OrganisationSSO.Protocol.OIDC:
        nonce, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(48)
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        doc = discover(cfg)
        params = {
            "client_id": cfg.client_id,
            "response_type": "code",
            "scope": "openid email profile",
            "redirect_uri": callback_url(request),
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        cookie = signing.dumps(
            {"s": state, "n": nonce, "v": verifier, "x": _safe_next(next_path)}, salt=STATE_SALT
        )
        return f"{doc['authorization_endpoint']}?{urllib.parse.urlencode(params)}", cookie
    request_id = "_" + secrets.token_hex(20)
    issued = now().astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    xml = (
        f'<samlp:AuthnRequest xmlns:samlp="{NS["samlp"]}" xmlns:saml="{NS["saml"]}" '
        f'ID="{request_id}" Version="2.0" IssueInstant="{issued}" '
        f'Destination="{_xml_attr(cfg.idp_sso_url)}" '
        f'AssertionConsumerServiceURL="{_xml_attr(acs_url(request))}" '
        f'ProtocolBinding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST">'
        f"<saml:Issuer>{_xml_attr(sp_entity_id(request))}</saml:Issuer>"
        f'<samlp:NameIDPolicy Format="urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress" '
        f'AllowCreate="true"/></samlp:AuthnRequest>'
    )
    deflated = zlib.compress(xml.encode())[2:-4]  # raw DEFLATE (redirect binding)
    params = {"SAMLRequest": base64.b64encode(deflated).decode(), "RelayState": state}
    separator = "&" if "?" in cfg.idp_sso_url else "?"
    cookie = signing.dumps(
        {"s": state, "r": request_id, "x": _safe_next(next_path)}, salt=STATE_SALT
    )
    return f"{cfg.idp_sso_url}{separator}{urllib.parse.urlencode(params)}", cookie


def _xml_attr(value: str) -> str:
    from xml.sax.saxutils import escape

    return escape(value, {'"': "&quot;", "'": "&apos;"})


# --- OIDC ----------------------------------------------------------------------------------------


def finish_oidc(
    request: HttpRequest, cfg: OrganisationSSO, code: str, state: dict[str, Any]
) -> dict[str, Any]:
    doc = discover(cfg)
    tokens = _http_json(
        doc["token_endpoint"],
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": callback_url(request),
            "client_id": cfg.client_id,
            "client_secret": cfg.client_secret,
            "code_verifier": state["v"],
        },
    )
    id_token = tokens.get("id_token")
    if not id_token:
        raise SSOError("token_exchange")
    try:
        keys = jwt.PyJWKSet.from_dict(_http_json(doc["jwks_uri"]))
        kid = jwt.get_unverified_header(id_token).get("kid")
        key = next((k for k in keys.keys if kid is None or k.key_id == kid), None)
        if key is None:
            raise SSOError("id_token")
        claims: dict[str, Any] = jwt.decode(
            id_token,
            key.key,
            algorithms=["RS256", "ES256", "PS256"],
            audience=cfg.client_id,
            issuer=doc["issuer"],
            options={"require": ["exp", "iat", "iss", "sub", "aud"]},
            leeway=60,
        )
    except jwt.PyJWTError as exc:
        raise SSOError("id_token") from exc
    if not secrets.compare_digest(str(claims.get("nonce", "")), state["n"]):
        raise SSOError("nonce")
    if claims.get("email_verified") is False:
        raise SSOError("email_unverified")
    return {
        "sub": str(claims["sub"]),
        "email": str(claims.get("email") or claims.get("preferred_username") or ""),
        "given_name": str(claims.get("given_name", "")),
        "family_name": str(claims.get("family_name", "")),
    }


# --- SAML ----------------------------------------------------------------------------------------


def _time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def finish_saml(
    request: HttpRequest, cfg: OrganisationSSO, saml_response: str, state: dict[str, Any]
) -> dict[str, Any]:
    from lxml import etree
    from signxml import XMLVerifier
    from signxml.exceptions import InvalidInput, InvalidSignature

    try:
        raw = base64.b64decode(saml_response, validate=False)
        parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
        root = etree.fromstring(raw, parser=parser)
    except (ValueError, etree.XMLSyntaxError) as exc:
        raise SSOError("saml_response") from exc
    status = root.find("samlp:Status/samlp:StatusCode", NS)
    if status is None or not str(status.get("Value", "")).endswith(":Success"):
        raise SSOError("denied")
    if root.find(".//saml:EncryptedAssertion", NS) is not None:
        raise SSOError("saml_encrypted")
    try:
        verified = XMLVerifier().verify(raw, x509_cert=cfg.idp_certificate)
    except (InvalidSignature, InvalidInput, ValueError) as exc:
        raise SSOError("saml_signature") from exc
    results = verified if isinstance(verified, list) else [verified]
    signed = results[0].signed_xml
    if signed is None:
        raise SSOError("saml_signature")
    assertion = (
        signed if signed.tag == f"{{{NS['saml']}}}Assertion" else signed.find("saml:Assertion", NS)
    )
    if assertion is None:
        raise SSOError("saml_response")
    current = now()
    issuer = assertion.findtext("saml:Issuer", namespaces=NS)
    if (issuer or "").strip() != cfg.idp_entity_id.strip():
        raise SSOError("issuer")
    conditions = assertion.find("saml:Conditions", NS)
    if conditions is not None:
        before, after = _time(conditions.get("NotBefore")), _time(conditions.get("NotOnOrAfter"))
        if (before and current + CLOCK_SKEW < before) or (after and current - CLOCK_SKEW >= after):
            raise SSOError("expired")
        audiences = [
            (a.text or "").strip()
            for a in conditions.findall("saml:AudienceRestriction/saml:Audience", NS)
        ]
        if audiences and sp_entity_id(request) not in audiences:
            raise SSOError("audience")
    confirmation = assertion.find(
        "saml:Subject/saml:SubjectConfirmation/saml:SubjectConfirmationData", NS
    )
    if confirmation is None:
        raise SSOError("saml_response")
    if confirmation.get("Recipient") != acs_url(request):
        raise SSOError("recipient")
    expiry = _time(confirmation.get("NotOnOrAfter"))
    if expiry is None or current - CLOCK_SKEW >= expiry:
        raise SSOError("expired")
    if not secrets.compare_digest(str(confirmation.get("InResponseTo", "")), str(state["r"])):
        raise SSOError("state")
    name_id = (assertion.findtext("saml:Subject/saml:NameID", namespaces=NS) or "").strip()
    attributes: dict[str, str] = {}
    for attribute in assertion.findall("saml:AttributeStatement/saml:Attribute", NS):
        value = attribute.findtext("saml:AttributeValue", namespaces=NS)
        if value:
            attributes[str(attribute.get("Name", "")).lower()] = value.strip()
    email = next((attributes[a] for a in EMAIL_ATTRIBUTES if a in attributes), "")
    if not email and "@" in name_id:
        email = name_id
    if not name_id:
        raise SSOError("saml_response")
    return {
        "sub": name_id,
        "email": email,
        "given_name": attributes.get("givenname", attributes.get("firstname", "")),
        "family_name": attributes.get("sn", attributes.get("surname", "")),
    }


def metadata(request: HttpRequest) -> str:
    """Service provider metadata for the IdP administrator."""
    entity, acs = _xml_attr(sp_entity_id(request)), _xml_attr(acs_url(request))
    return (
        '<?xml version="1.0"?>'
        f'<md:EntityDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata" entityID="{entity}">'
        '<md:SPSSODescriptor AuthnRequestsSigned="false" WantAssertionsSigned="true" '
        'protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">'
        "<md:NameIDFormat>urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress</md:NameIDFormat>"
        '<md:AssertionConsumerService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST" '
        f'Location="{acs}" index="0"/></md:SPSSODescriptor></md:EntityDescriptor>'
    )


# --- matching ------------------------------------------------------------------------------------


def match_user(cfg: OrganisationSSO, claims: dict[str, Any]) -> User:
    """The person signing in, with an active membership here (provisioned if allowed)."""
    from tutortrack.core.context import require_organisation_id

    org_id = require_organisation_id()
    subject = f"{org_id}:{claims['sub']}"[:255]
    account = (
        SocialAccount.objects.select_related("user")
        .filter(provider=PROVIDER, subject=subject)
        .first()
    )
    email = str(claims.get("email") or "").strip().lower()
    if account is not None:
        user = account.user
        SocialAccount.objects.filter(pk=account.pk).update(last_login_at=now())
    else:
        if not email or not covers(cfg, email):
            raise SSOError("domain")
        found = User.objects.filter(email=email).first()
        if found is not None:
            user = found
        else:
            if not cfg.auto_provision:
                raise SSOError("no_account")
            user = User.objects.create_user(
                email,
                None,
                first_name=str(claims.get("given_name", ""))[:100],
                last_name=str(claims.get("family_name", ""))[:100],
            )
        SocialAccount.objects.create(
            user=user, provider=PROVIDER, subject=subject, email=email, last_login_at=now()
        )
    if not user.is_active:
        raise SSOError("inactive")
    if user.email_verified_at is None:
        user.email_verified_at = now()
        user.save(update_fields=["email_verified_at"])
    membership = Membership.objects.filter(user=user).first()
    if membership is None:
        if not cfg.auto_provision:
            raise SSOError("no_account")
        Membership.objects.create(
            user=user, role=cfg.default_role, status=Membership.Status.ACTIVE, joined_at=now()
        )
    elif membership.status != Membership.Status.ACTIVE:
        raise SSOError("inactive")
    return user
