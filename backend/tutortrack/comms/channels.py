"""Delivery channels (FR-13-1).

* **Email** goes through Django's mail backend (Postmark over SMTP in production,
  Mailpit locally). Our message id and organisation travel in ``X-PM-Metadata-*`` headers so
  Postmark's delivery webhooks can be matched back.
* **SMS** goes through Twilio's REST API (or a fake that records messages when Twilio isn't
  configured, for development and tests). The status callback carries the organisation and
  message id and is verified with Twilio's signature.
* SMS credits come from the subscription (E04), which registers ``set_credit_meter``.
* **Web Push** (E16-T09) encrypts with ``pywebpush`` (RFC 8291, aes128gcm) and signs with
  VAPID (RFC 8292, ``py_vapid``), then posts through ``core.net.safe_urlopen``: the endpoint
  comes from a browser, so it must be https on a known push service and resolve to public
  addresses. Without a VAPID private key a fake records pushes. Endpoints are capability
  URLs: they are never logged or put in errors.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from functools import cache
from typing import Any, Protocol

from django.conf import settings
from django.core.mail import EmailMultiAlternatives


class ChannelError(Exception):
    pass


def send_email(
    *,
    to: str,
    subject: str,
    text: str,
    html: str,
    from_name: str,
    reply_to: str,
    headers: dict[str, str],
    attachments: list[tuple[str, bytes, str]],
    from_address: str = "",
) -> str:
    """``from_address`` is a verified custom sending address (E13-T12); otherwise the
    platform's own sender with the organisation's name."""
    sender = settings.DEFAULT_FROM_EMAIL
    address = from_address or sender.split("<")[-1].rstrip(">").strip()
    from_email = f'"{from_name}" <{address}>' if from_name else (from_address or sender)
    message = EmailMultiAlternatives(
        subject=subject,
        body=text,
        from_email=from_email,
        to=[to],
        reply_to=[reply_to] if reply_to else None,
        headers=headers,
    )
    message.attach_alternative(html, "text/html")
    for name, content, mime in attachments:
        message.attach(name, content, mime)
    message.send()
    return str(message.extra_headers.get("Message-ID", ""))


# --- SMS ----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SmsResult:
    ref: str
    status: str


class SmsProvider(Protocol):
    def send(self, *, to: str, body: str, status_callback: str, sender: str = "") -> SmsResult: ...


class TwilioSms:
    def __init__(self) -> None:
        self.sid = settings.TWILIO["ACCOUNT_SID"]
        self.token = settings.TWILIO["AUTH_TOKEN"]
        self.sender = settings.TWILIO["FROM"]

    def send(self, *, to: str, body: str, status_callback: str, sender: str = "") -> SmsResult:
        url = f"https://api.twilio.com/2010-04-01/Accounts/{self.sid}/Messages.json"
        data = urllib.parse.urlencode(
            {
                "To": to,
                "From": sender or self.sender,
                "Body": body,
                "StatusCallback": status_callback,
            }
        ).encode()
        auth = base64.b64encode(f"{self.sid}:{self.token}".encode()).decode()
        request = urllib.request.Request(url, data=data, headers={"Authorization": f"Basic {auth}"})
        try:
            with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310
                payload = json.loads(response.read())
        except Exception as exc:
            raise ChannelError(f"Twilio: {exc}") from exc
        return SmsResult(str(payload.get("sid", "")), str(payload.get("status", "queued")))


class FakeSms:
    """Records texts instead of sending them (no Twilio credentials)."""

    def __init__(self) -> None:
        self.outbox: list[dict[str, str]] = []

    def send(self, *, to: str, body: str, status_callback: str, sender: str = "") -> SmsResult:
        self.outbox.append(
            {"to": to, "body": body, "status_callback": status_callback, "from": sender}
        )
        return SmsResult(f"SMfake{len(self.outbox)}", "queued")


@cache
def sms_provider() -> SmsProvider:
    if settings.TWILIO["ACCOUNT_SID"]:
        return TwilioSms()
    return FakeSms()


def twilio_signature(url: str, params: dict[str, str]) -> str:
    """Twilio's request signature: HMAC-SHA1 of the URL plus sorted POST params."""
    payload = url + "".join(f"{k}{params[k]}" for k in sorted(params))
    digest = hmac.new(
        settings.TWILIO["AUTH_TOKEN"].encode(), payload.encode(), hashlib.sha1
    ).digest()
    return base64.b64encode(digest).decode()


def twilio_signature_valid(url: str, params: dict[str, str], signature: str) -> bool:
    if not settings.TWILIO["AUTH_TOKEN"]:
        return signature == "fake-signature"  # development and tests
    return hmac.compare_digest(twilio_signature(url, params), signature)


# --- SMS credits (E04) --------------------------------------------------------------------------


class CreditMeter(Protocol):
    def consume(self, segments: int, *, country: str) -> bool:
        """Deduct SMS credits for the organisation in context; False if there are none."""
        ...


class _Unlimited:
    def consume(self, segments: int, *, country: str) -> bool:
        return True


_meter: CreditMeter = _Unlimited()


def set_credit_meter(meter: CreditMeter) -> None:
    global _meter
    _meter = meter


