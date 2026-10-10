"""Notifications about integrations (E13 catalogue entries registered by this app):

* ``integration_problem``: a connection failed or needs reconnecting. Personal
  connections tell their owner; organisation connections tell ``integrations.manage``.
* ``calendar_notice``: something a tutor should know about their synced calendar (a
  lesson deleted in Google was put back, a move was proposed as a reschedule).
* ``staff_meeting_failed``: an online meeting couldn't be created after retries.
"""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _lazy

from tutortrack.comms import catalogue
from tutortrack.comms.defaults import DEFAULTS, SIGN
from tutortrack.comms.registry import Delivery, NotificationType, register

SETTINGS_LINK = "/settings/integrations"


def _deliveries(payload: Any) -> list[Delivery]:
    """``payload`` = (title, body, link, user id or None for organisation-level)."""
    from tutortrack.identity.models import User

    title, body, link, user_id = payload
    if user_id:
        user = User.objects.filter(pk=user_id).first()
        recipients = [catalogue.user_recipient(user)] if user else []
    else:
        recipients = catalogue.staff_with("integrations.manage")
    base = {
        "organisation": catalogue.organisation(),
        "alert": {"title": title, "body": body, "link": link},
    }
    return [
        Delivery(r, {**base, "recipient": {"name": r.name, "first_name": r.first_name}})
        for r in recipients
    ]


for _key, _label, _audience in (
    ("integration_problem", _lazy("A connected account needs attention"), "staff"),
    ("calendar_notice", _lazy("Calendar sync notices"), "tutor"),
):
    register(
        NotificationType(
            key=_key,
            label=str(_label),
            category="account",
            audience=_audience,
            channels=("in_app", "email"),
            default_channels=("in_app", "email") if _key == "integration_problem" else ("in_app",),
            resolve=_deliveries,
            load=lambda pk: None,
            related_type="",
            variables=("alert.title", "alert.body", "alert.link"),
            sample=catalogue.SAMPLE_ALERT,
            transactional=True,
            link=lambda payload: payload[2],
        )
    )
register(
    NotificationType(
        key="staff_meeting_failed",
        label=str(_lazy("An online lesson has no meeting room")),
        category="staff",
        audience="staff",
        channels=("in_app", "email"),
        default_channels=("in_app", "email"),
        resolve=catalogue._alert("scheduling.lesson.edit"),
        load=lambda pk: None,
        related_type="",
        variables=("alert.title", "alert.body", "alert.link"),
        sample=catalogue.SAMPLE_ALERT,
        link=lambda payload: payload[2],
    )
)
for _key in ("integration_problem", "calendar_notice", "staff_meeting_failed"):
    DEFAULTS[(_key, "in_app")] = ("{{ alert.title }}", "{{ alert.body }}")
    DEFAULTS[(_key, "email")] = (
        "{{ alert.title }}",
        "{{ alert.body }}\n\n{{ alert.link }}" + SIGN,
    )


def _send(type_key: str, payload: tuple[str, str, str, Any], key: str) -> None:
    from tutortrack.comms import services as comms

    transaction.on_commit(lambda: comms.notify(type_key, payload, key=key))


def notify_problem(connection: Any) -> None:
    from tutortrack.integrations import providers

    label = providers.get_spec(connection.provider).label
    if connection.status == "needs_reconnect":
        title = _("Reconnect %(provider)s") % {"provider": label}
        body = _(
            "TutorTrack can no longer reach your %(provider)s account. Connect it again "
            "to keep things in sync."
        ) % {"provider": label}
    else:
        title = _("%(provider)s isn't syncing") % {"provider": label}
        body = _("We'll keep retrying. Last error: %(error)s") % {"error": connection.error}
    _send(
        "integration_problem",
        (title, body, SETTINGS_LINK, str(connection.user_id) if connection.user_id else None),
        key=f"{connection.pk}:{connection.status}:{connection.error_count}",
    )


def notify_calendar(user_id: Any, title: str, body: str, key: str, link: str = "") -> None:
    _send("calendar_notice", (title, body, link or "/calendar", str(user_id)), key=key)


def notify_meeting_failed(lesson: Any, error: str) -> None:
    from tutortrack.comms import services as comms

    title = _("No meeting room for %(lesson)s") % {"lesson": lesson.title}
    body = _(
        "We couldn't create the online meeting after several tries (%(error)s). Add a "
        "link to the lesson by hand or check the video integration."
    ) % {"error": error}
    payload = (title, body, f"/calendar?lesson={lesson.pk}")
    transaction.on_commit(
        lambda: comms.notify("staff_meeting_failed", payload, key=f"meeting:{lesson.pk}:{error}")
    )
