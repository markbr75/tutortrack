"""Report files: CSV, Excel (XLSX) and PDF (E26-T07).

XLSX is written directly as a minimal SpreadsheetML package (no extra dependency); numbers
and money are numeric cells. Text cells that look like formulas are neutralised in CSV
and XLSX (CSV injection).
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from typing import Any
from xml.sax.saxutils import escape

from django.utils.translation import gettext as _

from .reports.base import NUMERIC, Column, Params, ReportDef, Result

CONTENT_TYPES = {
    "csv": "text/csv",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
}
FORMULA = ("=", "+", "-", "@", "\t", "\r")


def filename(report: ReportDef, params: Params, fmt: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(report.title).lower()).strip("-") or report.key
    if report.period:
        return f"{slug}-{params.period.start.isoformat()}-to-{params.period.end.isoformat()}.{fmt}"
    return f"{slug}.{fmt}"


def _safe_text(value: Any) -> str:
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(FORMULA) else text


def _cell(column: Column, value: Any) -> Any:
    if column.type in NUMERIC or column.type == "percent":
        return "" if value in (None, "") else value
    return _safe_text(value)


def _table(result: Result) -> tuple[list[str], list[list[Any]]]:
    header = [str(c.label) for c in result.columns]
    rows = [[_cell(c, row.get(c.key)) for c in result.columns] for row in result.rows]
    for total in result.totals or []:
        line = []
        for index, c in enumerate(result.columns):
            if index == 0:
                line.append(_("Total"))
            elif c.key in total:
                line.append(_cell(c, total[c.key]))
            else:
                line.append("")
        rows.append(line)
    return header, rows


def to_csv(result: Result) -> bytes:
    header, rows = _table(result)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    writer.writerows(rows)
    return ("﻿" + buffer.getvalue()).encode("utf-8")  # BOM: Excel opens UTF-8 correctly


def _col(index: int) -> str:
    name = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        name = chr(65 + rem) + name
    return name


def _xlsx_cell(ref: str, value: Any, numeric: bool) -> str:
    if numeric and value not in (None, ""):
        try:
            float(str(value))
            return f'<c r="{ref}"><v>{escape(str(value))}</v></c>'
        except ValueError:
            pass
    text = escape("" if value is None else str(value))
    return f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{text}</t></is></c>'


def to_xlsx(result: Result, title: str) -> bytes:
    header, rows = _table(result)
    numeric = [c.type in NUMERIC or c.type == "percent" for c in result.columns]
    lines = [
        '<row r="1">'
        + "".join(_xlsx_cell(f"{_col(i)}1", h, False) for i, h in enumerate(header))
        + "</row>"
    ]
    for r, row in enumerate(rows, start=2):
        cells = "".join(_xlsx_cell(f"{_col(i)}{r}", v, numeric[i]) for i, v in enumerate(row))
        lines.append(f'<row r="{r}">{cells}</row>')
    sheet_name = escape(re.sub(r"[\[\]:*?/\\]", " ", title)[:31] or "Report")
    files = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" '
            'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/'
            'vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/'
            'vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            "</Types>"
        ),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/'
            '2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>"
        ),
        "xl/workbook.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f'<sheets><sheet name="{sheet_name}" sheetId="1" r:id="rId1"/></sheets>'
            "</workbook>"
        ),
        "xl/_rels/workbook.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/'
            '2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            "</Relationships>"
        ),
        "xl/worksheets/sheet1.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f"<sheetData>{''.join(lines)}</sheetData></worksheet>"
        ),
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def to_pdf(result: Result, report: ReportDef, params: Params) -> bytes:
    from django.utils import translation
    from weasyprint import HTML

    from tutortrack.core.context import require_organisation_id
    from tutortrack.tenancy.models import Organisation

    header, rows = _table(result)
    numeric = [c.type in NUMERIC or c.type == "percent" for c in result.columns]
    org = Organisation.objects.get(pk=require_organisation_id())
    locale = str(getattr(org, "locale", "") or "en-GB")
    with translation.override(locale):
        html = _render_html(org, report, params, result, header, rows, numeric)
    return bytes(HTML(string=html).write_pdf())


def _render_html(
    org: Any,
    report: ReportDef,
    params: Params,
    result: Result,
    header: list[str],
    rows: list[list[Any]],
    numeric: list[bool],
) -> str:
    from django.template.loader import render_to_string

    return render_to_string(
        "reporting/report.html",
        {
            "org": org,
            "title": report.title,
            "period": params.period if report.period else None,
            "header": header,
            "rows": [[(value, numeric[i]) for i, value in enumerate(row)] for row in rows],
            "notes": result.notes,
        },
    )


def render(fmt: str, report: ReportDef, params: Params, result: Result) -> bytes:
    if fmt == "csv":
        return to_csv(result)
    if fmt == "xlsx":
        return to_xlsx(result, str(report.title))
    if fmt == "pdf":
        return to_pdf(result, report, params)
    raise ValueError(f"unknown format {fmt!r}")
