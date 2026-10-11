"""Human-readable sync errors (FR-23-3): what went wrong and what to do about it, in the
finance team's words rather than the provider's."""

from __future__ import annotations

import re
from dataclasses import dataclass

from django.utils.translation import gettext as _

from tutortrack.integrations.providers import (
    AuthError,
    ConfigurationError,
    NotFound,
    ProviderError,
    RateLimited,
    Rejected,
)

from .providers.base import LedgerRejected

LABELS = {"xero": "Xero", "quickbooks": "QuickBooks"}


class MappingMissing(ProviderError):
    """Nothing to send it to: an account or tax mapping is missing."""

    retryable = False

    def __init__(self, message: str, code: str = "mapping_missing"):
        super().__init__(message)
        self.code = code


class PeriodLocked(ProviderError):
    retryable = False
    code = "period_locked"


class PrerequisiteMissing(ProviderError):
    """Something it depends on (the contact, the invoice) isn't in the ledger yet."""

    retryable = False
    code = "waiting"


@dataclass(frozen=True)
class Explained:
    code: str
    message: str
    retryable: bool


_ARCHIVED = re.compile(r"Account code '?([\w-]+)'? has been archived", re.IGNORECASE)
_TAX = re.compile(r"TaxType code '?([\w-]+)'? does not exist", re.IGNORECASE)


def explain(provider: str, exc: Exception) -> Explained:
    label = LABELS.get(provider, provider)
    text = str(exc)
    code = getattr(exc, "code", "") or ""
    if isinstance(exc, AuthError):
        return Explained(
            "reconnect",
            _("%(provider)s needs reconnecting: our access was revoked or expired.")
            % {"provider": label},
            False,
        )
    if isinstance(exc, RateLimited):
        return Explained(
            "rate_limited",
            _("%(provider)s is limiting how fast we send; we'll retry shortly.")
            % {"provider": label},
            True,
        )
    if isinstance(exc, MappingMissing | PrerequisiteMissing | PeriodLocked):
        return Explained(code or "rejected", text, False)
    match = _ARCHIVED.search(text)
    if match:
        return Explained(
            "account_archived",
            _(
                "Account code %(code)s is archived in %(provider)s. Choose another account in "
                "the mappings, then retry."
            )
            % {"code": match.group(1), "provider": label},
            False,
        )
    match = _TAX.search(text)
    if match:
        return Explained(
            "tax_code",
            _("The tax code %(code)s doesn't exist in %(provider)s. Check the tax mappings.")
            % {"code": match.group(1), "provider": label},
            False,
        )
    if code == "period_locked" or "lock date" in text.lower() or "closed period" in text.lower():
        return Explained(
            "period_locked",
            _("The accounting period is locked in %(provider)s.") % {"provider": label},
            False,
        )
    if "duplicate" in text.lower():
        return Explained(
            "duplicate",
            _("%(provider)s already has a record with this number: %(detail)s")
            % {"provider": label, "detail": text[:200]},
            False,
        )
    if isinstance(exc, NotFound):
        return Explained(
            "not_found",
            _("A linked record no longer exists in %(provider)s (deleted there?): %(detail)s")
            % {"provider": label, "detail": text[:200]},
            False,
        )
    if isinstance(exc, LedgerRejected | Rejected | ConfigurationError):
        return Explained(
            code or "rejected",
            _("%(provider)s rejected it: %(detail)s") % {"provider": label, "detail": text[:300]},
            False,
        )
    return Explained(
        "unavailable",
        _("Couldn't reach %(provider)s (%(detail)s); we'll retry.")
        % {"provider": label, "detail": text[:200]},
        getattr(exc, "retryable", True),
    )
