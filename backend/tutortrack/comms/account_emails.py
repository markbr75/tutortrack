"""Identity and account emails on branded, editable comms templates (G4; E02/E03 carried
forward to E13).

Verification, magic links, password resets, invitations, email-change links and notices,
new-device and impossible-travel alerts, security alerts and the closure notice are E13
notification types in the ``account`` category. They are *locked*: an organisation can
edit their wording (per language and branch, like any template) but can't switch them
off, because sign-in depends on them.

Sending (``send``):

* **Inside an organisation** (the email is about a membership there, or was asked for on
  its address): the organisation's override is rendered with the sandboxed renderer if
  there is one, otherwise the translated platform text; either way the email gets the
  organisation's branding, sender name and verified sending domain, and is recorded in the
  message log. Links that carry a secret token (``secret`` values) are never stored: the
  logged copy has them replaced with "[link hidden]".
* **No organisation** (platform sign-in, an account with no membership yet): the platform
  template, translated into the user's language, from the platform sender. Nothing is
  logged (there is no tenant to log it in).
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import translation
from django.utils.translation import gettext_lazy as _l

from tutortrack.core.context import tenant_context

from .defaults import DEFAULTS
from .registry import NotificationType, register

logger = structlog.get_logger(__name__)
HIDDEN = "[link hidden]"

# key: (label, variables, sample)
ACCOUNT_TYPES: dict[str, tuple[Any, tuple[str, ...], dict[str, Any]]] = {
    "account_verify_email": (_l("Confirm your email address"), ("link",), {}),
    "account_magic_link": (_l("Sign-in link"), ("link",), {}),
    "account_password_reset": (_l("Password reset"), ("link",), {}),
    "account_invitation": (
        _l("Invitation to join"),
        ("link", "invite.inviter", "invite.organisation"),
        {"invite": {"inviter": "Sam Lee", "organisation": "Bright Minds Tutoring"}},
    ),
    "account_email_change_verify": (_l("Confirm a new email address"), ("link",), {}),
    "account_email_change_notice": (
        _l("Email address changed"),
        ("email.new", "email.done"),
        {"email": {"new": "priya.new@example.com", "done": True}},
    ),
    "account_new_device": (
        _l("New sign-in alert"),
        ("device.user_agent", "device.ip"),
        {"device": {"user_agent": "Firefox on Windows", "ip": "203.0.113.7"}},
    ),
    "account_impossible_travel": (
        _l("Sign-in from a new country"),
        ("travel.country", "travel.previous_country", "travel.ip"),
        {"travel": {"country": "FR", "previous_country": "GB", "ip": "203.0.113.7"}},
    ),
    "account_security_alert": (
        _l("Security alert"),
        ("alert.kind", "alert.detail", "alert.who"),
        {"alert": {"kind": "mass_export", "detail": "6 exports", "who": "Sam Lee"}},
    ),
    "account_closure_notice": (
        _l("Account closed"),
        ("closure.days", "closure.deletion_date"),
        {"closure": {"days": 30, "deletion_date": "2026-11-13"}},
    ),
}


def _no_recipients(payload: Any) -> list[Any]:
    return []  # sent by ``send`` below, never through ``notify``


for _key, (_label, _vars, _sample) in ACCOUNT_TYPES.items():
    register(
        NotificationType(
            key=_key,
            label=str(_label),
            category="account",
            audience="user",
            channels=("email",),
            default_channels=("email",),
            resolve=_no_recipients,
            load=lambda pk: None,
            related_type="",
            variables=("recipient.first_name", "organisation.name", *_vars),
            sample={
                "organisation": {"name": "Bright Minds Tutoring", "timezone": "Europe/London"},
                "recipient": {"name": "Priya Patel", "first_name": "Priya"},
                "link": "https://brightminds.tutortrack.app/…",
                **_sample,
            },
            transactional=True,
            locked=True,
        )
    )

# Starting points for the editor (the translated platform text is used until an
# organisation saves its own version).
HELLO = "Hi {{ recipient.first_name }},\n\n"
DEFAULTS.update(
    {
        ("account_verify_email", "email"): (
            "Confirm your email address",
            HELLO + "Please confirm your email address to finish setting up your account:"
            "\n\n{{ link }}\n\nThe link expires in 3 days. If you didn't sign up, you can "
            "ignore this email.",
        ),
        ("account_magic_link", "email"): (
            "Your sign-in link",
            HELLO + "Use this link to sign in. It works once and expires in 15 minutes:\n\n"
            "{{ link }}\n\nIf you didn't ask for it, you can ignore this email.",
        ),
        ("account_password_reset", "email"): (
            "Reset your password",
            HELLO + "Use this link to choose a new password. It expires in 1 hour:\n\n"
            "{{ link }}\n\nIf you didn't ask to reset your password, you can ignore this email.",
        ),
        ("account_invitation", "email"): (
            "You're invited to join {{ invite.organisation }}",
            "{{ invite.inviter }} has invited you to join {{ invite.organisation }}.\n\n"
            "Accept the invitation (the link expires in 7 days):\n\n{{ link }}",
        ),
        ("account_email_change_verify", "email"): (
            "Confirm your new email address",
            HELLO + "Use this link to confirm this as the new email address for your account. "
            "It expires in 24 hours:\n\n{{ link }}\n\nIf you didn't ask for this, you can "
            "ignore this email: nothing changes until the link is used.",
        ),
        ("account_email_change_notice", "email"): (
            "{% if email.done %}Your email address has changed"
            "{% else %}A change of email address was requested{% endif %}",
            "{% if email.done %}The email address for your account is now {{ email.new }}. "
            "Other devices have been signed out.{% else %}Someone asked to change the email "
            "address for your account to {{ email.new }}. Nothing changes until the new "
            "address is confirmed.{% endif %}\n\nIf this wasn't you, reset your password "
            "straight away and contact us.",
        ),
        ("account_new_device", "email"): (
            "New sign-in to your account",
            HELLO + "Your account was just used to sign in from a new device:\n\n"
            "{{ device.user_agent }}\nIP address: {{ device.ip }}\n\nIf this was you, there's "
            "nothing to do. If not, change your password now and sign out of all devices.",
        ),
        ("account_impossible_travel", "email"): (
            "Sign-in from a new country on your account",
            HELLO + "Your account was just used to sign in from {{ travel.country }}, shortly "
            "after a sign-in from {{ travel.previous_country }}.\n\nIP address: {{ travel.ip }}"
            "\n\nIf you use a VPN or were travelling, there's nothing to do. If not, change "
            "your password now and turn on two-step verification.",
        ),
        ("account_security_alert", "email"): (
            "Security alert on your account",
            "We noticed unusual activity in your organisation: {{ alert.kind }}: "
            "{{ alert.detail }} ({{ alert.who }}).\n\nIf this was expected, there's nothing to "
            "do. Otherwise review the audit log and the person's access in Team settings.",
        ),
        ("account_closure_notice", "email"): (
            "Your account has been closed",
            "The account for {{ organisation.name }} has been closed. We will keep your data "
            "for {{ closure.days }} days; it will be permanently deleted on or after "
            "{{ closure.deletion_date }}.",
        ),
    }
)


def _redact(text: str, secrets: tuple[str, ...]) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, HIDDEN)
    return text


def send(
    type_key: str,
    *,
    to: str,
    subject: str,
    django_template: str,
    legacy: dict[str, Any],
    variables: dict[str, Any],
    first_name: str = "",
    locale: str = "en-GB",
    organisation_id: Any = None,
    secrets: tuple[str, ...] = (),
    recipient: tuple[str, str] = ("user", ""),
) -> None:
    """Send one account email (see the module docstring). ``subject`` and
    ``django_template`` + ``legacy`` are the translated platform text; ``variables`` are
    the sandboxed template's values (``link`` and the type's own)."""
    with translation.override(locale or settings.LANGUAGE_CODE):
        if organisation_id is None:
            send_mail(
                subject=str(subject),
                message=render_to_string(django_template, legacy),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[to],
            )
            return
        with tenant_context(organisation_id):
            _send_branded(
                type_key,
                to=to,
                subject=str(subject),
                text=render_to_string(django_template, legacy),
                variables=variables,
                first_name=first_name,
                locale=locale,
                secrets=secrets,
                recipient=recipient,
            )


def _send_branded(
    type_key: str,
    *,
    to: str,
    subject: str,
    text: str,
    variables: dict[str, Any],
    first_name: str,
    locale: str,
    secrets: tuple[str, ...],
    recipient: tuple[str, str],
) -> None:
    from tutortrack.core import branding
    from tutortrack.core.context import require_organisation_id
    from tutortrack.core.time import now

    from . import channels, render, senders, services
    from .catalogue import organisation
    from .models import Message

    org = organisation()
    override = services._override(type_key, "email", locale, None)
    if override is not None:
        context = {
            "organisation": org,
            "recipient": {"name": first_name, "first_name": first_name},
            **variables,
        }
        try:
            subject = render.render(override.subject, context, timezone=org["timezone"])
            text = render.render(override.body, context, timezone=org["timezone"])
        except render.TemplateInvalid as exc:  # a broken override never blocks sign-in
            logger.warning("comms.account_template_invalid", type_key=type_key, error=str(exc))
    organisation_id = require_organisation_id()
    name = services._organisation_name()
    channels.send_email(
        to=to,
        subject=subject,
        text=text,
        html=render.to_html(text, organisation=name, brand=branding.for_email(organisation_id)),
        from_name=name,
        reply_to="",
        headers={"X-PM-Metadata-org": str(organisation_id)},
        attachments=[],
        from_address=senders.from_address(),
    )
    Message.objects.create(
        type_key=type_key,
        channel="email",
        recipient_type=recipient[0],
        recipient_id=(recipient[1] or to)[:64],
        recipient_name=first_name[:200],
        to=to.lower(),
        subject=_redact(subject, secrets)[:300],
        body=_redact(text, secrets),
        status=Message.Status.SENT,
        dedupe_key=f"{type_key}:{uuid.uuid4()}",
        sent_at=now(),
    )
