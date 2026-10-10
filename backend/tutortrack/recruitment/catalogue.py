"""Defaults created for each organisation on first use (FR-18-2, FR-18-5, FR-18-6)."""

from __future__ import annotations

from typing import Any

IN_PERSON = {"in_person_only": True}

REQUIREMENTS: dict[str, list[dict[str, Any]]] = {
    "GB": [
        {
            "key": "dbs_enhanced",
            "name": "Enhanced DBS check",
            "has_number": True,
            "has_expiry": True,
            "renewal_months": 36,
            "description": "Enhanced DBS certificate number, issue date and Update Service status.",
        },
        {
            "key": "right_to_work",
            "name": "Right to work",
            "has_number": True,
            "description": "Passport, or a Home Office share code.",
        },
    ],
    "IE": [
        {
            "key": "garda_vetting",
            "name": "Garda vetting",
            "has_number": True,
            "has_expiry": True,
            "renewal_months": 36,
        }
    ],
    "US": [
        {
            "key": "background_check",
            "name": "Background check",
            "has_expiry": True,
            "renewal_months": 24,
        },
        {"key": "i9", "name": "Employment eligibility (I-9)", "blocking": False},
    ],
    "CA": [
        {
            "key": "vsc",
            "name": "Vulnerable Sector Check",
            "has_number": True,
            "has_expiry": True,
            "renewal_months": 36,
        }
    ],
    "AU": [
        {
            "key": "wwcc",
            "name": "Working With Children Check",
            "has_number": True,
            "has_expiry": True,
            "description": "State and card number.",
        }
    ],
    "NZ": [
        {
            "key": "police_vetting",
            "name": "Police vetting",
            "has_expiry": True,
            "renewal_months": 36,
        }
    ],
}
COMMON: list[dict[str, Any]] = [
    {"key": "photo_id", "name": "Photo ID"},
    {
        "key": "safeguarding_training",
        "name": "Safeguarding training",
        "has_expiry": True,
        "renewal_months": 24,
    },
    {
        "key": "qualifications",
        "name": "Qualification certificates",
        "mandatory": False,
        "blocking": False,
    },
    {
        "key": "insurance",
        "name": "Public liability insurance",
        "has_expiry": True,
        "mandatory": False,
        "blocking": False,
        "applies_to": {"employment_types": ["self_employed"]},
    },
]

STAGES = [
    ("Applied", "open", []),
    ("Screening", "open", ["Subject knowledge", "Communication"]),
    ("Interview", "open", ["Teaching approach", "Communication", "Reliability"]),
    ("References & checks", "open", []),
    ("Decision", "open", []),
    ("Hired", "hired", []),
    ("Rejected", "rejected", []),
]

CHECKLIST = [
    {
        "key": "agreement",
        "label": "Sign the tutor agreement",
        "kind": "agreement",
        "mandatory": True,
    },
    {
        "key": "safeguarding_policy",
        "label": "Read the safeguarding policy",
        "kind": "agreement",
        "mandatory": True,
    },
    {
        "key": "self_billing",
        "label": "Accept self-billing",
        "kind": "self_billing",
        "mandatory": False,
    },
    {
        "key": "documents",
        "label": "Upload your compliance documents",
        "kind": "document",
        "mandatory": True,
    },
    {
        "key": "availability",
        "label": "Set your availability",
        "kind": "availability",
        "mandatory": True,
    },
    {"key": "payout", "label": "Add your bank details", "kind": "payout", "mandatory": True},
    {"key": "profile", "label": "Write your profile", "kind": "profile", "mandatory": False},
]
