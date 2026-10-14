# E28 — Data Import, Export & Competitor Migration: manual tests

**Scope.** The import pipeline (upload, header detection, column and value mapping, validation, dry-run, background import, error report, 7-day rollback), the 14 importers, the cutover assistant with reconciliation, the TutorCruncher and Teachworks API connectors, TutorBird/TutorCruncher/Teachworks CSV presets, Google Sheets import, and the full tenant export; workflows `ImportWorkflow`, `MigrationProjectWorkflow` and `TenantExportWorkflow` on the `imports` task queue. Spec: [E28](../epics/E28-import-export-migration.md).

**Built differently from the spec (Implementation notes win):**
- Source ids are kept in `ExternalRef`, not `external_id` columns.
- Imported invoices are history: original number, one summary line, no ledger entry, no `invoice.issued`, no dunning.
- Imported package balances become active `PackagePurchase`s (no invoice or ledger).
- TutorCruncher agents, reviews, proformas and ad hoc charges are counted (`not_imported_*`) but not imported.
- "Payment methods" and "Switch reminders on" are guidance steps; they change no settings.
- Per-subject DSAR export lives in E29; grid exports are E05.

**Common preconditions.**
- Sign in as admin@tutortrack.localhost (owner). Screen: **Import and export** (`/data`) with tabs Imports, Move from another system, Export all data. Import detail: `/data/imports/<id>`.
- Templates: download from the Imports tab ("template" link) or `GET /api/v1/import-templates/<entity>`. There are no sample files in the repo: build test files from the templates. Keep a small set: `students-10.csv` (10 rows, 2 with bad emails), `clients-household.csv`, `lessons-weekly.csv` (one student weekly for 4 weeks, two weeks before and two after a cutover date), `opening-balances.csv`, `students.xlsx`.
- With no API credentials the TutorCruncher, Teachworks and Google Sheets connectors use **fakes** that serve a sample agency (any API key value works; an empty key is refused).
- Uploads go through the ClamAV scan; with `CLAMAV_ENABLED=false` (local default) files are marked clean at once.
- Temporal worker running (queue `imports`); Mailpit at http://localhost:8025.

