from __future__ import annotations

import datetime

import factory

from tutortrack.core.tests.factories import TenantFactory
from tutortrack.migration.models import ExportJob, ImportBatch, MigrationProject


class ImportBatchFactory(TenantFactory):
    class Meta:
        model = ImportBatch

    entity = "students"
    source = "csv"
    filename = factory.Sequence(lambda n: f"students-{n}.csv")
    headers = factory.LazyFunction(lambda: ["First name", "Last name"])
    mapping = factory.LazyFunction(lambda: {"First name": "first_name", "Last name": "last_name"})


class MigrationProjectFactory(TenantFactory):
    class Meta:
        model = MigrationProject

    name = factory.Sequence(lambda n: f"Migration {n}")
    source = "tutorbird"
    cutover_date = datetime.date(2026, 11, 1)


class ExportJobFactory(TenantFactory):
    class Meta:
        model = ExportJob
