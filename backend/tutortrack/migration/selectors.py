"""Reads for imports, migration projects and exports (E28), scoped by permission."""

from __future__ import annotations

from typing import Any

from django.db.models import QuerySet

from tutortrack.core.permissions import scope_queryset

from .models import ExportJob, ImportBatch, ImportRow, MigrationProject, SavedImportMapping


def batches(user: Any) -> QuerySet[ImportBatch]:
    return scope_queryset(user, ImportBatch.objects.all(), "migration.import.view").select_related(
        "requested_by", "error_file", "project"
    )


def rows(batch: ImportBatch, *, status: str = "", problems: bool = False) -> QuerySet[ImportRow]:
    qs = batch.rows.order_by("row_number")
    if status:
        qs = qs.filter(status=status)
    if problems:
        qs = qs.exclude(errors=[]) | qs.exclude(warnings=[])
        qs = qs.order_by("row_number")
    return qs


def saved_mappings(user: Any, entity: str = "") -> QuerySet[SavedImportMapping]:
    qs = scope_queryset(user, SavedImportMapping.objects.all(), "migration.import.manage")
    return qs.filter(entity=entity) if entity else qs


def projects(user: Any) -> QuerySet[MigrationProject]:
    return scope_queryset(user, MigrationProject.objects.all(), "migration.project.manage")


def exports(user: Any) -> QuerySet[ExportJob]:
    return scope_queryset(user, ExportJob.objects.all(), "migration.export.full").select_related(
        "requested_by"
    )
