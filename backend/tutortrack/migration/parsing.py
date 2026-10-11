"""Reading uploaded spreadsheets (FR-28-1): CSV (any common delimiter and encoding) and
XLSX (read directly from the Office Open XML package, no extra dependency).

Untrusted input: XML parts declaring a DTD or entities are refused (XXE / billion laughs),
the uncompressed size of the package is capped (zip bombs) and so is the row count.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from xml.etree import ElementTree as ET

MAX_ROWS = 50_000
MAX_COLUMNS = 200
MAX_UNCOMPRESSED = 200 * 1024 * 1024
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PKG_REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"
DATE_FORMAT_IDS = {14, 15, 16, 17, 18, 19, 20, 21, 22, 45, 46, 47}
EXCEL_EPOCH = datetime(1899, 12, 30)  # noqa: DTZ001 - a naive calendar origin


class SpreadsheetError(ValueError):
    pass


@dataclass
class Table:
    headers: list[str]
    rows: list[dict[str, str]]
    sheets: list[str] = field(default_factory=list)
    truncated: bool = False


# --- CSV ----------------------------------------------------------------------------------------


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16") if data[:2] in (b"\xff\xfe", b"\xfe\xff") else ():
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def _dialect(sample: str) -> type[csv.Dialect] | csv.Dialect:
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        return csv.excel


def read_csv(data: bytes) -> list[list[str]]:
    text = _decode(data)
    dialect = _dialect(text[:8192])
    out = []
    for row in csv.reader(io.StringIO(text), dialect):
        out.append([cell.strip() for cell in row[:MAX_COLUMNS]])
        if len(out) > MAX_ROWS + 20:
            break
    return out


# --- XLSX ---------------------------------------------------------------------------------------


def _xml(archive: zipfile.ZipFile, name: str) -> ET.Element | None:
    try:
        data = archive.read(name)
    except KeyError:
        return None
    head = data[:2048].upper()
    if b"<!DOCTYPE" in head or b"<!ENTITY" in data.upper():
        raise SpreadsheetError("The spreadsheet contains unsupported XML declarations.")
    return ET.fromstring(data)  # noqa: S314 - DTD/entities refused above


def _col_index(ref: str) -> int:
    letters = re.match(r"[A-Z]+", ref.upper())
    index = 0
    for ch in letters.group(0) if letters else "A":
        index = index * 26 + (ord(ch) - 64)
    return index - 1


def _date_styles(archive: zipfile.ZipFile) -> set[int]:
    """Indices of cell formats (``s`` attribute) that display dates."""
    styles = _xml(archive, "xl/styles.xml")
    if styles is None:
        return set()
    custom: set[int] = set()
    num_fmts = styles.find(f"{NS}numFmts")
    for fmt in num_fmts if num_fmts is not None else []:
        code = re.sub(r'"[^"]*"|\[[^\]]*\]', "", fmt.get("formatCode", "")).lower()
        if any(ch in code for ch in "dy") or ("m" in code and "h" not in code and "0" not in code):
            custom.add(int(fmt.get("numFmtId", "0")))
    out = set()
    xfs = styles.find(f"{NS}cellXfs")
    for index, xf in enumerate(xfs if xfs is not None else []):
        fmt_id = int(xf.get("numFmtId", "0"))
        if fmt_id in DATE_FORMAT_IDS or fmt_id in custom:
            out.add(index)
    return out


def _serial_to_text(value: str, *, with_time: bool) -> str:
    try:
        moment = EXCEL_EPOCH + timedelta(days=float(value))
    except (ValueError, OverflowError):
        return value
    if with_time and (moment.hour or moment.minute or moment.second):
        return moment.strftime("%Y-%m-%d %H:%M")
    return moment.strftime("%Y-%m-%d")


def _number_text(value: str) -> str:
    try:
        number = float(value)
    except ValueError:
        return value
    if number.is_integer() and "e" not in value.lower() and abs(number) < 1e15:
        return str(int(number))
    return value


def read_xlsx(data: bytes, sheet: str = "") -> tuple[list[list[str]], list[str]]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise SpreadsheetError("This isn't a valid Excel (.xlsx) file.") from exc
    with archive:
        if sum(info.file_size for info in archive.infolist()) > MAX_UNCOMPRESSED:
            raise SpreadsheetError("The spreadsheet is too large.")
        workbook = _xml(archive, "xl/workbook.xml")
        if workbook is None:
            raise SpreadsheetError("This isn't a valid Excel (.xlsx) file.")
        rels = _xml(archive, "xl/_rels/workbook.xml.rels")
        targets = {
            r.get("Id"): r.get("Target", "")
            for r in (rels if rels is not None else [])
            if r.tag == f"{PKG_REL_NS}Relationship"
        }
        sheets_el = workbook.find(f"{NS}sheets")
        sheets = [
            (s.get("name", ""), targets.get(s.get(f"{REL_NS}id"), ""))
            for s in (sheets_el if sheets_el is not None else [])
        ]
        if not sheets:
            raise SpreadsheetError("The workbook has no sheets.")
        names = [name for name, _target in sheets]
        chosen = next((s for s in sheets if s[0] == sheet), sheets[0])
        target = chosen[1].lstrip("/")
        path = target if target.startswith("xl/") else f"xl/{target}"
        shared: list[str] = []
        sst = _xml(archive, "xl/sharedStrings.xml")
        for si in sst if sst is not None else []:
            shared.append("".join(t.text or "" for t in si.iter(f"{NS}t")))
        dates = _date_styles(archive)
        root = _xml(archive, path)
        if root is None:
            raise SpreadsheetError("The sheet could not be read.")
        rows: list[list[str]] = []
        data_el = root.find(f"{NS}sheetData")
        for row_el in data_el if data_el is not None else []:
            cells: dict[int, str] = {}
            for c in row_el.findall(f"{NS}c"):
                index = _col_index(c.get("r", "A"))
                if index >= MAX_COLUMNS:
                    continue
                kind = c.get("t", "n")
                v = c.find(f"{NS}v")
                raw = v.text if v is not None and v.text is not None else ""
                if kind == "s":
                    text = shared[int(raw)] if raw.isdigit() and int(raw) < len(shared) else ""
                elif kind == "inlineStr":
                    text = "".join(t.text or "" for t in c.iter(f"{NS}t"))
                elif kind == "b":
                    text = "TRUE" if raw == "1" else "FALSE"
                elif kind in ("str", "e", "d"):
                    text = raw
                elif raw and int(c.get("s", "0") or 0) in dates:
                    text = _serial_to_text(raw, with_time=True)
                else:
                    text = _number_text(raw)
                cells[index] = text.strip()
            if cells:
                width = max(cells) + 1
                position = int(row_el.get("r", "0") or 0)
                while position and len(rows) < position - 1:
                    rows.append([])  # keep blank rows so row numbers match the sheet
                rows.append([cells.get(i, "") for i in range(width)])
            if len(rows) > MAX_ROWS + 20:
                break
        return rows, names


# --- tables -------------------------------------------------------------------------------------


def _header_index(rows: list[list[str]]) -> int:
    """The first row that looks like headers: about as full as the fullest early row (title
    rows such as "Export from ..." are skipped) and mostly text."""
    sample = rows[:20]
    widest = max((sum(1 for c in row if c) for row in sample), default=0)
    for index, row in enumerate(sample):
        filled = [c for c in row if c]
        texty = sum(1 for c in filled if not NUMBER.fullmatch(c))
        if filled and len(filled) * 10 >= widest * 6 and texty * 2 >= len(filled):
            return index
    return 0


def _unique_headers(raw: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for position, name in enumerate(raw, start=1):
        name = name.strip() or f"Column {position}"
        if name in seen:
            seen[name] += 1
            name = f"{name} ({seen[name]})"
        else:
            seen[name] = 1
        out.append(name[:120])
    return out


def to_table(rows: list[list[str]], header_row: int | None = None) -> Table:
    if not rows:
        raise SpreadsheetError("The file is empty.")
    start = _header_index(rows) if header_row is None else max(header_row - 1, 0)
    headers = _unique_headers(rows[start])
    out = []
    for row in rows[start + 1 :]:
        if not any(cell.strip() for cell in row):
            continue
        out.append({h: (row[i] if i < len(row) else "") for i, h in enumerate(headers)})
    truncated = len(out) > MAX_ROWS
    if not out:
        raise SpreadsheetError("The file has headers but no rows.")
    return Table(headers=headers, rows=out[:MAX_ROWS], truncated=truncated)


def parse(data: bytes, *, filename: str, content_type: str = "", sheet: str = "") -> Table:
    """Headers and rows of an uploaded CSV or XLSX file."""
    name = filename.lower()
    if name.endswith((".xlsx", ".xlsm")) or "spreadsheetml" in content_type:
        rows, sheets = read_xlsx(data, sheet)
        table = to_table(rows)
        table.sheets = sheets
        return table
    if name.endswith(".xls") or content_type == "application/vnd.ms-excel":
        if data[:2] == b"PK":
            rows, sheets = read_xlsx(data, sheet)
            table = to_table(rows)
            table.sheets = sheets
            return table
        raise SpreadsheetError("Save old .xls workbooks as .xlsx or CSV and upload again.")
    return to_table(read_csv(data))


def to_csv(headers: list[str], rows: list[list[object]]) -> bytes:
    """CSV with a BOM; text that looks like a formula is neutralised (CSV injection)."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([safe_cell(h) for h in headers])
    writer.writerows([[safe_cell(v) for v in row] for row in rows])
    return ("﻿" + buffer.getvalue()).encode("utf-8")


NUMBER = re.compile(r"-?\d+(\.\d+)?")


def safe_cell(value: object) -> str:
    text = "" if value is None else str(value)
    if NUMBER.fullmatch(text):
        return text
    return "'" + text if text[:1] in {"=", "+", "-", "@", "\t", "\r"} else text
