"""E21-T01 resource library: org and personal libraries, files and links, sharing to
students/jobs/lessons/classes, portal display, view tracking and storage (FR-21-1)."""

from __future__ import annotations

import pytest

from tutortrack.core import entitlements
from tutortrack.core.context import tenant_context
from tutortrack.core.models import StoredFile
from tutortrack.learning import selectors, services
from tutortrack.learning.models import Resource, ResourceActivity, ResourceShare

from .conftest import at, events_of, lesson_for

pytestmark = pytest.mark.django_db

URL = "/api/v1/learning/resources"


def uploaded_pdf(org, user=None, size=2048):
    with tenant_context(org):
        return StoredFile.objects.create(
            filename="worksheet.pdf",
            content_type="application/pdf",
            size_bytes=size,
            storage_key=f"org/{org.pk}/test/{size}/worksheet.pdf",
            status=StoredFile.Status.UPLOADED,
            scan_status=StoredFile.ScanStatus.CLEAN,
            uploaded_by=user,
        )


def test_links_are_typed_by_where_they_point(org, world):
    api = world["admin_api"]
    youtube = api.post(
        URL,
        {"title": "Fractions video", "kind": "link", "url": "https://youtu.be/abc", "tags": ["y6"]},
        format="json",
    )
    assert youtube.status_code == 201, youtube.content
    assert youtube.json()["media_type"] == "youtube"
    docs = api.post(
        URL,
        {"title": "Notes", "kind": "link", "url": "https://docs.google.com/document/d/1"},
        format="json",
    )
    assert docs.json()["media_type"] == "google_docs"
    bad = api.post(URL, {"title": "x", "kind": "link", "url": "javascript:alert(1)"}, format="json")
    assert bad.status_code == 422


def test_file_resources_need_an_upload_and_take_its_type(org, world):
    stored = uploaded_pdf(org, world["admin"])
    api = world["admin_api"]
    response = api.post(
        URL, {"title": "Worksheet", "kind": "file", "file": str(stored.pk)}, format="json"
    )
    assert response.status_code == 201, response.content
    body = response.json()
    assert (body["media_type"], body["file_name"]) == ("pdf", "worksheet.pdf")
    with tenant_context(org):
        stored.refresh_from_db()
        assert stored.owner_object_id == body["id"]  # access rules follow the resource
    missing = api.post(URL, {"title": "Nothing", "kind": "file"}, format="json")
    assert missing.status_code == 422


def test_storage_usage_reports_the_plan_allowance(org, world, monkeypatch):
    uploaded_pdf(org, size=5000)
    monkeypatch.setattr(entitlements, "limit", lambda key, organisation_id=None: 5)
    body = world["admin_api"].get("/api/v1/learning/storage").json()
    assert body["used_bytes"] >= 5000
    assert body["limit_gb"] == 5


def test_tutors_have_a_personal_library_and_see_the_tutor_library(org, world):
    with tenant_context(org):
        staff_only = services.save_resource(
            None, title="Answers", kind="link", url="https://e.com/a", visibility="staff"
        )
        shared_library = services.save_resource(
            None, title="Library", kind="link", url="https://e.com/l", visibility="tutors"
        )
    mine = world["tutor_api"].post(
        URL, {"title": "My notes", "kind": "link", "url": "https://e.com/n"}, format="json"
    )
    assert mine.status_code == 201, mine.content
    assert mine.json()["owner"] == str(world["tutor"].pk)
    assert mine.json()["visibility"] == "private"
    seen = {r["id"] for r in world["tutor_api"].get(URL).json()["results"]}
    assert seen == {mine.json()["id"], str(shared_library.pk)}
    assert str(staff_only.pk) not in seen
    other_sees = {r["id"] for r in world["other_api"].get(URL).json()["results"]}
    assert mine.json()["id"] not in other_sees
    # Tutors can't change the organisation library.
    edit = world["tutor_api"].patch(
        f"{URL}/{shared_library.pk}", {"title": "Mine now"}, format="json"
    )
    assert edit.status_code == 403


