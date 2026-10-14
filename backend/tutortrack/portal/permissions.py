"""Permission codenames for the client and student portal (E15 §4).

Clients hold ``portal.client.*`` and students ``portal.student.*`` (own household or self);
staff manage announcements with ``comms.announcement.manage``.
"""

PERMISSIONS = {
    "portal.client.view": "Client portal: see the household's lessons, reports and bills",
    "portal.client.cancel": "Client portal: cancel lessons and report absences",
    "portal.client.pay": "Client portal: pay and manage payment methods",
    "portal.client.profile": "Client portal: edit the household's details",
    "portal.client.book": "Client portal: book lessons online (E08 self-booking)",
    "portal.client.reschedule": "Client portal: ask to move lessons",
    "portal.client.message": "Client portal: message the business (and tutors, if allowed)",
    "portal.student.view": "Student portal: see own lessons and reports",
    "portal.student.message": "Student portal: message the business (if allowed)",
    "comms.announcement.manage": "Post news for clients and tutors",
}
