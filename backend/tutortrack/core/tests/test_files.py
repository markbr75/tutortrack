from unittest import mock
from urllib.parse import unquote

import pytest

from tutortrack.core.context import tenant_context
from tutortrack.core.exceptions import BusinessRuleViolation, Conflict, PermissionDenied
from tutortrack.core.models import AuditEntry, StoredFile
from tutortrack.core.storage import services
from tutortrack.core.storage.clamav import ScanError, parse_response
from tutortrack.core.storage.tasks import scan_file
from tutortrack.core.testing import TenantIsolationTestMixin, client_for
from tutortrack.identity.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

PDF = b"%PDF-1.4 tutor agreement"


def _upload_bytes(s3, stored, data=PDF, content_type="application/pdf"):
    s3.put_object(
        Bucket="tutortrack-test", Key=stored.storage_key, Body=data, ContentType=content_type
    )


def _create(**overrides):
    params = {
        "filename": "Tutor Agreement (signed).pdf",
        "content_type": "application/pdf",
        "size_bytes": len(PDF),
        **overrides,
    }
    return services.create_upload(**params)


def test_create_upload_returns_presigned_put(tenant, s3):
    stored, upload = _create()
    assert stored.status == StoredFile.Status.PENDING_UPLOAD
    assert stored.storage_key.startswith(f"org/{tenant.pk}/")
    assert stored.storage_key.endswith("/Tutor-Agreement-signed-.pdf")
    assert upload.method == "PUT"
    assert "X-Amz-Signature" in upload.url
    assert upload.headers == {"Content-Type": "application/pdf"}


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"content_type": "application/x-msdownload"}, "file_type_not_allowed"),
        ({"size_bytes": 0}, "file_too_large"),
        ({"size_bytes": 10**10}, "file_too_large"),
    ],
)
def test_create_upload_validates_type_and_size(tenant, s3, overrides, code):
    with pytest.raises(BusinessRuleViolation) as exc:
        _create(**overrides)
    assert exc.value.extra["code"] == code


def test_safe_filename_strips_paths_and_odd_characters():
    assert services.safe_filename("../../etc/passwd") == "passwd"
    assert services.safe_filename("C:\\Users\\me\\Report 1.pdf") == "Report-1.pdf"
    assert services.safe_filename("") == "file"


def test_complete_upload_verifies_object_and_scans(tenant, s3, django_capture_on_commit_callbacks):
    stored, _ = _create()
    _upload_bytes(s3, stored)
    with django_capture_on_commit_callbacks(execute=True):
        services.complete_upload(stored)
    stored.refresh_from_db()
    assert stored.status == StoredFile.Status.UPLOADED
    assert stored.scan_status == StoredFile.ScanStatus.SKIPPED  # scanning disabled in tests
    assert stored.is_downloadable
    assert AuditEntry.objects.filter(object_id=str(stored.pk), action="upload").exists()


def test_complete_upload_rejects_missing_or_mismatched_objects(tenant, s3):
    stored, _ = _create()
    with pytest.raises(BusinessRuleViolation, match="not been uploaded"):
        services.complete_upload(stored)

    _upload_bytes(s3, stored, data=PDF + b"extra bytes")
    with pytest.raises(BusinessRuleViolation, match="does not match"):
        services.complete_upload(stored)
    stored.refresh_from_db()
    assert stored.status == StoredFile.Status.REJECTED

    with pytest.raises(Conflict):
        services.complete_upload(stored)


def test_infected_files_are_quarantined(tenant, s3, settings):
    settings.CLAMAV = {**settings.CLAMAV, "ENABLED": True}
    stored, _ = _create()
    _upload_bytes(s3, stored)
    stored.status = StoredFile.Status.UPLOADED
    stored.save()

    infected = mock.Mock(clean=False, signature="Eicar-Test-Signature")
    with mock.patch("tutortrack.core.storage.tasks.scan_stream", return_value=infected):
        scan_file.delay(file_id=str(stored.pk), organisation_id=str(tenant.pk))

    stored.refresh_from_db()
    assert stored.scan_status == StoredFile.ScanStatus.INFECTED
    assert stored.status == StoredFile.Status.REJECTED
    assert not stored.is_downloadable
    assert s3.list_objects_v2(Bucket="tutortrack-test").get("KeyCount") == 0


def test_clamav_response_parsing():
    assert parse_response("stream: OK").clean
    result = parse_response("stream: Eicar-Test-Signature FOUND")
    assert not result.clean
    assert result.signature == "Eicar-Test-Signature"
    with pytest.raises(ScanError):
        parse_response("INSTREAM size limit exceeded. ERROR")


def test_download_requires_clean_file_and_access(tenant, s3, user):
    owner, stranger = user, UserFactory()
    with mock.patch("tutortrack.core.storage.services.get_request_context") as ctx:
        ctx.return_value.user_id = owner.pk
        stored, _ = _create()

    with pytest.raises(Conflict):
        services.download_url(owner, stored)  # not uploaded yet

    stored.status = StoredFile.Status.UPLOADED
    stored.scan_status = StoredFile.ScanStatus.CLEAN
    stored.save()

    url, expires = services.download_url(owner, stored)
    assert "X-Amz-Signature" in url
    assert "attachment" in unquote(url)
    assert expires == 900

    with pytest.raises(PermissionDenied):
        services.download_url(stranger, stored)  # private file

    stored.visibility = StoredFile.Visibility.INTERNAL
    stored.save()
    assert services.download_url(stranger, stored)


def test_full_upload_flow_via_api(org, user, s3, django_capture_on_commit_callbacks):
    api = client_for(org, user)
    created = api.post(
        "/api/v1/files/uploads",
        {"filename": "notes.pdf", "content_type": "application/pdf", "size_bytes": len(PDF)},
        format="json",
    )
    assert created.status_code == 201, created.json()
    file_id = created.json()["file"]["id"]
    assert created.json()["upload"]["method"] == "PUT"

    with tenant_context(org):
        _upload_bytes(s3, StoredFile.objects.get(pk=file_id))

    with django_capture_on_commit_callbacks(execute=False):
        completed = api.post(f"/api/v1/files/{file_id}/complete")
    assert completed.status_code == 200
    assert completed.json()["status"] == "uploaded"

    pending = api.get(f"/api/v1/files/{file_id}/download")
    assert pending.status_code == 409  # stays pending until the scan task has run
    assert pending.json()["scan_status"] == "pending"
    assert pending.json()["status"] == 409

    with tenant_context(org):
        scan_file.delay(file_id=file_id, organisation_id=str(org.pk))
    download = api.get(f"/api/v1/files/{file_id}/download")
    assert download.status_code == 200
    assert "X-Amz-Signature" in download.json()["url"]


def test_private_files_of_other_users_are_hidden(org, user, s3):
    with (
        tenant_context(org),
        mock.patch("tutortrack.core.storage.services.get_request_context") as ctx,
    ):
        ctx.return_value.user_id = user.pk
        stored, _ = _create()
    response = client_for(org, UserFactory()).get(f"/api/v1/files/{stored.pk}")
    assert response.status_code == 404


class TestFileIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/files"

    def make_object(self, organisation):
        return StoredFile.all_tenants.create(
            organisation=organisation,
            filename="a.pdf",
            content_type="application/pdf",
            size_bytes=1,
            storage_key=f"org/{organisation.pk}/a.pdf",
            visibility=StoredFile.Visibility.INTERNAL,
        )

    def test_list_only_returns_own_organisation(self, org, other_org):
        pytest.skip("files have no list endpoint; detail isolation is still enforced")
