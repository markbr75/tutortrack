# E26 — Reporting, Analytics & Dashboards: manual tests

**Scope.** Fact tables and FX rates, the home dashboard (simple MVP layout and role layouts with 21 widgets), 31 standard reports with filters, grouping, charts and totals, exports (CSV/XLSX/PDF), saved views, scheduled report emails (`ScheduledReportWorkflow` on a Temporal Schedule), multi-currency reporting, the Phase 2b custom report builder (T08), and the Enterprise warehouse export (T09, Phase 3). Spec: [E26](../epics/E26-reporting-analytics.md).

**Built differently from the spec (Implementation notes win):**
- Dashboard tiles are reordered and resized with buttons and a size select (WCAG 2.5.7), not drag and drop.
- Package liabilities, referral/affiliate/review reports are not built. Room utilisation is per location.
- Custom-field filters on standard reports cover client fields only. Reports cap long lists at 5,000 rows and run synchronously.
- Tutors use the portal Today page for their figures; the admin dashboard is for staff.
- The custom builder caps results at 1,000 rows, 3 group-by columns, 6 measures and 10 filters, with a 15-second query timeout. Custom reports can't be scheduled.
- T09 warehouse export is being built by another agent. Its cases are marked **Verify after the Phase 3 merge**.

**Common preconditions.**
- `make seed` run; it also runs `rebuild_reporting_facts` and loads the fake FX table (`fx.FakeProvider`). Rebuild at any time with `cd backend && uv run python manage.py rebuild_reporting_facts`.
- Seeded data: weekly GCSE Maths lessons for Arjun with Nia (Tuesday 16:30), services and rates, enquiries and pay data only if created by earlier test areas. For revenue figures, issue at least one invoice and record one payment first (see E10/E11 test files).
- Reports live under **Reports and dashboards** (`/analytics`): All reports, Saved and scheduled (`/analytics/saved`) and Build a report (`/analytics/builder`). The dashboard is on the admin home page (`/`).
- Temporal worker and Celery worker running; Mailpit at http://localhost:8025.

## Facts and FX (T01, FR-26-6, FR-26-7)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E26-001 | Completing a lesson updates reports | Owner | A scheduled lesson today or earlier | 1. Note "Lessons by status" for this month.<br>2. Complete one lesson.<br>3. Re-run the report. | Completed count +1 and scheduled count −1 without a manual rebuild. | P1 | backend: `tutortrack/reporting/tests/test_reporting.py::test_handlers_refresh_facts_incrementally` | |
| TP-E26-002 | Issuing an invoice and recording a payment update revenue | Finance | A draft invoice of £45.00 | 1. Issue it; check Revenue (this month).<br>2. Record payment; check Payments received. | Revenue invoiced +£45.00. Payments received lists £45.00 by method. | P1 | backend: `tutortrack/reporting/tests/test_reporting.py::test_facts_mirror_lessons_charges_payments_and_pay` | |
| TP-E26-003 | A lesson with two attendees counts once | Owner | Group class session with 2 students | 1. Complete the session.<br>2. Run Lessons by status. | One lesson; revenue for both attendees. | P2 | backend: `tutortrack/reporting/tests/test_reporting.py::test_facts_mirror_lessons_charges_payments_and_pay` | |
| TP-E26-004 | Rebuild command and API | Owner | — | 1. Run `manage.py rebuild_reporting_facts`.<br>2. As finance, `POST /api/v1/reporting/rebuild`.<br>3. As coordinator, the same. | 1–2: counts printed / 200, figures unchanged. 3: 403 (needs `reporting.manage`). | P2 | backend: `tutortrack/reporting/tests/test_reporting.py::test_rebuild_requires_reporting_manage` | |
| TP-E26-005 | Dates follow the organisation's time zone | Owner | Org tz Europe/London; a lesson at 23:30 local on the last day of a month | 1. Run Lessons by status for each month. | The lesson counts in its local month, not the UTC month. | P2 | backend: `tutortrack/reporting/tests/test_reporting.py::test_periods_and_comparisons` | |
| TP-E26-006 | FX rates fetched | Owner | — | 1. Run `manage.py fetch_fx_rates`. | Rates stored for today (fake table in dev). Running again does not duplicate. | P2 | backend: `tutortrack/reporting/tests/test_reporting.py::test_fx_rates_are_stored_and_convert_with_half_up_rounding` | |
| TP-E26-007 | Report in another currency | Finance | Payments in GBP | 1. Open Revenue → Show in currency = EUR. | Amounts in EUR, rounded half-up to cents. Detail rows keep the original GBP amount. | P1 | backend: `tutortrack/reporting/tests/test_reporting.py::test_reports_convert_into_a_reporting_currency` | |
| TP-E26-008 | Organisation reporting currency default | Owner | Settings: `reporting.currency` = USD | 1. Open any money report with no currency chosen.<br>2. Choose GBP. | Default is USD. `?currency=` overrides it. | P2 | backend: `tutortrack/reporting/tests/test_reporting.py::test_organisation_reporting_currency_is_the_default` | |
| TP-E26-009 | Row without a rate | Finance | A payment dated before any FX rate | 1. Show in another currency. | The row stays in its own currency with a note. Totals are per currency, never mixed. | P3 | No | |

