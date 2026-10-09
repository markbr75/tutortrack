"""Delivery channels (FR-13-1).

* **Email** goes through Django's mail backend (Postmark over SMTP in production,
  Mailpit locally). Our message id and organisation travel in ``X-PM-Metadata-*`` headers so
  Postmark's delivery webhooks can be matched back.
* **SMS** goes through Twilio's REST API (or a fake that records messages when Twilio isn't
  configured, for development and tests). The status callback carries the organisation and
  message id and is verified with Twilio's signature.
* SMS credits come from the subscription (E04), which registers ``set_credit_meter``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from functools import cache
from typing import Protocol

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
) -> str:
    sender = settings.DEFAULT_FROM_EMAIL
    address = sender.split("<")[-1].rstrip(">").strip()
    from_email = f'"{from_name}" <{address}>' if from_name else sender
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
    def send(self, *, to: str, body: str, status_callback: str) -> SmsResult: ...


class TwilioSms:
    def __init__(self) -> None:
        self.sid = settings.TWILIO["ACCOUNT_SID"]
        self.token = settings.TWILIO["AUTH_TOKEN"]
        self.sender = settings.TWILIO["FROM"]

    def send(self, *, to: str, body: str, status_callback: str) -> SmsResult:
        url = f"https://api.twilio.com/2010-04-01/Accounts/{self.sid}/Messages.json"
        data = urllib.parse.urlencode(
            {"To": to, "From": self.sender, "Body": body, "StatusCallback": status_callback}
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

    def send(self, *, to: str, body: str, status_callback: str) -> SmsResult:
        self.outbox.append({"to": to, "body": body, "status_callback": status_callback})
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
