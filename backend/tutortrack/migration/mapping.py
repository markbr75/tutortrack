"""Column mapping (FR-28-1): automatic matching by name and synonyms, saved mappings and
the competitor presets (FR-28-3/4/5: TutorBird export files, TutorCruncher and Teachworks
CSV exports). A preset maps their column headers to our fields and their status words to
ours."""

from __future__ import annotations

import re
from typing import Any

from .importers.base import Importer

IGNORE = ""


def normal(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text).lower()).strip()


# --- presets ------------------------------------------------------------------------------------

STUDENT_STATUS_WORDS = {
    "Active": "active",
    "Inactive": "finished",
    "Waiting": "waiting",
    "Waitlist": "waiting",
    "Waiting List": "waiting",
    "Lead": "lead",
    "Trial": "trial",
    "Paused": "paused",
    "On Hold": "paused",
    "Finished": "finished",
    "Prospect": "lead",
    "Dormant": "paused",
    "Archived": "finished",
}
LESSON_STATUS_WORDS = {
    "Present": "completed",
    "Attended": "completed",
    "Complete": "completed",
    "Completed": "completed",
    "Absent": "missed",
    "No Show": "missed",
    "Missed": "missed",
    "Unrecorded": "planned",
    "Planned": "planned",
    "Scheduled": "planned",
    "Cancelled": "cancelled",
    "Canceled": "cancelled",
    "Cancelled by client": "cancelled",
    "Cancelled by tutor": "cancelled",
    "Awaiting report": "completed",
}
INVOICE_STATUS_WORDS = {
    "Paid": "paid",
    "Unpaid": "issued",
    "Partially Paid": "partially_paid",
    "Partial": "partially_paid",
    "Overdue": "issued",
    "Open": "issued",
    "Void": "void",
    "Voided": "void",
    "Sent": "issued",
    "Written off": "written_off",
    "Draft": "issued",
}
TUTOR_STATUS_WORDS = {
    "Active": "active",
    "Inactive": "inactive",
    "Archived": "inactive",
    "Pending": "onboarding",
    "Applicant": "applicant",
    "Approved": "active",
    "Dormant": "inactive",
}