## Dashboard (T02, T03)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E26-010 | Simple dashboard for a one-tutor organisation | Owner | A fresh organisation with ≤ 1 active tutor (sign up a new org) | 1. Open the home page. | Four tiles: revenue, outstanding, lessons, today's lessons. | P1 | backend: `tutortrack/reporting/tests/test_reporting.py::test_sole_trader_gets_the_simple_dashboard` | |
| TP-E26-011 | Role layout for Bright Minds owner | Owner | Seed (2 tutors) | 1. Sign in as admin@ and open Home. | The owner layout with revenue, outstanding/ageing, margin, cash forecast, lessons, utilisation, enquiries etc. Every tile loads (no "This figure couldn't be loaded."). | P1 | backend: `tutortrack/reporting/tests/test_reporting.py::test_roles_get_their_default_layouts`; `test_reporting.py::test_every_widget_computes` | |
| TP-E26-012 | Coordinator and finance layouts | Coordinator; Finance | Seed | 1. Sign in as each and open Home. | Coordinator: operations/sales tiles, no margin or pay figures. Finance: money, pay run, ageing tiles. | P1 | backend: `tutortrack/reporting/tests/test_reporting.py::test_roles_get_their_default_layouts` | |
| TP-E26-013 | Dashboard preset setting | Owner | Settings: `reporting.dashboard_preset` | 1. Set "simple" and reload Home.<br>2. Set "role" and reload. | The layout follows the setting. | P2 | No | |
| TP-E26-014 | Period and comparison | Owner | Seed | 1. Period = Last month, Compare with = Previous period.<br>2. Compare with = Same period last year. | Tiles show "Up n% on the previous period" / "Same as…" / "Nothing to compare with". | P1 | backend: `tutortrack/reporting/tests/test_reporting.py::test_widgets_compare_with_the_previous_period` | |
| TP-E26-015 | Branch filter | Owner | Multi-branch with a second branch | 1. Choose the second branch. | Figures reflect only that branch's lessons and money. | P2 | backend: `tutortrack/reporting/tests/test_reporting.py::test_branch_scope_limits_figures` | |
| TP-E26-016 | Customise: add, move, resize, remove, save | Owner | Seed | 1. Customise → Add a figure → "Cash forecast" → Add.<br>2. Move it earlier; Size = Large.<br>3. Remove "Churned students".<br>4. Save layout; reload. | Order, size and widgets persist for this user only (other users unchanged). | P1 | backend: `tutortrack/reporting/tests/test_reporting.py::test_users_customise_and_reset_their_dashboard` | |
| TP-E26-017 | Back to the default | Owner | TP-E26-016 | 1. Customise → Back to the default. | The role default layout returns. | P2 | backend: same | |
| TP-E26-018 | Click-through to the report | Owner | Seed | 1. On a tile select "Open the … report". | The matching report opens with the same period and branch. | P1 | No | |
| TP-E26-019 | Keyboard-only customisation | Owner | Keyboard only | 1. Tab to Customise; use Earlier/Later buttons and the size select. | All actions work without a mouse; focus stays on the moved tile's control. | P2 | No | |
| TP-E26-020 | Cash forecast prices planned lessons | Finance | Weekly £45 lessons for Arjun | 1. Open Cash forecast (30/60/90 days). | Forecast ≈ number of planned lessons × £45 for each window. | P2 | backend: `tutortrack/reporting/tests/test_reporting.py::test_cash_forecast_prices_planned_lessons` | |

