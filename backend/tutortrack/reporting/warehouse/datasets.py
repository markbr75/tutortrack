"""The exported datasets and their documented schemas (E26-T09, FR-26-5 "documented
schemas").

Facts come from the E26 reporting layer (already denormalised, FR-26-7); dimensions give
the names behind their ids. Sensitive fields (dates of birth, tax and bank details,
safeguarding notes, notes about people) are never exported. Every row carries
``updated_at``: exports are incremental on it, so a warehouse keeps the latest row per
``id``; a weekly full refresh (per destination) also clears out rows deleted here.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any

from django.db.models import QuerySet


@dataclass(frozen=True)
class Column:
    name: str
    type: str  # STRING | INTEGER | NUMERIC | BOOLEAN | DATE | TIMESTAMP
    source: str = ""  # ORM lookup (defaults to the name)
    description: str = ""

    @property
    def lookup(self) -> str:
        return self.source or self.name


@dataclass(frozen=True)
class Dataset:
    key: str
    model: str  # "app_label.module:Model"
    description: str
    columns: tuple[Column, ...]

    def queryset(self) -> QuerySet[Any]:
        module, _, name = self.model.partition(":")
        model = getattr(importlib.import_module(module), name)
        manager = model.objects
        # Branch-scoped models: the export is organisation-wide (not one user's branches).
        from tutortrack.core.context import branch_scope

        with branch_scope(None):
            return manager.all()


def _c(name: str, kind: str, source: str = "", description: str = "") -> Column:
    return Column(name, kind, source, description)


COMMON = (_c("id", "STRING"), _c("updated_at", "TIMESTAMP"))

DATASETS: dict[str, Dataset] = {
    d.key: d
    for d in (
        Dataset(
            "fact_lesson",
            "tutortrack.reporting.models:FactLesson",
            "One row per lesson and tutor; revenue on the primary row only.",
            (
                *COMMON,
                _c("lesson_id", "STRING"),
                _c("tutor_id", "STRING"),
                _c("job_id", "STRING"),
                _c("service_id", "STRING"),
                _c("subject_id", "STRING"),
                _c("branch_id", "STRING"),
                _c("primary", "BOOLEAN"),
                _c("date", "DATE"),
                _c("start", "TIMESTAMP"),
                _c("end", "TIMESTAMP"),
                _c("status", "STRING"),
                _c("cancelled_by", "STRING"),
                _c("minutes", "INTEGER"),
                _c("delivered_minutes", "INTEGER"),
                _c("attendees", "INTEGER"),
                _c("present", "INTEGER"),
                _c("absent", "INTEGER"),
                _c("currency", "STRING"),
                _c("revenue", "NUMERIC", "revenue_amount"),
                _c("pay", "NUMERIC", "pay_amount"),
            ),
        ),
        Dataset(
            "fact_charge",
            "tutortrack.reporting.models:FactCharge",
            "Client charges (lesson fees, ad hoc charges) with their invoice.",
            (
                *COMMON,
                _c("charge_id", "STRING"),
                _c("invoice_id", "STRING"),
                _c("client_id", "STRING"),
                _c("student_id", "STRING"),
                _c("tutor_id", "STRING"),
                _c("lesson_id", "STRING"),
                _c("service_id", "STRING"),
                _c("branch_id", "STRING"),
                _c("date", "DATE"),
                _c("kind", "STRING"),
                _c("status", "STRING"),
                _c("currency", "STRING"),
                _c("net", "NUMERIC", "net_amount"),
                _c("tax", "NUMERIC", "tax_amount"),
                _c("gross", "NUMERIC", "gross_amount"),
            ),
        ),
        Dataset(
            "fact_payment",
            "tutortrack.reporting.models:FactPayment",
            "Payments received, refunds and provider fees.",
            (
                *COMMON,
                _c("payment_id", "STRING"),
                _c("client_id", "STRING"),
                _c("branch_id", "STRING"),
                _c("date", "DATE"),
                _c("method", "STRING"),
                _c("provider", "STRING"),
                _c("status", "STRING"),
                _c("currency", "STRING"),
                _c("amount", "NUMERIC", "amount_amount"),
                _c("refunded", "NUMERIC", "refunded_amount"),
                _c("fee", "NUMERIC", "fee_amount"),
            ),
        ),
        Dataset(
            "fact_pay_item",
            "tutortrack.reporting.models:FactPayItem",
            "Tutor pay items (lesson pay, expenses, bonuses).",
            (
                *COMMON,
                _c("pay_item_id", "STRING"),
                _c("tutor_id", "STRING"),
                _c("lesson_id", "STRING"),
                _c("pay_run_id", "STRING"),
                _c("branch_id", "STRING"),
                _c("date", "DATE"),
                _c("kind", "STRING"),
                _c("status", "STRING"),
                _c("currency", "STRING"),
                _c("amount", "NUMERIC", "amount_amount"),
                _c("quantity", "NUMERIC"),
            ),
        ),
        Dataset(
            "daily_aggregate",
            "tutortrack.reporting.models:DailyAggregate",
            "Daily totals per branch and currency.",
            (
                *COMMON,
                _c("branch_id", "STRING"),
                _c("date", "DATE"),
                _c("currency", "STRING"),
                _c("lessons_completed", "INTEGER"),
                _c("lessons_cancelled", "INTEGER"),
                _c("lessons_planned", "INTEGER"),
                _c("delivered_minutes", "INTEGER"),
                _c("revenue", "NUMERIC"),
                _c("collected", "NUMERIC"),
                _c("pay_cost", "NUMERIC"),
            ),
        ),
        Dataset(
            "dim_client",
            "tutortrack.people.models:Client",
            "Bill payers (names only; no contact details).",
            (
                *COMMON,
                _c("name", "STRING", "display_name"),
                _c("type", "STRING"),
                _c("status", "STRING"),
                _c("branch_id", "STRING"),
                _c("created_at", "TIMESTAMP"),
            ),
        ),
        Dataset(
            "dim_student",
            "tutortrack.people.models:Student",
            "Students (no date of birth, school or notes).",
            (
                *COMMON,
                _c("client_id", "STRING"),
                _c("first_name", "STRING"),
                _c("last_name", "STRING"),
                _c("year_group", "STRING"),
                _c("status", "STRING"),
                _c("branch_id", "STRING"),
                _c("created_at", "TIMESTAMP"),
            ),
        ),
        Dataset(
            "dim_tutor",
            "tutortrack.people.models:TutorProfile",
            "Tutors (no contact, tax or bank details).",
            (
                *COMMON,
                _c("first_name", "STRING"),
                _c("last_name", "STRING"),
                _c("employment_type", "STRING"),
                _c("status", "STRING"),
                _c("created_at", "TIMESTAMP"),
            ),
        ),
        Dataset(
            "dim_service",
            "tutortrack.catalogue.models:Service",
            "Services offered.",
            (*COMMON, _c("name", "STRING"), _c("created_at", "TIMESTAMP")),
        ),
    )
}


def schema(keys: list[str] | None = None) -> list[dict[str, Any]]:
    """The documented schemas (also written to each export's ``manifest.json``)."""
    return [
        {
            "dataset": d.key,
            "description": d.description,
            "columns": [{"name": c.name, "type": c.type} for c in d.columns],
        }
        for d in DATASETS.values()
        if not keys or d.key in keys
    ]