PRESETS: dict[str, dict[str, dict[str, Any]]] = {
    "tutorbird": {
        "clients": {
            "columns": {
                "Family ID": "external_id",
                "Family Name": "client_name",
                "Parent First Name": "first_name",
                "Parent Last Name": "last_name",
                "First Name": "first_name",
                "Last Name": "last_name",
                "Email": "email",
                "Email Address": "email",
                "Phone": "phone",
                "Mobile Phone": "mobile",
                "Home Phone": "phone",
                "Address": "address_line1",
                "City": "address_city",
                "State/Province": "address_region",
                "State": "address_region",
                "Postal Code": "address_postcode",
                "Zip": "address_postcode",
                "Country": "address_country",
                "Referrer": "referral_source",
            },
            "values": {},
        },
        "students": {
            "columns": {
                "Student ID": "external_id",
                "First Name": "first_name",
                "Last Name": "last_name",
                "Status": "status",
                "Birthday": "date_of_birth",
                "Birth Date": "date_of_birth",
                "School": "school",
                "Grade": "year_group",
                "Family": "client_name",
                "Family Name": "client_name",
                "Family ID": "client_external_id",
                "Parent First Name": "parent_first_name",
                "Parent Last Name": "parent_last_name",
                "Parent Email": "parent_email",
                "Parent Phone": "parent_phone",
                "Email": "parent_email",
                "Phone": "parent_phone",
                "Subjects": "subjects",
                "Skill Level": "goals",
                "Notes": "goals",
                "Default Lesson Category": "subjects",
            },
            "values": {"status": STUDENT_STATUS_WORDS},
        },
        "tutors": {
            "columns": {
                "Teacher ID": "external_id",
                "Tutor ID": "external_id",
                "First Name": "first_name",
                "Last Name": "last_name",
                "Email": "email",
                "Phone": "phone",
                "Mobile Phone": "phone",
                "Status": "status",
                "Subjects": "subjects",
                "Pay Rate": "pay_rate",
            },
            "values": {"status": TUTOR_STATUS_WORDS},
        },
        "lessons": {
            "columns": {
                "Event ID": "external_id",
                "Date": "date",
                "Start Date": "date",
                "Start Time": "start_time",
                "End Time": "end_time",
                "Duration": "duration_minutes",
                "Student": "student_names",
                "Students": "student_names",
                "Teacher": "tutor_name",
                "Tutor": "tutor_name",
                "Event Category": "service",
                "Category": "service",
                "Attendance": "status",
                "Status": "status",
                "Price": "charge_rate",
                "Family": "client_name",
                "Notes": "notes",
                "Location": "notes",
            },
            "values": {"status": LESSON_STATUS_WORDS},
        },
        "invoices": {
            "columns": {
                "Invoice #": "number",
                "Invoice Number": "number",
                "Invoice ID": "number",
                "Family": "client_name",
                "Family Name": "client_name",
                "Date": "issue_date",
                "Invoice Date": "issue_date",
                "Due Date": "due_date",
                "Amount": "total",
                "Total": "total",
                "Paid": "amount_paid",
                "Amount Paid": "amount_paid",
                "Status": "status",
                "Description": "description",
                "Tax": "tax",
            },
            "values": {"status": INVOICE_STATUS_WORDS},
        },
        "payments": {
            "columns": {
                "Family": "client_name",
                "Family Name": "client_name",
                "Date": "date",
                "Amount": "amount",
                "Payment Method": "method",
                "Method": "method",
                "Reference": "reference",
                "Invoice #": "invoice_number",
                "Description": "reference",
            },
            "values": {
                "method": {
                    "Cash": "cash",
                    "Check": "cheque",
                    "Cheque": "cheque",
                    "Bank Transfer": "bank_transfer",
                    "E-Transfer": "bank_transfer",
                    "ACH": "bank_transfer",
                    "Other": "other",
                }
            },
        },
        "opening_balances": {
            "columns": {
                "Family": "client_name",
                "Family Name": "client_name",
                "Balance": "balance",
                "Account Balance": "balance",
                "Email": "client_email",
            },
            "values": {},
        },
    },
    "tutorcruncher": {
        "clients": {
            "columns": {
                "ID": "external_id",
                "Client ID": "external_id",
                "First Name": "first_name",
                "Last Name": "last_name",
                "Email": "email",
                "Phone": "phone",
                "Mobile": "mobile",
                "Street": "address_line1",
                "Town": "address_city",
                "Postcode": "address_postcode",
                "Country": "address_country",
                "Status": "status",
                "Labels": "tags",
                "Company Name": "client_name",
            },
            "values": {"status": {"Live": "active", "Prospect": "prospect", "Dormant": "dormant"}},
        },
        "students": {
            "columns": {
                "ID": "external_id",
                "Recipient ID": "external_id",
                "First Name": "first_name",
                "Last Name": "last_name",
                "Date of Birth": "date_of_birth",
                "School": "school",
                "Academic Year": "year_group",
                "Paying Client ID": "client_external_id",
                "Client ID": "client_external_id",
                "Labels": "tags",
            },
            "values": {},
        },
        "tutors": {
            "columns": {
                "ID": "external_id",
                "Contractor ID": "external_id",
                "First Name": "first_name",
                "Last Name": "last_name",
                "Email": "email",
                "Phone": "phone",
                "Mobile": "phone",
                "Status": "status",
                "Skills": "subjects",
                "Labels": "tags",
                "Postcode": "address_postcode",
                "Town": "address_city",
            },
            "values": {
                "status": {
                    "Approved": "active",
                    "Pending": "onboarding",
                    "Rejected": "inactive",
                    "Dormant": "inactive",
                }
            },
        },
        "jobs": {
            "columns": {
                "ID": "external_id",
                "Service ID": "external_id",
                "Name": "name",
                "Client ID": "client_external_id",
                "Recipients": "student_names",
                "Contractor Email": "tutor_email",
                "Contractor ID": "tutor_external_id",
                "Charge Rate": "charge_rate",
                "Pay Rate": "pay_rate",
                "Status": "status",
                "Service": "service",
                "Type": "service",
            },
            "values": {
                "status": {
                    "Available": "seeking_tutor",
                    "In Progress": "active",
                    "Finished": "completed",
                    "Gone Cold": "cancelled",
                    "Pending": "draft",
                    "Planned": "active",
                }
            },
        },
        "lessons": {
            "columns": {
                "ID": "external_id",
                "Appointment ID": "external_id",
                "Date": "date",
                "Start": "start_time",
                "Finish": "end_time",
                "Service ID": "job_external_id",
                "Status": "status",
                "Contractor Email": "tutor_email",
                "Charge Rate": "charge_rate",
                "Pay Rate": "pay_rate",
            },
            "values": {
                "status": {
                    "Planned": "planned",
                    "Awaiting report": "completed",
                    "Complete": "completed",
                    "Cancelled": "cancelled",
                    "Cancelled but chargeable": "cancelled",
                }
            },
        },
        "invoices": {
            "columns": {
                "Display ID": "number",
                "Invoice ID": "number",
                "Client ID": "client_external_id",
                "Date Sent": "issue_date",
                "Date": "issue_date",
                "Due": "due_date",
                "Gross": "total",
                "Total": "total",
                "Tax": "tax",
                "Status": "status",
            },
            "values": {
                "status": {
                    "Paid": "paid",
                    "Unpaid": "issued",
                    "Void": "void",
                    "Partially paid": "partially_paid",
                }
            },
        },
    },
    "teachworks": {
        "clients": {
            "columns": {
                "Customer ID": "external_id",
                "ID": "external_id",
                "First Name": "first_name",
                "Last Name": "last_name",
                "Email": "email",
                "Home Phone": "phone",
                "Mobile Phone": "mobile",
                "Address": "address_line1",
                "City": "address_city",
                "State": "address_region",
                "Zip": "address_postcode",
                "Country": "address_country",
                "Status": "status",
            },
            "values": {
                "status": {"Active": "active", "Inactive": "dormant", "Prospective": "prospect"}
            },
        },
        "students": {
            "columns": {
                "Student ID": "external_id",
                "ID": "external_id",
                "First Name": "first_name",
                "Last Name": "last_name",
                "Customer ID": "client_external_id",
                "Grade": "year_group",
                "School": "school",
                "Birth Date": "date_of_birth",
                "Status": "status",
            },
            "values": {"status": STUDENT_STATUS_WORDS},
        },
        "tutors": {
            "columns": {
                "Employee ID": "external_id",
                "ID": "external_id",
                "First Name": "first_name",
                "Last Name": "last_name",
                "Email": "email",
                "Mobile Phone": "phone",
                "Status": "status",
                "Wage Tier": "pay_rate",
            },
            "values": {"status": TUTOR_STATUS_WORDS},
        },
        "services": {
            "columns": {
                "Service ID": "external_id",
                "Name": "name",
                "Cost": "charge_rate",
                "Wage": "pay_rate",
                "Duration": "default_duration_minutes",
            },
            "values": {},
        },
        "lessons": {
            "columns": {
                "Lesson ID": "external_id",
                "Date": "date",
                "From": "start_time",
                "To": "end_time",
                "Student": "student_names",
                "Employee": "tutor_name",
                "Service": "service",
                "Status": "status",
                "Customer": "client_name",
            },
            "values": {
                "status": {
                    "Scheduled": "planned",
                    "Attended": "completed",
                    "Missed": "missed",
                    "Cancelled": "cancelled",
                }
            },
        },
        "invoices": {
            "columns": {
                "Invoice Number": "number",
                "Customer ID": "client_external_id",
                "Date": "issue_date",
                "Due Date": "due_date",
                "Total": "total",
                "Paid": "amount_paid",
                "Status": "status",
            },
            "values": {"status": INVOICE_STATUS_WORDS},
        },
        "payments": {
            "columns": {
                "Customer ID": "client_external_id",
                "Date": "date",
                "Amount": "amount",
                "Method": "method",
                "Reference": "reference",
                "Invoice": "invoice_number",
            },
            "values": {},
        },
        "packages": {
            "columns": {
                "Customer ID": "client_external_id",
                "Package": "package",
                "Remaining Value": "remaining_value",
                "Remaining Hours": "remaining_hours",
                "Expires": "expires_on",
            },
            "values": {},
        },
    },
}


