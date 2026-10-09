# ADR 0005: CRM items attach to records through a target registry

- **Status:** Accepted
- **Date:** 2026-10-09
- **Epic:** E05

## Context
Notes, tasks, tags, documents and the activity timeline must attach to clients, contacts,
students and tutors now. Later they must also attach to jobs, lessons, invoices and leads.
The spec says "generic relations". Django's `GenericForeignKey` couples CRM rows to
`ContentType` ids, which differ between databases, so they are awkward in exports, events
and RLS-checked raw SQL. It also gives no way to check whether the viewer may see the
record a note is attached to.

## Decision
1. CRM rows store `target_type` (a stable label such as `people.client`) and `target_id`
   (string primary key).
2. Owning apps register each target in `crm.targets.register(type, model, view_permission)`
   from `AppConfig.ready()`.
3. Every CRM read and write calls `targets.can_see` / `visible_ids`. These apply the
   record's own view permission and data scope (`scope_queryset`). A CRM item is never
   more visible than the record it is attached to.
4. Bulk actions and tag application use the same check, so only records the user can see
   are touched.

## Consequences
- New record types (E07 jobs, E08 lessons, E10 invoices) get notes, tasks, documents and
  timeline entries by registering a target. No CRM migration is needed.
- There is no database-level foreign key from a note to its record. Deleting records is
  already forbidden for financial data, and archived people keep their CRM history.
- Timeline queries filter on `(target_type, target_id)`, which is indexed on each CRM
  table.
