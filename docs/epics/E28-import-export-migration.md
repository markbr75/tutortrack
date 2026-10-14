# E28 — Data Import, Export & Competitor Migration

| | |
|---|---|
| **Phase** | Agency (Phase 2); CSV import of students basic in MVP |
| **Depends on** | E05–E12 |
| **Parity** | TutorBird spreadsheet import; TutorCruncher full data export (GDPR). **Beyond:** one-click migration from TutorCruncher/TutorBird/Teachworks |

## 1. Summary
Remove switching costs: guided CSV/XLSX imports for every core entity with field mapping, validation and rollback; direct migration connectors from TutorCruncher (API), TutorBird (export files) and Teachworks (API); and complete tenant data export.

## 2. Functional requirements

### FR-28-1 Import framework
- Upload CSV/XLSX → detect headers → **mapping UI** (auto-match by name/synonyms, custom fields, "ignore column", value mapping for enums such as statuses) → validation preview (row-level errors/warnings, duplicates against existing data) → dry-run summary ("will create 120 clients, 180 students, update 4") → execute as a background job → results report (download errors CSV) → **rollback** of the whole batch within 7 days (deletes created records if untouched, reverts updates).
- Templates downloadable per entity; saved mappings reusable.
- Upsert by external ID or email.
- Entities: clients+contacts (household rows), students, tutors, services, jobs, lessons (historic and future, with series detection for regular patterns), invoices (historic, imported as `issued`/`paid` with original numbers, no ledger side-effects beyond opening balances), payments, opening balances (client credit/debt as of cutover date), packages (remaining balances), availability, enquiries, tags, notes.
- Import jobs are tenant-scoped, audited and idempotent per row (`import_batch_id`, `row_number`).
- **AC:** importing a 5,000-row student file with 12 invalid rows completes in < 2 minutes, imports 4,988 rows, and provides an error file with the 12 rows and reasons.

### FR-28-2 Cutover assistant
- Guided migration checklist: choose cutover date → import people → services/rates → active jobs & future schedule → opening balances → payment methods (clients must re-authorise cards unless the source is Stripe on the same account; DD mandates can move via GoCardless bulk change where supported) → invite users → switch reminders on.
- Reconciliation report comparing source totals (clients count, balances sum, future lessons count) with imported data.

### FR-28-3 TutorCruncher connector
- Enter TutorCruncher API key → fetch clients, recipients, contractors, agents, services/jobs, appointments, invoices, proformas, ad hoc charges, balances, labels, custom fields, reviews via their REST API with pagination and rate limits → mapping to our model (`01-competitive-analysis.md` terminology table) → same preview/execute/rollback pipeline.

### FR-28-4 TutorBird connector
- Accept TutorBird export files (students/families CSV, calendar export, invoices/transactions export) with predefined mappings.

### FR-28-5 Teachworks connector
- API key based import of customers, students, employees, services, lessons, invoices, payments, packages and wage tiers.

### FR-28-6 Generic spreadsheet & Google Sheets
- Import from a Google Sheet URL (OAuth read-only) using the CSV pipeline.

### FR-28-7 Data export
- Full tenant export (Owner): ZIP of CSVs per entity + JSON with relationships + documents/files + invoice PDFs; async job, emailed link (expires 7 days, re-auth to download). Also used at account closure (E02) and GDPR portability (E29).
- Per-list exports from grids (E05) honour permissions and are audited.

## 3. Data model
`ImportBatch(entity, source, file, mapping, status, stats, rollback_until)`, `ImportRow(batch, row_number, raw, status, errors, created_object refs)`, `SavedImportMapping`, `MigrationProject(source, credentials enc, steps state, reconciliation)`, `ExportJob`.

## 4. Delivery plan
- [x] **E28-T01** Import framework: upload, header detection, mapping, validation, dry-run, background execute, error report, rollback.
- [x] **E28-T02** Entity importers: clients/contacts/students, tutors, services (MVP: clients/students first).
- [x] **E28-T03** Jobs and lessons import with series detection.
- [x] **E28-T04** Financial imports: opening balances, historic invoices/payments, packages.
- [x] **E28-T05** Cutover assistant and reconciliation report.
- [x] **E28-T06** TutorCruncher API connector.
- [x] **E28-T07** TutorBird file mappings.
- [x] **E28-T08** Teachworks API connector.
- [x] **E28-T09** Google Sheets import.
- [x] **E28-T10** Full tenant export.

## Temporal workflows (E32)

