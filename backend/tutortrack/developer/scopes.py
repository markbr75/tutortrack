"""OAuth/API-key scopes and the public API surface (FR-27-1, E27-T01).

A scope is ``<resource>:read`` or ``<resource>:write`` and maps to permission codename
*patterns*. A token request is allowed when **both** hold:

1. the endpoint is public and the token has a scope for its resource (``read`` for safe
   methods, ``write`` otherwise), checked by ``auth.ApiTokenMiddleware``; and
2. every permission the view checks is granted by the token's user *and* covered by one of
   the token's scopes (``core.permissions.has_perm`` consults ``user.token_permissions``).

``write`` implies ``read`` for the same resource.

Public endpoints are declared here by view class (``app.api.views.ViewClass``) so apps keep
their views unchanged; everything else is ``internal`` (first-party apps only).
"""

from __future__ import annotations

from dataclasses import dataclass

from django.utils.translation import gettext_lazy as _


@dataclass(frozen=True)
class Resource:
    key: str
    label: str
    read: tuple[str, ...]
    write: tuple[str, ...] = ()


RESOURCES: dict[str, Resource] = {
    r.key: r
    for r in (
        Resource(
            "clients", str(_("Clients and contacts")),
            read=("people.client.view", "people.contact.view", "people.contact.view_details",
                  "people.contact.view_phone"),
            write=("people.client.create", "people.client.edit", "people.client.archive",
                   "people.contact.create", "people.contact.edit", "people.contact.archive"),
        ),
        Resource(
            "students", str(_("Students")),
            read=("people.student.view",),
            write=("people.student.create", "people.student.edit", "people.student.archive"),
        ),
        Resource(
            "tutors", str(_("Tutors")),
            read=("people.tutor.view",),
            write=("people.tutor.create", "people.tutor.edit", "people.tutor.archive"),
        ),
        Resource(
            "services", str(_("Services and catalogue")),
            read=("catalogue.view", "billing.rates.view_charge"),
            write=("catalogue.manage",),
        ),
        Resource(
            "jobs", str(_("Jobs")),
            read=("jobs.job.view",),
            write=("jobs.job.create", "jobs.job.edit", "jobs.job.manage_tutors",
                   "jobs.job.change_status"),
        ),
        Resource(
            "lessons", str(_("Lessons, attendance and lesson reports")),
            read=("scheduling.lesson.view", "scheduling.event.view", "delivery.report.view"),
            write=("scheduling.lesson.create", "scheduling.lesson.edit",
                   "scheduling.lesson.cancel", "scheduling.lesson.complete",
                   "delivery.attendance.edit"),
        ),
        Resource(
            "availability", str(_("Availability and free slots")),
            read=("scheduling.availability.view",),
            write=("scheduling.availability.edit", "scheduling.availability.manage_others"),
        ),
        Resource(
            "invoices", str(_("Invoices, charges and payment requests")),
            read=("billing.invoice.view", "billing.charge.view", "billing.payment_request.view"),
            write=("billing.invoice.create", "billing.invoice.issue", "billing.charge.create",
                   "billing.payment_request.manage"),
        ),
        Resource(
            "payments", str(_("Payments")),
            read=("payments.payment.view",),
            write=("payments.payment.record",),
        ),
        Resource("payroll", str(_("Tutor pay items")), read=("payroll.view",)),
        Resource(
            "enquiries", str(_("Enquiries and form submissions")),
            read=("leads.enquiry.view",),
            write=("leads.enquiry.create", "leads.enquiry.edit"),
        ),
        Resource(
            "crm", str(_("Tags, custom fields, notes and tasks")),
            read=("crm.note.view", "crm.task.view", "crm.search"),
            write=("crm.note.create", "crm.note.edit", "crm.task.create", "crm.task.edit",
                   "crm.tag.apply", "crm.tag.manage", "crm.customfield.manage"),
        ),
        Resource("branches", str(_("Branches")), read=("org.settings.view",)),
        Resource(
            "webhooks", str(_("Webhook endpoints")),
            read=("developer.webhook.view",),
            write=("developer.webhook.manage",),
        ),
    )
}  # fmt: skip

