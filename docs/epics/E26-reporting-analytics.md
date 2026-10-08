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
- [ ] **E26-T01** Fact tables and incremental refresh from events; FX rates.
- [ ] **E26-T02** MVP fixed dashboard.
- [ ] **E26-T03** Configurable dashboard and widget library.
- [ ] **E26-T04** Finance reports set.
- [ ] **E26-T05** Payroll and operations reports.
- [ ] **E26-T06** Sales/growth and people/compliance reports.
- [ ] **E26-T07** Exports (CSV/XLSX/PDF) and scheduled reports.
- [ ] **E26-T08** (Phase 2b) Custom report builder on semantic layer.
- [ ] **E26-T09** (Enterprise) Warehouse export.
