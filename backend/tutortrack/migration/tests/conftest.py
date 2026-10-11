"""Helpers for the import tests: run the whole pipeline (validate → import → report)
synchronously through the same service functions the workflow's activities call."""

from __future__ import annotations

from typing import Any

import pytest
from django.db import transaction

from tutortrack.migration import services
from tutortrack.migration.models import ImportBatch


def make_batch(
    entity: str,
    rows: list[dict[str, str]],
    *,
    headers: list[str] | None = None,
    preset: str = "",
    options: dict[str, Any] | None = None,
    user: Any = None,
    project: Any = None,
    step: str = "",
    column_map: dict[str, str] | None = None,
    value_map: dict[str, dict[str, str]] | None = None,
) -> ImportBatch:
    headers = headers or list(dict.fromkeys(k for row in rows for k in row))
    with transaction.atomic():
        batch = services.create_batch(
            user=user,
            entity=entity,
            headers=headers,
            rows=[{h: row.get(h, "") for h in headers} for row in rows],
            source="csv",
            filename=f"{entity}.csv",
            preset=preset,
            options=options,
            project=project,
            project_step=step,
        )
    if column_map is not None or value_map is not None:
        services.update_mapping(batch, column_map=column_map, value_map=value_map)
        batch.refresh_from_db()
    return batch


def validate(batch: ImportBatch) -> ImportBatch:
    with transaction.atomic():
        services.submit(batch)
    services.validate(batch.pk)
    batch.refresh_from_db()
    return batch


def execute(batch: ImportBatch, chunk: int = 250) -> ImportBatch:
    services.start_import(batch.pk)
    row = 0
    while True:
        result = services.import_chunk(batch.pk, row, chunk)
        row = result["last_row"]
        if result["done"]:
            break
    services.finish_import(batch.pk)
    batch.refresh_from_db()
    return batch


def run_import(entity: str, rows: list[dict[str, str]], **kwargs: Any) -> ImportBatch:
    return execute(validate(make_batch(entity, rows, **kwargs)))


def roll_back(batch: ImportBatch) -> dict[str, int]:
    before = 2**31 - 1
    while True:
        result = services.rollback_chunk(batch.pk, before, 100)
        if result["done"]:
            break
        before = result["before_row"]
    return services.finish_rollback(batch.pk)


@pytest.fixture
def s3_tenant(s3: Any, tenant: Any) -> Any:
    return tenant