## Import pipeline (T01)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E28-001 | Download a template | Owner | — | 1. Imports → What are you importing? = students → template link. | CSV with every field as a header (required ones first). | P2 | backend: `tutortrack/migration/tests/test_api.py::test_catalogue_and_templates` | |
| TP-E28-002 | Upload and auto-match columns | Owner | `students-10.csv` | 1. New import → students → A CSV or Excel file → Upload and match columns. | Status "Match the columns"; columns auto-matched by name and synonyms; unmatched columns set to ignore. | P1 | backend: `tutortrack/migration/tests/test_api.py::test_upload_map_and_submit` | |
| TP-E28-003 | Manual mapping, ignore column, custom field | Owner | File with an extra "Favourite colour" column and a custom field column | 1. Map the custom field column to `cf.<key>`; set "Favourite colour" to ignore.<br>2. Try mapping two columns to the same single field. | Custom field mapped; duplicate single-field mapping refused. | P1 | backend: `tutortrack/migration/tests/test_parsing.py::test_automap_uses_synonyms_presets_and_each_field_once` | |
| TP-E28-004 | Value mapping for statuses | Owner | Column Status with "Waiting List", "Active", "Left" | 1. Map values: Waiting List → waiting, Left → archived. | Values are translated in the preview. | P2 | backend: `tutortrack/migration/tests/test_imports.py::test_value_mapping_and_custom_fields` | |
| TP-E28-005 | Options: date order, match on | Owner | US-format dates (MM/DD/YYYY) | 1. Set date order to month-first; match existing on email. | Dates parse correctly; preview shows updates for existing emails. | P2 | backend: `tutortrack/migration/tests/test_parsing.py::test_us_date_order_and_choice_value_maps` | |
| TP-E28-006 | Required columns missing | Owner | File without a first-name column | 1. Submit. | Refused: required column(s) listed. | P1 | backend: `tutortrack/migration/tests/test_api.py::test_submit_needs_the_required_columns` | |
| TP-E28-007 | Validation preview and dry-run | Owner | `students-10.csv` | 1. Submit mapping.<br>2. Wait for "Checked: ready to import". | Summary "will create N … update M"; preview table lists the 2 bad rows with reasons and any warnings/duplicates. Progress is announced (aria-live). | P1 | backend: `tutortrack/migration/tests/test_imports.py::test_dry_run_counts_creates_and_updates`; `test_invalid_rows_are_reported_and_left_out` | |
| TP-E28-008 | Confirm and import | Owner | TP-E28-007 | 1. Confirm. | Status "Importing…" then "Imported"; 8 students created; 2 rows reported; error report CSV downloads with original columns plus reasons. | P1 | backend: `tutortrack/migration/tests/test_imports.py::test_invalid_rows_are_reported_and_left_out` | |
| TP-E28-009 | Cancel before confirming | Owner | A validated import | 1. Cancel. | Status Cancelled; nothing created; Temporal workflow ends. | P2 | backend: `tutortrack/migration/tests/test_workflows.py::test_cancel_before_confirming` | |
| TP-E28-010 | Rollback within the window | Owner | TP-E28-008 | 1. Select rollback. | Created students removed (newest first); updates reverted; status shows rolled back. | P1 | backend: `tutortrack/migration/tests/test_workflows.py::test_rollback_signal_reverts_the_batch`; `tutortrack/migration/tests/test_imports.py::test_upsert_by_email_updates_and_rollback_restores` | |
| TP-E28-011 | Records changed after import are kept | Owner | An import; edit one imported student | 1. Roll back. | The edited student row is `kept`; others are removed. | P1 | backend: `tutortrack/migration/tests/test_imports.py::test_records_changed_after_the_import_are_kept` | |
| TP-E28-012 | Window closes and finalises | Owner | `migration.rollback_days` = 1 (Settings) | 1. Import; wait past the window (Temporal timer on `import:<org>:<batch>`). | Status finalised; rollback no longer offered. | P2 | backend: `tutortrack/migration/tests/test_workflows.py::test_confirmed_import_is_finalised_when_the_window_closes`; `tutortrack/migration/tests/test_imports.py::test_rollback_window_and_finalise` | |
| TP-E28-013 | Re-importing the same file is idempotent | Owner | TP-E28-008 file | 1. Import the same file again (match on email). | Rows already imported are skipped; no duplicates. | P1 | backend: `tutortrack/migration/tests/test_imports.py::test_rows_are_idempotent` | |
| TP-E28-014 | Saved mappings | Owner | — | 1. Save the mapping as "Old CRM students".<br>2. Start a new import with a file of the same shape. | Saved mapping is offered and applied. | P2 | backend: `tutortrack/migration/tests/test_imports.py::test_saved_mappings_are_reused` | |
| TP-E28-015 | File formats | Owner | CSV with `;` and BOM and a title row; cp1252 file; UTF-16; `.xlsx` with dates on sheet 1 | 1. Upload each. | Headers detected; title row skipped; accents correct; Excel dates parsed. | P2 | backend: `tutortrack/migration/tests/test_parsing.py::test_csv_with_semicolons_bom_and_a_title_row`; `test_csv_latin1_and_duplicate_headers`; `test_xlsx_shared_strings_numbers_and_dates` | |
| TP-E28-016 | Malicious or wrong files | Owner | XLSX with a DTD; a PDF renamed `.csv`; a huge file | 1. Upload each. | Refused with a clear message; no server error. | P1 | backend: `tutortrack/migration/tests/test_parsing.py::test_xlsx_with_a_dtd_is_refused`; `test_not_a_spreadsheet` | |
| TP-E28-017 | File still being scanned | Owner | `CLAMAV_ENABLED=true` with ClamAV profile | 1. Upload and submit at once. | UI waits ("Uploading and checking the file…") until the scan ends; API returns 409 meanwhile. | P3 | backend: `tutortrack/migration/tests/test_api.py::test_unscanned_files_and_unknown_fields_are_refused` | |
| TP-E28-018 | AC: 5,000 students with 12 invalid rows | Owner | Generated 5,000-row file with 12 bad emails | 1. Import it; time it. | 4,988 imported; error file has 12 rows with reasons; under 2 minutes (≈ 85 s on a 2-CPU dev box). | P1 | backend: `tutortrack/migration/tests/test_imports.py::test_five_thousand_students_with_twelve_invalid_rows` (full size with `PERF_TESTS=1`) | |

