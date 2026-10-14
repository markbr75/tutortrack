"""E16-T08: the tutor PWA's offline pack, conflict checks for reports written offline,
replaying queued completions without double-recording, and the installable manifest."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from tutortrack.core.context import tenant_context
from tutortrack.core.models import OutboxEvent
from tutortrack.core.testing import client_for
from tutortrack.core.time import now
from tutortrack.delivery import services as delivery

from .test_tutor import lesson, setup  # noqa: F401  (fixture)

pytestmark = pytest.mark.django_db


def test_offline_pack_has_the_next_week_with_report_forms(org, setup):  # noqa: F811
    s = setup
    tomorrow = lesson(org, s, hours=24)
    written = lesson(org, s, hours=-2)
    with tenant_context(org):
        report = delivery.open_report(written, s["tutor"])
    lesson(org, s, hours=24 * 9)  # beyond the week
    lesson(org, s, hours=5, tutor=s["other"])  # someone else's
    pack = s["api"].get("/api/v1/tutor/offline").json()
    assert pack["days"] == 7
    rows = {row["id"]: row for row in pack["lessons"]}
    assert set(rows) == {str(tomorrow.pk), str(written.pk)}
    fresh = rows[str(tomorrow.pk)]
    assert fresh["report"] is None
    assert fresh["report_fields"]
    assert fresh["attendees"][0]["name"] == s["student"].full_name
    opened = rows[str(written.pk)]
    assert opened["report"]["id"] == str(report.pk)
    assert opened["report"]["etag"].startswith('W/"')


def test_offline_pack_is_for_tutors_only(org, admin_api):
    assert admin_api.get("/api/v1/tutor/offline").status_code == 403


def test_reports_saved_offline_fail_on_conflict(org, setup):  # noqa: F811
    s = setup
    done = lesson(org, s, hours=-2)
    with tenant_context(org):
        report = delivery.open_report(done, s["tutor"])
    url = f"/api/v1/lesson-reports/{report.pk}"
    first = s["api"].get(url)
    etag = first["ETag"]
    assert etag
    answers = {"summary": "Fractions"}
    saved = s["api"].put(url, {"answers": answers}, format="json", HTTP_IF_MATCH=etag)
    assert saved.status_code == 200, saved.content
    assert saved["ETag"] != etag
    # A second offline edit based on the old version is a conflict for review.
    stale = s["api"].put(url, {"answers": answers}, format="json", HTTP_IF_MATCH=etag)
    assert stale.status_code == 412
    stale_submit = s["api"].post(f"{url}/submit", {}, format="json", HTTP_IF_MATCH=etag)
    assert stale_submit.status_code == 412
    # Without If-Match (online autosave) nothing changes.
    assert s["api"].put(url, {"answers": answers}, format="json").status_code == 200


def test_replayed_completion_is_recorded_once(org, setup):  # noqa: F811
    s = setup
    done = lesson(org, s, hours=-2)
    url = f"/api/v1/lessons/{done.pk}/complete"
    key = "offline-3f9a"
    first = s["api"].post(url, {}, format="json", HTTP_IDEMPOTENCY_KEY=key)
    assert first.status_code == 200, first.content
    # The phone lost the response and the service worker sends the same request again.
    replay = s["api"].post(url, {}, format="json", HTTP_IDEMPOTENCY_KEY=key)
    assert replay.status_code == 200
    assert replay["Idempotent-Replayed"] == "true"
    assert replay.json()["status"] == "completed"
    with tenant_context(org):
        completed = OutboxEvent.objects.filter(event_type="lesson.completed")
        assert [e.payload["subject"]["id"] for e in completed] == [str(done.pk)]


def test_completion_by_someone_else_needs_review(org, setup, admin_api):  # noqa: F811
    s = setup
    done = lesson(org, s, hours=-2)
    assert admin_api.post(f"/api/v1/lessons/{done.pk}/complete").status_code == 200
    queued = s["api"].post(
        f"/api/v1/lessons/{done.pk}/complete", {}, format="json", HTTP_IDEMPOTENCY_KEY="q-1"
    )
    assert 400 <= queued.status_code < 500  # the PWA shows "your changes need review"


def test_manifest_is_installable_without_a_brand_kit(org):
    manifest = client_for(org).get("/api/v1/public/manifest").json()
    assert manifest["id"] == manifest["start_url"] == manifest["scope"] == "/portal/"
    assert manifest["display"] == "standalone"
    sizes = {(i["sizes"], i["purpose"]) for i in manifest["icons"]}
    assert {("192x192", "any"), ("512x512", "any"), ("512x512", "maskable")} <= sizes
    assert manifest["shortcuts"][0]["url"] == "/portal/tutor"


def test_lessons_a_week_ahead_are_offline_but_not_the_past(org, setup):  # noqa: F811
    s = setup
    old = lesson(org, s, hours=-50)
    pack = s["api"].get("/api/v1/tutor/offline").json()
    assert str(old.pk) not in {row["id"] for row in pack["lessons"]}
    generated = datetime.fromisoformat(pack["generated_at"])
    assert abs(generated - now()) < timedelta(minutes=1)
