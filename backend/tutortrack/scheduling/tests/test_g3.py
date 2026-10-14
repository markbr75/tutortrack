"""Gap G3 (E08): the booking cancellation window is enforced in the portal (FR-08-9), the
website builder's ``booking`` block (FR-24-4) and the printable timetable (FR-08-7)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from tutortrack.core.context import tenant_context
from tutortrack.portal.tests.test_portal import lesson_for, world  # noqa: F401 - fixture
from tutortrack.scheduling.models import BookingSettings, Lesson
from tutortrack.sites.tests.factories import SiteFactory, SitePageFactory
from tutortrack.sites.tests.test_profiles_sites import site_client

pytestmark = pytest.mark.django_db


def booked_online(org, world, hours):  # noqa: F811
    lesson = lesson_for(org, world, [world["a"]["students"][0]], hours=hours)
    with tenant_context(org):
        Lesson.objects.filter(pk=lesson.pk).update(created_via=Lesson.CreatedVia.CLIENT_BOOKING)
        BookingSettings.objects.update_or_create(defaults={"cancellation_window_hours": 24})
    return lesson


# --- booking cancellation window (FR-08-9) ------------------------------------------------------


def test_self_booked_lessons_cant_be_cancelled_online_inside_the_window(org, world):  # noqa: F811
    api = world["a"]["api"]
    soon = booked_online(org, world, hours=10)
    refused = api.post(f"/api/v1/portal/lessons/{soon.pk}/cancel?preview=true", {}, format="json")
    assert refused.status_code == 422
    assert refused.json()["code"] == "cancellation_window_closed"
    later = booked_online(org, world, hours=72)
    schedule = api.get("/api/v1/portal/schedule").json()
    until = {row["id"]: row["cancel_online_until"] for row in schedule}
    assert until[str(later.pk)] is not None
    ok = api.post(f"/api/v1/portal/lessons/{later.pk}/cancel", {}, format="json")
    assert ok.status_code == 200
    assert ok.json()["cancelled"] is True


def test_staff_booked_lessons_and_a_zero_window_are_not_limited(org, world):  # noqa: F811
    api = world["a"]["api"]
    staff_booked = lesson_for(org, world, [world["a"]["students"][0]], hours=10)
    ok = api.post(
        f"/api/v1/portal/lessons/{staff_booked.pk}/cancel?preview=true", {}, format="json"
    )
    assert ok.status_code == 200
    soon = booked_online(org, world, hours=5)
    with tenant_context(org):
        BookingSettings.objects.update(cancellation_window_hours=0)
    ok = api.post(f"/api/v1/portal/lessons/{soon.pk}/cancel?preview=true", {}, format="json")
    assert ok.status_code == 200


# --- website builder booking block (FR-24-4) -----------------------------------------------------


def test_booking_block_renders_the_widget_when_booking_is_on(org, admin_api):
    blocks = {b["key"] for b in admin_api.get("/api/v1/sites/blocks").json()}
    assert "booking" in blocks
    site = SiteFactory(organisation=org, published=True)
    page = SitePageFactory(organisation=org, site=site, path="", title="Home")
    saved = admin_api.patch(
        f"/api/v1/sites/pages/{page.pk}",
        {"blocks": [{"type": "booking", "props": {"heading": "Book a trial", "days": 14}}]},
        format="json",
    )
    assert saved.status_code == 200, saved.content
    admin_api.post(f"/api/v1/sites/pages/{page.pk}/publish")
    closed = site_client(org).get("/").content.decode()
    assert "Book a trial" in closed
    assert "<tt-booking" not in closed
    with tenant_context(org):
        BookingSettings.objects.update_or_create(defaults={"enabled": True})
    admin_api.post(f"/api/v1/sites/pages/{page.pk}/publish")
    html = site_client(org).get("/").content.decode()
    assert '<tt-booking days="14">' in html
    assert 'type="module"' in html  # the widgets script is loaded for the block


def test_booking_block_props_are_validated(org, admin_api):
    site = SiteFactory(organisation=org, published=True)
    page = SitePageFactory(organisation=org, site=site, path="", title="Home")
    bad = admin_api.patch(
        f"/api/v1/sites/pages/{page.pk}",
        {"blocks": [{"type": "booking", "props": {"days": 90}}]},
        format="json",
    )
    assert bad.status_code == 422


# --- printable timetable (FR-08-7) --------------------------------------------------------------


def test_timetable_pdf_for_a_tutor(org, world, admin_api):  # noqa: F811
    lesson = lesson_for(org, world, [world["a"]["students"][0]], hours=30)
    start = (lesson.start - timedelta(days=1)).isoformat()
    end = (lesson.start + timedelta(days=6)).isoformat()
    response = admin_api.get(
        "/api/v1/calendar/timetable",
        {"start": start, "end": end, "tutor": str(world["tutor"].pk)},
    )
    assert response.status_code == 200, response.content
    assert response["Content-Type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
    too_long = admin_api.get(
        "/api/v1/calendar/timetable",
        {"start": start, "end": (lesson.start + timedelta(days=60)).isoformat()},
    )
    assert too_long.status_code == 400
