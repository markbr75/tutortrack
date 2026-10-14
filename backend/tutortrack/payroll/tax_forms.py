"""US 1099-NEC data (E12-T12, FR-12-9 "1099-NEC data export for US tenants").

* A tutor's taxpayer id (SSN, ITIN or EIN) is stored encrypted on the pay profile with
  only its type and last four digits in clear (``set_tax_identity``). Reading the full
  number needs ``payroll.tax.view`` and is audited.
* ``year_totals`` works out box 1 (nonemployee compensation) per tutor for a calendar tax
  year on a cash basis: the pay items paid out in that year (by the payout's paid date in
  the organisation's time zone), in USD, for tutors who are not employees. Expense and
  mileage reimbursements are left out (accounted for by receipts). Only tutors at or over
  the reporting threshold need a form: $600 up to tax year 2025, $2,000 from 2026 (the
  One Big Beautiful Bill Act); the organisation may set its own.
* ``finalise`` freezes the year's figures as ``TaxFormFiling`` rows (immutable; a later
  change creates a correction that supersedes the earlier row).
* ``export_csv`` writes the filings in the column order of the IRS IRIS 1099-NEC CSV
  template (payer, recipient, box 1), masked unless the full TIN is asked for (audited).
"""

from __future__ import annotations

import csv
import io
import re
from collections import defaultdict
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils.translation import gettext as _

from tutortrack.core import audit
from tutortrack.core.exceptions import BusinessRuleViolation, PermissionDenied
from tutortrack.core.money import Money
from tutortrack.core.permissions import has_perm
from tutortrack.core.time import now
from tutortrack.people.models import TutorProfile
from tutortrack.tenancy.settings_service import get_setting

from .models import PayItem, Payout, TaxFormFiling, TinType, TutorPayProfile

CURRENCY = "USD"
EXCLUDED_KINDS = (PayItem.Kind.EXPENSE, PayItem.Kind.MILEAGE)


def threshold(year: int) -> Decimal:
    custom = str(get_setting("payroll.form_1099_threshold") or "").strip()
    if custom:
        try:
            return Decimal(custom)
        except ArithmeticError:
            pass
    return Decimal(600) if year <= 2025 else Decimal(2000)


# --- tax identity -----------------------------------------------------------------------------


def clean_tin(value: str, tin_type: str) -> str:
    digits = re.sub(r"\D", "", value or "")
    errors: dict[str, list[str]] = {}
    if tin_type not in TinType.values:
        errors["tin_type"] = [_("Choose SSN, ITIN or EIN.")]
    elif len(digits) != 9 or len(set(digits)) == 1:
        errors["tin"] = [_("Enter the 9-digit number.")]
    elif tin_type == TinType.ITIN and not digits.startswith("9"):
        errors["tin"] = [_("An ITIN starts with 9.")]
    elif tin_type == TinType.SSN and (digits[:3] in ("000", "666") or digits[0] == "9"):
        errors["tin"] = [_("That isn't a valid Social Security number.")]
    if errors:
        raise BusinessRuleViolation(next(iter(errors.values()))[0], extra={"errors": errors})
    return digits


@transaction.atomic
def set_tax_identity(tutor: TutorProfile, *, tin: str, tin_type: str) -> TutorPayProfile:
    from .services import profile_for

    digits = clean_tin(tin, tin_type)
    profile = profile_for(tutor)
    with audit.track(profile, action="tax_identity"):
        profile.tin = digits
        profile.tin_type = tin_type
        profile.tin_hint = digits[-4:]
        profile.save(update_fields=["tin", "tin_type", "tin_hint", "updated_at"])
    return profile


def format_tin(digits: str, tin_type: str) -> str:
    if len(digits) != 9:
        return ""
    if tin_type == TinType.EIN:
        return f"{digits[:2]}-{digits[2:]}"
    return f"{digits[:3]}-{digits[3:5]}-{digits[5:]}"


def tax_identity(profile: TutorPayProfile, *, user: Any, full: bool) -> dict[str, str]:
    masked = f"•••-••-{profile.tin_hint}" if profile.tin_hint else ""
    if not full:
        return {"tin_type": profile.tin_type, "tin": masked, "tin_hint": profile.tin_hint}
    if not has_perm(user, "payroll.tax.view"):
        raise PermissionDenied()
    audit.record_read(profile, reason="tax_identity")
    return {
        "tin_type": profile.tin_type,
        "tin": format_tin(profile.tin, profile.tin_type),
        "tin_hint": profile.tin_hint,
    }


