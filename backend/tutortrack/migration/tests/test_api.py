"""E28 API: upload → mapping → submit, templates, permissions, exports and tenant isolation."""

from __future__ import annotations

from typing import Any

import pytest
from django.conf import settings

from tutortrack.core.context import tenant_context
from tutortrack.core.models import StoredFile
from tutortrack.core.testing import TenantIsolationTestMixin, client_for
from tutortrack.identity.models import Membership
from tutortrack.identity.tests.factories import MembershipFactory, UserFactory
from tutortrack.migration.models import ExportJob
from tutortrack.migration.tests.factories import (
    ExportJobFactory,
    ImportBatchFactory,
    MigrationProjectFactory,
)

pytestmark = pytest.mark.django_db
CSV = b"First name,Last name,Parent email\nAva,Brown,kate@example.com\nNoah,,bad-email\n"


def upload(api: Any, s3: Any, org: Any, data: bytes = CSV, *, scanned: bool = True) -> str:
    created = api.post(
        "/api/v1/files/uploads",
        {"filename": "students.csv", "content_type": "text/csv", "size_bytes": len(data)},
        format="json",
    )
    assert created.status_code == 201, created.content
    file_id = created.json()["file"]["id"]
    with tenant_context(org):
        stored = StoredFile.objects.get(pk=file_id)
        s3.put_object(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME,
            Key=stored.storage_key,
            Body=data,
            ContentType="text/csv",
        )
        stored.status = StoredFile.Status.UPLOADED
        stored.scan_status = "skipped" if scanned else "pending"
        stored.save()
    return str(file_id)


def test_upload_map_and_submit(api, s3, org):
    file_id = upload(api, s3, org)
    response = api.post("/api/v1/imports", {"file": file_id, "entity": "students"}, format="json")
    assert response.status_code == 201, response.content
    batch = response.json()
    assert batch["status"] == "mapping"
    assert batch["stats"] == {"rows": 2}
    preview = api.get(f"/api/v1/imports/{batch['id']}/preview").json()
    assert preview["column_map"] == {
        "First name": "first_name",
        "Last name": "last_name",
        "Parent email": "parent_email",
    }
    assert preview["sample"][0]["First name"] == "Ava"
    assert any(f["key"] == "first_name" and f["required"] for f in preview["field_specs"])
    changed = api.put(
        f"/api/v1/imports/{batch['id']}/mapping",
        {
            "column_map": {**preview["column_map"], "Last name": ""},
            "options": {"date_format": "MDY"},
        },
        format="json",
    )
    assert changed.status_code == 200, changed.content
    assert changed.json()["column_map"]["Last name"] == ""
    submitted = api.post(f"/api/v1/imports/{batch['id']}/submit")
    assert submitted.status_code == 200, submitted.content
    assert submitted.json()["status"] == "validating"
    assert api.get(f"/api/v1/imports/{batch['id']}/rows").json()["results"][0]["row_number"] == 1
    saved = api.post(f"/api/v1/imports/{batch['id']}/save-mapping", {"name": "Ours"}, format="json")
    assert saved.status_code == 201
    assert api.get("/api/v1/import-mappings?entity=students").json()["results"][0]["name"] == "Ours"


def test_unscanned_files_and_unknown_fields_are_refused(api, s3, org):
    file_id = upload(api, s3, org, scanned=False)
    response = api.post("/api/v1/imports", {"file": file_id, "entity": "students"}, format="json")
    assert response.status_code == 409
    assert "virus" in response.json()["detail"]
    with tenant_context(org):
        StoredFile.objects.filter(pk=file_id).update(scan_status="clean")
    batch = api.post("/api/v1/imports", {"file": file_id, "entity": "students"}, format="json")
    bad = api.put(
        f"/api/v1/imports/{batch.json()['id']}/mapping",
        {"column_map": {"First name": "password"}},
        format="json",
    )
    assert bad.status_code == 422


