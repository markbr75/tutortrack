"""Bank payment files: golden files pin the exact output (E12 §7)."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.money import Money
from tutortrack.payroll import bankfiles, banking

GOLDEN = Path(__file__).parent / "golden"
WHEN = datetime(2026, 10, 30, 9, 15, tzinfo=UTC)

CASES = {
    "bacs18": (
        bankfiles.Originator(
            "Bright Minds Ltd", {"sort_code": "200000", "account_number": "55779911"}, {}
        ),
        [
            bankfiles.Line(
                "Nia Okafor",
                {"account_name": "N Okafor", "sort_code": "309634", "account_number": "12345678"},
                Money("412.50", "GBP"),
                "PR-000001",
            ),
            bankfiles.Line(
                "Sam Lee",
                {"account_name": "Samuel Lee", "sort_code": "404784", "account_number": "87654321"},
                Money("90.00", "GBP"),
                "PR-000001",
            ),
        ],
    ),
    "sepa": (
        bankfiles.Originator(
            "Bright Minds BV", {"iban": "NL91ABNA0417164300", "bic": "ABNANL2A"}, {}
        ),
        [
            bankfiles.Line(
                "Eva de Vries",
                {
                    "account_name": "E de Vries",
                    "iban": "DE89370400440532013000",
                    "bic": "COBADEFFXXX",
                },
                Money("250.00", "EUR"),
                "PR-000002",
            )
        ],
    ),
    "nacha": (
        bankfiles.Originator(
            "Bright Minds Inc",
            {"routing_number": "021000021", "account_number": "123456789"},
            {"company_id": "1234567890", "destination_name": "JPMORGAN CHASE"},
        ),
        [
            bankfiles.Line(
                "Ana Diaz",
                {
                    "account_name": "Ana Diaz",
                    "routing_number": "011000015",
                    "account_number": "000123456",
                    "account_type": "checking",
                },
                Money("300.25", "USD"),
                "PR-000003",
            ),
            bankfiles.Line(
                "Bo Chen",
                {
                    "account_name": "Bo Chen",
                    "routing_number": "026009593",
                    "account_number": "98765",
                    "account_type": "savings",
                },
                Money("75.00", "USD"),
                "PR-000003",
            ),
        ],
    ),
    "aba": (
        bankfiles.Originator(
            "Bright Minds Pty",
            {"bsb": "062000", "account_number": "12345678"},
            {"apca_id": "301500", "bank": "CBA"},
        ),
        [
            bankfiles.Line(
                "Liam Smith",
                {"account_name": "Liam Smith", "bsb": "083004", "account_number": "123456"},
                Money("180.00", "AUD"),
                "PR-000004",
            )
        ],
    ),
    "csv": (
        bankfiles.Originator("Bright Minds", {}, {}),
        [
            bankfiles.Line(
                "Nia Okafor",
                {"account_name": "N Okafor", "sort_code": "309634", "account_number": "12345678"},
                Money("412.50", "GBP"),
                "PR-000001",
            )
        ],
    ),
}
LENGTHS = {"bacs18": 100, "nacha": 94, "aba": 120}


@pytest.mark.parametrize("fmt", list(CASES))
def test_bank_file_matches_golden(fmt):
    originator, lines = CASES[fmt]
    filename, content = bankfiles.write(fmt, originator, lines, when=WHEN, file_id="PR-TEST")
    golden = GOLDEN / f"{fmt}.{filename.rsplit('.', 1)[1]}"
    if os.environ.get("RECORD_GOLDEN") or not golden.exists():
        golden.write_bytes(content.encode())
    assert content == golden.read_bytes().decode()
    if fmt in LENGTHS:
        assert {len(r) for r in content.splitlines()} == {LENGTHS[fmt]}


def test_nacha_is_blocked_to_ten_records_with_hash_and_totals():
    _, content = bankfiles.write("nacha", *CASES["nacha"], when=WHEN, file_id="PR-TEST")
    records = content.splitlines()
    assert len(records) % 10 == 0
    batch_control = next(r for r in records if r.startswith("8"))
    assert batch_control[10:20] == f"{(1100001 + 2600959) % 10**10:010d}"  # entry hash
    assert batch_control[32:44] == f"{37525:012d}"  # credit total in cents


def test_formats_reject_other_currencies_and_missing_details():
    originator, lines = CASES["sepa"]
    with pytest.raises(BusinessRuleViolation):
        bankfiles.write("bacs18", CASES["bacs18"][0], lines, when=WHEN, file_id="X")
    bad = [bankfiles.Line("X", {"account_name": "X"}, Money("1.00", "EUR"), "R")]
    with pytest.raises(BusinessRuleViolation):
        bankfiles.write("sepa", originator, bad, when=WHEN, file_id="X")


@pytest.mark.parametrize(
    ("country", "details", "field"),
    [
        (
            "GB",
            {"account_name": "A", "sort_code": "12-34-5", "account_number": "12345678"},
            "sort_code",
        ),
        ("DE", {"account_name": "A", "iban": "DE89370400440532013001"}, "iban"),
        (
            "US",
            {"account_name": "A", "routing_number": "021000022", "account_number": "1234"},
            "routing_number",
        ),
        ("AU", {"account_name": "A", "bsb": "06200", "account_number": "123456"}, "bsb"),
    ],
)
def test_bank_details_are_validated(country, details, field):
    with pytest.raises(BusinessRuleViolation) as exc:
        banking.clean(country, details)
    assert field in exc.value.extra["errors"]


def test_bank_details_are_normalised_and_masked():
    details = banking.clean(
        "GB", {"account_name": "N Okafor", "sort_code": "30-96-34", "account_number": "1234 5678"}
    )
    assert details == {
        "account_name": "N Okafor",
        "sort_code": "309634",
        "account_number": "12345678",
    }
    assert banking.hint(details) == "••5678"
    assert banking.mask(details)["account_number"] == "••••5678"
    assert banking.iban_valid("GB82 WEST 1234 5698 7654 32")