# --- totals -------------------------------------------------------------------------------------


def _year_bounds(year: int) -> tuple[datetime, datetime]:
    from tutortrack.payroll.services import _org

    zone = ZoneInfo(_org().timezone)
    start = datetime.combine(date(year, 1, 1), time.min, tzinfo=zone)
    end = datetime.combine(date(year + 1, 1, 1), time.min, tzinfo=zone)
    return start, end


def _address(tutor: TutorProfile) -> dict[str, str]:
    address = tutor.address
    if address is None:
        return {}
    return {
        "line1": address.line1,
        "line2": address.line2,
        "city": address.city,
        "state": address.region,
        "zip": address.postcode,
        "country": address.country or "US",
    }


def year_totals(year: int) -> list[dict[str, Any]]:
    """One row per contractor tutor paid in USD during ``year``, highest first."""
    start, end = _year_bounds(year)
    sums: dict[Any, Decimal] = defaultdict(Decimal)
    payouts: dict[Any, set[Any]] = defaultdict(set)
    items = (
        PayItem.objects.filter(
            status=PayItem.Status.PAID,
            currency=CURRENCY,
            payout__status=Payout.Status.PAID,
            payout__paid_at__gte=start,
            payout__paid_at__lt=end,
        )
        .exclude(kind__in=EXCLUDED_KINDS)
        .exclude(tutor__employment_type=TutorProfile.Employment.EMPLOYEE)
        .values_list("tutor_id", "amount_amount", "payout_id")
    )
    for tutor_id, amount, payout_id in items:
        sums[tutor_id] += Decimal(amount)
        payouts[tutor_id].add(payout_id)
    tutors = TutorProfile.objects.select_related("address").in_bulk(list(sums))
    profiles = {p.tutor_id: p for p in TutorPayProfile.objects.filter(tutor_id__in=list(sums))}
    filed = {
        f.tutor_id: f
        for f in TaxFormFiling.objects.filter(tax_year=year, superseded=False, tutor_id__in=sums)
    }
    limit = threshold(year)
    rows = []
    for tutor_id, total in sums.items():
        tutor = tutors[tutor_id]
        profile = profiles.get(tutor_id)
        box1 = Money(total, CURRENCY).round_to_minor()
        address = _address(tutor)
        problems = []
        if profile is None or not profile.tin_hint:
            problems.append("missing_tin")
        if not address.get("line1") or not address.get("zip"):
            problems.append("missing_address")
        filing = filed.get(tutor_id)
        rows.append(
            {
                "tutor": tutor,
                "name": (profile.payee_name if profile and profile.payee_name else "")
                or tutor.full_name,
                "tin_type": profile.tin_type if profile else "",
                "tin_hint": profile.tin_hint if profile else "",
                "address": address,
                "box1": box1,
                "payment_count": len(payouts[tutor_id]),
                "reportable": box1.amount >= limit,
                "problems": problems,
                "filing": filing,
                "changed_since_filing": filing is not None and filing.box1 != box1,
            }
        )
    rows.sort(key=lambda r: (-r["box1"].amount, r["name"]))
    return rows


def summary(year: int) -> dict[str, Any]:
    rows = year_totals(year)
    return {
        "tax_year": year,
        "currency": CURRENCY,
        "threshold": str(threshold(year)),
        "rows": rows,
        "reportable": sum(1 for r in rows if r["reportable"]),
        "problems": sum(1 for r in rows if r["reportable"] and r["problems"]),
    }


@transaction.atomic
def finalise(year: int, *, user: Any) -> list[TaxFormFiling]:
    """Freeze the reportable rows; unchanged filings are kept, changed ones corrected."""
    from tutortrack.payroll.services import _org

    if year >= now().year:
        message = _("A tax year can be finalised once it has ended.")
        raise BusinessRuleViolation(message, extra={"errors": {"tax_year": [message]}})
    rows = [r for r in year_totals(year) if r["reportable"]]
    blocked = [r["name"] for r in rows if r["problems"]]
    if blocked:
        message = _("Add the missing tax ids and addresses first: %(names)s.") % {
            "names": ", ".join(blocked[:10])
        }
        raise BusinessRuleViolation(message)
    org = _org()
    payer = {
        "name": org.legal_name or org.name,
        "address": org.address,
        "tin_hint": re.sub(r"\D", "", org.vat_number or "")[-4:],
    }
    created: list[TaxFormFiling] = []
    for row in rows:
        previous = row["filing"]
        if previous is not None and previous.box1 == row["box1"]:
            continue
        if previous is not None:
            TaxFormFiling.objects.filter(pk=previous.pk).update(superseded=True)
        filing = TaxFormFiling(
            tutor=row["tutor"],
            tax_year=year,
            currency=CURRENCY,
            payment_count=row["payment_count"],
            tin_type=row["tin_type"],
            tin_hint=row["tin_hint"],
            payee={"name": row["name"], "address": row["address"]},
            payer=payer,
            corrects=previous,
            finalised_by=user,
            finalised_at=now(),
        )
        filing.box1 = row["box1"]
        filing.save()
        audit.record_create(filing)
        created.append(filing)
    if created:
        from tutortrack.core.events import publish

        from .events import TaxFormsFinalised

        publish(TaxFormsFinalised(subject_id=str(year), tax_year=year, filings=len(created)))
    return created


