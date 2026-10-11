"""Account, tax and tracking mappings (FR-23-1): what each kind of money posts to, and
whether a mapping set is complete enough to switch sync on.

A *mapping set* is a provider key (``xero``, ``quickbooks``) or ``export`` (GL files,
where an account is just its code). Lookups go from the most specific key to
``default``; revenue also falls back to the account code saved on the service or product
(``Service.revenue_account_code``, ``Product.account_code``) when the ledger has it.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _lazy

from .errors import MappingMissing
from .models import AccountingConnection, AccountMapping, TaxMapping, TrackingMapping

EXPORT = "export"

# kind -> label; the order is the mapping form's order.
KINDS: dict[str, Any] = {
    "revenue": _lazy("Sales (revenue)"),
    "clearing": _lazy("Payments received into (clearing or bank)"),
    "bank": _lazy("Bank account for payouts"),
    "fees": _lazy("Payment provider fees (expense)"),
    "tutor_cost": _lazy("Tutor costs (cost of sales)"),
    "expense": _lazy("Tutor expenses"),
    "bad_debt": _lazy("Bad debts (write-offs)"),
    "rounding": _lazy("Rounding"),
    "receivable": _lazy("Accounts receivable"),
    "payable": _lazy("Accounts payable (tutors)"),
    "sales_tax": _lazy("Sales tax (VAT) liability"),
}
ALWAYS = ("revenue", "clearing", "bank", "fees", "bad_debt")
JOURNAL = ("receivable", "sales_tax", "rounding")
EXPORT_REQUIRED = (*ALWAYS, "tutor_cost", "receivable", "payable", "sales_tax", "rounding")


@dataclass(frozen=True)
class AccountRef:
    id: str
    code: str = ""
    name: str = ""


def required_kinds(conn: AccountingConnection | None) -> tuple[str, ...]:
    if conn is None:
        return EXPORT_REQUIRED
    kinds = list(ALWAYS)
    if conn.sync_bills:
        kinds.append("tutor_cost")
    if conn.mode == AccountingConnection.Mode.SUMMARY:
        kinds.extend(JOURNAL)
    return tuple(kinds)


class Mappings:
    """One mapping set, loaded once per build."""

    def __init__(self, provider: str, chart: dict[str, Any] | None = None):
        self.provider = provider
        self.accounts = {
            (m.kind, m.key): AccountRef(m.external_id, m.code, m.name)
            for m in AccountMapping.objects.filter(provider=provider)
        }
        self.taxes = {
            (str(m.tax_rate_id) if m.tax_rate_id else ""): m.external_id
            for m in TaxMapping.objects.filter(provider=provider)
        }
        self.tracking = {
            str(m.branch_id): (m.category_id, m.option_id)
            for m in TrackingMapping.objects.filter(provider=provider)
        }
        self.by_code = {
            str(a.get("code")): AccountRef(str(a["id"]), str(a.get("code", "")), str(a["name"]))
            for a in (chart or {}).get("accounts", [])
            if a.get("code") and a.get("active", True)
        }

    def find(self, kind: str, *keys: str) -> AccountRef | None:
        for key in (*keys, "default"):
            if key and (kind, key) in self.accounts:
                return self.accounts[(kind, key)]
        return None

    def account(self, kind: str, *keys: str, code: str = "") -> AccountRef:
        found = self.find(kind, *keys)
        if found is None and code:
            found = AccountRef(code, code) if self.provider == EXPORT else self.by_code.get(code)
            if found is not None:
                return found
        if found is None:
            raise MappingMissing(
                _("Map an account for “%(kind)s” before syncing.") % {"kind": KINDS[kind]}
            )
        return found

    def tax_code(self, tax_rate_id: Any, percent: Decimal = Decimal(0)) -> str:
        key = str(tax_rate_id) if tax_rate_id else ""
        if key in self.taxes:
            return self.taxes[key]
        if not key and percent == 0 and "" in self.taxes:
            return self.taxes[""]
        if not key and percent:
            from tutortrack.catalogue.models import TaxRate

            rate = TaxRate.objects.filter(percent=percent).order_by("-is_default").first()
            if rate is not None and str(rate.pk) in self.taxes:
                return self.taxes[str(rate.pk)]
        raise MappingMissing(
            _("Map a tax code for the %(percent)s%% tax rate before syncing.")
            % {"percent": percent.normalize() if percent else 0},
            "tax_mapping_missing",
        )

    def tracking_for(self, branch_id: Any) -> tuple[tuple[str, str], ...]:
        found = self.tracking.get(str(branch_id)) if branch_id else None
        return (found,) if found else ()


def problems(provider: str, conn: AccountingConnection | None) -> list[dict[str, str]]:
    """What stops sync being switched on (FR-23-1 validation)."""
    from tutortrack.catalogue.models import TaxRate

    chart = (conn.chart if conn is not None else {}) or {}
    accounts = {str(a["id"]): a for a in chart.get("accounts", [])}
    tax_codes = {str(t["id"]) for t in chart.get("tax_codes", [])}
    out: list[dict[str, str]] = []
    mapped = {(m.kind, m.key): m for m in AccountMapping.objects.filter(provider=provider)}
    for kind in required_kinds(conn):
        mapping = mapped.get((kind, "default"))
        if mapping is None:
            out.append(
                {
                    "kind": kind,
                    "key": "default",
                    "message": _("Choose an account for “%(kind)s”.") % {"kind": KINDS[kind]},
                }
            )
    if accounts:
        for (kind, key), mapping in mapped.items():
            if kind == "purchase_tax":  # a tax code, not an account
                continue
            account = accounts.get(mapping.external_id)
            if account is None or not account.get("active", True):
                out.append(
                    {
                        "kind": kind,
                        "key": key,
                        "message": _("The account mapped for “%(kind)s” is archived or deleted.")
                        % {"kind": KINDS.get(kind, kind)},
                    }
                )
    taxes = {
        (str(m.tax_rate_id) if m.tax_rate_id else ""): m
        for m in TaxMapping.objects.filter(provider=provider)
    }
    wanted = [("", _("No tax"))] + [
        (str(rate.pk), str(rate)) for rate in TaxRate.objects.filter(active=True)
    ]
    for key, label in wanted:
        tax = taxes.get(key)
        if tax is None:
            out.append(
                {
                    "kind": "tax",
                    "key": key,
                    "message": _("Choose a tax code for “%(rate)s”.") % {"rate": label},
                }
            )
        elif tax_codes and provider != EXPORT and tax.external_id not in tax_codes:
            out.append(
                {
                    "kind": "tax",
                    "key": key,
                    "message": _("The tax code mapped for “%(rate)s” no longer exists.")
                    % {"rate": label},
                }
            )
    return out
