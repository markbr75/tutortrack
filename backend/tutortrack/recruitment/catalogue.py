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
        "sign": True,  # click-to-sign with a signed PDF copy (FR-18-5, gap batch G2)
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


def _field(key: str, label: str, kind: str, maps_to: str = "", **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"key": key, "label": label, "type": kind, **extra}
    if maps_to:
        out["maps_to"] = maps_to
    return out


# G5a (FR-18-1): the standard tutor application form a new job opening can start from. Staff
# can change it in the form builder like any other form.
APPLICATION_FORM: dict[str, Any] = {
    "steps": [
        {
            "title": "About you",
            "fields": [
                _field("first_name", "First name", "text", "applicant.first_name", required=True),
                _field("last_name", "Last name", "text", "applicant.last_name", required=True),
                _field("email", "Email", "email", "applicant.email", required=True),
                _field("phone", "Phone", "phone", "applicant.phone"),
                _field("postcode", "Postcode", "postcode", "applicant.postcode"),
                _field("right_to_work", "Right to work", "text", "applicant.right_to_work"),
            ],
        },
        {
            "title": "Your teaching",
            "fields": [
                _field(
                    "subjects",
                    "Subjects and levels you teach",
                    "text",
                    "applicant.subjects",
                    required=True,
                ),
                _field(
                    "qualifications",
                    "Qualifications and grades",
                    "textarea",
                    "applicant.qualifications",
                ),
                _field("experience", "Tutoring experience", "textarea", "applicant.experience"),
                _field("cv", "CV (PDF or Word)", "file", "applicant.cv", file_kind="cv"),
                _field(
                    "video",
                    "Video introduction (optional)",
                    "file",
                    "applicant.video",
                    file_kind="video",
                ),
                _field("video_url", "Or a link to your video", "text", "applicant.video_url"),
            ],
        },
        {
            "title": "References",
            "fields": [
                _field("referees", "Two referees", "referees", "referees", required=True),
                _field("privacy", "I have read the privacy notice", "consent", required=True),
            ],
        },
    ]
}

# G5a (FR-18-9): the offboarding checklist. ``auto`` items complete themselves from the
# tutor's data; the others are ticked by staff.
OFFBOARDING: list[dict[str, Any]] = [
    {"key": "jobs", "label": "Reassign or end the tutor's jobs", "auto": True},
    {"key": "lessons", "label": "Reassign or cancel future lessons", "auto": True},
    {"key": "access", "label": "Revoke access to TutorTrack", "auto": True},
    {"key": "final_pay", "label": "Pay everything owed in a final pay run", "auto": True},
    {"key": "equipment", "label": "Collect resources, keys and equipment", "auto": False},
    {"key": "records", "label": "Keep records for the retention period", "auto": False},
]
