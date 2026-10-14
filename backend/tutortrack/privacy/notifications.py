"""Privacy and safeguarding messages on the E13 registry (E29 Part 2).

Every type takes a ``(title, body, link)`` payload, like the staff alerts. Safeguarding
messages never carry names or descriptions: only the case reference, category and link.
``notify_*`` helpers send them (after the surrounding transaction commits).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from django.utils.translation import gettext_lazy as _

from tutortrack.comms.catalogue import SAMPLE_BASE, organisation, tenant_link, user_recipient
from tutortrack.comms.defaults import DEFAULTS, SIGN
from tutortrack.comms.registry import Delivery, NotificationType, Recipient, register

Payload = tuple[str, str, str]


def holders(codename: str, *, staff_only: bool = False) -> list[Recipient]:
    """Active members (staff, tutors with custom roles...) holding ``codename``."""
    from tutortrack.core.permission_registry import matches
    from tutortrack.identity.models import Membership
    from tutortrack.identity.rbac import grants_for

    staff_roles = {"owner", "admin", "branch_manager", "coordinator", "finance"}
    out: list[Recipient] = []
    for membership in Membership.objects.filter(status=Membership.Status.ACTIVE).select_related(
        "user"
    ):
        if staff_only and membership.role not in staff_roles:
            continue
        if not membership.user.is_active:
            continue
        grants, denies = grants_for(membership)
        if any(matches(d, codename) for d in denies):
            continue
        if any(matches(g.pattern, codename) and g.scope == "all" for g in grants):
            out.append(user_recipient(membership.user))
    return out


def _deliveries(recipients: list[Recipient], payload: Payload) -> list[Delivery]:
    title, body, link = payload
    seen: set[tuple[str, str]] = set()
    out = []
    for r in recipients:
        if (r.kind, r.id) in seen:
            continue
        seen.add((r.kind, r.id))
        out.append(
            Delivery(
                r,
                {
                    "organisation": organisation(),
                    "recipient": {"name": r.name, "first_name": r.first_name},
                    "alert": {"title": title, "body": body, "link": link},
                },
            )
        )
    return out


def _to(codename: str, *, staff_only: bool = False) -> Callable[[Any], list[Delivery]]:
    def resolve(payload: Payload) -> list[Delivery]:
        return _deliveries(holders(codename, staff_only=staff_only), payload)

    return resolve


def _to_requester(payload: Any) -> list[Delivery]:
    """``(title, body, link, request)``: the person who asked for their data."""
    title, body, link, request = payload
    if not request.requester_email:
        return []
    recipient = Recipient(
        kind="dsar",
        id=str(request.pk),
        name=request.requester_name,
        first_name=request.requester_name.split(" ")[0] if request.requester_name else "",
        email=request.requester_email,
        target=(request.subject_type, request.subject_id),
    )
    return _deliveries([recipient], (title, body, link))


def _lone_working(payload: Any) -> list[Delivery]:
    """``(title, body, link, tutor, escalate)``: monitors (and DSLs once escalated)."""
    from tutortrack.comms.catalogue import tutor_recipient

    title, body, link, tutor, escalate = payload
    recipients = holders("safeguarding.lone_working.monitor")
    if escalate:
        recipients += holders("safeguarding.dsl")
    if tutor is not None:
        recipients.append(tutor_recipient(tutor))
    return _deliveries(recipients, (title, body, link))


SAMPLE = {
    **SAMPLE_BASE,
    "alert": {"title": "Data request DSAR-00012 is due in 7 days", "body": "", "link": "/"},
}
ALERT_VARS = ("alert.title", "alert.body", "alert.link")


def _type(
    key: str,
    label: Any,
    resolve: Callable[[Any], list[Delivery]],
    *,
    audience: str = "staff",
    channels: tuple[str, ...] = ("in_app", "email"),
    default_channels: tuple[str, ...] = ("in_app", "email"),
    transactional: bool = True,
) -> None:
    register(
        NotificationType(
            key=key,
            label=str(label),
            category="account" if audience != "staff" else "staff",
            audience=audience,
            channels=channels,
            default_channels=default_channels,
            resolve=resolve,
            load=lambda pk: None,
            related_type="",
            variables=ALERT_VARS,
            sample=SAMPLE,
            transactional=transactional,
            link=lambda payload: payload[2],
        )
    )
    DEFAULTS[(key, "in_app")] = ("{{ alert.title }}", "{{ alert.body }}")
    DEFAULTS[(key, "email")] = (
        "{{ alert.title }}",
        "Hello {{ recipient.first_name }},\n\n{{ alert.body }}"
        "{% if alert.link %}\n\n{{ alert.link }}{% endif %}" + SIGN,
    )


_type(
    "privacy_dsar_staff",
    _("Data subject requests (deadlines and reviews)"),
    _to("privacy.dsar.manage", staff_only=True),
)
_type(
    "privacy_dsar_requester",
    _("Your data request (to the person who asked)"),
    _to_requester,
    audience="client",
    channels=("email",),
    default_channels=("email",),
)
_type(
    "privacy_retention_report",
    _("Retention purge report"),
    _to("privacy.retention.manage", staff_only=True),
)
_type(
    "safeguarding_alert",
    _("Safeguarding concern or flagged message (to safeguarding leads)"),
    _to("safeguarding.dsl"),
    channels=("in_app", "email", "push"),
    default_channels=("in_app", "email", "push"),
)
_type(
    "lone_working_overdue",
    _("A tutor hasn't checked out of a lesson"),
    _lone_working,
    channels=("in_app", "email", "sms", "push"),
    default_channels=("in_app", "email", "push"),
)
_type(
    "privacy_subprocessors_changed",
    _("TutorTrack's sub-processors changed"),
    _to("org.settings.manage", staff_only=True),
)


def send(type_key: str, payload: Any, *, key: str, immediate: bool = False) -> None:
    """Send after commit, capturing the tenant now (on_commit runs outside the context)."""
    from django.db import transaction

    from tutortrack.comms.services import notify
    from tutortrack.core.context import require_organisation_id, tenant_context

    org_id = require_organisation_id()

    def go() -> None:
        with tenant_context(org_id):
            notify(type_key, payload, key=key, immediate=immediate)

    transaction.on_commit(go)


def admin_link(path: str) -> str:
    return tenant_link(path)


def local_date(moment: Any) -> str:
    """A date in the organisation's timezone and locale format (no hard-coded formats)."""
    from zoneinfo import ZoneInfo

    from django.utils import formats

    tz = ZoneInfo(organisation()["timezone"] or "UTC")
    return str(formats.date_format(moment.astimezone(tz).date(), "DATE_FORMAT"))


def local_time(moment: Any) -> str:
    from zoneinfo import ZoneInfo

    from django.utils import formats

    tz = ZoneInfo(organisation()["timezone"] or "UTC")
    return str(formats.time_format(moment.astimezone(tz).time(), "TIME_FORMAT"))
