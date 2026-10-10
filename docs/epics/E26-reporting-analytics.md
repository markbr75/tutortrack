# E26 — Reporting, Analytics & Dashboards

| | |
|---|---|
| **Phase** | Agency (Phase 2) with basic MVP dashboard |
| **Depends on** | All operational epics |
| **Parity** | TutorCruncher customisable dashboard, financial reports, contractor pay reports, client statements, lesson reports, custom exports, BigQuery export; TutorBird revenue tracking and business reports |

## 1. Summary
Operational and financial insight: a configurable home dashboard with KPI widgets, a library of standard reports with filters and exports, a custom report builder, scheduled report emails and a data warehouse export for advanced users.

## 2. Functional requirements

### FR-26-1 Dashboard
- Widget grid per user (drag, resize), role-based default layouts (Owner, Coordinator, Finance, Tutor, Branch Manager).
- Widgets: revenue (invoiced/collected) this period vs last; outstanding & overdue (ageing); lessons delivered/hours; cancellations rate; active students/clients/tutors; new enquiries & conversion; margin; upcoming lessons today; unconfirmed lessons; overdue reports; compliance expiring; uninvoiced charges; next pay run total; cash forecast (scheduled lessons × rates for next 30/60/90 days); tutor utilisation; churned students.
- Period selector, branch filter, comparison period; click-through to underlying report.
- MVP: a fixed dashboard for sole traders (this month revenue, outstanding, lessons, upcoming).

### FR-26-2 Standard reports
**Finance:** revenue by period/service/subject/tutor/branch/client; invoices register; payments received (by method/provider, fees); aged debtors; client balances & credit liability; package liabilities (unused prepaid units = deferred revenue); tax/VAT summary; refunds & write-offs; margin by job/tutor/service; cash forecast.
**Payroll:** tutor earnings by period; pay run summaries; held items; expenses by category; mileage.
**Operations:** lessons by status; attendance & cancellation analysis (by who/when/policy outcome); tutor hours & utilisation vs availability; report SLA compliance by tutor; unconfirmed lessons; room utilisation.
**Sales & growth:** enquiry funnel, source attribution, conversion time, lost reasons; student retention/churn cohorts; lifetime value; referral and affiliate performance; review scores.
**People/compliance:** active students by subject/level; tutor compliance status; recruitment funnel.
- Each report: filters (date range, branch, tutor, service, client, tags, custom fields), grouping, sorting, charts + table, export CSV/XLSX/PDF, save as view, permission-scoped data (e.g. tutors only see their own; finance-only reports).

### FR-26-3 Custom report builder (Phase 2b)
- Choose a dataset (Lessons, Attendees, Charges, Invoices, Payments, Pay items, Students, Clients, Tutors, Enquiries), pick columns (incl. related and custom fields), filters, group-by, aggregates (sum/count/avg), chart type; save/share.
- Implementation: semantic layer of whitelisted dataset definitions → safe ORM query builder (no raw SQL from users); query timeouts; heavy queries run async on a read replica with results cached.

### FR-26-4 Scheduled reports
- Email a report/export (CSV/PDF) daily/weekly/monthly to staff recipients.

### FR-26-5 Data warehouse export (Enterprise)
- Nightly export of tenant data to the tenant's BigQuery/Snowflake/S3 (Parquet) using documented schemas; or read-only Postgres replica access via a reporting schema of views (row-filtered per tenant).

### FR-26-6 Multi-currency reporting
- Reports in a chosen reporting currency using daily FX rates (ECB/openexchangerates) stored in `FxRate`; original currency shown in detail.

### FR-26-7 Performance
- Reporting uses denormalised fact tables refreshed incrementally from events (`fact_lesson`, `fact_charge`, `fact_payment`, `fact_pay_item`), with materialised daily aggregates; reports query facts, not OLTP joins.
- p95 standard report < 3s for 1 year of data for a 200-tutor agency.

## 3. Data model
`DashboardLayout`, `Widget`, `SavedReport`, `ScheduledReport`, `ReportRun(result file)`, `FxRate`, fact tables and aggregates.

