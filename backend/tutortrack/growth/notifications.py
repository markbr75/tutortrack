"""Messages for reviews and affiliates (E25), on the E13 registry."""

from __future__ import annotations

from typing import Any

from django.utils.translation import gettext_lazy as _

from tutortrack.comms.catalogue import (
    SAMPLE_BASE,
    client_contacts,
    contact_recipient,
    organisation,
    tenant_link,
)
from tutortrack.comms.defaults import DEFAULTS, SIGN
from tutortrack.comms.registry import Delivery, NotificationType, Recipient, register


def _review_request(payload: Any) -> list[Delivery]:
    from .models import ReviewRequest

    request_id, token, reminder = payload
    request = (
        ReviewRequest.objects.select_related("client", "contact", "tutor")
        .filter(pk=request_id)
        .first()
    )
    if request is None:
        return []
    contacts = [request.contact] if request.contact else client_contacts(request.client)
    tutor = request.tutor
    review = {
        "tutor": (tutor.display_name or tutor.first_name) if tutor else "",
        "link": tenant_link(f"/review/{token}"),
        "reminder": bool(reminder),
    }
    return [
        Delivery(
            contact_recipient(c),
            {
                "organisation": organisation(),
                "recipient": {"name": c.full_name, "first_name": c.first_name},
                "review": review,
            },
        )
        for c in contacts
        if c is not None
    ]


def load_statement(pk: Any) -> Any:
    from .models import AffiliateStatement

    return AffiliateStatement.objects.select_related("affiliate").filter(pk=pk).first()


def _statement(statement_id: Any) -> list[Delivery]:
    statement = load_statement(statement_id)
    if statement is None:
        return []
    affiliate = statement.affiliate
    first = affiliate.name.split()[0] if affiliate.name else ""
    return [
        Delivery(
            Recipient(
                kind="affiliate",
                id=str(affiliate.pk),
                name=affiliate.name,
                first_name=first,
                email=affiliate.email,
                user_id=str(affiliate.user_id) if affiliate.user_id else None,
            ),
            {
                "organisation": organisation(),
                "recipient": {"name": affiliate.name, "first_name": first},
                "statement": {
                    "number": statement.number,
                    "period_end": statement.period_end.isoformat(),
                    "total": statement.total.format(),
                    "link": tenant_link("/portal/affiliate"),
                },
            },
        )
    ]


register(
    NotificationType(
        key="review_request",
        label=str(_("Review request")),
        category="account",
        audience="client",
        channels=("email", "sms"),
        default_channels=("email",),
        resolve=_review_request,
        load=lambda pk: None,
        related_type="",
        variables=("review.tutor", "review.link", "review.reminder"),
        sample={
            **SAMPLE_BASE,
            "review": {"tutor": "Nia", "link": "https://example.com", "reminder": False},
        },
    )
)
register(
    NotificationType(
        key="affiliate_statement_issued",
        label=str(_("Affiliate commission statement")),
        category="billing",
        audience="affiliate",
        channels=("email",),
        default_channels=("email",),
        resolve=_statement,
        load=load_statement,
        related_type="growth.affiliatestatement",
        variables=("statement.number", "statement.period_end", "statement.total", "statement.link"),
        sample={
            **SAMPLE_BASE,
            "statement": {
                "number": "AFS-000001",
                "period_end": "2026-09-30",
                "total": "£120.00",
                "link": "https://example.com",
            },
        },
        transactional=True,
    )
)

DEFAULTS[("review_request", "email")] = (
    "{% if review.reminder %}Reminder: {% endif %}How are lessons going"
    "{% if review.tutor %} with {{ review.tutor }}{% endif %}?",
    "Hello {{ recipient.first_name }},\n\nWe'd love to hear how lessons are going"
    "{% if review.tutor %} with {{ review.tutor }}{% endif %}. It takes a minute: "
    "{{ review.link }}" + SIGN,
)
DEFAULTS[("review_request", "sms")] = (
    "",
    "{{ organisation.name }}: how are lessons going? Leave a quick review: {{ review.link }}",
)
DEFAULTS[("affiliate_statement_issued", "email")] = (
    "Your commission statement {{ statement.number }}",
    "Hello {{ recipient.first_name }},\n\nYour commission statement {{ statement.number }} "
    "to {{ statement.period_end }} is ready: {{ statement.total }}.\n\n"
    "See the details in your partner portal: {{ statement.link }}" + SIGN,
)
