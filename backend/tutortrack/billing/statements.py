"""Scheduled, emailed client statements (FR-10-9, gap G3).

With ``billing.statement_schedule = monthly`` a per-organisation **Temporal Schedule**
(``StatementRunWorkflow``, kept in sync with the settings) runs on
``billing.statement_day`` at 07:00 local time. It emails last month's statement (opening
balance, movements, closing balance, ageing; PDF attached) to the invoice contacts of every
client who had account activity in the month or still has a balance, per currency. Each
statement is sent once: the comms dedupe key is the client, currency and period.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from django.db import transaction
from django.db.models import Sum

from tutortrack.core.context import require_organisation_id
from tutortrack.core.events import publish
from tutortrack.tenancy.settings_service import get_setting

from . import events, selectors
from .models import ClientLedgerEntry

NOTIFICATION = "client_statement"


@dataclass(frozen=True)
class StatementSubject:
    """What a statement email is about; ``pk`` lets comms rebuild it to attach the PDF."""

    client: Any
    currency: str
    start: date
    end: date

    @property
    def pk(self) -> str:
        return f"{self.client.pk}:{self.currency}:{self.start:%Y%m%d}:{self.end:%Y%m%d}"

    def data(self) -> selectors.Statement:
        from tutortrack.tenancy.models import Organisation

        tz = Organisation.objects.get(pk=require_organisation_id()).timezone
        return selectors.statement(self.client, self.currency, self.start, self.end, tz)


def load(pk: str) -> StatementSubject | None:
    from tutortrack.people.models import Client

    try:
        client_id, currency, start, end = pk.split(":")
        first = date(int(start[:4]), int(start[4:6]), int(start[6:8]))
        last = date(int(end[:4]), int(end[4:6]), int(end[6:8]))
    except ValueError:
        return None
    client = Client.objects.filter(pk=client_id).first()
    return StatementSubject(client, currency, first, last) if client else None


def last_month(today: date) -> tuple[date, date]:
    end = today.replace(day=1) - timedelta(days=1)
    return end.replace(day=1), end


def due(start: date, end: date) -> list[tuple[str, str]]:
    """``(client id, currency)`` pairs with ledger movements in the period or a balance at
    its end (statements of nothing aren't sent)."""
    from tutortrack.core.time import local_date_range_to_utc
    from tutortrack.tenancy.models import Organisation

    tz = Organisation.objects.get(pk=require_organisation_id()).timezone
    since, until = local_date_range_to_utc(start, end, tz)
    active = set(
        ClientLedgerEntry.objects.filter(occurred_at__gte=since, occurred_at__lt=until)
        .values_list("client_id", "currency")
        .distinct()
    )
    balances = (
        ClientLedgerEntry.objects.filter(occurred_at__lt=until)
        .values("client_id", "currency")
        .annotate(total=Sum("amount_amount"))
        .exclude(total=0)
    )
    owing = {(row["client_id"], row["currency"]) for row in balances}
    return sorted((str(c), cur) for c, cur in active | owing)


def send(client_ids: list[str], start: date, end: date) -> int:
    """Email the statements (idempotent per client, currency and period)."""
    from tutortrack.comms.services import notify
    from tutortrack.people.models import Client

    currencies: dict[str, list[str]] = {}
    for client_id, currency in due(start, end):
        currencies.setdefault(client_id, []).append(currency)
    sent = 0
    for client in Client.objects.filter(pk__in=client_ids):
        for currency in currencies.get(str(client.pk), []):
            subject = StatementSubject(client, currency, start, end)
            messages = notify(
                NOTIFICATION, subject, key=subject.pk, immediate=True, only_channel="email"
            )
            delivered = sum(1 for m in messages if m.status == "sent")
            if delivered:
                with transaction.atomic():
                    publish(
                        events.StatementSent(
                            subject_id=client.pk,
                            currency=currency,
                            period_start=start.isoformat(),
                            period_end=end.isoformat(),
                        ),
                        branch_id=client.branch_id,
                        dedupe_key=f"statement:{subject.pk}",
                    )
            sent += delivered
    return sent


def schedule_enabled() -> bool:
    return get_setting("billing.statement_schedule") == "monthly"


def sync_schedule() -> str:
    """Create, update or delete the organisation's statement schedule."""
    from tutortrack.core.workflows.schedules import delete_schedule, ensure_schedule, schedule_id
    from tutortrack.tenancy.models import Organisation

    from .processes import STATEMENT_PROCESS, StatementRunInput, StatementRunWorkflow

    org_id = require_organisation_id()
    if not schedule_enabled():
        delete_schedule(org_id, schedule_id(STATEMENT_PROCESS, org_id))
        return ""
    day = min(int(get_setting("billing.statement_day")), 28)
    org = Organisation.objects.get(pk=org_id)
    return ensure_schedule(
        process=STATEMENT_PROCESS,
        workflow=StatementRunWorkflow,
        input=StatementRunInput(organisation_id=str(org_id)),
        cron=[f"0 7 {day} * *"],
        timezone=str(org.timezone),
    )