def presets() -> dict[str, list[str]]:
    return {name: sorted(entities) for name, entities in PRESETS.items()}


def preset_for(preset: str, entity: str) -> dict[str, Any]:
    return PRESETS.get(preset, {}).get(entity) or {"columns": {}, "values": {}}


# --- automatic matching -------------------------------------------------------------------------


def _candidates(importer: Importer, extra: list[Any]) -> dict[str, str]:
    """Normalised name → field key, most specific first (key, label, synonyms)."""
    out: dict[str, str] = {}
    specs = [*importer.fields, *extra]
    for spec in specs:
        out.setdefault(normal(spec.key), spec.key)
        out.setdefault(normal(str(spec.label)), spec.key)
    for spec in specs:
        for synonym in spec.synonyms:
            out.setdefault(normal(synonym), spec.key)
    return out


def automap(
    headers: list[str], importer: Importer, *, preset: str = "", extra: list[Any] | None = None
) -> dict[str, str]:
    """``{header: field key or ""}``; each field is used once (lists may take several)."""
    specs = {s.key: s for s in [*importer.fields, *(extra or [])]}
    from_preset = {normal(k): v for k, v in preset_for(preset, importer.key)["columns"].items()}
    names = _candidates(importer, extra or [])
    mapping: dict[str, str] = {}
    used: set[str] = set()
    for header in headers:
        key = from_preset.get(normal(header)) or names.get(normal(header), IGNORE)
        spec = specs.get(key)
        if key and (key not in used or (spec is not None and spec.type == "list")):
            mapping[header] = key
            used.add(key)
        else:
            mapping[header] = IGNORE
    return mapping


def default_values(preset: str, entity: str) -> dict[str, dict[str, str]]:
    values: dict[str, dict[str, str]] = preset_for(preset, entity).get("values") or {}
    return {k: dict(v) for k, v in values.items()}


def clean_mapping(mapping: dict[str, Any], headers: list[str], allowed: set[str]) -> dict[str, str]:
    """Only known headers and fields; anything else is ignored."""
    return {
        h: (str(mapping.get(h) or "") if mapping.get(h) in allowed else IGNORE) for h in headers
    }
