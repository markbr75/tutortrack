"""E05-T04..T09: custom fields, tags, notes, tasks, documents, timeline, search, saved views,
bulk actions."""

from __future__ import annotations

from datetime import timedelta

import pytest

from tutortrack.core.context import tenant_context
from tutortrack.core.models import AuditEntry, OutboxEvent, StoredFile
from tutortrack.core.testing import TenantIsolationTestMixin, client_for, result_ids
from tutortrack.core.time import now
from tutortrack.crm import services
from tutortrack.crm.models import BulkJob, Note, TaggedItem, Task
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.people.models import Client, Student
from tutortrack.people.tests.factories import ClientFactory, StudentFactory, TutorProfileFactory

from .factories import NoteFactory, SavedViewFactory, TagFactory, TaskFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin(org):
    return MembershipFactory(organisation=org, role="admin").user


@pytest.fixture
def admin_api(org, admin):
    return client_for(org, admin)


def target(obj, kind="client"):
    return {"target_type": f"people.{kind}", "target_id": str(obj.pk)}


# --- custom fields (FR-05-5) ----------------------------------------------------------------------


def test_custom_field_definition_validates_values_on_records(org, admin_api):
    response = admin_api.post(
        "/api/v1/custom-fields",
        {
            "entity_type": "people.client",
            "key": "heard_about",
            "label": "Heard about us",
            "type": "select",
            "options": ["Google", "Friend"],
            "required": True,
        },
        format="json",
    )
    assert response.status_code == 201, response.json()
    bad = admin_api.post(
        "/api/v1/clients",
        {"type": "household", "display_name": "The Lees", "custom_fields": {"heard_about": "TV"}},
        format="json",
    )
    assert bad.status_code == 400, bad.json()
    assert bad.json()["errors"]["custom_fields"]["heard_about"] != "This field is required."
    missing = admin_api.post(
        "/api/v1/clients", {"type": "household", "display_name": "The Lees"}, format="json"
    )
    assert missing.status_code == 400
    ok = admin_api.post(
        "/api/v1/clients",
        {
            "type": "household",
            "display_name": "The Lees",
            "custom_fields": {"heard_about": "Friend"},
        },
        format="json",
    )
    assert ok.status_code == 201, ok.json()
    assert ok.json()["custom_fields"] == {"heard_about": "Friend"}
    listed = admin_api.get("/api/v1/clients?cf_heard_about=Friend")
    assert result_ids(listed) == {ok.json()["id"]}


def test_choice_field_needs_options(admin_api):
    response = admin_api.post(
        "/api/v1/custom-fields",
        {"entity_type": "people.student", "key": "house", "label": "House", "type": "select"},
        format="json",
    )
    assert response.status_code == 422


def test_custom_fields_need_manage_permission(org):
    tutor = client_for(org, MembershipFactory(organisation=org, role="tutor").user)
    response = tutor.post(
        "/api/v1/custom-fields",
        {"entity_type": "people.client", "key": "x", "label": "X", "type": "text"},
        format="json",
    )
    assert response.status_code == 403


# --- tags (FR-05-6) -------------------------------------------------------------------------------


def test_tag_apply_and_filter(org, admin_api):
    tag = TagFactory(organisation=org, name="VIP")
    clients = [ClientFactory(organisation=org) for _ in range(3)]
    response = admin_api.post(
        f"/api/v1/tags/{tag.pk}/apply",
        {"target_type": "people.client", "target_ids": [str(c.pk) for c in clients[:2]]},
        format="json",
    )
    assert response.json() == {"changed": 2}
    listed = admin_api.get(f"/api/v1/clients?tag={tag.pk}")
    assert sorted(result_ids(listed)) == sorted(str(c.pk) for c in clients[:2])
    again = admin_api.post(
        f"/api/v1/tags/{tag.pk}/apply",
        {"target_type": "people.client", "target_ids": [str(clients[0].pk)], "remove": True},
        format="json",
    )
    assert again.json() == {"changed": 1}
    with tenant_context(org):
        assert TaggedItem.objects.count() == 1


def test_tag_limited_to_entity_types(org, tenant):
    tag = TagFactory(organisation=org, entity_types=["people.student"])
    client = ClientFactory(organisation=org)
    with pytest.raises(Exception, match="isn't used"):
        services.apply_tag(tag, "people.client", [str(client.pk)])


# --- notes (FR-05-7) ------------------------------------------------------------------------------