def test_submit_needs_the_required_columns(api, s3, org):
    file_id = upload(api, s3, org, b"Surname\nBrown\n")
    batch = api.post("/api/v1/imports", {"file": file_id, "entity": "students"}, format="json")
    response = api.post(f"/api/v1/imports/{batch.json()['id']}/submit")
    assert response.status_code == 422
    assert "First name" in response.json()["detail"]


def test_catalogue_and_templates(api):
    catalogue = api.get("/api/v1/import-catalogue").json()
    students = next(e for e in catalogue["entities"] if e["key"] == "students")
    assert students["allowed"]
    assert "tutorbird" in catalogue["presets"]
    template = api.get("/api/v1/import-templates/students")
    assert template.status_code == 200
    assert template["Content-Type"] == "text/csv"
    assert b"First name" in template.content
    assert api.get("/api/v1/import-templates/nope").status_code == 404


def test_tutors_cannot_import_and_admins_cannot_export(org):
    tutor = UserFactory()
    MembershipFactory(organisation=org, user=tutor, role=Membership.Role.TUTOR)
    assert client_for(org, tutor).get("/api/v1/imports").status_code == 403
    admin = UserFactory()
    MembershipFactory(organisation=org, user=admin, role=Membership.Role.ADMIN)
    as_admin = client_for(org, admin)
    assert as_admin.get("/api/v1/imports").status_code == 200
    assert as_admin.post("/api/v1/data-exports", {}, format="json").status_code == 403
    manager = UserFactory()
    MembershipFactory(organisation=org, user=manager, role=Membership.Role.BRANCH_MANAGER)
    assert client_for(org, manager).get("/api/v1/imports").status_code == 403


def test_owner_exports_and_downloads_with_password(org, s3):
    owner = UserFactory(password="correct horse 1")
    MembershipFactory(organisation=org, user=owner, role=Membership.Role.OWNER)
    api = client_for(org, owner)
    created = api.post("/api/v1/data-exports", {"reason": "backup"}, format="json")
    assert created.status_code == 201, created.content
    export_id = created.json()["id"]
    from tutortrack.migration import files

    with tenant_context(org):
        job = ExportJob.objects.get(pk=export_id)
        stored = files.save(job, "export.zip", "application/zip", b"PK..", kind="exports")
        ExportJob.objects.filter(pk=export_id).update(
            status="ready", file=stored, expires_at=job.created_at.replace(year=2100)
        )
    wrong = api.post(
        f"/api/v1/data-exports/{export_id}/download", {"password": "nope"}, format="json"
    )
    assert wrong.status_code == 403
    assert wrong.json()["type"].endswith("reauthentication-failed")
    ok = api.post(
        f"/api/v1/data-exports/{export_id}/download", {"password": "correct horse 1"}, format="json"
    )
    assert ok.status_code == 200, ok.content
    assert stored.storage_key.split("/")[-1] in ok.json()["url"]
    # The generic file download never hands out export archives.
    assert api.get(f"/api/v1/files/{stored.pk}/download").status_code in (403, 404)
    with tenant_context(org):
        assert ExportJob.objects.get(pk=export_id).download_count == 1


class TestImportIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/imports"

    def make_object(self, organisation):
        return ImportBatchFactory(organisation=organisation)


class TestProjectIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/migration-projects"

    def make_object(self, organisation):
        return MigrationProjectFactory(organisation=organisation)


class TestExportIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/data-exports"

    def make_object(self, organisation):
        return ExportJobFactory(organisation=organisation)


class TestSavedMappingIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/import-mappings"

    def make_object(self, organisation):
        from tutortrack.core.tests.factories import TenantFactory
        from tutortrack.migration.models import SavedImportMapping

        class Factory(TenantFactory):
            class Meta:
                model = SavedImportMapping

            name = "Mine"
            entity = "students"

        return Factory(organisation=organisation)


def test_rows_of_another_organisations_batch_are_404(org, other_org, api):
    theirs = ImportBatchFactory(organisation=other_org)
    assert api.get(f"/api/v1/imports/{theirs.pk}/rows").status_code == 404
    assert api.post(f"/api/v1/imports/{theirs.pk}/confirm").status_code == 404