Implement these processes as Temporal workflows following the rules in [E32](E32-workflow-orchestration-temporal.md) (deterministic workflow code, side effects in tenant-scoped activities that call services, tenant-prefixed workflow IDs, signals for human decisions). Where the requirements above mention sweeper tasks, `next_*_at` / `resume_at` columns or retry schedules, the workflow replaces them.

- [x] **E28-TW1** Import, migration and export workflows (requires E32).

| Workflow | Started by | Steps, timers and signals | Replaces |
|---|---|---|---|
| `ImportWorkflow` `import:{org}:{batch}` | User confirms an import after the dry-run | Validate → import rows in checkpointed batches (activities) → report → **7-day rollback window timer**. Signal `rollback` reverts the batch; the timer expiry finalises it | ImportBatch status polling + rollback cutoff job |
| `MigrationProjectWorkflow` | Cutover assistant started | Orchestrates connector pulls (TutorCruncher/TutorBird/Teachworks) step by step with human confirmation signals between steps → reconciliation report | Manual steps |
| `TenantExportWorkflow` | Owner requests a full export / account closure | Export per entity in batches → zip → link email → link expiry timer (7 days) → delete file | Export job + cleanup job |

## Implementation notes (as built 2026-10-10)

**App and model (ADR 0020).** New app `tutortrack.migration` (the `migration/` folder in the
architecture). Every table has RLS. The tables:
- `ImportBatch`: entity, origin, preset, file, mapping, value map, options, status, stats,
  error report, rollback window, project and step.
- `ImportRow`: raw cells, checked values, errors, warnings, the planned action, created
  records and previous values.
- `SavedImportMapping`.
- `ExternalRef(system, target_type, external_id → target_id)`. It holds the source ids,
  so no other app gained an `external_id` column.
- `MigrationProject`: the source, a link to the framework's `IntegrationConnection` (the
  API key is stored encrypted there), the cutover date, step states, source totals and the
  reconciliation report.
- `ExportJob`.

**Pipeline (T01).**
- The browser uploads through the core presigned upload and ClamAV scan. Importing a file
  that is still being scanned returns 409, and the admin UI polls until the scan is done.
- CSV files can use `,`, `;`, tab or `|` and UTF-8, UTF-16 or cp1252. XLSX is read with the
  standard library: shared strings, date styles, and sheets other than the first. Workbooks
  that declare a DTD or entity are refused, and unpacked size and row count are capped.
- A title row above the headers is skipped.
- Columns are matched automatically by field key, label and synonyms, after any preset.
  Each field can be used once, except list fields. Unknown fields are refused, and custom
  fields can be mapped as `cf.<key>`.