## Standard reports (T04–T06)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E26-021 | Library is filtered by permission | Coordinator; Finance | Seed | 1. Open All reports as each role. | Finance sees finance, payroll, operations, sales and people. Coordinator sees operations, sales and people only; no finance or payroll. | P1 | backend: `tutortrack/reporting/tests/test_reporting.py::test_report_library_is_filtered_by_permission` | |
| TP-E26-022 | Revenue by tutor and service | Finance | Invoices issued | 1. Revenue → Group by Tutor, then Service. | Rows per tutor/service; totals per currency; chart and table show the same numbers. | P1 | backend: `tutortrack/reporting/tests/test_reporting.py::test_revenue_by_tutor_and_service` | |
| TP-E26-023 | Invoices register, payments received, aged debtors, client balances | Finance | Issued invoices, one overdue | 1. Open each report. | Register lists each invoice with number and status; payments by method/provider with fees and refunds; aged debtors in ageing buckets; client balances with credit held. | P1 | backend: `tutortrack/reporting/tests/test_reporting.py::test_aged_debtors_and_client_balances` | |
| TP-E26-024 | Tax summary, refunds and write-offs, not yet invoiced | Finance | A credit note and a write-off | 1. Open each. | Tax summary is net of credit notes. Refunds/write-offs listed. Uninvoiced charges listed. | P2 | backend: `tutortrack/reporting/tests/test_reporting.py::test_every_report_runs_with_each_grouping` | |
| TP-E26-025 | Margin is revenue less tutor pay | Finance | Completed GCSE Maths lessons (£45 charge, £28 pay) | 1. Margin → by tutor. | Margin per hour £17.00 for Nia's lessons. | P1 | backend: `tutortrack/reporting/tests/test_reporting.py::test_margin_is_revenue_less_tutor_pay` | |
| TP-E26-026 | Payroll reports | Finance | A pay run, held items, expenses with mileage | 1. Open Tutor earnings, Pay runs, Pay on hold, Expenses, Mileage. | Each lists correct figures; totals per currency. | P1 | backend: `tutortrack/reporting/tests/test_reporting.py::test_every_report_runs_with_each_grouping` | |
| TP-E26-027 | Operations reports | Coordinator | Lessons with cancellations and attendance | 1. Open Lessons by status, Attendance, Cancellations, Tutor hours and utilisation, Lesson report deadlines, Unconfirmed lessons, Location use, Lesson feedback. | Cancellation analysis by who, notice and policy outcome. Utilisation against weekly availability (15:00–20:00 Mon–Fri for seeded tutors). | P1 | backend: `tutortrack/reporting/tests/test_reporting.py::test_operations_reports` | |
| TP-E26-028 | Sales and people reports | Coordinator | Enquiries won and lost | 1. Open Enquiry funnel, Sources, Lost reasons, Retention cohorts, Churned students, Lifetime value, Active students, Tutor compliance, Recruitment funnel. | Each loads; funnel by stage; days to win shown. | P2 | backend: `tutortrack/reporting/tests/test_reporting.py::test_people_and_sales_reports` | |
| TP-E26-029 | Shared filters | Finance | Tags VIP / Exam year; client custom field | 1. Revenue → filter Tag = VIP; then client custom field `key=value`; then Tutor = Nia; then Service. | Results narrow correctly; clearing filters restores totals. | P2 | No | |
| TP-E26-030 | Invalid parameters | Finance | — | 1. Call `/api/v1/reporting/reports/revenue?group_by=nonsense`. | 400/422 problem response; no server error. | P3 | backend: `tutortrack/reporting/tests/test_reporting.py::test_invalid_parameters_are_rejected` | |
| TP-E26-031 | Charts are accessible | Owner | Any report with a chart | 1. Use a screen reader on the chart. | The drawing is hidden; a data table with the same numbers is announced. Colours are the Okabe-Ito palette. | P2 | No | |