def test_note_html_is_sanitised_and_mentions_recorded(org, admin, admin_api):
    colleague = MembershipFactory(organisation=org, role="coordinator").user
    client = ClientFactory(organisation=org)
    body = (
        f'<p>Ask <span data-mention="{colleague.pk}">@Sam</span> to call.</p>'
        '<script>alert(1)</script><a href="javascript:x()" onclick="y()">link</a>'
    )
    response = admin_api.post("/api/v1/notes", {**target(client), "body": body}, format="json")
    assert response.status_code == 201, response.json()
    note = response.json()
    assert "<script" not in note["body"]
    assert "onclick" not in note["body"]
    assert "javascript:" not in note["body"]
    assert note["mentions"] == [str(colleague.pk)]
    assert note["created_by"] == str(admin.pk)
    with tenant_context(org):
        event = OutboxEvent.objects.get(event_type="note.created")
        assert event.payload["data"]["mentions"] == [str(colleague.pk)]


def test_empty_note_rejected(org, admin_api):
    client = ClientFactory(organisation=org)
    response = admin_api.post(
        "/api/v1/notes", {**target(client), "body": "<script>x</script>"}, format="json"
    )
    assert response.status_code == 422


def test_notes_list_requires_a_visible_target(org, other_org, admin_api):
    response = admin_api.get("/api/v1/notes")
    assert response.status_code == 404
    theirs = ClientFactory(organisation=other_org)
    assert admin_api.get("/api/v1/notes", target(theirs)).status_code == 404


def test_staff_only_notes_hidden_from_tutors(org):
    membership = MembershipFactory(organisation=org, role="tutor")
    profile = TutorProfileFactory(organisation=org, membership=membership)
    staff = NoteFactory(organisation=org, **target(profile, "tutor"), visibility="staff_only")
    shared = NoteFactory(
        organisation=org, **target(profile, "tutor"), visibility="staff_and_tutors"
    )
    tutor = client_for(org, membership.user)
    response = tutor.get("/api/v1/notes", target(profile, "tutor"))
    assert response.status_code == 200, response.json()
    assert result_ids(response) == {str(shared.pk)}
    assert tutor.get(f"/api/v1/notes/{staff.pk}").status_code == 404
    # A tutor can't create a staff-only note: it is downgraded to staff and tutors.
    created = tutor.post(
        "/api/v1/notes",
        {**target(profile, "tutor"), "body": "<p>Hi</p>", "visibility": "staff_only"},
        format="json",
    )
    assert created.json()["visibility"] == "staff_and_tutors"


def test_tutor_cannot_note_records_they_cannot_see(org):
    tutor = client_for(org, MembershipFactory(organisation=org, role="tutor").user)
    client = ClientFactory(organisation=org)
    response = tutor.post("/api/v1/notes", {**target(client), "body": "<p>Hi</p>"}, format="json")
    assert response.status_code == 404


# --- tasks (FR-05-8) ------------------------------------------------------------------------------


def test_my_tasks_and_overdue(org, admin, admin_api):
    mine = TaskFactory(organisation=org, assignee=admin, due_at=now() - timedelta(days=1))
    TaskFactory(organisation=org, assignee=admin, due_at=now() + timedelta(days=1))
    TaskFactory(organisation=org)  # unassigned
    assert len(result_ids(admin_api.get("/api/v1/tasks?mine=true"))) == 2
    overdue = admin_api.get("/api/v1/tasks?overdue=true")
    assert result_ids(overdue) == {str(mine.pk)}
    assert overdue.json()["results"][0]["is_overdue"] is True


def test_completing_a_task_sets_completed_at_and_emits(org, admin, admin_api):
    colleague = MembershipFactory(organisation=org, role="coordinator").user
    client = ClientFactory(organisation=org)
    created = admin_api.post(
        "/api/v1/tasks",
        {"title": "Chase payment", "assignee": str(colleague.pk), **target(client)},
        format="json",
    )
    assert created.status_code == 201, created.json()
    task_id = created.json()["id"]
    done = admin_api.patch(f"/api/v1/tasks/{task_id}", {"status": "done"}, format="json")
    assert done.json()["completed_at"] is not None
    with tenant_context(org):
        types = set(OutboxEvent.objects.values_list("event_type", flat=True))
    assert {"task.created", "task.completed"} <= types


def test_tutor_sees_only_their_own_tasks(org):
    membership = MembershipFactory(organisation=org, role="tutor")
    own = TaskFactory(organisation=org, assignee=membership.user)
    TaskFactory(organisation=org)
    tutor = client_for(org, membership.user)
    assert result_ids(tutor.get("/api/v1/tasks")) == {str(own.pk)}


# --- documents (FR-05-9) --------------------------------------------------------------------------


def stored_file(org, **overrides):
    with tenant_context(org):
        return StoredFile.objects.create(
            filename="dbs.pdf",
            content_type="application/pdf",
            size_bytes=10,
            storage_key=f"org/{org.pk}/dbs-{now().timestamp()}.pdf",
            **{"status": StoredFile.Status.UPLOADED, **overrides},
        )