- Value maps translate status words, for example TutorBird "Waiting List" → `waiting`.
- Options: what to match existing records on, the date order (the default follows the
  organisation's locale), the cutover date, currency and time zone.
- `submit` → validate and dry-run (`stats.will` counts creates and updates per record type)
  → `confirm` → 250-row chunks → error report CSV (original columns plus the reasons) →
  rollback window (`migration.rollback_days`, default 7) → finalised.
- Rows found to need nothing (duplicates, records already imported) are skipped. Invalid
  rows are reported and left out. Rows that fail while importing are reported the same way.
- Downloadable templates are at `/import-templates/{entity}`; mappings can be saved and reused.
- Imports need `migration.import.manage` plus permission to create each kind of record
  (for example `people.student.create`).

**Importers (T02–T04).** There are 14 importers: clients (household rows with contacts and
an optional student), students, tutors, services, jobs, lessons, invoices, payments, opening
balances, package balances, availability, enquiries, tags and notes.
- **Students** are linked to their client by id, email or name. Otherwise a household is
  made from the parent columns; rows that name the same parent email share one household.
  An adult learner becomes their own individual client.
- **Tutors** are created without an invitation (see the cutover step "invite users").
- **Matching existing records**: by external id, email or name, depending on the entity.
  Updates remember the previous values so a rollback can restore them.
- **Lessons** are a lesson series when the same people, service and time repeat every week
  or fortnight, at least `migration.series_min_lessons` (default 3) times; the series uses
  `create_series(..., notify=False, conflict_mode="create")`. Lessons before the cutover
  date (or already completed or cancelled) are history: `scheduling.import_lesson` creates
  them delivered and locked `paid`, and billing and payroll skip them through
  `is_imported_history`.
- **Invoices** are history with their original numbers (`billing.import_invoice`): one
  summary line, no ledger entry, no `invoice.issued`, no dunning. They publish
  `invoice.imported`.
- **Opening balances** are one ledger adjustment per client, marked
  `ref_type=opening_balance`, so importing the same file twice skips the second time.
- **Payments** are real money after cutover (`record_manual_payment`), allocated to a named
  open invoice. Repeats are skipped.
- **Packages (updated 2026-10-12, with E10-T12):** each package still being used becomes an
  active `PackagePurchase` holding the hours, lessons or credit left (`billing.packages.
  import_package`); its price is the remaining value, so consumption values stay right, and
  there is no invoice or ledger entry (the money was taken in the old system). Optional
  columns: counted in (hours/lessons/credit), package size, student, expiry. Rolling back
  cancels an imported package nobody has used yet; a used one is kept. (Before E10-T12 the
  remaining value became client credit.)
- **Enquiries** use source `import`, so there is no acknowledgement and no SLA workflow.
  The leads bridge now ignores `enquiry.received` with source `import`.
- **Rollback** deletes created records newest first through the owning apps' new
  `discard_*` services, but only while their `updated_at` is not after the import finished;
  otherwise the row is `kept`. Updates are reverted. Money is reversed rather than deleted:
  invoices are voided, adjustments reversed and payments refunded. Series with delivered
  lessons are ended instead of deleted.

**Changes to other apps (all additive).**
- people: `discard_imported`.
- catalogue: `discard_imported_service`.
- jobs: `discard_imported_job`.
- scheduling: `import_lesson`, `discard_imported_lesson/series`,
  `add/remove_availability_window`, `is_imported_history`, a `notify` flag on
  `create_series`, and `notify` in the `lesson.scheduled` and `lesson_series.created` data.
- billing: `import_invoice`, `discard_imported_invoice`, `post_opening_balance`,
  `reverse_import_adjustment`, `selectors.has_opening_balance`, `ledger.post(ref_label=)`,
  the `invoice.imported` event, and charge sync skips imported history.
- payroll: pay sync skips imported history.
- payments: `selectors.similar_payment_exists`.
- crm: `delete_note`.
- leads: `discard_imported_enquiry`, and the bridge skips imported enquiries.
- comms: `lesson_booked` and `series_created` respect `notify`.
- identity roles: `migration.export.full` is owner-only, and Branch Managers are denied
  `migration.*` because imports are organisation-wide.

**Cutover assistant (T05).**
- Steps in order: people → services and rates → jobs and future schedule (jobs, lessons,
  availability) → opening balances (with invoice history, payments and packages) → payment
  methods → invite users → switch reminders on.
- For API sources, each step pulls its records into import batches that validate in the
  background. The user confirms each batch, then confirms the step. A step can't be
  confirmed while its imports are still open, but it can be skipped.
- "Invite users" sends invitations to the tutors the migration created.
- "Payment methods" and "reminders" are guidance steps. Cards must be re-authorised through
  E11 setup links, and imports never send messages, so reminders stay as configured in
  Notifications. Neither step changes settings.
- The reconciliation report compares, between source and imported: clients, students,
  tutors, jobs, invoices, the sum of balances and the number of future lessons. For API
  sources the source side comes from the API; for file sources it comes from the uploaded
  rows.

**Connectors (T06–T09).**
- TutorCruncher (`Authorization: token`, `next` paging, detail calls for people) and
  Teachworks (`Token token=`, page paging) are E22 `credentials` providers at organisation
  level, with `manage_permission=migration.project.manage`.
- TutorCruncher mapping:
  - services become jobs, with rates on the job, under one catalogue service,
    "Tuition (TutorCruncher)";
  - their positive client balance (credit) becomes a negative opening balance;
  - agents, reviews, proformas and ad hoc charges are counted (`not_imported_*` in the
    totals) but not imported, because E25 and E10 Phase 2 don't exist yet.
- Teachworks: wage tiers set the tutor pay rate, and payments before cutover are skipped
  (they are carried by the invoices and balances).
- TutorBird (T07), TutorCruncher and Teachworks CSV exports have presets: column names and
  status words (`mapping.PRESETS`).
- Google Sheets (T09) is a user-level OAuth provider `google_sheets`
  (`spreadsheets.readonly`). Only the spreadsheet id is taken from the pasted link and the
  requests go to Google's fixed host, so there's no SSRF surface.
- Without credentials, fakes serve a sample agency in the providers' own JSON shapes. They
  can be replaced in tests with `connectors.fake.set_dataset`.

**Full export (T10).**
- The ZIP contains `csv/<entity>.csv` and `json/<entity>.json` for 59 tenant models,
  `relationships.json` (columns, the file each `*_id` points to, and generic references),
  `README.txt`, uploaded files (capped at 2 GB) and invoice PDFs (capped at 5,000).
- Secrets aren't exported: integration tokens, API keys and webhook secrets aren't listed,
  and fields with secret-like names are dropped. Encrypted personal data that belongs to
  the tenant (learning needs, tax ids) is exported decrypted.
- Text that looks like a formula is neutralised.
- `organisation.export_requested` (account closure, platform console) starts an export for
  the owners. The owner can also start one from the `/data/export` tab (API `/api/v1/data-exports`).
- The `data_export_ready` email (editable in comms) links to `/data/export`. Downloading
  needs the owner's password again, gives a 5-minute presigned link, and is audited as a
  read. The generic file download refuses export archives.
- Archives expire after `migration.export_link_days` (default 7) and the file is deleted.
- **Boundary with E29:** privacy (E29 part 1) has consent only, so there was nothing to
  reuse. The per-subject access and portability export is left for E29 part 2, which can
  build on `exporter.rows_for`. Per-list grid exports (FR-28-7, second bullet) already exist
  from E05 (`crm.listing.csv_export`).

**Workflows (TW1)**, all on the `imports` task queue:
- `ImportWorkflow` `import:{org}:{batch}`: signals `confirm`, `revalidate`, `cancel` and
  `rollback`; retries failing chunks up to 5 times.
- `MigrationProjectWorkflow` `migration:{org}:{project}`: signals `step_done(step)` and
  `cancel`; expires after 60 days without a decision.
- `TenantExportWorkflow` `tenant-export:{org}:{export}`: signal `cancel`; ends with the
  link-expiry timer.

Windows are measured in real time and waited for on the workflow clock (seconds returned by
activities). Replay histories are in `backend/tests/workflow_histories/`.

**Acceptance criterion.** 5,000 student rows with 12 invalid emails: 4,988 are imported and
the error file has the 12 rows with their reasons. It takes about 85 seconds on a 2-CPU
development box (`test_five_thousand_students_with_twelve_invalid_rows`). The full-size timed run
is opt-in with `PERF_TESTS=1`: on shared CI runners it took 212 seconds, so by default the
test imports 600 rows with the same 12 bad ones and no time limit.

**Admin UI.**
- "Import and export" (`/data`) has three tabs:
  - **Imports**: entity, preset, file or Google Sheet, a template link, and the history.
  - **Move from another system**: the cutover checklist, each step's imports, and the
    reconciliation table.
  - **Export all data** (owner): the export list and a password form for downloading.
- `/data/imports/:id` has the mapping wizard (columns, value mapping, options), a progress
  status (polled, `aria-live`), the dry-run summary, an accessible preview table of rows
  with errors and warnings, confirm or cancel, and the results with the error-report
  download and rollback.

## Gap backlog (as built 2026-10-14)

Batch G6 of `docs/05-gap-backlog.md`; design in ADR 0034.


- **TutorCruncher and Teachworks (FR-28-3/5; E28:186-188):** new importers `affiliates`
  (agents → E25 affiliates with a percentage commission rule and the clients they introduced),
  `reviews` (→ E25 reviews, source `import`; published ones approved, nothing sent),
  `charges` (ad hoc charges dated on or after the cutover → uninvoiced E10 charges; earlier
  ones are in the invoice history and opening balance) and `payment_requests` (unpaid
  proformas → E10 payment requests; paid ones are in the balance). The TutorCruncher connector
  maps them (`UNSUPPORTED` is now empty) and reconciles `affiliates` and `reviews`. Projects
  gain a `growth` step after balances; charges and payment requests join the balances step.
  Teachworks wage tiers become E06 pay tiers: tutors get `pay_tier` (created if new, assigned
  from the cutover) and services get `tier_pay_rates` (`Tier: rate; …`, each tier's wage).
  Rollback voids charges, cancels requests and removes unused affiliates, reviews, tiers and
  assignments.
- **Consent columns (FR-29-3):** client and student imports accept consent columns (marketing
  email/SMS, data processing, photos and video, lesson recording); "yes" grants and "no"
  records a withdrawal as E29 consent records (method `import`, source
  `import:<system>:<batch>`), skipped when the latest record already says the same; rollback
  removes them.
