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
- [ ] **E28-T01** Import framework: upload, header detection, mapping, validation, dry-run, background execute, error report, rollback.
- [ ] **E28-T02** Entity importers: clients/contacts/students, tutors, services (MVP: clients/students first).
- [ ] **E28-T03** Jobs and lessons import with series detection.
- [ ] **E28-T04** Financial imports: opening balances, historic invoices/payments, packages.
- [ ] **E28-T05** Cutover assistant and reconciliation report.
- [ ] **E28-T06** TutorCruncher API connector.
- [ ] **E28-T07** TutorBird file mappings.
- [ ] **E28-T08** Teachworks API connector.
- [ ] **E28-T09** Google Sheets import.
- [ ] **E28-T10** Full tenant export.