def test_sharing_reaches_the_family_portal_and_tracks_views(org, world):
    with tenant_context(org):
        resource = services.save_resource(
            None, title="Ratio video", kind="link", url="https://youtu.be/r"
        )
    response = world["tutor_api"].post(
        f"{URL}/{resource.pk}/share",
        {"students": [str(world["student"].pk)], "message": "Watch before Tuesday"},
        format="json",
    )
    assert response.status_code == 201, response.content
    assert response.json()[0]["target"] == "student"
    assert events_of(org, "resource.shared")[0]["data"]["student_ids"] == [str(world["student"].pk)]

    family = world["family"]["api"]
    listed = family.get("/api/v1/portal/learning/resources").json()
    assert [r["title"] for r in listed] == ["Ratio video"]
    assert listed[0]["message"] == "Watch before Tuesday"
    assert world["others"]["api"].get("/api/v1/portal/learning/resources").json() == []

    opened = family.post(f"/api/v1/portal/learning/resources/{resource.pk}/open")
    assert opened.json() == {"url": "https://youtu.be/r", "expires_in": None, "kind": "link"}
    family.post(f"/api/v1/portal/learning/resources/{resource.pk}/open")
    with tenant_context(org):
        activity = ResourceActivity.objects.get(resource=resource)
        assert (activity.views, activity.downloads) == (2, 0)
    stranger = world["others"]["api"].post(f"/api/v1/portal/learning/resources/{resource.pk}/open")
    assert stranger.status_code == 404
    tracked = world["admin_api"].get(f"{URL}/{resource.pk}/activity").json()
    assert tracked[0]["views"] == 2


def test_shares_to_jobs_lessons_and_classes_reach_their_students(org, world):
    lesson = lesson_for(org, world, at(2), [world["sibling"]])
    with tenant_context(org):
        by_job = services.save_resource(None, title="Job", kind="link", url="https://e.com/j")
        by_lesson = services.save_resource(None, title="Lesson", kind="link", url="https://e.com/l")
        services.share_resource(by_job, jobs=[world["job"]])
        services.share_resource(by_lesson, lessons=[lesson])
        household = world["family"]
        from tutortrack.portal.household import household_for

        titles = set(
            selectors.household_resources(household_for(household["user"])).values_list(
                "title", flat=True
            )
        )
    assert titles == {"Job", "Lesson"}


def test_tutors_only_share_with_their_own_students(org, world):
    with tenant_context(org):
        resource = services.save_resource(None, title="R", kind="link", url="https://e.com/r")
    response = world["tutor_api"].post(
        f"{URL}/{resource.pk}/share", {"students": [str(world["stranger"].pk)]}, format="json"
    )
    assert response.status_code == 403
    nobody = world["tutor_api"].post(f"{URL}/{resource.pk}/share", {}, format="json")
    assert nobody.status_code == 422


def test_unsharing_and_archiving(org, world):
    with tenant_context(org):
        resource = services.save_resource(None, title="R", kind="link", url="https://e.com/r")
        share = services.share_resource(resource, students=[world["student"]])[0]
    again = world["admin_api"].post(
        f"{URL}/{resource.pk}/share", {"students": [str(world["student"].pk)]}, format="json"
    )
    assert again.json()[0]["id"] == str(share.pk)  # already shared: kept, not duplicated
    assert (
        world["admin_api"].delete(f"/api/v1/learning/resource-shares/{share.pk}").status_code == 204
    )
    with tenant_context(org):
        assert not ResourceShare.objects.exists()
    archived = world["admin_api"].post(
        f"{URL}/{resource.pk}/archive", {"archived": True}, format="json"
    )
    assert archived.json()["archived_at"] is not None
    with tenant_context(org), pytest.raises(Exception, match="Archived"):
        services.share_resource(Resource.objects.get(pk=resource.pk), students=[world["student"]])


def test_folders_nest_without_cycles(org, world):
    api = world["admin_api"]
    top = api.post("/api/v1/learning/folders", {"name": "Maths"}, format="json").json()
    child = api.post(
        "/api/v1/learning/folders", {"name": "Fractions", "parent": top["id"]}, format="json"
    ).json()
    cycle = api.patch(
        f"/api/v1/learning/folders/{top['id']}", {"parent": child["id"]}, format="json"
    )
    assert cycle.status_code == 422
    assert api.delete(f"/api/v1/learning/folders/{top['id']}").status_code == 204
    assert [f["name"] for f in api.get("/api/v1/learning/folders").json()] == ["Fractions"]