def credit_meter() -> CreditMeter:
    return _meter


def normalise_phone(phone: str, country: str = "GB") -> str:
    """Best-effort E.164: keeps ``+`` numbers, turns a national 0 prefix into the code."""
    digits = "".join(c for c in phone if c.isdigit() or c == "+")
    if digits.startswith("+"):
        return digits
    codes = {"GB": "44", "IE": "353", "AU": "61", "NZ": "64", "US": "1", "CA": "1"}
    if digits.startswith("00"):
        return "+" + digits[2:]
    if digits.startswith("0") and country in codes:
        return f"+{codes[country]}{digits[1:]}"
    return f"+{codes.get(country, '')}{digits}" if digits else ""


# --- Web Push (E16-T09) -------------------------------------------------------------------------


@dataclass(frozen=True)
class PushTarget:
    endpoint: str
    p256dh: str
    auth: str


@dataclass(frozen=True)
class PushResult:
    status: int  # the push service's HTTP status

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    @property
    def gone(self) -> bool:
        """The subscription expired or was revoked: forget it."""
        return self.status in {404, 410}


class PushProvider(Protocol):
    def send(
        self, target: PushTarget, payload: bytes, *, ttl: int, urgency: str, topic: str
    ) -> PushResult: ...


def push_host(endpoint: str) -> str:
    """The push service's host, if the endpoint is an https URL on an allowed service."""
    parts = urllib.parse.urlsplit(endpoint.strip())
    host = (parts.hostname or "").rstrip(".").lower()
    if parts.scheme != "https" or parts.username or parts.password or not host:
        raise ValueError("not an https push endpoint")
    if parts.port not in {None, 443}:
        raise ValueError("non-standard port")
    allowed = settings.WEB_PUSH["ALLOWED_HOSTS"]
    if not any(host == h or host.endswith("." + h) for h in allowed):
        raise ValueError("unknown push service")
    return host


class WebPush:
    """Encrypts and signs with ``pywebpush``/``py_vapid``; sends via ``safe_urlopen``."""

    def __init__(self) -> None:
        self.private_key = settings.WEB_PUSH["VAPID_PRIVATE_KEY"]
        self.subject = settings.WEB_PUSH["VAPID_SUBJECT"]

    def headers(self, endpoint: str, *, ttl: int, urgency: str, topic: str) -> dict[str, str]:
        from py_vapid import Vapid

        parts = urllib.parse.urlsplit(endpoint)
        claims: dict[str, Any] = {
            "aud": f"{parts.scheme}://{parts.netloc}",
            "sub": self.subject,
            "exp": int(time.time()) + 12 * 60 * 60,
        }
        headers = dict(Vapid.from_string(private_key=self.private_key).sign(claims))
        headers.update(
            {
                "TTL": str(ttl),
                "Urgency": urgency,
                "Content-Encoding": "aes128gcm",
                "Content-Type": "application/octet-stream",
            }
        )
        if topic:
            headers["Topic"] = topic
        return headers

    def encrypt(self, target: PushTarget, payload: bytes) -> bytes:
        from pywebpush import WebPusher

        keys = {"p256dh": target.p256dh, "auth": target.auth}
        encoded = WebPusher({"endpoint": target.endpoint, "keys": keys}).encode(payload)
        return bytes(encoded["body"])

    def send(
        self, target: PushTarget, payload: bytes, *, ttl: int, urgency: str, topic: str
    ) -> PushResult:
        from tutortrack.core.net import UnsafeURL, safe_urlopen

        try:
            push_host(target.endpoint)
            body = self.encrypt(target, payload)
            headers = self.headers(target.endpoint, ttl=ttl, urgency=urgency, topic=topic)
            with safe_urlopen(
                target.endpoint, data=body, headers=headers, method="POST", timeout=10
            ) as response:
                return PushResult(int(response.status))
        except urllib.error.HTTPError as exc:
            return PushResult(int(exc.code))
        except (ValueError, UnsafeURL) as exc:
            # Never the URL in the message: endpoints are secrets.
            raise ChannelError(f"Push endpoint refused ({type(exc).__name__}).") from None
        except (urllib.error.URLError, OSError) as exc:
            raise ChannelError(f"Push service unreachable ({type(exc).__name__}).") from None


class FakePush:
    """Records pushes (no VAPID key: development and tests). Endpoints in ``gone`` answer
    410 Gone, like an expired subscription."""

    def __init__(self) -> None:
        self.outbox: list[dict[str, Any]] = []
        self.gone: set[str] = set()

    def send(
        self, target: PushTarget, payload: bytes, *, ttl: int, urgency: str, topic: str
    ) -> PushResult:
        if target.endpoint in self.gone:
            return PushResult(410)
        self.outbox.append(
            {
                "endpoint": target.endpoint,
                "payload": json.loads(payload),
                "ttl": ttl,
                "urgency": urgency,
                "topic": topic,
            }
        )
        return PushResult(201)


@cache
def push_provider() -> PushProvider:
    if settings.WEB_PUSH["VAPID_PRIVATE_KEY"]:
        return WebPush()
    return FakePush()
