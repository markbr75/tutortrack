"""Billing notifications added with gap G3, on the E13 registry (owned by this app):

* ``client_statement``: the monthly statement email with its PDF (FR-10-9);
* ``tutor_invoice_review``: tutors are asked to check their lessons on draft invoices
  (FR-10-3), in-app first;
* ``staff_invoice_review_flagged``: staff alert when a tutor reports a problem (the drafts
  are held).
"""

from __future__ import annotations

from typing import Any

from django.utils.translation import gettext_lazy as _

from tutortrack.comms.catalogue import (
    SAMPLE_ALERT,
    SAMPLE_BASE,
    _alert,
    _billing_deliveries,
    organisation,
    tenant_link,
    tutor_recipient,
)
from tutortrack.comms.defaults import DEFAULTS, SIGN
from tutortrack.comms.registry import Delivery, NotificationType, register

from . import statements

# --- monthly statements ------------------------------------------------------------------------


def _money(value: Any) -> dict[str, str]:
    return value.round_to_minor().to_dict()


def _statement(subject: statements.StatementSubject) -> list[Delivery]:
    data = subject.data()
    return _billing_deliveries(
        subject.client,
        {
            "statement": {
                "start": subject.start.isoformat(),
                "end": subject.end.isoformat(),
                "opening": _money(data.opening),
                "closing": _money(data.closing),
            }
        },
    )


def _statement_pdf(subject: statements.StatementSubject) -> list[tuple[str, bytes, str]]:
    from . import pdf

    name = f"statement-{subject.end.isoformat()}-{subject.currency}.pdf"
    return [(name, pdf.statement_pdf(subject.client, subject.data()), "application/pdf")]


register(
    NotificationType(
        key=statements.NOTIFICATION,
        label=str(_("Monthly statement (with the PDF)")),
        category="billing",
        audience="client",
        channels=("email",),
        default_channels=("email",),
        resolve=_statement,
        load=statements.load,
        related_type="people.client",
        variables=(
            "recipient.first_name",
            "statement.start",
            "statement.end",
            "statement.opening",
            "statement.closing",
        ),
        sample={
            **SAMPLE_BASE,
            "statement": {
                "start": "2026-09-01",
                "end": "2026-09-30",
                "opening": {"amount": "40.00", "currency": "GBP"},
                "closing": {"amount": "120.00", "currency": "GBP"},
            },
        },
        transactional=True,
        attachments=_statement_pdf,
    )
)
DEFAULTS[(statements.NOTIFICATION, "email")] = (
    "Your statement to {{ statement.end|date }}",
    "Hello {{ recipient.first_name }},\n\nHere is your statement for "
    "{{ statement.start|date }} to {{ statement.end|date }}. Your balance at the end of the "
    "period was {{ statement.closing|money }}. The PDF is attached." + SIGN,
)


# --- tutor pre-review of drafts ------------------------------------------------------------------

REVIEW_PATH = "/portal/tutor/invoice-review"


def load_run(pk: str) -> Any:
    from .models import InvoiceRun

    return InvoiceRun.objects.filter(pk=pk).first()


def _tutor_review(payload: Any) -> list[Delivery]:
    run, tutor = payload
    r = tutor_recipient(tutor)
    return [
        Delivery(
            r,
            {
                "organisation": organisation(),
                "recipient": {"name": r.name, "first_name": r.first_name},
                "review": {
                    "until": run.review_until.isoformat() if run.review_until else "",
                    "link": tenant_link(REVIEW_PATH),
                },
            },
        )
    ]


register(
    NotificationType(
        key="tutor_invoice_review",
        label=str(_("Check your lessons before invoices go out (to the tutor)")),
        category="billing",
        audience="tutor",
        channels=("in_app", "email"),
        default_channels=("in_app", "email"),
        resolve=_tutor_review,
        load=load_run,
        related_type="billing.invoicerun",
        variables=("recipient.first_name", "review.until", "review.link"),
        sample={
            **SAMPLE_BASE,
            "review": {"until": "2026-11-03T09:00:00Z", "link": "https://example.test/x"},
        },
        link=lambda payload: REVIEW_PATH,
    )
)
DEFAULTS[("tutor_invoice_review", "in_app")] = (
    "Please check your lessons",
    "Invoices are about to go out. Check your lessons on them by {{ review.until|date }}.",
)
DEFAULTS[("tutor_invoice_review", "email")] = (
    "Please check your lessons before invoices go out",
    "Hello {{ recipient.first_name }},\n\nInvoices for your lessons are about to be sent. "
    "Please check that the lessons are right by {{ review.until|date }}: {{ review.link }}" + SIGN,
)

register(
    NotificationType(
        key="staff_invoice_review_flagged",
        label=str(_("A tutor reported a problem with draft invoices")),
        category="staff",
        audience="staff",
        channels=("in_app", "email"),
        default_channels=("in_app",),
        resolve=_alert("billing.invoice.issue"),
        load=lambda pk: None,
        related_type="",
        variables=("alert.title", "alert.body", "alert.link"),
        sample=SAMPLE_ALERT,
        link=lambda payload: payload[2],
    )
)
DEFAULTS[("staff_invoice_review_flagged", "in_app")] = ("{{ alert.title }}", "{{ alert.body }}")
DEFAULTS[("staff_invoice_review_flagged", "email")] = (
    "{{ alert.title }}",
    "{{ alert.body }}\n\n{{ alert.link }}" + SIGN,
)