## Importers (T02–T04)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E28-019 | Household rows | Owner | `clients-household.csv`: two parents and two students on rows sharing a family email | 1. Import clients and contacts. | One client with both contacts and both students. | P1 | backend: `tutortrack/migration/tests/test_imports.py::test_household_rows_make_one_client_with_contacts_and_students` | |
| TP-E28-020 | Students create households from parent columns | Owner | Student rows with parent name/email, no client id | 1. Import students. | Rows with the same parent email share one household; an adult learner becomes their own client. | P1 | backend: `tutortrack/migration/tests/test_imports.py::test_students_create_households_from_parent_columns` | |
| TP-E28-021 | Duplicate students flagged | Owner | A row duplicating Arjun Patel | 1. Validate. | Warning "duplicate"; row skipped. | P2 | backend: `tutortrack/migration/tests/test_imports.py::test_duplicate_students_are_flagged_and_skipped` | |
| TP-E28-022 | Tutors imported without invitations | Owner | Tutor rows | 1. Import tutors. | Tutors created; no invitation emails in Mailpit. | P1 | No | |
| TP-E28-023 | Services and jobs; upsert by name | Owner | Services file including "GCSE Maths 1:1" with a new rate | 1. Import services, then jobs. | Existing service updated (previous values remembered); new ones created; jobs link to students and services. | P2 | backend: `tutortrack/migration/tests/test_imports.py::test_services_jobs_and_upsert_by_name` | |
| TP-E28-024 | Lessons: history and weekly series | Owner | `lessons-weekly.csv`; cutover date in the middle | 1. Import lessons with the cutover date. | Past lessons created delivered and locked (not invoiced, not on payroll); future weekly lessons become a lesson series (≥ 3 repeats); no booking emails sent. | P1 | backend: `tutortrack/migration/tests/test_imports.py::test_lessons_history_and_weekly_series` | |
| TP-E28-025 | Opening balances | Finance | `opening-balances.csv` (Patel £-40 credit, Okafor £120 debt) | 1. Import.<br>2. Import the same file again. | One ledger adjustment per client (`opening_balance`); second import skips. Client balances reflect it. | P1 | backend: `tutortrack/migration/tests/test_imports.py::test_opening_balances_invoices_payments_and_packages` | |
| TP-E28-026 | Historic invoices | Finance | Invoices file with numbers INV-OLD-001… | 1. Import. | Invoices with original numbers, issued/paid status, one summary line; no ledger entries, no dunning, no `invoice.issued` emails. | P1 | backend: same | |
| TP-E28-027 | Payments after cutover | Finance | Payment rows naming open invoices | 1. Import. | Manual payments allocated to the named invoices; repeated rows skipped. | P2 | backend: same | |
| TP-E28-028 | Package balances | Finance | Package rows (hours left) | 1. Import.<br>2. Roll back one unused and one used package. | Active package purchases with remaining hours; rollback cancels the unused one and keeps the used one. | P2 | backend: same | |
| TP-E28-029 | Tags, notes, enquiries, availability | Owner | Small files for each | 1. Import each. | Tags applied; notes attached; enquiries with source `import` (no acknowledgement email, no SLA workflow); availability windows added. | P2 | backend: `tutortrack/migration/tests/test_imports.py::test_tags_notes_enquiries_and_availability` | |
| TP-E28-030 | Rollback of money reverses, never deletes | Finance | TP-E28-025–027 imported | 1. Roll back each batch. | Invoices voided; adjustments reversed; payments refunded; nothing deleted. | P1 | backend: `tutortrack/migration/tests/test_imports.py::test_opening_balances_invoices_payments_and_packages` | |

