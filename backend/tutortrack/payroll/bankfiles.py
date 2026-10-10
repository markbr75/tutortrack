"""Bank payment files for pay runs (FR-12-7). Each writer is a pure function of its input,
so golden-file tests pin the exact output.

* ``csv``: one row per payment, for banks with a CSV bulk upload.
* ``bacs18``: UK BACS Standard 18 payment records (100 characters each) with a contra
  record, in the layout bulk-payment bureaux accept.
* ``sepa``: ISO 20022 ``pain.001.001.03`` credit transfer (EUR only).
* ``nacha``: US ACH PPD credits (94-character records, blocked to 10).
* ``aba``: Australian Bankers' Association (Cemtext) direct entry file.
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from xml.sax.saxutils import escape

from django.utils.translation import gettext as _

from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.money import Money


@dataclass(frozen=True)
class Line:
    payee: str
    details: dict[str, str]
    amount: Money
    reference: str


@dataclass(frozen=True)
class Originator:
    name: str
    details: dict[str, str]
    # NACHA: company id and immediate destination; ABA: APCA user id and bank (e.g. "CBA").
    extra: dict[str, str]


FORMATS = ("csv", "bacs18", "sepa", "nacha", "aba")
FORMAT_CHOICES = [(f, f.upper()) for f in FORMATS]
CURRENCY = {"bacs18": "GBP", "sepa": "EUR", "nacha": "USD", "aba": "AUD"}


def _ascii(value: str, length: int | None = None, *, upper: bool = True) -> str:
    text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    text = re.sub(r"[^A-Za-z0-9 .&/-]", " ", text)
    text = text.upper() if upper else text
    return text if length is None else text[:length].ljust(length)


def _cents(amount: Money) -> int:
    return amount.to_minor()


def _need(line: Line, *keys: str) -> None:
    missing = [k for k in keys if not line.details.get(k)]
    if missing:
        raise BusinessRuleViolation(
            _("%(payee)s has no %(what)s for this file format.")
            % {"payee": line.payee, "what": ", ".join(missing)}
        )


def write(
    fmt: str, originator: Originator, lines: Sequence[Line], *, when: datetime, file_id: str
) -> tuple[str, str]:
    """Returns ``(filename, content)``."""
    if fmt not in FORMATS:
        raise BusinessRuleViolation(_("Unknown bank file format."))
    currency = CURRENCY.get(fmt)
    if currency and any(line.amount.currency != currency for line in lines):
        raise BusinessRuleViolation(
            _("This format only pays %(currency)s.") % {"currency": currency}
        )
    writer = {"csv": _csv, "bacs18": _bacs18, "sepa": _sepa, "nacha": _nacha, "aba": _aba}[fmt]
    extension = {"sepa": "xml", "csv": "csv"}.get(fmt, "txt")
    return f"{file_id}.{extension}", writer(originator, lines, when, file_id)


def _csv(originator: Originator, lines: Sequence[Line], when: datetime, file_id: str) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    fields = ["sort_code", "account_number", "iban", "bic", "routing_number", "bsb"]
    writer.writerow(["payee_name", *fields, "amount", "currency", "reference"])
    for line in lines:
        writer.writerow([
            line.details.get("account_name") or line.payee,
            *(line.details.get(f, "") for f in fields),
            f"{line.amount.amount:.2f}", line.amount.currency, line.reference[:18],
        ])  # fmt: skip
    return out.getvalue()


def _bacs18(originator: Originator, lines: Sequence[Line], when: datetime, file_id: str) -> str:
    origin = originator.details
    if not (origin.get("sort_code") and origin.get("account_number")):
        raise BusinessRuleViolation(_("Add your sort code and account number in pay settings."))
    rows = []
    for line in lines:
        _need(line, "sort_code", "account_number")
        rows.append(
            line.details["sort_code"] + line.details["account_number"] + "0" + "99"
            + origin["sort_code"] + origin["account_number"] + " " * 4
            + f"{_cents(line.amount):011d}"
            + _ascii(originator.name, 18) + _ascii(line.reference, 18)
            + _ascii(line.details.get("account_name") or line.payee, 18)
        )  # fmt: skip
    total = sum(_cents(line.amount) for line in lines)
    rows.append(
        origin["sort_code"] + origin["account_number"] + "0" + "17"
        + origin["sort_code"] + origin["account_number"] + " " * 4
        + f"{total:011d}" + _ascii(originator.name, 18) + _ascii("CONTRA", 18)
        + _ascii(originator.name, 18)
    )  # fmt: skip
    return "\n".join(rows) + "\n"


def _sepa(originator: Originator, lines: Sequence[Line], when: datetime, file_id: str) -> str:
    origin = originator.details
    if not origin.get("iban"):
        raise BusinessRuleViolation(_("Add your IBAN in pay settings."))
    total = sum((line.amount.amount for line in lines), Decimal(0))
    stamp = when.strftime("%Y-%m-%dT%H:%M:%S")
    debtor_agent = (
        f"<DbtrAgt><FinInstnId><BIC>{origin['bic']}</BIC></FinInstnId></DbtrAgt>"
        if origin.get("bic") else
        "<DbtrAgt><FinInstnId><Othr><Id>NOTPROVIDED</Id></Othr></FinInstnId></DbtrAgt>"
    )  # fmt: skip
    txs = []
    for i, line in enumerate(lines, 1):
        _need(line, "iban")
        agent = (
            f"<CdtrAgt><FinInstnId><BIC>{line.details['bic']}</BIC></FinInstnId></CdtrAgt>"
            if line.details.get("bic") else ""
        )  # fmt: skip
        txs.append(
            "<CdtTrfTxInf>"
            f"<PmtId><EndToEndId>{escape(file_id)}-{i}</EndToEndId></PmtId>"
            f'<Amt><InstdAmt Ccy="EUR">{line.amount.amount:.2f}</InstdAmt></Amt>'
            f"{agent}"
            f"<Cdtr><Nm>{escape(_ascii(line.details.get('account_name') or line.payee, upper=False).strip()[:70])}</Nm></Cdtr>"  # noqa: E501
            f"<CdtrAcct><Id><IBAN>{line.details['iban']}</IBAN></Id></CdtrAcct>"
            f"<RmtInf><Ustrd>{escape(line.reference[:140])}</Ustrd></RmtInf>"
            "</CdtTrfTxInf>"
        )
    name = escape(_ascii(originator.name, upper=False).strip()[:70])
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.001.001.03">'
        "<CstmrCdtTrfInitn>"
        f"<GrpHdr><MsgId>{escape(file_id)}</MsgId><CreDtTm>{stamp}</CreDtTm>"
        f"<NbOfTxs>{len(lines)}</NbOfTxs><CtrlSum>{total:.2f}</CtrlSum>"
        f"<InitgPty><Nm>{name}</Nm></InitgPty></GrpHdr>"
        f"<PmtInf><PmtInfId>{escape(file_id)}</PmtInfId><PmtMtd>TRF</PmtMtd>"
        f"<NbOfTxs>{len(lines)}</NbOfTxs><CtrlSum>{total:.2f}</CtrlSum>"
        "<PmtTpInf><SvcLvl><Cd>SEPA</Cd></SvcLvl></PmtTpInf>"
        f"<ReqdExctnDt>{when.date().isoformat()}</ReqdExctnDt>"
        f"<Dbtr><Nm>{name}</Nm></Dbtr>"
        f"<DbtrAcct><Id><IBAN>{origin['iban']}</IBAN></Id></DbtrAcct>"
        f"{debtor_agent}<ChrgBr>SLEV</ChrgBr>"
        + "".join(txs)
        + "</PmtInf></CstmrCdtTrfInitn></Document>\n"
    )


def _nacha(originator: Originator, lines: Sequence[Line], when: datetime, file_id: str) -> str:
    origin, extra = originator.details, originator.extra
    if not origin.get("routing_number") or not extra.get("company_id"):
        raise BusinessRuleViolation(
            _("Add your routing number and ACH company ID in pay settings.")
        )
    destination = extra.get("immediate_destination") or origin["routing_number"]
    odfi = origin["routing_number"][:8]
    ymd, hm = when.strftime("%y%m%d"), when.strftime("%H%M")
    records = [
        "1" + "01" + f" {destination[:9]}" + f" {origin['routing_number'][:9]}" + ymd + hm
        + "A" + "094" + "10" + "1"
        + _ascii(extra.get("destination_name", ""), 23) + _ascii(originator.name, 23)
        + _ascii(file_id, 8)
    ]  # fmt: skip
    records.append(
        "5" + "220" + _ascii(originator.name, 16) + " " * 20 + _ascii(extra["company_id"], 10)
        + "PPD" + _ascii("PAYROLL", 10) + ymd + ymd + "   " + "1" + odfi + "0000001"
    )  # fmt: skip
    entry_hash = 0
    total = 0
    for i, line in enumerate(lines, 1):
        _need(line, "routing_number", "account_number")
        routing = line.details["routing_number"]
        code = "32" if line.details.get("account_type") == "savings" else "22"
        cents = _cents(line.amount)
        entry_hash += int(routing[:8])
        total += cents
        records.append(
            "6" + code + routing[:8] + routing[8] + _ascii(line.details["account_number"], 17)
            + f"{cents:010d}" + _ascii(line.reference, 15)
            + _ascii(line.details.get("account_name") or line.payee, 22) + "  " + "0"
            + odfi + f"{i:07d}"
        )  # fmt: skip
    hash10 = f"{entry_hash % 10**10:010d}"
    count = len(lines)
    records.append(
        "8" + "220" + f"{count:06d}" + hash10 + f"{0:012d}" + f"{total:012d}"
        + _ascii(extra["company_id"], 10) + " " * 19 + " " * 6 + odfi + "0000001"
    )  # fmt: skip
    blocks = -(-(len(records) + 1) // 10)
    records.append(
        "9" + "000001" + f"{blocks:06d}" + f"{count:08d}" + hash10 + f"{0:012d}"
        + f"{total:012d}" + " " * 39
    )  # fmt: skip
    while len(records) % 10:
        records.append("9" * 94)
    return "\n".join(records) + "\n"


def _bsb(value: str) -> str:
    return f"{value[:3]}-{value[3:6]}"


def _aba(originator: Originator, lines: Sequence[Line], when: datetime, file_id: str) -> str:
    origin, extra = originator.details, originator.extra
    if not (origin.get("bsb") and origin.get("account_number") and extra.get("apca_id")):
        raise BusinessRuleViolation(
            _("Add your BSB, account number and APCA user ID in pay settings.")
        )
    process_date = when.strftime("%d%m%y")
    records = [
        "0" + " " * 17 + "01" + _ascii(extra.get("bank", ""), 3) + " " * 7
        + _ascii(originator.name, 26) + f"{int(_digits_only(extra['apca_id'])):06d}"
        + _ascii("PAYROLL", 12) + process_date + " " * 40
    ]  # fmt: skip
    total = 0
    for line in lines:
        _need(line, "bsb", "account_number")
        cents = _cents(line.amount)
        total += cents
        records.append(
            "1" + _bsb(line.details["bsb"]) + line.details["account_number"].rjust(9) + " "
            + "53" + f"{cents:010d}" + _ascii(line.details.get("account_name") or line.payee, 32)
            + _ascii(line.reference, 18) + _bsb(origin["bsb"])
            + origin["account_number"].rjust(9) + _ascii(originator.name, 16) + f"{0:08d}"
        )  # fmt: skip
    records.append(
        "7" + "999-999" + " " * 12 + f"{total:010d}" + f"{total:010d}" + f"{0:010d}"
        + " " * 24 + f"{len(lines):06d}" + " " * 40
    )  # fmt: skip
    return "\r\n".join(records) + "\r\n"


def _digits_only(value: str) -> str:
    return re.sub(r"\D", "", value) or "0"


def payment_date(when: datetime) -> date:
    return when.date()