ALL_SCOPES: tuple[str, ...] = tuple(
    f"{key}:{level}"
    for key, resource in RESOURCES.items()
    for level in ("read", "write")
    if level == "read" or resource.write
)


def scope_label(scope: str) -> str:
    key, _sep, level = scope.partition(":")
    resource = RESOURCES[key]
    verb = _("Read") if level == "read" else _("Read and write")
    return f"{verb}: {resource.label}"


def validate_scopes(scopes: list[str]) -> list[str]:
    """Known scopes, de-duplicated and sorted; raises ``ValueError`` on an unknown one."""
    unknown = [s for s in scopes if s not in ALL_SCOPES]
    if unknown:
        raise ValueError(", ".join(unknown))
    return sorted(set(scopes))


def has_scope(scopes: list[str] | tuple[str, ...], resource: str, write: bool) -> bool:
    if f"{resource}:write" in scopes:
        return True
    return not write and f"{resource}:read" in scopes


def permission_patterns(scopes: list[str] | tuple[str, ...]) -> frozenset[str]:
    """Permission codename patterns a set of scopes covers (``write`` includes ``read``)."""
    patterns: set[str] = set()
    for scope in scopes:
        key, _sep, level = scope.partition(":")
        resource = RESOURCES.get(key)
        if resource is None:
            continue
        patterns.update(resource.read)
        if level == "write":
            patterns.update(resource.write)
    return frozenset(patterns)


# --- the public API surface ---------------------------------------------------------------------

# View class (module path without "tutortrack.") → resource whose scope it needs.
PUBLIC_VIEWS: dict[str, str] = {
    "people.api.views.ClientViewSet": "clients",
    "people.api.views.ClientContactViewSet": "clients",
    "people.api.views.ContactViewSet": "clients",
    "people.api.views.StudentViewSet": "students",
    "people.api.views.TutorViewSet": "tutors",
    "catalogue.api.views.ServiceViewSet": "services",
    "catalogue.api.views.SubjectViewSet": "services",
    "catalogue.api.views.LevelViewSet": "services",
    "catalogue.api.views.CategoryViewSet": "services",
    "catalogue.api.views.LocationViewSet": "services",
    "jobs.api.views.JobViewSet": "jobs",
    "scheduling.api.views.LessonViewSet": "lessons",
    "delivery.api.views.LessonReportViewSet": "lessons",
    "delivery.api.views.LessonReportsView": "lessons",
    "scheduling.api.views.AvailabilityView": "availability",
    "scheduling.api.views.SlotsView": "availability",
    "billing.api.views.InvoiceViewSet": "invoices",
    "billing.api.views.ChargeViewSet": "invoices",
    "billing.api.views.PaymentRequestViewSet": "invoices",
    "payments.api.views.PaymentViewSet": "payments",
    "payroll.api.views.PayItemViewSet": "payroll",
    "leads.api.views.EnquiryViewSet": "enquiries",
    "crm.api.views.TagViewSet": "crm",
    "crm.api.views.CustomFieldViewSet": "crm",
    "crm.api.views.NoteViewSet": "crm",
    "crm.api.views.TaskViewSet": "crm",
    "tenancy.api.views.BranchViewSet": "branches",
    "developer.api.views.WebhookEndpointViewSet": "webhooks",
    "developer.api.views.WebhookDeliveryViewSet": "webhooks",
    "developer.api.views.EventTypesView": "webhooks",
    "developer.api.views.EventSampleView": "webhooks",
}

_extra_public: dict[str, str] = {}


def register_public(view_path: str, resource: str) -> None:
    """Mark another view public (plugins and tests)."""
    if resource not in RESOURCES:
        raise ValueError(f"Unknown resource {resource!r}")
    _extra_public[view_path] = resource


def view_path(view_class: type) -> str:
    return f"{view_class.__module__.removeprefix('tutortrack.')}.{view_class.__qualname__}"


def resource_for(view_class: type | None) -> str | None:
    """The resource of a public view class, or None when the view is internal."""
    if view_class is None:
        return None
    path = view_path(view_class)
    return PUBLIC_VIEWS.get(path) or _extra_public.get(path)