## Exports, saved views and scheduled reports (T07)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E26-032 | Download CSV, Excel and PDF | Finance | Revenue report | 1. Download → CSV, Excel, PDF. | Three files open correctly; PDF uses en-GB dates and £. Audit log has `export` entries. | P1 | backend: `tutortrack/reporting/tests/test_reporting.py::test_exports_csv_xlsx_and_pdf_are_audited` | |
| TP-E26-033 | Formula injection is neutralised | Finance | A client named `=HYPERLINK("http://x")` | 1. Export Client balances to CSV and XLSX; open in a spreadsheet. | The cell shows text, not a formula. | P1 | backend: `tutortrack/reporting/tests/test_reporting.py::test_csv_neutralises_formulas` | |
| TP-E26-034 | Mass-export alert | Finance | — | 1. Export 5 or more reports within an hour. | Owners get a security alert email (once per window). | P2 | No | |
| TP-E26-035 | Export needs `reporting.export` | Tutor | — | 1. Try the export URL as a tutor via API. | 403. | P2 | No | |
| TP-E26-036 | Save a private view with a relative period | Finance | Revenue, Last month, grouped by tutor | 1. Save this view as "Monthly revenue by tutor".<br>2. Reopen from Saved and scheduled next month (or change the system date window). | View restores filters; "Last month" stays relative. Only the creator sees it ("Only you"). | P1 | backend: `tutortrack/reporting/tests/test_reporting.py::test_saved_reports_are_private_unless_shared` | |
| TP-E26-037 | Share a view | Finance | TP-E26-036 | 1. Share with staff.<br>2. Open as admin (has permission) and as coordinator (no finance permission). | Admin sees "Shared by …" and can run it; coordinator can't see it. Only the owner can edit or delete. | P2 | backend: same | |
| TP-E26-038 | Schedule an emailed report | Finance | Saved view | 1. Email on a schedule → Weekly, Monday, 08:00, PDF, recipients finance@ and office@.<br>2. Save. | Schedule listed; a Temporal Schedule exists (Temporal UI → Schedules). | P1 | backend: `tutortrack/reporting/tests/test_workflows.py::test_schedule_follows_the_scheduled_report` | |
| TP-E26-039 | Scheduled run delivers the file | Finance | TP-E26-038 | 1. In the Temporal UI, trigger the schedule now (Schedules → … → Trigger).<br>2. Check Mailpit and the run history. | Each recipient gets one `scheduled_report` email with the PDF attached. Run history shows "delivered:2" and the stored file. | P1 | backend: `tutortrack/reporting/tests/test_workflows.py::test_scheduled_report_is_generated_and_emailed`; `tutortrack/reporting/tests/test_reporting.py::test_scheduled_run_stores_the_file_and_emails_it` | |
| TP-E26-040 | Recipients must hold the permission | Finance | — | 1. Add tutor@ or coordinator@ as a recipient of a finance report. | Refused on save. If a recipient later loses the permission, they are skipped at delivery. | P1 | backend: `tutortrack/reporting/tests/test_reporting.py::test_scheduled_reports_only_go_to_allowed_staff` | |
| TP-E26-041 | Paused or deleted schedule is skipped | Finance | TP-E26-038 | 1. Pause the schedule and trigger it. | Run is `skipped`; no email. Deleting removes the Temporal Schedule. | P2 | backend: `tutortrack/reporting/tests/test_workflows.py::test_paused_schedule_is_skipped` | |
| TP-E26-042 | Failing generation is retried then failed | Owner | Make generation fail (e.g. stop object storage) | 1. Trigger a schedule. | Activity retries; after retries the run is `failed`. Restarting storage and triggering again succeeds. | P3 | backend: `tutortrack/reporting/tests/test_workflows.py::test_a_run_that_keeps_failing_is_marked_failed` | |