def test_attach_document_to_a_record(org, admin_api):
    profile = TutorProfileFactory(organisation=org)
    file = stored_file(org)
    response = admin_api.post(
        "/api/v1/documents",
        {**target(profile, "tutor"), "file": str(file.pk), "category": "id"},
        format="json",
    )
    assert response.status_code == 201, response.json()
    assert response.json()["title"] == "dbs.pdf"
    listed = admin_api.get("/api/v1/documents", target(profile, "tutor"))
    assert result_ids(listed) == {response.json()["id"]}


def test_unuploaded_file_cannot_be_attached(org, admin_api):
    client = ClientFactory(organisation=org)
    file = stored_file(org, status=StoredFile.Status.PENDING_UPLOAD)
    response = admin_api.post(
        "/api/v1/documents", {**target(client), "file": str(file.pk)}, format="json"
    )
    assert response.status_code == 422


# --- timeline and search (FR-05-10, global search) ----------------------------------------------


def test_timeline_merges_notes_tasks_and_changes(org, admin_api):
    created = admin_api.post(
        "/api/v1/clients", {"type": "household", "display_name": "The Okafors"}, format="json"
    )
    client_id = created.json()["id"]
    admin_api.patch(f"/api/v1/clients/{client_id}", {"po_number": "PO-1"}, format="json")
    ref = {"target_type": "people.client", "target_id": client_id}
    admin_api.post("/api/v1/notes", {**ref, "body": "<p>Hello</p>"}, format="json")
    admin_api.post("/api/v1/tasks", {**ref, "title": "Call back"}, format="json")
    response = admin_api.get("/api/v1/timeline", ref)
    assert response.status_code == 200, response.json()
    kinds = [i["kind"] for i in response.json()]
    assert {"note", "task", "change"} <= set(kinds)
    times = [i["at"] for i in response.json()]
    assert times == sorted(times, reverse=True)
    only_notes = admin_api.get("/api/v1/timeline", {**ref, "kinds": "note"})
    assert {i["kind"] for i in only_notes.json()} == {"note"}


def test_timeline_of_other_tenant_record_is_404(org, other_org, admin_api):
    theirs = ClientFactory(organisation=other_org)
    assert admin_api.get("/api/v1/timeline", target(theirs)).status_code == 404


def test_global_search_is_fuzzy_and_tenant_scoped(org, other_org, admin_api):
    mine = ClientFactory(organisation=org, display_name="The Fitzgerald Family")
    StudentFactory(organisation=org, client=mine, first_name="Aoife", last_name="Fitzgerald")
    ClientFactory(organisation=other_org, display_name="The Fitzgerald Family")
    response = admin_api.get("/api/v1/search", {"q": "fitzgerld"})
    assert response.status_code == 200
    hits = response.json()
    assert {h["type"] for h in hits} == {"client", "student"}
    assert str(mine.pk) in {h["id"] for h in hits}
    assert len([h for h in hits if h["type"] == "client"]) == 1


def test_search_respects_permissions(org):
    ClientFactory(organisation=org, display_name="The Nguyen Family")
    tutor = client_for(org, MembershipFactory(organisation=org, role="tutor").user)
    assert tutor.get("/api/v1/search", {"q": "Nguyen"}).json() == []


# --- saved views (FR-05-11) -----------------------------------------------------------------------


def test_saved_views_private_unless_shared(org, admin, admin_api):
    colleague = MembershipFactory(organisation=org, role="coordinator").user
    private = SavedViewFactory(organisation=org, owner=colleague)
    shared = SavedViewFactory(organisation=org, owner=colleague, shared=True)
    created = admin_api.post(
        "/api/v1/saved-views",
        {"entity_type": "people.client", "name": "Active VIPs", "filters": {"status": "active"}},
        format="json",
    )
    assert created.status_code == 201, created.json()
    ids = {v["id"] for v in admin_api.get("/api/v1/saved-views").json()}
    assert ids == {str(shared.pk), created.json()["id"]}
    assert str(private.pk) not in ids
    # Someone else's shared view can be used but not changed.
    response = admin_api.patch(f"/api/v1/saved-views/{shared.pk}", {"name": "x"}, format="json")
    assert response.status_code == 404


# --- bulk actions (FR-05-12) ----------------------------------------------------------------------


def test_bulk_archive_runs_in_background_with_report(
    org, admin_api, django_capture_on_commit_callbacks
):
    clients = [ClientFactory(organisation=org) for _ in range(3)]
    with django_capture_on_commit_callbacks(execute=True):
        response = admin_api.post(
            "/api/v1/bulk/client/archive",
            {"target_ids": [str(c.pk) for c in clients] + ["00000000-0000-0000-0000-000000000000"]},
            format="json",
        )
    assert response.status_code == 202, response.json()
    job = admin_api.get(f"/api/v1/bulk-jobs/{response.json()['id']}").json()
    assert (job["status"], job["total"], job["succeeded"]) == ("completed", 3, 3)
    with tenant_context(org):
        assert Client.objects.filter(status="archived").count() == 3


