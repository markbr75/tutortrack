"""Prevent negative balance (FR-09-1, TutorCruncher parity): registered with delivery.

A prepaid client (their job bills from prepaid credit) needs enough available credit,
plus their credit limit, to cover the lesson before a tutor can complete it.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Any

from tutortrack.core.money import Money
from tutortrack.delivery.balance import Shortfall
from tutortrack.tenancy.settings_service import get_setting

from . import ledger


class PrepaidBalanceGuard:
    def shortfalls(self, lesson: Any, charges: list[tuple[Any, Decimal]]) -> list[Shortfall]:
        if not (lesson.job_id and lesson.job.billing_method == "prepaid_credit"):
            return []
        needed: dict[Any, Money] = defaultdict(lambda: Money.zero(lesson.job.currency))
        clients = {}
        for attendee, percent in charges:
            if attendee.charge_amount is None:
                continue
            clients[attendee.client_id] = attendee.client
            price = (attendee.charge_amount * percent / Decimal(100)).round_to_minor()
            needed[attendee.client_id] = needed[attendee.client_id] + price
        out = []
        for client_id, need in needed.items():
            client = clients[client_id]
            prevent = client.prevent_negative_balance
            if prevent is None:
                prevent = bool(get_setting("billing.prevent_negative_balance"))
            if not prevent:
                continue
            balances = ledger.balances(client, need.currency)
            limit = Money(client.credit_limit_amount or Decimal(0), need.currency)
            available = balances.available_credit - balances.uninvoiced + limit
            if available < need:
                out.append(
                    Shortfall(str(client_id), client.display_name, balances.available_credit, need)
                )
        return out
