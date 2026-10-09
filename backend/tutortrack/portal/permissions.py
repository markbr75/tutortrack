"""Permission codenames for the client and student portal (E15 §4).

Clients hold ``portal.client.*`` and students ``portal.student.*`` (own household or self);
staff manage announcements with ``comms.announcement.manage``.
"""

PERMISSIONS = {
    "portal.client.view": "Client portal: see the household's lessons, reports and bills",
    "portal.client.cancel": "Client portal: cancel lessons and report absences",
    "portal.client.pay": "Client portal: pay and manage payment methods",
    "portal.client.profile": "Client portal: edit the household's details",
    "portal.student.view": "Student portal: see own lessons and reports",
    "comms.announcement.manage": "Post news for clients and tutors",
}