IRIS_COLUMNS = (
    "Form Type",
    "Tax Year",
    "Payer Name",
    "Payer TIN (last 4)",
    "Payer Address",
    "Recipient TIN Type",
    "Recipient TIN",
    "Recipient Name",
    "Recipient Address Line 1",
    "Recipient Address Line 2",
    "Recipient City",
    "Recipient State",
    "Recipient ZIP",
    "Recipient Country",
    "Box 1 Nonemployee Compensation",
    "Corrected",
    "Account Number",
)


def _cell(value: Any) -> str:
    text = str(value or "")
    return f"'{text}" if text[:1] in ("=", "+", "-", "@") else text  # CSV formula injection


def export_csv(year: int, *, user: Any, full_tin: bool = False) -> tuple[str, str]:
    """The finalised filings for ``year`` as CSV. ``full_tin`` needs ``payroll.tax.view``;
    each full number read is audited."""
    if full_tin and not has_perm(user, "payroll.tax.view"):
        raise PermissionDenied()
    filings = list(
        TaxFormFiling.objects.filter(tax_year=year, superseded=False).select_related("tutor")
    )
    if not filings:
        raise BusinessRuleViolation(_("Finalise the tax year first."))
    profiles = {
        p.tutor_id: p
        for p in TutorPayProfile.objects.filter(tutor_id__in=[f.tutor_id for f in filings])
    }
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(IRIS_COLUMNS)
    for filing in filings:
        tin = f"XXX-XX-{filing.tin_hint}"
        profile = profiles.get(filing.tutor_id)
        if full_tin and profile is not None and profile.tin:
            audit.record_read(profile, reason="1099_export")
            tin = format_tin(profile.tin, profile.tin_type)
        address = filing.payee.get("address") or {}
        payer_address = filing.payer.get("address") or {}
        writer.writerow(
            [
                _cell(v)
                for v in (
                    filing.form,
                    filing.tax_year,
                    filing.payer.get("name"),
                    filing.payer.get("tin_hint"),
                    ", ".join(str(v) for v in payer_address.values() if v)
                    if isinstance(payer_address, dict)
                    else payer_address,
                    filing.tin_type.upper(),
                    tin,
                    filing.payee.get("name"),
                    address.get("line1"),
                    address.get("line2"),
                    address.get("city"),
                    address.get("state"),
                    address.get("zip"),
                    address.get("country"),
                    f"{filing.box1.amount:.2f}",
                    "X" if filing.corrects_id else "",
                    str(filing.tutor_id).replace("-", "")[:20],
                )
            ]
        )
    from tutortrack.payroll.services import _org

    audit.record(
        _org(),
        "export",
        {"export": "form_1099_nec", "tax_year": year, "rows": len(filings), "full_tin": full_tin},
    )
    return f"1099-nec-{year}.csv", out.getvalue()


def tutor_summary(tutor: TutorProfile, year: int) -> dict[str, Any]:
    """The tutor's own view (portal): what was paid in the year and any filed form."""
    row = next((r for r in year_totals(year) if r["tutor"].pk == tutor.pk), None)
    filing = TaxFormFiling.objects.filter(tutor=tutor, tax_year=year, superseded=False).first()
    return {
        "tax_year": year,
        "currency": CURRENCY,
        "box1": str(row["box1"].amount) if row else "0.00",
        "reportable": bool(row and row["reportable"]),
        "filed": filing is not None,
        "filed_box1": str(filing.box1.amount) if filing else None,
        "tin_hint": row["tin_hint"] if row else "",
    }
