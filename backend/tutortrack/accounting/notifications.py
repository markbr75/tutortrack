"""Notifications about accounting sync (E13 catalogue entry registered by this app):
``accounting_sync_errors``, a daily digest of records that need someone (FR-23-3), sent to
staff with ``integrations.accounting.manage`` (Finance)."""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _lazy

from tutortrack.comms import catalogue
from tutortrack.comms.defaults import DEFAULTS, SIGN
from tutortrack.comms.registry import NotificationType, register

LINK = "/settings/accounting"

register(
    NotificationType(
        key="accounting_sync_errors",
        label=str(_lazy("Accounting sync errors (daily digest)")),
        category="staff",
        audience="staff",
        channels=("in_app", "email"),
        default_channels=("in_app", "email"),
        resolve=catalogue._alert("integrations.accounting.manage"),
        load=lambda pk: None,
        related_type="",
        variables=("alert.title", "alert.body", "alert.link"),
        sample=catalogue.SAMPLE_ALERT,
        link=lambda payload: payload[2],
    )
)
DEFAULTS[("accounting_sync_errors", "in_app")] = ("{{ alert.title }}", "{{ alert.body }}")
DEFAULTS[("accounting_sync_errors", "email")] = (
    "{{ alert.title }}",
    "{{ alert.body }}\n\n{{ alert.link }}" + SIGN,
)


def notify_digest(conn: Any, errors: list[Any], *, total: int) -> None:
    from tutortrack.comms import services as comms

    from .errors import LABELS

    label = LABELS.get(conn.provider, conn.provider)
    title = _("%(count)s records didn't sync to %(provider)s") % {
        "count": total,
        "provider": label,
    }
    body = "\n".join(f"• {link.label}: {link.error}" for link in errors)
    payload = (title, body, LINK)
    key = f"accounting-digest:{conn.pk}:{conn.last_digest_at or ''}:{total}"
    transaction.on_commit(lambda: comms.notify("accounting_sync_errors", payload, key=key))