def test_bulk_tag_students(org, admin_api, django_capture_on_commit_callbacks):
    tag = TagFactory(organisation=org)
    students = [StudentFactory(organisation=org) for _ in range(2)]
    with django_capture_on_commit_callbacks(execute=True):
        response = admin_api.post(
            "/api/v1/bulk/student/tag",
            {"target_ids": [str(s.pk) for s in students], "params": {"tag": str(tag.pk)}},
            format="json",
        )
    assert response.status_code == 202
    with tenant_context(org):
        assert BulkJob.objects.get().succeeded == 2
        assert TaggedItem.objects.filter(target_type="people.student").count() == 2


def test_bulk_errors_reported_per_record(org, admin_api, django_capture_on_commit_callbacks):
    students = [StudentFactory(organisation=org) for _ in range(2)]
    with django_capture_on_commit_callbacks(execute=True):
        response = admin_api.post(
            "/api/v1/bulk/student/set_status",
            {"target_ids": [str(s.pk) for s in students], "params": {"status": "nonsense"}},
            format="json",
        )
    job = admin_api.get(f"/api/v1/bulk-jobs/{response.json()['id']}").json()
    assert job["succeeded"] == 0
    assert set(job["errors"]) == {str(s.pk) for s in students}
    with tenant_context(org):
        assert not Student.objects.filter(status="nonsense").exists()


def test_bulk_needs_permission(org):
    tutor = client_for(org, MembershipFactory(organisation=org, role="tutor").user)
    response = tutor.post(
        "/api/v1/bulk/client/archive",
        {"target_ids": [str(ClientFactory(organisation=org).pk)]},
        format="json",
    )
    assert response.status_code == 403


def test_unknown_bulk_action_rejected(org, admin_api):
    response = admin_api.post(
        "/api/v1/bulk/contact/archive",
        {"target_ids": [str(ClientFactory(organisation=org).pk)]},
        format="json",
    )
    assert response.status_code in {403, 422}


def test_crm_writes_are_audited(org, tenant):
    client = ClientFactory(organisation=org)
    services.create_note(**target(client), body="<p>x</p>")
    services.create_task(title="t")
    assert set(AuditEntry.objects.values_list("action", flat=True)) >= {"create"}
    assert AuditEntry.objects.filter(object_type__in=["crm.note", "crm.task"]).count() >= 2


# --- isolation ------------------------------------------------------------------------------------


class TestTagIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/tags"

    def make_object(self, organisation):
        return TagFactory(organisation=organisation)

    def test_list_only_returns_own_organisation(self, org, other_org):
        mine, theirs = TagFactory(organisation=org), TagFactory(organisation=other_org)
        body = client_for(org, self.acting_user(org)).get(self.list_url).json()
        ids = {t["id"] for t in body}
        assert str(mine.pk) in ids
        assert str(theirs.pk) not in ids


class TestTaskIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/tasks"

    def make_object(self, organisation):
        return TaskFactory(organisation=organisation)


class TestNoteIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/notes"

    def make_object(self, organisation):
        client = ClientFactory(organisation=organisation)
        return NoteFactory(organisation=organisation, **target(client))

    def test_list_only_returns_own_organisation(self, org, other_org):
        mine = self.make_object(org)
        api = client_for(org, self.acting_user(org))
        response = api.get(
            self.list_url, {"target_type": mine.target_type, "target_id": mine.target_id}
        )
        assert result_ids(response) == {str(mine.pk)}
        theirs = self.make_object(other_org)
        response = api.get(
            self.list_url, {"target_type": theirs.target_type, "target_id": theirs.target_id}
        )
        assert response.status_code == 404


class TestCustomFieldIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/custom-fields"

    def make_object(self, organisation):
        from tutortrack.crm.models import CustomFieldDefinition

        with tenant_context(organisation):
            return CustomFieldDefinition.objects.create(
                entity_type="people.client", key="k", label="K", type="text"
            )

    def test_list_only_returns_own_organisation(self, org, other_org):
        mine, theirs = self.make_object(org), self.make_object(other_org)
        ids = {f["id"] for f in client_for(org, self.acting_user(org)).get(self.list_url).json()}
        assert str(mine.pk) in ids
        assert str(theirs.pk) not in ids


def test_task_overdue_flag_false_when_done(org, tenant):
    task = TaskFactory(organisation=org, due_at=now() - timedelta(days=1), status=Task.Status.DONE)
    assert Note.Visibility.STAFF == "staff_only"
    from tutortrack.crm.api.views import TaskSerializer

    assert TaskSerializer(task).data["is_overdue"] is False
