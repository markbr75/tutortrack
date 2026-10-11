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
    "LedgerRejected",
    "LedgerTaxCode",
    "TrackingCategory",
    "client_for",
]

PROVIDERS = ("xero", "quickbooks")
CAPABILITY = "accounting"
MANAGE = "integrations.accounting.manage"


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
            ("organisation",),
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
            ("organisation",),
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
