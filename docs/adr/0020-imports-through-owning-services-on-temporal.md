# ADR 0020: Imports through the owning apps' services, checkpointed on Temporal

- **Status:** Accepted
- **Date:** 2026-10-11
- **Epic:** E28 (builds on ADR 0002, ADR 0015)

## Context
Tenants switching from TutorCruncher, TutorBird, Teachworks or spreadsheets bring thousands of
records. Imports must:
- respect the same validation, audit, events, tenancy and plan limits as records made by hand;
- show a preview and a dry run before anything is written;
- survive worker restarts half-way through a 5,000-row file;
- be undoable for a week.

History also needs care: past lessons and invoices must not create charges, pay or ledger
entries a second time, and nobody should get "lesson booked" emails for a migration.

## Decision
1. **A `migration` app; every row goes through the owning app's services.** One `Importer`
   per entity (`importers/`) declares its fields (with synonyms, used for automatic column
   matching), a `check` (validation plus dry-run plan) and an `apply` that calls the services
   of people, catalogue, jobs, scheduling, billing, payments, leads and crm. The migration app
   never writes another app's tables.
   - Where a service was missing, a small one was added to the owning app:
     - deleting rows an import created: `people.discard_imported`, `discard_imported_service`,
       `discard_imported_job`, `discard_imported_lesson/series`, `discard_imported_enquiry`
       and `crm.delete_note`;
     - imported history: `billing.import_invoice` and `scheduling.import_lesson`;
     - balances: `billing.post_opening_balance` and `reverse_import_adjustment`;
     - availability windows: `scheduling.add_availability_window` and
       `remove_availability_window`;
     - `payments.selectors.similar_payment_exists`.
2. **Rows are the unit of idempotency.** `ImportRow(batch, row_number)` stores the raw cells,
   the checked values, errors, warnings, the planned action and, after applying, every record
   it created (`created_refs`) and the previous values of what it updated (`previous`). Each
   row is applied in its own savepoint together with its status change, so a retried chunk
   skips finished rows. External ids live in `ExternalRef(system, target_type, external_id)`,
   not on other apps' models. Spreadsheets share the `file` namespace; API pulls use the source
   name.
3. **History is settled, not replayed.**
   - Past lessons are imported as delivered and locked `paid`. Billing and payroll ignore them
     through `scheduling.is_imported_history`.
   - Historic invoices keep their original numbers but post no ledger entry.
   - The money position comes over as one opening balance per client, at the cutover date.
   - Payments after the cutover are real and go through `record_manual_payment`.
   - Imports publish events with `notify: false` (lessons and series), source `import`
     (enquiries) or `invoice.imported`, so comms, dunning and lead follow-ups stay quiet.
4. **Temporal runs the process (E28-TW1).**
   - `ImportWorkflow` validates, waits for a `confirm` signal (or `revalidate` or `cancel`),
     imports 250-row chunks as activities, writes the error report and then holds a
     rollback-window timer. The `rollback` signal undoes rows newest first; when the timer
     expires the batch is finalised.
   - `MigrationProjectWorkflow` runs the cutover steps. Each step waits for a `step_done`
     signal, and the workflow ends with a reconciliation report.
   - `TenantExportWorkflow` exports entity by entity, zips, emails the link and deletes the
     file when the link expires.
   - Windows are measured in real time but waited for on the workflow clock, as a number of
     seconds returned by the activity.
5. **Rollback deletes only untouched records and reverses money.** A record is "untouched"
   when its `updated_at` is not later than the batch's completion. Records that were changed
   or are referenced (PROTECT) are kept, and the row is reported as `kept`. Imported invoices
   are voided, ledger adjustments reversed and payments refunded. Financial records are never
   deleted.
6. **Connectors are framework providers.** TutorCruncher and Teachworks are organisation-level
   `credentials` providers with a `migration` client kind. Google Sheets is a user-level OAuth
   provider (`spreadsheets.readonly`) with a `sheets` client. Fakes speak the providers' JSON
   shapes, so the real mapping code is tested. Pulled records become ordinary import batches.

## Consequences
- An import behaves exactly like manual entry: audit trail, domain events, plan limits,
  custom-field validation. The trade-off is speed: about 60 rows a second, so 5,000 students
  take around 80–90 seconds on the CI box, within the 2-minute acceptance criterion.
- Other apps gained a few small, documented services. Merges touch people, catalogue, jobs,
  scheduling, billing, payments, payroll, leads, crm and comms, but only additively.
- Package purchases (E10-T12) don't exist yet, so remaining package value becomes client
  credit. A later importer can create real packages instead.
- The full export reads tenant tables generically and leaves out secrets. E29's subject
  access export can reuse `exporter.rows_for`.
