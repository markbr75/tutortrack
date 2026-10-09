"""Permission codenames owned by people (E05 §6)."""

_ACTIONS = ("view", "create", "edit", "archive", "export")

PERMISSIONS = {
    **{f"people.client.{a}": f"Clients: {a}" for a in (*_ACTIONS, "merge")},
    **{f"people.contact.{a}": f"Contacts: {a}" for a in _ACTIONS},
    **{f"people.student.{a}": f"Students: {a}" for a in (*_ACTIONS, "merge")},
    "people.student.view_sensitive": "See students' date of birth and learning needs/medical notes",
    **{f"people.tutor.{a}": f"Tutors: {a}" for a in _ACTIONS},
    "people.tutor.view_financial": "See tutors' pay rate and tax reference",
    "people.tutor.approve_subjects": "Approve the subjects a tutor may teach",
    "people.contact.view_phone": "See contacts' phone numbers (tutor toggle)",
    "people.contact.view_details": "See contacts' full details (tutor toggle)",
}