## Custom report builder (T08, Phase 2b)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E26-043 | Build a lessons report | Coordinator | Seed lessons | 1. Build a report → Report on = Lessons.<br>2. Column Tutor; Column Date by month.<br>3. Figures: count; sum of hours.<br>4. Period This year; Bar chart; Run. | Grouped rows by tutor and month; hours to one decimal; totals row; bar chart and table match. | P1 | backend: `tutortrack/reporting/tests/test_builder.py::test_grouped_sums_counts_and_averages_match_the_rows` | |
| TP-E26-044 | Money is summed per currency, averages half-up | Finance | Charges in GBP | 1. Report on Charges; Figures sum and average of gross by service. | Sums per currency; averages rounded half-up to 2 places; average total = overall average. | P1 | backend: `tutortrack/reporting/tests/test_builder.py::test_measure_formatting_rounds_half_up` | |
| TP-E26-045 | Filters per type | Coordinator | — | 1. Add filters: Status is one of completed, cancelled; Date is at least …; Student contains "Ar"; a yes/no field. | Results filter correctly; "is empty" / "is not empty" work. | P2 | backend: `tutortrack/reporting/tests/test_builder.py::test_filters_dates_and_labels` | |
| TP-E26-046 | Custom fields are columns | Coordinator | A client custom field | 1. Report on Clients; group by `cf.client.<key>`. | Values of the custom field appear as groups. | P2 | backend: `tutortrack/reporting/tests/test_builder.py::test_client_custom_fields_are_dimensions` | |
| TP-E26-047 | Limits | Coordinator | — | 1. Try a 4th group-by column.<br>2. Run a list with more than 1,000 rows. | "You can group by up to 3 columns." Results truncated at 1,000 with a note. | P2 | backend: `tutortrack/reporting/tests/test_builder.py::test_list_mode_and_row_cap` | |
| TP-E26-048 | Unknown fields and raw SQL refused | Coordinator | — | 1. POST `/api/v1/reporting/builder/run` with a field `people__email` or SQL text. | 422 "Check the report definition". | P1 | backend: `tutortrack/reporting/tests/test_builder.py::test_only_known_names_are_accepted` | |
| TP-E26-049 | Datasets follow permissions | Coordinator; Tutor | — | 1. As coordinator, list datasets.<br>2. As tutor (API) run Lessons. | Coordinator has no Charges/Payments/Pay items datasets. Tutor sees only own lessons (no builder UI). | P1 | backend: `tutortrack/reporting/tests/test_builder.py::test_datasets_are_whitelisted_and_permission_filtered`; `test_builder.py::test_branch_scope_applies` | |
| TP-E26-050 | Save, share, export a custom report | Coordinator | TP-E26-043 | 1. Save as "Hours by tutor", shared.<br>2. Open as another coordinator: run it.<br>3. Download CSV. | Shared report runs with the viewer's own scope; only the owner edits/deletes; export audited (`custom:<id>`). | P1 | backend: `tutortrack/reporting/tests/test_builder.py::test_save_share_run_and_only_the_owner_edits`; `test_builder.py::test_exports_are_audited` | |
| TP-E26-051 | Slow query stopped | Owner | Very large dataset (staging) | 1. Run a heavy report. | Stopped after 15 s with a clear error; app stays responsive. | P3 | backend: `tutortrack/reporting/tests/test_builder.py::test_slow_queries_are_stopped` | |
| TP-E26-052 | Lesson feedback dataset | Coordinator | Lesson feedback answers (E09-T09) | 1. Report on Lesson feedback; average rating by tutor. | Averages match the feedback page. | P2 | backend: `tutortrack/reporting/tests/test_builder.py::test_lesson_feedback_dataset` | |

