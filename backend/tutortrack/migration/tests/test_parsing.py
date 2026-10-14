"""E28-T01: reading CSV and XLSX files, header detection, mapping and value coercion."""

from __future__ import annotations

import io
import zipfile
from datetime import date, time
from decimal import Decimal

import pytest

from tutortrack.migration import mapping, parsing
from tutortrack.migration.importers import base, get
from tutortrack.migration.importers.base import Context, FieldSpec, coerce


def xlsx(rows: list[list[object]], *, date_cells: set[str] = frozenset(), extra: str = "") -> bytes:
    """A minimal workbook: shared strings, numbers and date-formatted serials."""
    shared: list[str] = []
    lines = []
    for r, row in enumerate(rows, start=1):
        cells = []
        for c, value in enumerate(row):
            ref = f"{chr(65 + c)}{r}"
            if isinstance(value, str):
                shared.append(value)
                cells.append(f'<c r="{ref}" t="s"><v>{len(shared) - 1}</v></c>')
            else:
                style = ' s="1"' if ref in date_cells else ""
                cells.append(f'<c r="{ref}"{style}><v>{value}</v></c>')
        lines.append(f'<row r="{r}">{"".join(cells)}</row>')
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    files = {
        "xl/workbook.xml": (
            f'<workbook {ns} xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/'
            'relationships"><sheets><sheet name="Families" sheetId="1" r:id="rId1"/></sheets>'
            "</workbook>"
        ),
        "xl/_rels/workbook.xml.rels": (
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Target="worksheets/sheet1.xml" Type="x"/></Relationships>'
        ),
        "xl/sharedStrings.xml": f"<sst {ns}>"
        + "".join(f"<si><t>{s}</t></si>" for s in shared)
        + "</sst>",
        "xl/styles.xml": (
            f'<styleSheet {ns}><cellXfs count="2"><xf numFmtId="0"/><xf numFmtId="14"/>'
            "</cellXfs></styleSheet>"
        ),
        "xl/worksheets/sheet1.xml": f"{extra}<worksheet {ns}><sheetData>{''.join(lines)}"
        "</sheetData></worksheet>",
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def test_csv_with_semicolons_bom_and_a_title_row():
    data = "﻿Export from TutorBird;;\nFirst Name;Last Name;Email\nAva;Brown;a@x.com\n;;\n"
    table = parsing.parse(data.encode("utf-8"), filename="students.csv")
    assert table.headers == ["First Name", "Last Name", "Email"]
    assert table.rows == [{"First Name": "Ava", "Last Name": "Brown", "Email": "a@x.com"}]


def test_csv_latin1_and_duplicate_headers():
    data = "Name,Name,Café\nZoë,Ann,yes\n".encode("cp1252")
    table = parsing.parse(data, filename="x.csv")
    assert table.headers == ["Name", "Name (2)", "Café"]
    assert table.rows[0]["Name"] == "Zoë"


def test_xlsx_shared_strings_numbers_and_dates():
    data = xlsx([["Name", "Lessons", "Born"], ["Tom", 12, 45000]], date_cells={"C2"})
    table = parsing.parse(data, filename="families.xlsx")
    assert table.sheets == ["Families"]
    assert table.rows == [{"Name": "Tom", "Lessons": "12", "Born": "2023-03-15"}]


def test_xlsx_with_a_dtd_is_refused():
    data = xlsx([["Name"], ["Tom"]], extra='<!DOCTYPE x [<!ENTITY a "aaaa">]>')
    with pytest.raises(parsing.SpreadsheetError):
        parsing.parse(data, filename="evil.xlsx")


def test_not_a_spreadsheet():
    with pytest.raises(parsing.SpreadsheetError):
        parsing.parse(b"PK\x03\x04garbage", filename="x.xlsx")
    with pytest.raises(parsing.SpreadsheetError):
        parsing.parse(b"", filename="x.csv")


def test_csv_output_neutralises_formulas():
    out = parsing.to_csv(["a"], [["=HYPERLINK(1)"], ["-12.50"], ["@cmd"]]).decode("utf-8-sig")
    assert out.splitlines() == ["a", "'=HYPERLINK(1)", "-12.50", "'@cmd"]


def _ctx(date_format: str = "DMY") -> Context:
    return Context(
        batch=None,
        system="file",
        upsert_key="none",
        date_format=date_format,
        cutover=date(2026, 11, 1),
        currency="GBP",
        timezone="Europe/London",
        options={},
    )


@pytest.mark.parametrize(
    ("kind", "text", "expected"),
    [
        ("date", "03/04/2026", date(2026, 4, 3)),
        ("date", "2026-04-03", date(2026, 4, 3)),
        ("date", "3 Apr 2026", date(2026, 4, 3)),
        ("time", "4:30 PM", time(16, 30)),
        ("time", "16.30", time(16, 30)),
        ("decimal", "£1,234.50", Decimal("1234.50")),
        ("decimal", "1.234,50", Decimal("1234.50")),
        ("decimal", "(12.00)", Decimal("-12.00")),
        ("bool", "Yes", True),
        ("bool", "n", False),
        ("weekday", "Thurs", 3),
        ("list", "Maths: GCSE; Physics", ["Maths: GCSE", "Physics"]),
    ],
)
def test_coercion(kind, text, expected):
    assert coerce(FieldSpec("f", "F", kind), text, _ctx(), {}) == expected


def test_us_date_order_and_choice_value_maps():
    assert coerce(FieldSpec("d", "D", "date"), "03/04/2026", _ctx("MDY"), {}) == date(2026, 3, 4)
    spec = FieldSpec("s", "S", "choice", choices=("active", "finished"))
    assert coerce(spec, "Inactive", _ctx(), {"inactive": "finished"}) == "finished"
    with pytest.raises(ValueError, match="Use one of"):
        coerce(spec, "Unknown", _ctx(), {})


def test_automap_uses_synonyms_presets_and_each_field_once():
    importer = get("students")
    result = mapping.automap(
        ["First Name", "Surname", "DOB", "Family", "Mystery", "First name"], importer
    )
    assert result == {
        "First Name": "first_name",
        "Surname": "last_name",
        "DOB": "date_of_birth",
        "Family": "client_name",
        "Mystery": "",
        "First name": "",
    }
    preset = mapping.automap(["Grade", "Birthday"], importer, preset="tutorbird")
    assert preset == {"Grade": "year_group", "Birthday": "date_of_birth"}


def test_every_importer_describes_itself():
    keys = {i.key for i in base.all_importers()}
    assert keys == {
        "clients",
        "students",
        "tutors",
        "services",
        "jobs",
        "lessons",
        "invoices",
        "payments",
        "opening_balances",
        "packages",
        "availability",
        "enquiries",
        "tags",
        "notes",
        "affiliates",
        "reviews",
        "charges",
        "payment_requests",
    }
    for importer in base.all_importers():
        info = importer.describe()
        assert info["field_specs"], importer.key
        assert importer.default_upsert in importer.upsert_keys
