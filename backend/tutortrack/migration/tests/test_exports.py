"""E28-T10: the full tenant export (FR-28-7)."""

from __future__ import annotations

import csv
import io
import json
import zipfile

import pytest
from django.db import transaction

from tutortrack.comms.models import Message
from tutortrack.core.models import OutboxEvent, StoredFile
from tutortrack.identity.models import Membership
from tutortrack.identity.tests.factories import MembershipFactory, UserFactory
from tutortrack.migration import exporter, files, services
from tutortrack.migration.models import ExportJob
from tutortrack.people.tests.factories import ClientFactory, ContactFactory, StudentFactory

pytestmark = pytest.mark.django_db


def build(job: ExportJob) -> zipfile.ZipFile:
    for name in services.export_plan(job.pk):
        services.export_entity(job.pk, name)
    services.export_archive(job.pk)
    job.refresh_from_db()
    return zipfile.ZipFile(io.BytesIO(files.read(job.file, limit=10**9)))


def test_full_export_has_csv_json_relationships_and_files(tenant, s3):
    owner = UserFactory(email="owner@example.com")
    MembershipFactory(organisation=tenant, user=owner, role=Membership.Role.OWNER)
    client = ClientFactory(organisation=tenant, display_name="=cmd|' /C calc'!A0")
    ContactFactory(organisation=tenant, client=client, first_name="Jane")
    StudentFactory(organisation=tenant, client=client, first_name="Tom", learning_needs="Dyslexia")
    files.save(client, "notes.txt", "text/plain", b"hello", kind="docs")
    with transaction.atomic():
        job = services.request_export(user=owner, reason="backup")
    assert services.request_export(user=owner) == job  # one export at a time
    assert OutboxEvent.objects.filter(event_type="export.requested").count() == 1
    archive = build(job)
    names = set(archive.namelist())
    assert {
        "csv/clients.csv",
        "json/clients.json",
        "csv/students.csv",
        "relationships.json",
        "README.txt",
    } <= names
    rows = list(csv.DictReader(io.StringIO(archive.read("csv/clients.csv").decode("utf-8-sig"))))
    assert rows[0]["display_name"].startswith("'=")  # formulas neutralised
    students = json.loads(archive.read("json/students.json"))
    assert students[0]["client_id"] == str(client.pk)
    assert students[0]["learning_needs"] == "Dyslexia"  # their own data, decrypted
    relations = json.loads(archive.read("relationships.json"))
    assert relations["students"]["references"]["client_id"] == "clients"
    assert any(n.startswith("files/") and n.endswith("notes.txt") for n in names)
    assert all(
        "token" not in c and "secret" not in c for e in relations.values() for c in e["columns"]
    )
    job.refresh_from_db()
    assert job.status == "ready"
    assert job.expires_at is not None
    assert job.parts == []
    assert job.progress["clients"] == 1
    assert OutboxEvent.objects.filter(event_type="export.ready").exists()
    assert Message.objects.filter(to="owner@example.com", type_key="data_export_ready").exists()


def test_closure_requests_an_export_for_the_owners(tenant, s3):
    from tutortrack.migration.handlers import export_for_organisation

    event = type("E", (), {"data": {"reason": "closure"}})()
    export_for_organisation(event)  # type: ignore[arg-type]
    job = ExportJob.objects.get()
    assert job.requested_by is None
    assert job.reason == "closure"


def test_expiry_deletes_the_archive(tenant, s3):
    with transaction.atomic():
        job = services.request_export(reason="test")
    build(job)
    job.refresh_from_db()
    key = job.file.storage_key
    services.expire_export(job.pk)
    job.refresh_from_db()
    assert job.status == "expired"
    assert StoredFile.objects.get(pk=job.file_id).status == "rejected"
    with pytest.raises(Exception):  # noqa: B017, PT011 - the object is gone from storage
        files.read_key(key)
    assert OutboxEvent.objects.filter(event_type="export.expired").exists()


def test_every_listed_entity_resolves():
    assert set(exporter.entities()) == {name for name, _label in exporter.ENTITIES}
