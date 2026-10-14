"""E26-T09 (Enterprise): data warehouse export: destinations, incremental exports with
documented schemas, platform storage downloads, entitlement gating, schedules and the
real destinations' request shapes."""

from __future__ import annotations

import gzip
import json
from typing import Any

import pytest

from tutortrack.core import entitlements
from tutortrack.core.context import tenant_context
from tutortrack.core.models import AuditEntry
from tutortrack.core.testing import TenantIsolationTestMixin, client_for
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.people.tests.factories import ClientFactory, TutorProfileFactory
from tutortrack.reporting.warehouse import destinations, services
from tutortrack.reporting.warehouse.datasets import DATASETS, schema
from tutortrack.reporting.warehouse.destinations import FakeDestination
from tutortrack.reporting.warehouse.models import WarehouseDestination, WarehouseExport

pytestmark = pytest.mark.django_db


class Entitlements:
    def __init__(self, *denied: str):
        self.denied = set(denied)

    def has(self, key: str, organisation_id: Any) -> bool:
        return key not in self.denied

    def limit(self, key: str, organisation_id: Any) -> int | None:
        return None

    def required_plan(self, key: str, needed: int | None = None) -> str | None:
        return "enterprise"


@pytest.fixture(autouse=True)
def enterprise(monkeypatch):
    monkeypatch.setattr(entitlements, "_resolver", Entitlements())
    FakeDestination.reset()
    yield
    FakeDestination.reset()


@pytest.fixture
def finance(org) -> Any:
    with tenant_context(org):
        return MembershipFactory(organisation=org, role="finance").user


def make_destination(org, kind: str = "bigquery", **kwargs: Any) -> WarehouseDestination:
    config = {
        "bigquery": {"project": "bright-minds-1", "dataset": "tutortrack"},
        "s3": {"bucket": "bm-lake", "region": "eu-west-2"},
        "snowflake": {
            "account": "xy12345.eu-west-2",
            "user": "LOADER",
            "database": "TT",
            "warehouse": "LOAD_WH",
        },
        "platform": {},
    }[kind]
    credentials = {
        "bigquery": {"client_email": "x@y.iam.gserviceaccount.com", "private_key": "k"},
        "s3": {"access_key_id": "AK", "secret_access_key": "SK"},
        "snowflake": {"private_key": "k"},
        "platform": None,
    }[kind]
    with tenant_context(org):
        return services.save_destination(
            None, name=f"{kind} lake", kind=kind, config=config, credentials=credentials, **kwargs
        )


def run_export(org, destination, *, key: str, full: bool = False) -> WarehouseExport:
    with tenant_context(org):
        opened = services.begin(destination.pk, key, full=full, scheduled=False)
        for dataset in opened["datasets"]:
            services.export_dataset(opened["export"], dataset)
        services.finish(opened["export"])
        return WarehouseExport.objects.get(pk=opened["export"])


def test_documented_schemas_cover_facts_and_dimensions_without_sensitive_fields():
    keys = set(DATASETS)
    assert {"fact_lesson", "fact_charge", "fact_payment", "fact_pay_item", "dim_student"} <= keys
    columns = {c["name"] for d in schema() for c in d["columns"]}
    assert not columns & {"date_of_birth", "tax_reference", "bank_details", "email", "notes"}
    assert all(d["columns"][0]["name"] == "id" for d in schema())


def test_incremental_exports_send_only_what_changed(org):
    with tenant_context(org):
        tutor = TutorProfileFactory(organisation=org, status="active", first_name="Nia")
        ClientFactory(organisation=org)
    destination = make_destination(org, datasets=["dim_tutor", "dim_client"])
    first = run_export(org, destination, key="run-1")
    assert (first.status, first.full) == ("succeeded", True)
    written = FakeDestination.written[str(destination.pk)]
    assert [r["first_name"] for r in written["dim_tutor"]] == ["Nia"]
    assert len(written["dim_client"]) == 1
    with tenant_context(org):
        tutor.first_name = "Nia-Grace"
        tutor.save()
    second = run_export(org, destination, key="run-2")
    assert second.full is False
    assert [m["rows"] for m in second.manifest] == [1, 0]  # only the changed tutor
    assert written["dim_tutor"][-1]["first_name"] == "Nia-Grace"
    with tenant_context(org):
        again = services.begin(destination.pk, "run-2", full=False, scheduled=False)
    assert again["export"] == str(second.pk)  # a retried run reuses its record
    with tenant_context(org):
        destination.refresh_from_db()
        assert (destination.last_status, destination.last_export_at) == (
            "succeeded",
            second.finished_at,
        )
        assert AuditEntry.objects.filter(action="export", object_id=str(second.pk)).exists()


def test_platform_storage_export_writes_gzipped_csv_and_a_manifest(org, finance, s3):
    with tenant_context(org):
        TutorProfileFactory(organisation=org, status="active", first_name="Ada")
    destination = make_destination(org, "platform", datasets=["dim_tutor"])
    export = run_export(org, destination, key="run-p")
    [entry] = export.manifest
    bucket, key = entry["location"].removeprefix("s3://").split("/", 1)
    body = gzip.decompress(s3.get_object(Bucket=bucket, Key=key)["Body"].read())
    assert body.decode().splitlines()[0].startswith("id,updated_at,first_name")
    listed = s3.list_objects_v2(
        Bucket=bucket, Prefix=f"warehouse/{org.pk}/{destination.pk}/manifests/"
    )
    manifest_key = listed["Contents"][0]["Key"]
    manifest = json.loads(s3.get_object(Bucket=bucket, Key=manifest_key)["Body"].read())
    assert manifest["schemas"][0]["dataset"] == "dim_tutor"
    api = client_for(org, finance)
    link = api.get(f"/api/v1/reporting/warehouse/exports/{export.pk}/download?dataset=dim_tutor")
    assert link.status_code == 200
    assert "X-Amz-Signature" in link.json()["url"]


