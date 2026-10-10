"""Zapier and Make app definitions (FR-27-4, E27-T06/T07).

Both platforms are driven by the same public API, so the app definition is data: a
manifest the platform-specific packaging (Zapier CLI ``index.js`` / Make custom-app JSON)
is generated from, served at ``/api/v1/developer/connectors/<platform>``.

* **Auth**: OAuth2 authorisation code + PKCE against our provider, using the partner app
  seeded for each platform (``OAuthApplication.partner_key``).
* **Triggers**: REST hooks. Subscribe = ``POST /api/v1/webhook-endpoints`` with one event
  type; unsubscribe = ``DELETE /api/v1/webhook-endpoints/{id}``; samples ("perform list")
  = ``GET /api/v1/webhook-event-types/{type}/sample``.
* **Actions** and **searches** map to public endpoints; searches use ``?q=``.
"""

from __future__ import annotations

from typing import Any

PLATFORMS = ("zapier", "make")

TRIGGERS: tuple[dict[str, str], ...] = (
    {"key": "new_enquiry", "label": "New enquiry", "event": "enquiry.received"},
    {"key": "new_client", "label": "New client", "event": "client.created"},
    {"key": "lesson_completed", "label": "Lesson completed", "event": "lesson.completed"},
    {"key": "lesson_cancelled", "label": "Lesson cancelled", "event": "lesson.cancelled"},
    {"key": "invoice_issued", "label": "Invoice issued", "event": "invoice.issued"},
    {"key": "invoice_paid", "label": "Invoice paid", "event": "invoice.paid"},
    {"key": "payment_received", "label": "Payment received", "event": "payment.succeeded"},
    {"key": "report_submitted", "label": "Lesson report submitted",
     "event": "lesson_report.submitted"},
    {"key": "application_received", "label": "Tutor application received",
     "event": "application.submitted"},
)  # fmt: skip

ACTIONS: tuple[dict[str, str], ...] = (
    {"key": "create_client", "label": "Create client", "method": "POST", "path": "/api/v1/clients",
     "scope": "clients:write"},
    {"key": "update_client", "label": "Update client", "method": "PATCH",
     "path": "/api/v1/clients/{id}", "scope": "clients:write"},
    {"key": "create_student", "label": "Create student", "method": "POST",
     "path": "/api/v1/students", "scope": "students:write"},
    {"key": "update_student", "label": "Update student", "method": "PATCH",
     "path": "/api/v1/students/{id}", "scope": "students:write"},
    {"key": "create_enquiry", "label": "Create enquiry", "method": "POST",
     "path": "/api/v1/enquiries", "scope": "enquiries:write"},
    {"key": "create_lesson", "label": "Create lesson", "method": "POST", "path": "/api/v1/lessons",
     "scope": "lessons:write"},
    {"key": "add_note", "label": "Add note", "method": "POST", "path": "/api/v1/notes",
     "scope": "crm:write"},
    {"key": "add_task", "label": "Add task", "method": "POST", "path": "/api/v1/tasks",
     "scope": "crm:write"},
    {"key": "create_charge", "label": "Create ad hoc charge", "method": "POST",
     "path": "/api/v1/charges", "scope": "invoices:write"},
    {"key": "add_tag", "label": "Add tag", "method": "POST", "path": "/api/v1/tags/{id}/apply",
     "scope": "crm:write"},
)  # fmt: skip

SEARCHES: tuple[dict[str, str], ...] = (
    {"key": "find_client", "label": "Find client by email or name", "path": "/api/v1/clients",
     "query": "q", "scope": "clients:read"},
    {"key": "find_student", "label": "Find student by name", "path": "/api/v1/students",
     "query": "q", "scope": "students:read"},
    {"key": "find_tutor", "label": "Find tutor by email or name", "path": "/api/v1/tutors",
     "query": "q", "scope": "tutors:read"},
)  # fmt: skip


def manifest(platform: str) -> dict[str, Any]:
    from .models import OAuthApplication

    if platform not in PLATFORMS:
        raise KeyError(platform)
    app = OAuthApplication.objects.filter(partner_key=platform, revoked_at__isnull=True).first()
    scopes = sorted(
        {a["scope"] for a in ACTIONS} | {s["scope"] for s in SEARCHES} | {"webhooks:write"}
    )
    return {
        "platform": platform,
        "name": "TutorTrack",
        "version": "1.0.0",
        "authentication": {
            "type": "oauth2",
            "authorize_url": "https://{subdomain}.tutortrack.app/oauth/authorize",
            "token_url": "https://app.tutortrack.app/api/v1/oauth/token",
            "revoke_url": "https://app.tutortrack.app/api/v1/oauth/revoke",
            "pkce": True,
            "client_id": app.client_id if app else "",
            "scopes": scopes,
            "test_request": {"method": "GET", "path": "/api/v1/webhook-event-types"},
        },
        "triggers": [
            {
                **t,
                "type": "hook",
                "subscribe": {
                    "method": "POST",
                    "path": "/api/v1/webhook-endpoints",
                    "body": {"url": "{{bundle.targetUrl}}", "events": [t["event"]]},
                },
                "unsubscribe": {"method": "DELETE", "path": "/api/v1/webhook-endpoints/{id}"},
                "perform_list": {
                    "method": "GET",
                    "path": f"/api/v1/webhook-event-types/{t['event']}/sample",
                },
            }
            for t in TRIGGERS
        ],
        "actions": list(ACTIONS),
        "searches": list(SEARCHES),
    }
