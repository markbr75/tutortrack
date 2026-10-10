# ADR 0016: Reporting reads event-refreshed fact tables through a scoped report registry

- **Status:** Accepted
- **Date:** 2026-10-10
- **Epic:** E26

## Context
Reports and dashboard figures aggregate data owned by many apps (scheduling, billing,
payments, payroll, leads, recruitment, people). They must:
- respect tenancy (RLS) and the permission's data scope, so a tutor sees only their own
  figures and a branch manager only their branches;
- stay fast for a year of a 200-tutor agency (FR-26-7);
- never write other apps' tables;
- handle several currencies without floats.

Scheduled report emails are per-tenant recurring processes.

## Decision
1. **Fact tables, refreshed from domain events.**
   - `FactLesson` (one row per lesson and tutor; `primary` marks the row carrying the
     lesson's revenue), `FactCharge`, `FactPayment` and `FactPayItem` are tenant tables
     with RLS.
   - They are filled by idempotent `refresh_*` functions. Each re-reads one source record
     and upserts or deletes its row, called from `handlers.py` on lesson, attendance,
     charge, invoice, payment, pay item and pay run events.
   - `DailyAggregate` (per branch, day and currency) is recomputed for every day a refresh
     touches.
   - `rebuild()` (management command, API, dev seed) backfills and repairs.
   - Foreign keys from facts use `db_constraint=False, on_delete=DO_NOTHING`, so derived
     data never blocks or cascades into operational data.
2. **A report registry in code.**
   - Each standard report is a `ReportDef` with a key, a category, a permission codename
     (`reporting.finance.view`, `.payroll.view`, `.operations.view`, `.sales.view`,
     `.people.view`), its supported filters and groupings, and a `run(user, params)`
     function. `run` returns columns, rows, totals and a chart hint.
   - One API endpoint runs any report, and one exports it. The frontend renders any report
     generically.
   - Reports read facts (or other apps' records, read-only) through `scope_queryset`, or
     `scoped_by` for models without a `branch` field. `scoped_by` uses the new
     `core.permissions.permission_scope`.
3. **Money stays Decimal and per currency.**
   - Rows are grouped by currency.
   - A reporting currency converts each row at the day's `FxRate`, rounded half-up to the
     minor unit, and keeps `original_currency`.
   - Rates are platform data, fetched daily by a Celery Beat task. The provider is ECB, Open
     Exchange Rates, or a fake when `FX_RATES_PROVIDER` is empty.
4. **Scheduled reports are Temporal Schedules.**
   - Each `ScheduledReport` has a schedule (cron in the organisation's timezone), kept in
     step by a handler on `scheduled_report.saved/deleted`.
   - Each firing runs `ScheduledReportWorkflow`. It generates the file as the saved
     report's owner (with their branch restriction) and stores it in object storage, then
     emails it through the comms notification registry. Each step is retried.
   - A run that keeps failing is marked failed (`report_run.failed`) rather than failing
     the workflow.

## Consequences
- Report latency depends on narrow, indexed fact tables, not OLTP joins. Facts can lag
  the source by the outbox dispatch delay, and a missed event is repaired by `rebuild`.
- Adding a report is a Python function plus a registry entry. There is no user-defined
  SQL. The custom report builder (E26-T08, Phase 2b) will add a semantic layer on top of
  the same facts.
- Recipients must hold the report's permission when the schedule is saved and again at
  delivery. The figures are those the owner may see.
- Package liabilities, referral, affiliate and review reports wait for the epics that own
  that data (E10 Phase 2, E25).