def test_destinations_api_hides_credentials_and_needs_enterprise(org, finance, monkeypatch):
    api = client_for(org, finance)
    created = api.post(
        "/api/v1/reporting/warehouse/destinations",
        {
            "name": "Lake",
            "kind": "s3",
            "config": {"bucket": "bm-lake", "region": "eu-west-2"},
            "credentials": {"access_key_id": "AKIA", "secret_access_key": "secret"},
        },
        format="json",
    )
    assert created.status_code == 201, created.json()
    body = created.json()
    assert body["has_credentials"] is True
    assert "credentials" not in body
    with tenant_context(org):
        stored = WarehouseDestination.objects.get(pk=body["id"])
        assert json.loads(stored.credentials)["secret_access_key"] == "secret"
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT credentials FROM reporting_warehousedestination WHERE id=%s", [stored.pk]
            )
            assert "secret" not in cursor.fetchone()[0]
    bad = api.post(
        "/api/v1/reporting/warehouse/destinations",
        {
            "kind": "s3",
            "config": {"bucket": "x", "region": "nowhere"},
            "credentials": {"access_key_id": "a", "secret_access_key": "b"},
        },
        format="json",
    )
    assert bad.status_code == 422
    assert api.get("/api/v1/reporting/warehouse/schema").status_code == 200
    tutor = client_for(org, MembershipFactory(organisation=org, role="tutor").user)
    assert tutor.get("/api/v1/reporting/warehouse/destinations").status_code == 403
    monkeypatch.setattr(entitlements, "_resolver", Entitlements("warehouse_export"))
    refused = api.post(
        "/api/v1/reporting/warehouse/destinations",
        {"kind": "platform", "config": {}},
        format="json",
    )
    assert refused.status_code == 403
    assert refused.json()["type"].endswith("upgrade-required")
    with tenant_context(org):
        skipped = services.begin(body["id"], "run-x", full=False, scheduled=True)
    assert skipped == {"skipped": "not_entitled"}


def test_saving_syncs_the_nightly_schedule(org, monkeypatch):
    calls: list[dict[str, Any]] = []
    deleted: list[str] = []
    from tutortrack.core.workflows import schedules

    monkeypatch.setattr(schedules, "ensure_schedule", lambda **kw: calls.append(kw) or "sid-1")
    monkeypatch.setattr(schedules, "delete_schedule", lambda org_id, sid: deleted.append(sid))
    destination = make_destination(org, hour=3)
    with tenant_context(org):
        assert services.sync_schedule(destination.pk) == "sid-1"
        assert calls[0]["cron"] == ["0 3 * * *"]
        destination.enabled = False
        destination.save()
        assert services.sync_schedule(destination.pk) is None
    assert deleted


def test_destination_validation_and_real_request_shapes(monkeypatch):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    from tutortrack.integrations.providers import http

    with pytest.raises(destinations.DestinationError):
        destinations.S3Destination({"bucket": "b", "region": "http://169.254.169.254"}, {})
    with pytest.raises(destinations.DestinationError):
        destinations.BigQueryDestination({"project": "x", "dataset": "a b"}, {})
    with pytest.raises(destinations.DestinationError):
        destinations.SnowflakeDestination(
            {"account": "evil/../", "user": "u", "database": "d", "warehouse": "w"}, {}
        )
    pem = (
        rsa.generate_private_key(public_exponent=65537, key_size=2048)
        .private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        .decode()
    )
    calls: list[dict[str, Any]] = []

    def fake(method: str, url: str, **kwargs: Any) -> http.Response:
        calls.append({"method": method, "url": url, **kwargs})
        body = {"access_token": "tok"} if "oauth2" in url else {}
        return http.Response(200, None, json.dumps(body).encode())  # type: ignore[arg-type]

    monkeypatch.setattr(http, "request", fake)
    dataset = DATASETS["dim_service"]
    rows = [
        {
            "id": "1",
            "updated_at": "2026-10-14T00:00:00+00:00",
            "name": "Maths",
            "created_at": "2026-10-01T00:00:00+00:00",
        }
    ]
    batch = destinations.Batch(dataset, "f.csv.gz", b"", rows)
    bq = destinations.BigQueryDestination(
        {"project": "bright-minds-1", "dataset": "tutortrack"},
        {"client_email": "x@y.iam.gserviceaccount.com", "private_key": pem},
    )
    assert bq.write(batch) == "bigquery://bright-minds-1.tutortrack.dim_service"
    insert = calls[-1]
    assert insert["url"].endswith("/tables/dim_service/insertAll")
    assert insert["json_body"]["rows"][0]["json"]["name"] == "Maths"
    assert all(c["user_url"] for c in calls)
    calls.clear()
    sf = destinations.SnowflakeDestination(
        {"account": "xy12345.eu-west-2", "user": "LOADER", "database": "TT", "warehouse": "WH"},
        {"private_key": pem},
    )
    sf.write(batch)
    assert calls[0]["json_body"]["statement"].startswith("CREATE TABLE IF NOT EXISTS DIM_SERVICE")
    assert calls[1]["json_body"]["bindings"]["3"]["value"] == ["Maths"]
    assert calls[0]["headers"]["X-Snowflake-Authorization-Token-Type"] == "KEYPAIR_JWT"


class TestWarehouseDestinationIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/reporting/warehouse/destinations"

    def make_object(self, organisation: Any) -> WarehouseDestination:
        with tenant_context(organisation):
            return WarehouseDestination.objects.create(name="Lake", kind="platform")