## Warehouse export (T09, Enterprise — Phase 3)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E26-053 | Configure a warehouse destination | Owner | Verify after the Phase 3 merge. Enterprise entitlement (grant via `/platform` override if needed) | 1. Open the warehouse export settings.<br>2. Add an S3 (Parquet), BigQuery or Snowflake destination with test credentials. | Destination saved; secrets stored encrypted and never shown again; connection test result shown. | P2 | No (Phase 3) | |
| TP-E26-054 | Nightly export writes documented schemas | Owner | Verify after the Phase 3 merge. TP-E26-053 | 1. Run the export now (or wait for the nightly run).<br>2. Inspect the destination. | One file/table per documented entity in Parquet, only this organisation's rows. | P2 | No (Phase 3) | |
| TP-E26-055 | Read-only reporting schema / replica access | Owner | Verify after the Phase 3 merge | 1. Request reporting-schema access.<br>2. Connect with the issued credentials and query the views. | Read-only; views return only this organisation's rows; writes refused. | P2 | No (Phase 3) | |
| TP-E26-056 | Not available without the entitlement | Owner | Verify after the Phase 3 merge. Non-Enterprise org | 1. Open warehouse export. | Upgrade message; API refuses. | P2 | No (Phase 3) | |
| TP-E26-057 | Export failure is reported | Owner | Verify after the Phase 3 merge. Wrong credentials | 1. Run the export. | Failure recorded and shown with the reason; admins notified; retried next run. | P3 | No (Phase 3) | |

## Permissions

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E26-058 | Tutors see only their own figures | Tutor | Seed | 1. Portal Today page as tutor@.<br>2. API: `GET /api/v1/reporting/reports/tutor_earnings`. | Only Nia's lessons and earnings; Sam Clarke's figures never appear. | P1 | backend: `tutortrack/reporting/tests/test_reporting.py::test_tutors_see_only_their_own_earnings_and_lessons`; `test_reporting.py::test_tutor_dashboard_shows_only_their_own_figures` | |
| TP-E26-059 | Branch manager limited to their branch | Branch Manager | Two branches with lessons | 1. Open reports as manager@. | Only the MAIN branch's data. | P1 | backend: `tutortrack/reporting/tests/test_reporting.py::test_branch_scope_limits_figures` | |
| TP-E26-060 | Portal users can't open reports | Parent; Student; Affiliate | — | 1. Request `/api/v1/reporting/reports`. | 403. | P2 | No | |

## Tenant isolation

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E26-061 | Northside never sees Bright Minds figures | Owner (Northside) | Seed | 1. Sign in at http://northside.localhost:5173 and open the dashboard and Revenue. | Only Northside data (Noah Northside); no Bright Minds tutors, clients or totals. | P1 | backend: `tutortrack/reporting/tests/test_reporting.py` (`TestSavedReportIsolation`, `TestScheduledReportIsolation`, `TestReportRunIsolation`); `tutortrack/reporting/tests/test_builder.py::TestCustomReportIsolation` | |
| TP-E26-062 | Saved/custom report ids from another org | Owner (Northside) | Id of a Bright Minds saved view | 1. `GET /api/v1/saved-reports/<id>` and `/custom-reports/<id>` on Northside's host. | 404. | P1 | backend: same | |

## Errors and edge cases

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E26-063 | Empty organisation | Owner | New org with no data | 1. Open dashboard and several reports. | "Nothing to show for this period." — no errors. | P2 | No | |
| TP-E26-064 | Copilot still uses standard reports | Owner | AI copilot (E31) | 1. Ask the copilot "What's our revenue this month?". | Answer cites the Revenue report with a working `/analytics/...` link. | P2 | backend: `tutortrack/reporting/tests/test_builder.py::test_standard_reports_api_is_unchanged_for_the_ai_copilot` | |
| TP-E26-065 | Performance smoke | Finance | Staging with a year of data | 1. Time Revenue by tutor for the last 12 months. | Under 3 s (p95 target). | P3 | No | |
