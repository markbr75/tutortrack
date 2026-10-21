"""Accounting providers (E23), registered in the integration framework's registry with an
``accounting`` client kind. Without platform keys each gets the fake ledger."""

from __future__ import annotations

from typing import Any

from django.conf import settings

from tutortrack.integrations import providers as registry
from tutortrack.integrations.providers import Credentials, Provider, ProviderSpec

from .base import (
    AccountingClient,
    Chart,
    LedgerAccount,
    LedgerInfo,
    LedgerPayment,
    LedgerRejected,
    LedgerTaxCode,
    TrackingCategory,
)

__all__ = [
    "PROVIDERS",
    "AccountingClient",
    "Chart",
    "LedgerAccount",
    "LedgerInfo",
    "LedgerPayment",
    "LedgerRejected",
    "LedgerTaxCode",
    "TrackingCategory",
    "client_for",
]

PROVIDERS = ("xero", "quickbooks", "sage", "freeagent")  # Sage, FreeAgent: E23-T10
CAPABILITY = "accounting"
MANAGE = "integrations.accounting.manage"
# A ledger for the whole organisation, or a branch's own (gap G5: per-branch ledgers).
LEDGER_LEVELS = ("organisation", "branch")


def client_for(provider: str) -> AccountingClient:
    found: AccountingClient = registry.client(provider, "accounting")
    return found


def _live(*names: str) -> Any:
    return lambda: all(settings.INTEGRATIONS.get(n) for n in names)


def _xero_oauth() -> Any:
    from .xero import oauth_client

    return oauth_client()


def _xero() -> Any:
    from .xero import XeroClient

    return XeroClient()


def _qbo_oauth() -> Any:
    from .quickbooks import oauth_client

    return oauth_client()


def _qbo() -> Any:
    from .quickbooks import QuickBooksClient

    return QuickBooksClient()


def _fake(provider: str, rate: int) -> Any:
    def make() -> Any:
        from .fake import FakeAccountingClient

        return FakeAccountingClient(provider, rate)

    return make


def _health(provider: str) -> Any:
    def check(creds: Credentials) -> None:
        client_for(provider).info(creds)

    return check


def _scopes(module: str) -> tuple[str, ...]:
    import importlib

    found: tuple[str, ...] = importlib.import_module(f"{__name__}.{module}").SCOPES
    return found


registry.register(
    Provider(
        ProviderSpec(
            "xero",
            "Xero",
            frozenset({CAPABILITY}),
            "oauth2",
            LEDGER_LEVELS,
            manage_permission=MANAGE,
        ),
        live=_live("XERO_CLIENT_ID", "XERO_CLIENT_SECRET"),
        scopes=_scopes("xero"),
        oauth=_xero_oauth,
        clients={CAPABILITY: _xero},
        fake_clients={CAPABILITY: _fake("xero", 55)},
        health=_health("xero"),
    )
)
registry.register(
    Provider(
        ProviderSpec(
            "quickbooks",
            "QuickBooks Online",
            frozenset({CAPABILITY}),
            "oauth2",
            LEDGER_LEVELS,
            manage_permission=MANAGE,
        ),
        live=_live("QUICKBOOKS_CLIENT_ID", "QUICKBOOKS_CLIENT_SECRET"),
        scopes=_scopes("quickbooks"),
        oauth=_qbo_oauth,
        clients={CAPABILITY: _qbo},
        fake_clients={CAPABILITY: _fake("quickbooks", 400)},
        health=_health("quickbooks"),
    )
)


# --- E23-T10: Sage Business Cloud Accounting and FreeAgent ----------------------------------------


def _client(module: str, name: str) -> Any:
    def make() -> Any:
        import importlib

        return getattr(importlib.import_module(f"{__name__}.{module}"), name)()

    return make


def _oauth(module: str) -> Any:
    def make() -> Any:
        import importlib

        return importlib.import_module(f"{__name__}.{module}").oauth_client()

    return make


def _xero_payroll_oauth() -> Any:
    import dataclasses

    from .xero import oauth_client

    return dataclasses.replace(oauth_client(), provider="xero_payroll")


def _xero_payroll(fake: bool) -> Any:
    def make() -> Any:
        from .xero_payroll import FakeXeroPayroll, XeroPayrollClient

        return FakeXeroPayroll() if fake else XeroPayrollClient()

    return make


def payroll_client() -> Any:
    """Xero Payroll (E23-T10): the real API with platform keys, the fake otherwise."""
    return registry.client("xero_payroll", "payroll")


# Xero Payroll is its own connection (same Xero app, payroll scopes only), so organisations
# without Xero Payroll never get asked for payroll access when connecting their ledger.
registry.register(
    Provider(
        ProviderSpec(
            "xero_payroll",
            "Xero Payroll",
            frozenset({"payroll"}),
            "oauth2",
            ("organisation",),
            manage_permission=MANAGE,
        ),
        live=_live("XERO_CLIENT_ID", "XERO_CLIENT_SECRET"),
        scopes=("openid", "profile", "email", "offline_access", *_scopes("xero_payroll")),
        oauth=_xero_payroll_oauth,
        clients={"payroll": _xero_payroll(False)},
        fake_clients={"payroll": _xero_payroll(True)},
    )
)

for _key, _label, _module, _class, _rate in (
    ("sage", "Sage Business Cloud Accounting", "sage", "SageClient", 100),
    ("freeagent", "FreeAgent", "freeagent", "FreeAgentClient", 100),
):
    registry.register(
        Provider(
            ProviderSpec(
                _key,
                _label,
                frozenset({CAPABILITY}),
                "oauth2",
                LEDGER_LEVELS,
                manage_permission=MANAGE,
            ),
            live=_live(f"{_key.upper()}_CLIENT_ID", f"{_key.upper()}_CLIENT_SECRET"),
            scopes=_scopes(_module),
            oauth=_oauth(_module),
            clients={CAPABILITY: _client(_module, _class)},
            fake_clients={CAPABILITY: _fake(_key, _rate)},
            health=_health(_key),
        )
    )