## 4. Delivery plan
- [x] **E26-T01** Fact tables and incremental refresh from events; FX rates.
- [x] **E26-T02** MVP fixed dashboard.
- [x] **E26-T03** Configurable dashboard and widget library.
- [x] **E26-T04** Finance reports set.
- [x] **E26-T05** Payroll and operations reports.
- [x] **E26-T06** Sales/growth and people/compliance reports.
- [x] **E26-T07** Exports (CSV/XLSX/PDF) and scheduled reports.
- [ ] **E26-T08** (Phase 2b) Custom report builder on semantic layer.
- [ ] **E26-T09** (Enterprise) Warehouse export.

## Implementation notes (as built 2026-10-10)
- **App:** `reporting`, with RLS on every tenant table: `FactLesson`, `FactCharge`, `FactPayment`, `FactPayItem`, `DailyAggregate`, `DashboardLayout`, `SavedReport`, `ScheduledReport` and `ReportRun`. `FxRate` is platform data (no tenant). See ADR 0016.
- **Facts (T01):** `reporting.facts` refreshes one fact from its source record. Handlers call it on lesson, attendance, charge, invoice, credit note, payment, pay item and pay run events. Each refresh also recomputes the `DailyAggregate` rows of the days it touches.
  - `FactLesson` has one row per lesson and tutor. The `primary` row carries the attendees' charges, so lesson counts and revenue never double count.
  - Dates are in the organisation's timezone.
  - `rebuild()` backfills and repairs. It is exposed as `manage.py rebuild_reporting_facts`, `POST /api/v1/reporting/rebuild` (`reporting.manage`) and a dev seed step.
  - Deviation: "materialised daily aggregates" are an ordinary table kept current by the refresh, not Postgres materialised views. Reports query the facts; the dashboard trend charts query the aggregates.
- **FX (FR-26-6):** `FxRate` stores daily rates. They are fetched by the Celery Beat task `reporting.tasks.fetch_fx_rates` (global housekeeping) or `manage.py fetch_fx_rates`.
  - Provider: ECB (`FX_RATES_PROVIDER=ecb`), Open Exchange Rates (`oxr` plus `OPENEXCHANGERATES_APP_ID`), or a fixed fake table when unset.
  - Any report with money accepts `?currency=`. Each row is converted at its day's rate (crossing through the provider's base), rounded half-up to the minor unit, and keeps `original_currency`. Rows without a rate stay in their own currency, with a note.
  - The org setting `reporting.currency`, when set, is the default reporting currency; `?currency=` on a request overrides it.
