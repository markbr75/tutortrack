"""Bank statement parsers (E11-T13): CSV, OFX/QFX and CAMT.053. Each returns plain rows;
``bank.import_rows`` stores and matches them.

* **CSV:** headers are recognised by common names (date, amount or paid in/paid out,
  description, reference, id); dates in ISO, UK (day first) or, with ``month_first``,
  US order; amounts with currency symbols, thousands separators or brackets.
* **OFX:** SGML (v1) or XML (v2) ``<STMTTRN>`` blocks.
* **CAMT.053:** ``Ntry`` entries (namespaces ignored). Documents with a DTD or entities are
  refused (XML entity attacks).
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

MAX_ROWS = 20000


class StatementError(ValueError):
    pass


@dataclass
class Row:
    booked_on: date
    amount: Decimal  # credits positive
    description: str = ""
    reference: str = ""
    counterparty: str = ""
    external_id: str = ""
    currency: str = ""


@dataclass
class Parsed:
    rows: list[Row] = field(default_factory=list)
    currency: str = ""
    account_name: str = ""


def detect(filename: str, content: bytes) -> str:
    name = filename.lower()
    head = content[:2000].decode("utf-8", errors="ignore").lower()
    if name.endswith((".ofx", ".qfx")) or "<ofx>" in head or "ofxheader" in head:
        return "ofx"
    if name.endswith(".xml") or "camt.053" in head or "<bktocstmrstmt" in head:
        return "camt"
    return "csv"


def parse(source: str, content: bytes, *, month_first: bool = False) -> Parsed:
    if source == "ofx":
        parsed = parse_ofx(content)
    elif source == "camt":
        parsed = parse_camt(content)
    else:
        parsed = parse_csv(content, month_first=month_first)
    if len(parsed.rows) > MAX_ROWS:
        raise StatementError(f"Statements can have at most {MAX_ROWS} lines.")
    fill_ids(parsed.rows)
    return parsed


def fill_ids(rows: list[Row]) -> None:
    """Rows without a bank id get a stable hash (with a counter for identical lines), so
    importing the same file twice adds nothing."""
    seen: dict[str, int] = {}
    for row in rows:
        if row.external_id:
            continue
        base = "|".join(
            [row.booked_on.isoformat(), str(row.amount), row.description, row.reference]
        )
        seen[base] = seen.get(base, 0) + 1
        row.external_id = "h:" + hashlib.sha256(f"{base}|{seen[base]}".encode()).hexdigest()[:40]


# --- CSV ---------------------------------------------------------------------------------------

DATE_NAMES = (
    "date",
    "transaction date",
    "booking date",
    "posted date",
    "posting date",
    "value date",
    "completed date",
)
AMOUNT_NAMES = (
    "amount",
    "value",
    "transaction amount",
    "amount (gbp)",
    "amount (eur)",
    "amount (usd)",
)
CREDIT_NAMES = ("paid in", "money in", "credit", "credit amount", "deposits", "in")
DEBIT_NAMES = ("paid out", "money out", "debit", "debit amount", "withdrawals", "out")
DESCRIPTION_NAMES = (
    "description",
    "details",
    "narrative",
    "transaction description",
    "memo",
    "particulars",
    "name",
    "payee",
)
REFERENCE_NAMES = ("reference", "ref", "payment reference", "transaction reference")
COUNTERPARTY_NAMES = ("counterparty", "payer", "from", "counter party", "beneficiary")
ID_NAMES = ("id", "transaction id", "fitid", "bank reference")
CURRENCY_NAMES = ("currency", "ccy")


def _find(headers: list[str], names: tuple[str, ...]) -> int | None:
    for name in names:
        if name in headers:
            return headers.index(name)
    return None


def to_decimal(value: str) -> Decimal | None:
    text = (value or "").strip()
    if not text:
        return None
    negative = (text.startswith("(") and text.endswith(")")) or text.endswith("-")
    cleaned = re.sub(r"[^0-9.,\-]", "", text)
    if "," in cleaned and "." in cleaned:
        cleaned = (
            cleaned.replace(",", "")
            if cleaned.rfind(".") > cleaned.rfind(",")
            else (cleaned.replace(".", "").replace(",", "."))
        )
    elif "," in cleaned and re.search(r",\d{2}$", cleaned):
        cleaned = cleaned.replace(",", ".")
    else:
        cleaned = cleaned.replace(",", "")
    cleaned = cleaned.rstrip("-")
    try:
        number = Decimal(cleaned)
    except InvalidOperation:
        return None
    return -abs(number) if negative else number


def to_date(value: str, *, month_first: bool = False) -> date | None:
    text = (value or "").strip()[:19]
    formats = ["%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y/%m/%d", "%d %b %Y", "%d %B %Y", "%d-%b-%Y"]
    formats += ["%m/%d/%Y", "%m/%d/%y"] if month_first else ["%d/%m/%Y", "%d/%m/%y"]
    formats += ["%d-%m-%Y", "%d.%m.%Y"]
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).date()  # noqa: DTZ007 - a date
        except ValueError:
            continue
    return None


def parse_csv(content: bytes, *, month_first: bool = False) -> Parsed:
    text = content.decode("utf-8-sig", errors="replace")
    try:
        dialect: Any = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    lines = [row for row in reader if any(cell.strip() for cell in row)]
    if not lines:
        raise StatementError("The file is empty.")
    headers = [h.strip().lower() for h in lines[0]]
    columns = {
        "date": _find(headers, DATE_NAMES),
        "amount": _find(headers, AMOUNT_NAMES),
        "credit": _find(headers, CREDIT_NAMES),
        "debit": _find(headers, DEBIT_NAMES),
        "description": _find(headers, DESCRIPTION_NAMES),
        "reference": _find(headers, REFERENCE_NAMES),
        "counterparty": _find(headers, COUNTERPARTY_NAMES),
        "id": _find(headers, ID_NAMES),
        "currency": _find(headers, CURRENCY_NAMES),
    }
    if columns["date"] is None or (columns["amount"] is None and columns["credit"] is None):
        raise StatementError("Couldn't find the date and amount columns.")

    def cell(row: list[str], key: str) -> str:
        index = columns[key]
        return row[index].strip() if index is not None and index < len(row) else ""

    out = Parsed()
    for number, row in enumerate(lines[1:], start=2):
        day = to_date(cell(row, "date"), month_first=month_first)
        if columns["amount"] is not None:
            amount = to_decimal(cell(row, "amount"))
        else:
            credit = to_decimal(cell(row, "credit")) or Decimal(0)
            debit = to_decimal(cell(row, "debit")) or Decimal(0)
            amount = abs(credit) - abs(debit)
        if day is None or amount is None:
            raise StatementError(f"Line {number}: couldn't read the date or amount.")
        out.rows.append(
            Row(
                booked_on=day,
                amount=amount,
                description=cell(row, "description")[:500],
                reference=cell(row, "reference")[:200],
                counterparty=cell(row, "counterparty")[:200],
                external_id=cell(row, "id")[:120],
                currency=cell(row, "currency").upper()[:3],
            )
        )
    return out


# --- OFX ---------------------------------------------------------------------------------------


def _ofx_value(block: str, tag: str) -> str:
    match = re.search(rf"<{tag}>([^<\r\n]*)", block, re.IGNORECASE)
    return match.group(1).strip() if match else ""


def parse_ofx(content: bytes) -> Parsed:
    text = content.decode("utf-8", errors="replace")
    if "<!doctype" in text.lower() or "<!entity" in text.lower():
        raise StatementError("This file type isn't supported.")
    out = Parsed(
        currency=_ofx_value(text, "CURDEF").upper()[:3],
        account_name=_ofx_value(text, "ACCTID")[-8:],
    )
    for block in re.findall(
        r"<STMTTRN>(.*?)(?:</STMTTRN>|(?=<STMTTRN>)|(?=</BANKTRANLIST>))",
        text,
        re.IGNORECASE | re.DOTALL,
    ):
        posted = _ofx_value(block, "DTPOSTED")[:8]
        amount = to_decimal(_ofx_value(block, "TRNAMT"))
        try:
            day = datetime.strptime(posted, "%Y%m%d").date()  # noqa: DTZ007 - a date
        except ValueError as exc:
            raise StatementError("A transaction has no readable date.") from exc
        if amount is None:
            raise StatementError("A transaction has no readable amount.")
        name, memo = _ofx_value(block, "NAME"), _ofx_value(block, "MEMO")
        out.rows.append(
            Row(
                booked_on=day,
                amount=amount,
                description=" ".join(p for p in (name, memo) if p)[:500],
                reference=(_ofx_value(block, "REFNUM") or _ofx_value(block, "CHECKNUM") or memo)[
                    :200
                ],
                counterparty=name[:200],
                external_id=("ofx:" + _ofx_value(block, "FITID"))[:120]
                if _ofx_value(block, "FITID")
                else "",
                currency=out.currency,
            )
        )
    if not out.rows and "<stmttrn>" not in text.lower():
        raise StatementError("No transactions found in the OFX file.")
    return out


# --- CAMT.053 ----------------------------------------------------------------------------------


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(node: ET.Element, *path: str) -> ET.Element | None:
    current: ET.Element | None = node
    for name in path:
        if current is None:
            return None
        current = next((c for c in current if _local(c.tag) == name), None)
    return current


def _text(node: ET.Element, *path: str) -> str:
    found = _child(node, *path)
    return (found.text or "").strip() if found is not None and found.text else ""


def _all(node: ET.Element, name: str) -> list[ET.Element]:
    return [n for n in node.iter() if _local(n.tag) == name]


def parse_camt(content: bytes) -> Parsed:
    head = content[:4096].lower()
    if b"<!doctype" in head or b"<!entity" in content.lower():
        raise StatementError("This file type isn't supported.")
    try:
        root = ET.fromstring(content)  # noqa: S314 - no DTD/entities (checked above)
    except ET.ParseError as exc:
        raise StatementError("The XML file couldn't be read.") from exc
    out = Parsed()
    statements = _all(root, "Stmt")
    if statements:
        out.account_name = _text(statements[0], "Acct", "Id", "IBAN")[-8:]
        out.currency = _text(statements[0], "Acct", "Ccy").upper()
    for entry in _all(root, "Ntry"):
        amount_node = _child(entry, "Amt")
        if amount_node is None or not amount_node.text:
            continue
        amount = Decimal(amount_node.text.strip())
        if _text(entry, "CdtDbtInd") == "DBIT":
            amount = -amount
        day_text = _text(entry, "BookgDt", "Dt") or _text(entry, "BookgDt", "DtTm")[:10]
        day = to_date(day_text)
        if day is None:
            raise StatementError("An entry has no booking date.")
        details = _all(entry, "TxDtls")
        detail = details[0] if details else entry
        unstructured = " ".join(n.text.strip() for n in _all(detail, "Ustrd") if n.text)
        structured = _text(detail, "RmtInf", "Strd", "CdtrRefInf", "Ref")
        debtor = _text(detail, "RltdPties", "Dbtr", "Nm") or _text(
            detail, "RltdPties", "Dbtr", "Pty", "Nm"
        )
        ref = _text(entry, "AcctSvcrRef") or _text(entry, "NtryRef")
        out.rows.append(
            Row(
                booked_on=day,
                amount=amount,
                description=(unstructured or _text(entry, "AddtlNtryInf"))[:500],
                reference=(structured or _text(detail, "Refs", "EndToEndId") or unstructured)[:200],
                counterparty=debtor[:200],
                external_id=("camt:" + ref)[:120] if ref else "",
                currency=(amount_node.get("Ccy") or out.currency).upper(),
            )
        )
    return out