## Cutover assistant and connectors (T05–T09)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E28-031 | Start a TutorCruncher migration (fake) | Owner | No TutorCruncher credentials (fake) | 1. Move from another system → TutorCruncher → enter any API key, cutover date → start. | Project created; checklist steps in order: people → services and rates → jobs and future schedule → opening balances → payment methods → invite users → switch reminders on. | P1 | backend: `tutortrack/migration/tests/test_connectors.py::test_tutorcruncher_migration_end_to_end` | |
| TP-E28-032 | Wrong API key | Owner | Real-credential mode, or the fake's invalid key | 1. Enter a wrong key. | Clear "API key rejected" message. | P2 | backend: `tutortrack/migration/tests/test_connectors.py::test_wrong_api_key_is_rejected` | |
| TP-E28-033 | Steps wait for their imports | Owner | TP-E28-031 | 1. On "people", review each pulled batch; try Confirm step before confirming the batches.<br>2. Confirm the batches, then the step. | Step can't be confirmed while imports are open; it can be skipped; after confirming it moves to the next. | P1 | backend: `tutortrack/migration/tests/test_connectors.py::test_steps_wait_for_their_imports`; `tutortrack/migration/tests/test_workflows.py::test_migration_project_steps_wait_for_confirmation` | |
| TP-E28-034 | TutorCruncher mapping | Owner | TP-E28-031 completed | 1. Inspect imported records. | Their services became jobs with rates under "Tuition (TutorCruncher)"; positive TC balance (credit) became a negative opening balance; totals show `not_imported_*` counts for agents, reviews, proformas, ad hoc charges. | P2 | backend: `tutortrack/migration/tests/test_connectors.py::test_tutorcruncher_records_map_to_our_fields` | |
| TP-E28-035 | Reconciliation report | Owner | Migration completed | 1. Open the reconciliation table. | Source vs imported: clients, students, tutors, jobs, invoices, sum of balances, future lessons; differences highlighted. | P1 | backend: `tutortrack/migration/tests/test_connectors.py::test_tutorcruncher_migration_end_to_end` | |
| TP-E28-036 | Invite users step | Owner | Migration with tutors | 1. Run "Invite users". | Invitation emails to the migrated tutors only (Mailpit). | P2 | No | |
| TP-E28-037 | Guidance steps change nothing | Owner | — | 1. Confirm "Payment methods" and "Switch reminders on". | Guidance shown (E11 setup links; Notifications settings); no settings changed. | P3 | No | |
| TP-E28-038 | Teachworks (fake) | Owner | — | 1. Start a Teachworks migration with any key. | Customers, students, employees, services, lessons, invoices, packages pulled; wage tiers set tutor pay; payments before cutover skipped. | P2 | backend: `tutortrack/migration/tests/test_connectors.py::test_teachworks_pulls_customers_services_lessons_and_packages` | |
| TP-E28-039 | TutorBird files | Owner | TutorBird students/families CSV, calendar export and transactions export | 1. Start a TutorBird migration; upload each file with preset "TutorBird export". | Columns and status words auto-mapped (e.g. "Waiting List" → waiting); reconciliation source side comes from the uploaded rows. | P2 | backend: `tutortrack/migration/tests/test_connectors.py::test_tutorbird_files_reconcile_from_their_rows` | |
| TP-E28-040 | TutorCruncher and Teachworks CSV presets | Owner | CSV exports from those systems | 1. Import with presets "TutorCruncher export" / "Teachworks export". | Columns mapped by preset. | P3 | backend: `tutortrack/migration/tests/test_parsing.py::test_automap_uses_synonyms_presets_and_each_field_once` | |
| TP-E28-041 | Google Sheets import (fake) | Owner | Connect Google Sheets (fake OAuth in dev) | 1. Import from → A Google Sheet; paste a Sheets URL. | Rows read through the CSV pipeline; only the spreadsheet id is used (any other host in the URL is ignored). | P2 | backend: `tutortrack/migration/tests/test_connectors.py::test_google_sheet_import` | |
| TP-E28-042 | Migration project expires | Owner | Project untouched | 1. Check the Temporal workflow `migration:<org>:<project>`. | A 60-day expiry timer is pending; cancelling ends it. | P3 | No | |

