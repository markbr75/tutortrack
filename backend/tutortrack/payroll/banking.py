"""Bank details: validation per country and masking (FR-12-2).

Details are a small dict stored encrypted as JSON. Supported shapes:

* UK: ``sort_code`` (6 digits) and ``account_number`` (8 digits)
* IBAN countries: ``iban`` (mod-97 checked) and optional ``bic``
* US: ``routing_number`` (ABA checksum), ``account_number`` and ``account_type``
* AU: ``bsb`` (6 digits) and ``account_number`` (6 to 9 digits)
* elsewhere: ``account_number`` and optional ``bank_code``
"""

from __future__ import annotations

import json
import re
from typing import Any

from django.utils.translation import gettext as _

from tutortrack.core.exceptions import BusinessRuleViolation

IBAN_COUNTRIES = {
    "AT", "BE", "BG", "CH", "CY", "CZ", "DE", "DK", "EE", "ES", "FI", "FR", "GR", "HR", "HU",
    "IE", "IS", "IT", "LI", "LT", "LU", "LV", "MT", "NL", "NO", "PL", "PT", "RO", "SE", "SI",
    "SK",
}  # fmt: skip


def _digits(value: Any) -> str:
    return re.sub(r"\D", "", str(value or ""))


def _fail(field: str, message: str) -> BusinessRuleViolation:
    return BusinessRuleViolation(message, extra={"errors": {field: [message]}})


def iban_valid(iban: str) -> bool:
    iban = iban.replace(" ", "").upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{10,30}", iban):
        return False
    rearranged = iban[4:] + iban[:4]
    number = "".join(str(int(ch, 36)) for ch in rearranged)
    return int(number) % 97 == 1


def aba_routing_valid(routing: str) -> bool:
    if not re.fullmatch(r"\d{9}", routing):
        return False
    d = [int(c) for c in routing]
    return (3 * (d[0] + d[3] + d[6]) + 7 * (d[1] + d[4] + d[7]) + (d[2] + d[5] + d[8])) % 10 == 0


def clean(country: str, details: dict[str, Any]) -> dict[str, str]:
    """Validate and normalise; raises a field error for the first problem."""
    country = country.upper()
    name = str(details.get("account_name", "")).strip()[:70]
    if not name:
        raise _fail("account_name", _("Enter the name on the account."))
    out: dict[str, str] = {"account_name": name}
    if country == "GB":
        sort_code, account = (
            _digits(details.get("sort_code")),
            _digits(details.get("account_number")),
        )
        if len(sort_code) != 6:
            raise _fail("sort_code", _("A sort code has 6 digits."))
        if len(account) != 8:
            raise _fail("account_number", _("A UK account number has 8 digits."))
        out.update(sort_code=sort_code, account_number=account)
    elif country in IBAN_COUNTRIES:
        iban = str(details.get("iban", "")).replace(" ", "").upper()
        if not iban_valid(iban):
            raise _fail("iban", _("Check the IBAN."))
        bic = str(details.get("bic", "")).replace(" ", "").upper()
        if bic and not re.fullmatch(r"[A-Z]{6}[A-Z0-9]{2}([A-Z0-9]{3})?", bic):
            raise _fail("bic", _("Check the BIC."))
        out.update(iban=iban, bic=bic)
    elif country == "US":
        routing, account = (
            _digits(details.get("routing_number")),
            _digits(details.get("account_number")),
        )
        if not aba_routing_valid(routing):
            raise _fail("routing_number", _("Check the routing number."))
        if not 4 <= len(account) <= 17:
            raise _fail("account_number", _("Check the account number."))
        kind = str(details.get("account_type", "checking"))
        if kind not in ("checking", "savings"):
            raise _fail("account_type", _("Choose checking or savings."))
        out.update(routing_number=routing, account_number=account, account_type=kind)
    elif country == "AU":
        bsb, account = _digits(details.get("bsb")), _digits(details.get("account_number"))
        if len(bsb) != 6:
            raise _fail("bsb", _("A BSB has 6 digits."))
        if not 6 <= len(account) <= 9:
            raise _fail("account_number", _("Check the account number."))
        out.update(bsb=bsb, account_number=account)
    else:
        account = re.sub(r"\s", "", str(details.get("account_number", "")))
        if len(account) < 4:
            raise _fail("account_number", _("Check the account number."))
        out.update(account_number=account, bank_code=str(details.get("bank_code", ""))[:20])
    return out


def hint(details: dict[str, str]) -> str:
    """e.g. ``••3456`` (never more than the last four characters)."""
    key = details.get("iban") or details.get("account_number") or ""
    return f"••{key[-4:]}" if key else ""


def mask(details: dict[str, str]) -> dict[str, str]:
    masked = {}
    for key, value in details.items():
        if key in ("account_name", "account_type", "bic", "bank_code"):
            masked[key] = value
        else:
            masked[key] = "•" * max(len(value) - 4, 0) + value[-4:]
    return masked


def dumps(details: dict[str, str]) -> str:
    return json.dumps(details, sort_keys=True)


def loads(raw: str) -> dict[str, str]:
    return json.loads(raw) if raw else {}
