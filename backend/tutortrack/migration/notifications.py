"""The "your data export is ready" email (FR-28-7), registered with the comms notification
registry so organisations can edit its wording like any other message. It goes to whoever
asked for the export, or to the owners when account closure or the platform did."""

from __future__ import annotations

from typing import Any

from django.utils.translation import gettext_lazy as _

from tutortrack.comms import defaults
from tutortrack.comms.catalogue import SAMPLE_BASE, organisation, tenant_link, user_recipient
from tutortrack.comms.registry import Delivery, NotificationType, register

EXPORT_READY = "data_export_ready"


def _load(pk: str) -> Any:
    from .models import ExportJob

    return ExportJob.objects.select_related("requested_by").filter(pk=pk).first()


def _recipients(job: Any) -> list[Any]:
    from tutortrack.identity.models import Membership

    if job.requested_by is not None and job.requested_by.is_active:
        return [job.requested_by]
    return [
        m.user
        for m in Membership.objects.filter(
            role=Membership.Role.OWNER, status=Membership.Status.ACTIVE
        ).select_related("user")
        if m.user.is_active
    ]


def _resolve(job: Any) -> list[Delivery]:
    from django.utils import formats

    expires = formats.date_format(job.expires_at, "DATE_FORMAT") if job.expires_at else ""
    base = {
        "organisation": organisation(),
        "export": {
            "link": tenant_link("/data/export"),
            "expires": expires,
            "size_mb": round((job.size_bytes or 0) / (1024 * 1024), 1),
        },
    }
    out = []
    for user in _recipients(job):
        r = user_recipient(user)
        out.append(Delivery(r, {**base, "recipient": {"name": r.name, "first_name": r.first_name}}))
    return out


register(
    NotificationType(
        key=EXPORT_READY,
        label=str(_("Data export ready")),
        category="account",
        audience="staff",
        channels=("email",),
        default_channels=("email",),
        resolve=_resolve,
        load=_load,
        related_type="migration.exportjob",
        variables=(
            "recipient.first_name",
            "organisation.name",
            "export.link",
            "export.expires",
            "export.size_mb",
        ),
        sample={
            **SAMPLE_BASE,
            "export": {
                "link": "https://example.com/data/export",
                "expires": "18 October 2026",
                "size_mb": 12.5,
            },
        },
        transactional=True,
        link=lambda job: "/data/export",
    )
)

defaults.DEFAULTS[(EXPORT_READY, "email")] = (
    "Your {{ organisation.name }} data export is ready",
    "Hello {{ recipient.first_name }},\n\nThe full export of {{ organisation.name }}'s data "
    "({{ export.size_mb }} MB) is ready. Download it from {{ export.link }}; you'll be asked "
    "for your password. The link works until {{ export.expires }}." + defaults.SIGN,
)
