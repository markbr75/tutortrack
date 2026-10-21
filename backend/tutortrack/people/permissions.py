"""Permission codenames owned by people (E05 §6)."""

_ACTIONS = ("view", "create", "edit", "archive", "export")

PERMISSIONS = {
    **{f"people.client.{a}": f"Clients: {a}" for a in _ACTIONS},
    **{f"people.contact.{a}": f"Contacts: {a}" for a in _ACTIONS},
    **{f"people.student.{a}": f"Students: {a}" for a in _ACTIONS},
    "people.student.view_sensitive": "See students' date of birth and learning needs/medical notes",
    **{f"people.tutor.{a}": f"Tutors: {a}" for a in _ACTIONS},
    "people.tutor.view_financial": "See tutors' pay rate and tax reference",
    # Gap G5c (FR-19-1): gender is only used for families' gender preferences in matching.
    "people.tutor.view_sensitive": "See and edit tutors' gender (matching preferences)",
    "people.tutor.approve_subjects": "Approve the subjects a tutor may teach",
    "people.contact.view_phone": "See contacts' phone numbers (tutor toggle)",
    "people.contact.view_details": "See contacts' full details (tutor toggle)",
    # FR-05-13: not reversible, so only owners and admins by default (ADR 0035).
    "people.merge": "Merge duplicate clients, contacts and students",
}
