# ADR 0035: Merge provider registry for clients, contacts and students

- **Status:** Accepted
- **Date:** 2026-10-14
- **Epic:** E05 (FR-05-13), gap batch G1. Builds on ADR 0005 (CRM generic targets) and
  ADR 0028 (the privacy provider registry, whose shape this copies).

## Context
Duplicate *detection* existed since E05-T10; the merge tool did not. A family recorded twice
has records in almost every app: lessons and attendances (E08), invoices, charges and the
ledger (E10), payments and saved cards (E11), reports and makeup credits (E09), messages,
inbox threads and preferences (E13), enquiries (E17), enrolments (E20), homework and goals
(E21), referrals and reviews (E25), consent records (E29), import links (E28) and more. About
70 foreign keys and 20 generic `*_type`/`*_id` references point at the three mergeable
models. The rules that had to hold:
- An app writes only its own tables (CLAUDE.md rule 2): people cannot re-point invoices.
- Financial records are never edited after issue (rule 5); ledger entries and commission
  items refuse `save()` after creation.
- A merge must be all-or-nothing, audited, announced, explicitly confirmed and not reversible,
  and legal holds (E29) must block it.
- Nothing may be left pointing at the merged record, including references added by future
  epics.

## Decision

### 1. A registry, one provider per app (`tutortrack/people/merging.py`)
Each app ships `<app>/merge.py` registering a `MergeProvider` (autodiscovered by
`people.apps.ready` with `autodiscover_modules("merge")`) for the subject types it holds
references to (`people.client`, `people.contact`, `people.student`):
- `count(ctx) -> [Move]`: what would move (the preview's "what moves" list);
- `merge(ctx) -> [Move]`: re-point the app's own rows from `ctx.source` to `ctx.target`;
- `check(ctx) -> [problem]`: reasons the merge can't go ahead (both students booked on the
  same lesson, both families referred, both enrolled in the same class...);
- `notes(ctx) -> [warning]`: things to know before merging (saved cards that can't move,
  the accounting contact that won't be merged);
- `history`: FK fields deliberately left on the merged record (immutable history);
- `generic`: the generic references the app owns (`GenericRef(model, type field, id field,
  {subject type: (type values...)})`).

Helpers (`repoint`, `repoint_unique`, `clashes`, `repoint_generic`) keep providers short.
Providers: people, jobs, scheduling, delivery, billing, payments, catalogue, payroll,
leads, matching, comms, courses, growth, learning, crm, privacy, identity, calendar_sync,
automations, ai, migration, accounting and reporting.

### 2. The duplicate becomes a tombstone
The merged record is not deleted (hard delete is reserved for GDPR erasure, FR-05-14). It is
archived with `merged_into` (self FK) and `merged_at`; lists hide it and its page links to
the survivor. Earlier tombstones are re-pointed to the new survivor. Privacy expansion
includes tombstones, so a DSAR or erasure of the survivor covers them.

### 3. One transaction with a safety net
`people.services.merge_records` locks both rows (in a stable order), re-checks the problems,
applies the chosen surviving values through the normal update services (audited, events),
runs every provider, then asks `merging.references()` whether anything still points at the
merged record: every FK found through Django model meta (minus declared `history`) plus
every declared generic reference. Anything left raises and rolls the whole merge back.
It then archives the tombstone, writes an audit entry on the survivor with both ids, the
resolved field choices and the move counts, and publishes `client.merged` /
`contact.merged` / `student.merged`. `confirm: true` is required; there is no unmerge.

### 4. Money keeps its history
Invoices, credit notes, charges, payments, packages and plans are re-pointed with their
amounts untouched. Ledger entries never change, so they stay on the tombstone, and billing
moves the balance with a pair of `adjustment` entries per currency (one clears the
tombstone, one adds to the survivor, each naming the other). Commission items stay on the
tombstone. Saved card/mandate methods can't move between provider customers, so when both
clients are customers of the same provider account the duplicate's are retired and staff
are told. Accounting-system contacts are never merged from TutorTrack: a staff note on the
survivor says which contact to merge in the ledger by hand.

### 5. Scope rules
Contacts and students merge only within one family ("merge the families first"); a client
merge moves the duplicate's contacts and students to the survivor. Legal holds on either
record (or, for families, on anyone in them) block a merge. Only owners and admins hold
`people.merge` by default (coordinators and branch managers are denied it).

### 6. Tests guard the registry
`people/tests/test_merge.py` checks that every FK to the three models (via model meta)
belongs to an app with a provider, that every `*_type`/`*_id` pair in the codebase is
either declared by a provider or explicitly exempted with a reason, and (Hypothesis) that
whatever is linked to either record, a merge leaves no dangling reference.

## Consequences
- A new app that references people must add a `merge.py` (the registry tests fail until it
  does) and say what happens on a clash.
- Moving rows by queryset `update()` bypasses model `save()`; providers only do that on
  their own models, and never on immutable ones.
- The tombstone keeps the duplicate's personal data until the survivor is erased; erasure
  covers it.
- Reports built from facts are re-pointed, so figures for the merged family are counted once.