## Full tenant export (T10)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E28-043 | Owner requests a full export | Owner | — | 1. Export all data → start export.<br>2. Wait; open Mailpit. | `data_export_ready` email links to `/data/export`; the export is listed as ready with an expiry date (7 days). | P1 | backend: `tutortrack/migration/tests/test_api.py::test_owner_exports_and_downloads_with_password`; `tutortrack/migration/tests/test_workflows.py::test_export_is_built_offered_and_expires` | |
| TP-E28-044 | Download needs the password again | Owner | TP-E28-043 | 1. Enter a wrong password; then the right one. | Wrong: refused. Right: a ZIP downloads through a 5-minute link; audit log has a read entry. | P1 | backend: same | |
| TP-E28-045 | ZIP contents | Owner | TP-E28-044 | 1. Open the ZIP. | `csv/<entity>.csv`, `json/<entity>.json`, `relationships.json`, `README.txt`, uploaded files and invoice PDFs; no API keys, webhook or integration secrets; formula-like text neutralised. | P1 | backend: `tutortrack/migration/tests/test_exports.py::test_full_export_has_csv_json_relationships_and_files` | |
| TP-E28-046 | Archive expires | Owner | `migration.export_link_days` = 1 | 1. Wait past expiry. | File deleted; download no longer offered. | P2 | backend: `tutortrack/migration/tests/test_exports.py::test_expiry_deletes_the_archive` | |
| TP-E28-047 | Account closure and platform request start an export | Platform staff | E30 console | 1. `/platform` → Bright Minds → Request data export. | Export for the owners starts; owners get the email. | P2 | backend: `tutortrack/migration/tests/test_exports.py::test_closure_requests_an_export_for_the_owners` | |
| TP-E28-048 | Generic file download refuses export archives | Owner | Export file id | 1. Try the generic `GET /api/v1/files/<id>/download` with the archive id. | Refused. | P2 | No | |

## Permissions

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E28-049 | Admins import but can't export everything | Admin | — | 1. As office@, open `/data`. | Imports and migrations available; Export all data not available (owner-only). | P1 | backend: `tutortrack/migration/tests/test_api.py::test_tutors_cannot_import_and_admins_cannot_export` | |
| TP-E28-050 | Tutors and branch managers can't import | Tutor; Branch Manager | — | 1. Open `/data` as each. | No access ("You can't import any kind of record."); API 403. | P1 | backend: same | |
| TP-E28-051 | Import needs create permission per record type | Coordinator | Coordinator lacks invoice create | 1. Try importing invoices. | Invoices not offered or refused. | P2 | No | |

## Tenant isolation

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E28-052 | Another org's batches and rows are 404 | Owner (Northside) | Bright Minds batch id | 1. `GET /api/v1/imports/<id>` and its rows on Northside's host. | 404. | P1 | backend: `tutortrack/migration/tests/test_api.py::test_rows_of_another_organisations_batch_are_404` | |
| TP-E28-053 | Export contains only this organisation | Owner | TP-E28-045 | 1. Search the ZIP for "Northside". | No matches. | P1 | No | |

## i18n, time zones and currency

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E28-054 | Lesson times in the chosen time zone | Owner | Lessons file with local times; option time zone Europe/London across a DST change | 1. Import. | Lessons keep their local wall-clock times before and after the clock change. | P2 | No | |
| TP-E28-055 | Currency option | Finance | Opening balances in GBP | 1. Import with currency GBP; try EUR. | GBP accepted; a currency other than the org's is refused or clearly flagged. | P3 | No | |

## Errors and edge cases

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E28-056 | Failing chunk is retried | Owner | Temporarily break the DB connection mid-import (staging) | 1. Import a large file. | Chunk retried (up to 5 times); import completes or is marked failed with a report. | P3 | backend: `tutortrack/migration/tests/test_workflows.py::test_a_failing_chunk_is_retried` | |
| TP-E28-057 | Worker restart mid-import | Owner | 5,000-row import | 1. Stop the Temporal worker half-way; restart. | Import continues from the last checkpoint; no duplicate rows. | P2 | No | |