- **Dashboards (T02/T03):** 21 widgets (`reporting.widgets`), each tied to a report permission and drilling into a report. Each takes a period, an optional comparison (previous period or year) and a branch filter.
  - Widgets: revenue, invoiced, collected, outstanding and ageing, not yet invoiced, margin, cash forecast (30/60/90 days), revenue trend, next pay run, earnings, lessons and hours, cancellation rate, today's lessons, unconfirmed lessons, overdue reports, tutor utilisation, lessons trend, active students/clients/tutors, checks expiring, new enquiries and win rate, churned students.
  - Role layouts: owner/admin/branch manager, coordinator, finance and tutor. The MVP `simple` layout (revenue, outstanding, lessons, today's lessons) is the default for owners and admins of organisations with at most one active tutor. The org setting `reporting.dashboard_preset` is `auto`, `simple` or `role`.
  - Users customise order, size and widgets (`PUT/DELETE /api/v1/reporting/dashboard`).
  - Deviation: the spec's `Widget` model is the code registry, and a layout is a JSON list on `DashboardLayout`.
  - Deviation: tiles are reordered and resized with buttons and a size select rather than drag and drop. This is the WCAG 2.2 SC 2.5.7 single-pointer alternative; drag can be added later.
  - The dashboard is on the admin home page. Tutors use the portal, whose Today page (E16) already shows their own figures; the API serves the `tutor` layout for later use.
- **Reports (T04-T06):** 31 standard reports in `reporting.reports` (finance, payroll, operations, sales, people). All are served by `GET /api/v1/reporting/reports[/{key}]`.
  - Shared filters: date range presets or custom dates, branch, tutor, client, service, subject, tag (client, student or tutor tags), and a client custom field as `key=value`.
  - Options: group-by, ordering on any column, totals per currency, a chart hint and notes.
  - Data scope comes from each family's permission: `reporting.finance.view`, `.payroll.view`, `.operations.view`, `.sales.view`, `.people.view`. Tutors get `operations` and `payroll` with the `own` scope; coordinators get operations, sales and people; finance gets everything.
  - Finance: revenue by period/service/subject/tutor/branch/client, not yet invoiced, invoices register, payments received by method/provider with refunds and fees, aged debtors, client balances and credit held, tax summary net of credit notes, refunds and write-offs, margin by tutor/service/job/month, cash forecast.
  - Payroll: tutor earnings, pay run summaries, pay on hold, expenses by category, mileage.
  - Operations: lessons by status, attendance outcomes, cancellation analysis (who, notice, policy outcome), tutor hours and utilisation against weekly availability, lesson report deadlines, unconfirmed lessons, location use.
  - Sales: enquiry funnel by stage, sources and conversion with days to win, lost reasons, retention cohorts (1/3/6 months), churned students, client lifetime value.
  - People: active students by subject/level/service, tutor compliance, recruitment funnel.
  - Deviations:
    - Package liabilities are not built (prepaid packages are E10 Phase 2).
    - Referral, affiliate and review reports wait for E25.
    - "Room utilisation" is per location, because rooms are still a stub (E06-T10). Utilisation does not deduct time-off exceptions.
    - Custom-field filters cover client fields only.
    - Reports run synchronously and cap long lists at 5,000 rows. Async runs on a replica belong with the custom builder (T08).
- **Exports and scheduled reports (T07):**
  - `GET /api/v1/reporting/reports/{key}/export?file_format=csv|xlsx|pdf` needs `reporting.export`. Each export is recorded as a `ReportRun`, an `export` audit entry (with the mass-export alert) and `report.exported`.
  - CSV and XLSX neutralise formula-like text. XLSX is written directly as SpreadsheetML, so there is no new dependency. PDF uses WeasyPrint in the organisation's locale.
  - Saved views (`/api/v1/saved-reports`) store relative presets, so "last month" stays relative. They are private, or shared with staff who may run the report. Only the owner edits or deletes a view.
  - Scheduled reports (`/api/v1/scheduled-reports`) run daily, weekly or monthly at a local time, as CSV, XLSX or PDF. Recipients must be active staff who hold the report's permission; this is checked on save and again at delivery.
  - Each schedule is a Temporal Schedule (`core.workflows.schedules`), synced by a handler on `scheduled_report.saved/deleted`.
- **TW (ScheduledReportWorkflow):** generate (retried) → deliver (retried) → `delivered:n`; a run that keeps failing becomes `failed`; a paused or deleted schedule returns `skipped`.
  - Generation runs as the saved report's owner, with their branch restriction. It is idempotent per workflow id (`ReportRun.run_key`) and stores the file in object storage (`ReportRun.file`).
  - Delivery sends the comms notification `scheduled_report` (email with the file attached, editable template), once per recipient.
  - Tests cover the happy path, retry, failure, skip, the schedule sync and a replay of recorded histories.
  - Deviation: the workflow has no signals or timers to test; the Schedule provides the timing.
- **Not built:** T08 custom report builder (Phase 2b) and T09 warehouse export (Enterprise).
- **Frontend:** the admin home shows the dashboard. Reports live under `/analytics`: the library, a report page with filters, chart, table, totals, downloads and "save this view", and saved and scheduled reports with the run history.
  - Charts use Recharts with the Okabe-Ito palette. The drawing is hidden from assistive technology, and a table carries the same numbers.
