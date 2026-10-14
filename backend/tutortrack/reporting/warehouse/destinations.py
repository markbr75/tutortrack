"""Warehouse destinations (E26-T09).

Each destination takes one dataset batch at a time: the gzipped CSV, its rows as dicts and
the dataset's schema, and returns where it went.

* ``platform``: TutorTrack's own object storage (the existing ``AWS_*`` storage settings),
  under ``warehouse/<org>/<destination>/<dataset>/``; staff download from there.
* ``s3``: the organisation's AWS bucket with their access key. Only AWS regional
  endpoints are used (no custom endpoint), so no user-controlled host is ever called.
* ``bigquery``: streaming inserts (``tabledata.insertAll``) with a service account (an
  RS256 JWT exchanged for a token); tables are created from the schema if missing.
* ``snowflake``: the SQL API v2 with key-pair JWT authentication; ``CREATE TABLE IF NOT
  EXISTS`` then batched ``INSERT`` with bindings.

HTTP calls go through ``core.net.safe_urlopen`` (``user_url=True``). Without live
warehouse credentials (``WAREHOUSE_EXPORT["LIVE"]`` false: development and tests) the
customer-hosted kinds use ``FakeDestination``; the platform kind always uses storage.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import time
from dataclasses import dataclass
from typing import Any, ClassVar, Protocol

from django.conf import settings

from tutortrack.integrations.providers import ProviderError, http

from .datasets import Dataset

REGION = re.compile(r"^[a-z]{2}(-gov)?-[a-z]+-\d$")
IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]{0,254}$")
SNOWFLAKE_ACCOUNT = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
BQ_TYPES = {
    "STRING": "STRING",
    "INTEGER": "INT64",
    "NUMERIC": "NUMERIC",
    "BOOLEAN": "BOOL",
    "DATE": "DATE",
    "TIMESTAMP": "TIMESTAMP",
}
SF_TYPES = {
    "STRING": "VARCHAR",
    "INTEGER": "NUMBER(18,0)",
    "NUMERIC": "NUMBER(18,4)",
    "BOOLEAN": "BOOLEAN",
    "DATE": "DATE",
    "TIMESTAMP": "TIMESTAMP_TZ",
}


class DestinationError(Exception):
    """The destination refused or is misconfigured (message is safe to show staff)."""


@dataclass(frozen=True)
class Batch:
    dataset: Dataset
    filename: str
    content: bytes  # gzipped CSV
    rows: list[dict[str, Any]]


class Destination(Protocol):
    def check(self) -> None: ...

    def write(self, batch: Batch) -> str: ...


def _base64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def rs256_jwt(
    claims: dict[str, Any], private_key_pem: str, headers: dict[str, Any] | None = None
) -> str:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa

    key = serialization.load_pem_private_key(private_key_pem.encode(), password=None)
    if not isinstance(key, rsa.RSAPrivateKey):
        raise DestinationError("The private key must be an RSA key.")
    header = {"alg": "RS256", "typ": "JWT", **(headers or {})}
    signing = f"{_base64url(json.dumps(header).encode())}.{_base64url(json.dumps(claims).encode())}"
    signature = key.sign(signing.encode(), padding.PKCS1v15(), hashes.SHA256())
    return f"{signing}.{_base64url(signature)}"


# --- platform storage ----------------------------------------------------------------------------


class PlatformDestination:
    def __init__(self, organisation_id: str, destination_id: str, prefix: str = "") -> None:
        self.prefix = f"warehouse/{organisation_id}/{destination_id}"

    def check(self) -> None:
        return None

    def write(self, batch: Batch) -> str:
        from tutortrack.core.storage.client import bucket, s3_client

        key = f"{self.prefix}/{batch.dataset.key}/{batch.filename}"
        s3_client().put_object(
            Bucket=bucket(),
            Key=key,
            Body=batch.content,
            ContentType="application/gzip",
            ServerSideEncryption="AES256",
        )
        return f"s3://{bucket()}/{key}"


# --- the organisation's S3 bucket ---------------------------------------------------------------


class S3Destination:
    def __init__(self, config: dict[str, Any], credentials: dict[str, Any]) -> None:
        self.bucket = str(config.get("bucket", ""))
        self.prefix = str(config.get("prefix", "")).strip("/")
        self.region = str(config.get("region", "eu-west-2"))
        if not self.bucket or not REGION.match(self.region):
            raise DestinationError("Enter the bucket name and an AWS region.")
        self.credentials = credentials

    def _client(self) -> Any:
        import boto3

        return boto3.client(
            "s3",
            region_name=self.region,
            aws_access_key_id=self.credentials.get("access_key_id"),
            aws_secret_access_key=self.credentials.get("secret_access_key"),
        )

    def check(self) -> None:
        try:
            self._client().head_bucket(Bucket=self.bucket)
        except Exception as exc:  # botocore raises many types; the message is shown
            raise DestinationError(f"Couldn't reach the bucket: {exc}") from exc

    def write(self, batch: Batch) -> str:
        key = "/".join(p for p in (self.prefix, batch.dataset.key, batch.filename) if p)
        try:
            self._client().put_object(
                Bucket=self.bucket, Key=key, Body=batch.content, ContentType="application/gzip"
            )
        except Exception as exc:
            raise DestinationError(f"S3 refused the file: {exc}") from exc
        return f"s3://{self.bucket}/{key}"


# --- BigQuery -----------------------------------------------------------------------------------


class BigQueryDestination:
    TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 - a URL
    API = "https://bigquery.googleapis.com/bigquery/v2"

    def __init__(self, config: dict[str, Any], credentials: dict[str, Any]) -> None:
        self.project = str(config.get("project", ""))
        self.dataset = str(config.get("dataset", ""))
        self.account = credentials
        if not IDENT.match(self.dataset) or not re.match(r"^[a-z][a-z0-9-]{4,62}$", self.project):
            raise DestinationError("Enter the Google Cloud project and BigQuery dataset.")
        self._token = ""

    def _access_token(self) -> str:
        if self._token:
            return self._token
        now = int(time.time())
        assertion = rs256_jwt(
            {
                "iss": self.account.get("client_email"),
                "aud": self.TOKEN_URL,
                "scope": "https://www.googleapis.com/auth/bigquery",
                "iat": now,
                "exp": now + 3600,
            },
            str(self.account.get("private_key", "")),
        )
        body = http.request(
            "POST",
            self.TOKEN_URL,
            user_url=True,
            provider="bigquery",
            form={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": assertion,
            },
        ).json()
        self._token = str(body.get("access_token", ""))
        return self._token

    def _call(self, method: str, path: str, body: Any = None) -> Any:
        try:
            return http.request(
                method,
                f"{self.API}/projects/{self.project}{path}",
                json_body=body,
                token=self._access_token(),
                user_url=True,
                provider="bigquery",
            ).json()
        except ProviderError as exc:
            raise DestinationError(str(exc)) from exc

    def check(self) -> None:
        self._call("GET", f"/datasets/{self.dataset}")

    def _ensure_table(self, dataset: Dataset) -> None:
        from tutortrack.integrations.providers import NotFound

        try:
            http.request(
                "GET",
                f"{self.API}/projects/{self.project}/datasets/{self.dataset}/tables/{dataset.key}",
                token=self._access_token(),
                user_url=True,
                provider="bigquery",
            )
        except NotFound:
            self._call(
                "POST",
                f"/datasets/{self.dataset}/tables",
                {
                    "tableReference": {
                        "projectId": self.project,
                        "datasetId": self.dataset,
                        "tableId": dataset.key,
                    },
                    "description": dataset.description,
                    "schema": {
                        "fields": [
                            {"name": c.name, "type": BQ_TYPES[c.type]} for c in dataset.columns
                        ]
                    },
                },
            )

    def write(self, batch: Batch) -> str:
        self._ensure_table(batch.dataset)
        path = f"/datasets/{self.dataset}/tables/{batch.dataset.key}/insertAll"
        for start in range(0, len(batch.rows), 500):
            chunk = batch.rows[start : start + 500]
            result = self._call(
                "POST",
                path,
                {
                    "rows": [
                        {
                            "insertId": hashlib.sha256(
                                f"{r['id']}:{r['updated_at']}".encode()
                            ).hexdigest()[:64],
                            "json": r,
                        }
                        for r in chunk
                    ]
                },
            )
            if result.get("insertErrors"):
                raise DestinationError("BigQuery rejected some rows (check the table schema).")
        return f"bigquery://{self.project}.{self.dataset}.{batch.dataset.key}"


# --- Snowflake ----------------------------------------------------------------------------------


class SnowflakeDestination:
    def __init__(self, config: dict[str, Any], credentials: dict[str, Any]) -> None:
        self.account = str(config.get("account", ""))
        self.user = str(config.get("user", ""))
        self.database = str(config.get("database", ""))
        self.schema = str(config.get("schema", "PUBLIC"))
        self.warehouse = str(config.get("warehouse", ""))
        self.private_key = str(credentials.get("private_key", ""))
        if not SNOWFLAKE_ACCOUNT.match(self.account) or not all(
            IDENT.match(v) for v in (self.user, self.database, self.schema, self.warehouse)
        ):
            raise DestinationError("Enter the Snowflake account, user, database and warehouse.")

    def _jwt(self) -> str:
        from cryptography.hazmat.primitives import serialization

        key = serialization.load_pem_private_key(self.private_key.encode(), password=None)
        public = key.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        fingerprint = "SHA256:" + base64.b64encode(hashlib.sha256(public).digest()).decode()
        qualified = f"{self.account.split('.')[0].upper()}.{self.user.upper()}"
        now = int(time.time())
        return rs256_jwt(
            {"iss": f"{qualified}.{fingerprint}", "sub": qualified, "iat": now, "exp": now + 3000},
            self.private_key,
        )

    def _sql(self, statement: str, bindings: dict[str, Any] | None = None) -> Any:
        try:
            return http.request(
                "POST",
                f"https://{self.account}.snowflakecomputing.com/api/v2/statements",
                token=self._jwt(),
                headers={"X-Snowflake-Authorization-Token-Type": "KEYPAIR_JWT"},
                json_body={
                    "statement": statement,
                    "timeout": 120,
                    "database": self.database,
                    "schema": self.schema,
                    "warehouse": self.warehouse,
                    **({"bindings": bindings} if bindings else {}),
                },
                user_url=True,
                provider="snowflake",
            ).json()
        except ProviderError as exc:
            raise DestinationError(str(exc)) from exc

    def check(self) -> None:
        self._sql("SELECT 1")

    def write(self, batch: Batch) -> str:
        table = batch.dataset.key.upper()
        columns = batch.dataset.columns
        self._sql(
            f"CREATE TABLE IF NOT EXISTS {table} ("
            + ", ".join(f'"{c.name.upper()}" {SF_TYPES[c.type]}' for c in columns)
            + ")"
        )
        placeholders = ", ".join("?" for _ in columns)
        names = ", ".join(f'"{c.name.upper()}"' for c in columns)
        for start in range(0, len(batch.rows), 1000):
            chunk = batch.rows[start : start + 1000]
            bindings: dict[str, Any] = {}
            for n, column in enumerate(columns, start=1):
                bindings[str(n)] = {
                    "type": "TEXT",
                    "value": [
                        None if r.get(column.name) in (None, "") else str(r[column.name])
                        for r in chunk
                    ],
                }
            self._sql(f"INSERT INTO {table} ({names}) VALUES ({placeholders})", bindings)  # noqa: S608
        return f"snowflake://{self.account}/{self.database}.{self.schema}.{table}"


# --- fake ----------------------------------------------------------------------------------------


class FakeDestination:
    """In-memory (development and tests): ``written[destination][dataset]`` = row dicts."""

    written: ClassVar[dict[str, dict[str, list[dict[str, Any]]]]] = {}
    fail_next: ClassVar[int] = 0

    def __init__(self, destination_id: str, kind: str) -> None:
        self.destination_id = destination_id
        self.kind = kind

    @classmethod
    def reset(cls) -> None:
        cls.written.clear()
        cls.fail_next = 0

    def check(self) -> None:
        return None

    def write(self, batch: Batch) -> str:
        if FakeDestination.fail_next:
            FakeDestination.fail_next -= 1
            raise DestinationError("The warehouse is unavailable (fake).")
        store = self.written.setdefault(self.destination_id, {})
        store.setdefault(batch.dataset.key, []).extend(batch.rows)
        return f"fake-{self.kind}://{self.destination_id}/{batch.dataset.key}/{batch.filename}"


def for_destination(destination: Any, *, live: bool | None = None) -> Destination:
    """The destination's client. Configuration is validated even when the fake is used."""
    kind = destination.kind
    if kind == "platform":
        return PlatformDestination(str(destination.organisation_id), str(destination.pk))
    if live is None:
        live = bool(settings.WAREHOUSE_EXPORT["LIVE"])
    if not live:
        for_destination(destination, live=True)  # same validation as production
        return FakeDestination(str(destination.pk), kind)
    try:
        credentials = json.loads(destination.credentials or "{}")
    except ValueError as exc:
        raise DestinationError("The saved credentials aren't valid JSON.") from exc
    if kind == "s3":
        return S3Destination(destination.config, credentials)
    if kind == "bigquery":
        return BigQueryDestination(destination.config, credentials)
    if kind == "snowflake":
        return SnowflakeDestination(destination.config, credentials)
    raise DestinationError(f"Unknown destination {kind!r}.")
