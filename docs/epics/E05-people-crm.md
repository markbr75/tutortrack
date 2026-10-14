# E05 — People & CRM Core

| | |
|---|---|
| **Phase** | MVP |
| **Depends on** | E01–E03 |
| **Parity** | TutorCruncher clients/recipients/contractors, custom fields, labels, notes, tasks; TutorBird families, student statuses, attachments, import |

## 1. Summary
The records for Clients (billing accounts/households), Contacts (parents/guardians/payers), Students and Tutors, plus the generic CRM capabilities shared by every record: custom fields, tags, notes, tasks, documents, activity timeline, search, saved views, bulk actions and duplicate detection.

## 2. Functional requirements

### FR-05-1 Client (billing account)
- Fields: type (`household | individual | organisation`), display name (auto from primary contact surname, e.g. "The Patel Family", editable), branch, status (`prospect | active | dormant | archived`), primary contact, billing contact (may differ), billing address, currency (defaults from branch), payment terms (days), invoice delivery (email/portal/post), invoice grouping (one per client / per student / per job), preferred payment method, auto-pay enabled, credit limit, prevent negative balance (override org default), tax exempt + tax id, referral source, affiliate (E25), assigned account manager (staff membership), tags, custom fields, notes.
- Computed (selectors): balance, available credit, overdue amount, lifetime revenue, active students count, next lesson, last lesson.
- Organisation clients (schools, local authorities) can have a **PO number** per job/invoice and multiple finance contacts.
- **AC:** creating a household Client with "Add student" inline creates Client + primary Contact + Student(s) in one transaction (one-screen quick-add for sole traders).

### FR-05-2 Contact
- Fields: client, first/last name, relationship to students (parent, guardian, carer, self, finance contact, other), email(s), phone(s) with type, preferred contact method, address (inherit client address toggle), is_primary, is_bill_payer, receives (lesson reminders / invoices / reports / marketing: per-contact toggles), portal access (linked User), emergency contact flag, language preference.
- A contact can belong to only one client in v1 (separated-parent scenarios are handled by two contacts on one client, each with its own notification preferences, and optional **split billing**, see E10 FR-10-12).

### FR-05-3 Student
- Fields: client, first/last/preferred name, DOB (sensitive), year/grade, school, status (`lead | trial | active | waiting | paused | finished | archived`), subjects of interest (subject+level), goals, learning needs / SEN / medical notes (sensitive, encrypted), exam board(s), target grades, availability preferences, location for in-person lessons (address with geocode), preferred tutor(s), excluded tutors, photo consent, portal login (optional; username-based for minors), tags, custom fields.
- Adult learners: a Client of type `individual` where the primary contact **is** the student (`Contact.relationship = self` linked to the Student).
- Status changes are timestamped; `waiting` feeds the waitlist (E17/E20).

### FR-05-4 Tutor profile
- Linked to Membership (role Tutor). Fields: display name, photo, bio (public and private), headline, subjects/levels taught with proficiency and **approved** flag, qualifications (degree, teaching cert, with documents), languages, years of experience, employment type (`self_employed | employee | other`), pay tier (E06), default pay rate override, address + geocode + travel radius, delivery modes (online/in-person), max weekly hours, min lesson length, branches, status (`applicant | onboarding | active | restricted | inactive | archived`), compliance status (E18 computed), rating (E25 computed), public profile toggle (E24), tax info (UTR/SSN-last4/ABN, encrypted), bank/payout details (E12, encrypted, never shown in full), emergency contact, DOB (sensitive), tags, custom fields.
- Computed: active students, hours this month, utilisation (booked vs available), avg rating, report SLA compliance.

### FR-05-5 Custom fields
- `CustomFieldDefinition(entity_type, key, label, type, required, options, help_text, visibility: staff|tutor|client_portal|public, editable_by: staff|tutor|client, group, order, branch_scope, validation regex, active)`.
- Types: text, long text, number, decimal, currency, date, datetime, boolean, single select, multi select, email, phone, URL, file, user reference (staff), address.
- Rendered in record forms, portal forms (if visible/editable there), public forms (E17/E18/E24), list column chooser, filters, exports, the API, and automation conditions.
- **AC:** a required custom field added later does not block saving existing records until the field itself is edited (soft-required on legacy data, with a "missing required data" filter).

### FR-05-6 Tags (labels)
- Org-defined tags with colour, applicable to configurable entity types. Bulk add/remove. Filters and automations use tags.

### FR-05-7 Notes
- Generic notes attachable to any record: rich text (sanitised), pinned, visibility (`staff_only | staff_and_tutors | shared_with_client`), mentions (@staff, which notify via E13), attachments.
- **Safeguarding notes** are a separate, permission-restricted note type with encryption and a separate audit (E29).

### FR-05-8 Tasks
- Fields: title, description, due date/time, assignee (staff/tutor), priority, status (`open | done | cancelled`), related record, recurring option, reminder.
- "My tasks" view, overdue badge, task created from automations (E14).

### FR-05-9 Documents
- Upload to any record (via E01 storage), with category (contract, consent form, report, ID, other), visibility, expiry date (used by E18 compliance), e-signature status (Phase 2: integrate DocuSign/Dropbox Sign, or built-in simple click-to-sign with audit).

### FR-05-10 Activity timeline
- Unified feed per record: notes, emails/SMS sent and received (E13), lessons, invoices, payments, status changes, tasks, audit highlights. Filter by type.

### FR-05-11 Lists, search and saved views
- Data grids for Clients, Contacts, Students and Tutors with server-side filtering (any field incl. custom fields, tags, computed balance, status, branch, tutor, subject, last lesson date), sorting, column chooser, saved views (private/shared), and CSV/XLSX export (permissioned, audited).
- Global search (⌘K) across people, jobs and invoices using PG full-text + trigram on names, emails, phones and references; results respect permissions.
- **Map view** of students and tutors (geocoded) for agencies doing in-person matching (Mapbox/Google Maps; Phase 2).

### FR-05-12 Bulk actions
- Select many → tag, change status, assign account manager, send message (E13), export, archive, invite to portal.
- Bulk ops run as background jobs with progress and a result report.

### FR-05-13 Duplicate detection and merge
- On create: warn on matching email/phone/name+DOB.
- Merge tool for Clients, Contacts and Students (choose surviving values; re-points lessons, invoices, notes etc.; audited; not reversible — require confirmation).

### FR-05-14 Archive and restore
- Archive hides from default lists and blocks new lessons; restore available. Hard delete only via GDPR erasure (E29).

### FR-05-15 Geocoding
- Addresses are geocoded asynchronously (Google/Mapbox, provider abstraction), storing lat/lng for matching (E19) and travel calculations (E12).

## 3. Data model
`Client`, `Contact`, `Student`, `TutorProfile`, `TutorSubject(tutor, subject, level, approved, approved_by)`, `TutorQualification`, `Address(line1, line2, city, region, postcode, country, lat, lng, geocoded_at)` (embedded via FK or JSONB), `CustomFieldDefinition`, `Tag`, `TaggedItem(generic)`, `Note(generic, type, visibility)`, `Task(generic)`, `Document(generic → StoredFile)`, `SavedView(entity, owner, shared, filters JSONB, columns)`.

## 4. API
CRUD: `/api/v1/clients`, `/clients/{id}/contacts`, `/students`, `/tutors`, `/contacts`; `/custom-fields`, `/tags`, `/notes`, `/tasks`, `/documents`, `/saved-views`, `/search?q=`, `/clients/{id}/timeline`, `/merge/{entity}`, `/bulk/{entity}/{action}`; `/clients/quick-add`.

## 5. Events
`client.created/updated/archived/merged`, `contact.created/updated`, `student.created/updated/status_changed`, `tutor.created/updated/status_changed`, `note.created`, `task.created/assigned/completed/overdue`, `document.uploaded/expiring`.

## 6. Permissions
`people.client.{view,create,edit,archive,merge,export}`, `people.student.*`, `people.student.view_sensitive`, `people.tutor.*`, `people.tutor.view_financial`, `crm.note.*`, `crm.note.safeguarding`, `crm.task.*`, `crm.customfield.manage`, `crm.tag.manage`.
Tutor scope `own`: students on the tutor's active jobs only; client contact fields per the E03 FR-03-6 toggles.

## 7. UX notes
- Record page layout: header (name, status, key stats, quick actions) + tabs: Overview, Students/Contacts, Jobs, Lessons, Billing, Reports, Messages, Notes & Tasks, Documents, History.
- Sole-trader mode shows a merged "Family" page (client + students together).

## 8. Delivery plan
- [x] **E05-T01** Client, Contact and Student models, services and API; quick-add endpoint.
- [x] **E05-T02** TutorProfile, TutorSubject and qualifications; link to membership and invitations.
- [x] **E05-T03** Address model and async geocoding provider abstraction.
- [x] **E05-T04** Custom field definitions and validation; integration into serializers and filters.
- [x] **E05-T05** Tags, notes (visibility, mentions), tasks, documents (generic relations).
- [x] **E05-T06** Activity timeline aggregator selector.
- [x] **E05-T07** List filtering (incl. custom fields and computed fields), saved views, exports.
- [x] **E05-T08** Global search (FTS + trigram).
- [x] **E05-T09** Bulk actions framework (background job + progress).
- [x] **E05-T10** Duplicate detection and merge. *(Detection done 2026-10-09; the merge tool was built in gap batch G1 on 2026-10-14, see "Gap backlog" notes.)*
- [x] **E05-T11** Frontend: list grids, record pages, quick-add family, tutor profile pages.
- [x] **E05-T12** (Phase 2) Map view.

## Implementation notes (as built 2026-10-09)
- **Apps.** `people` holds clients, contacts, students, tutor profiles, subjects, qualifications and addresses; `crm` holds the generic capabilities (custom fields, tags, notes, tasks, documents, saved views, bulk jobs). Every table is a `TenantModel` with RLS.
- **Generic targets.** CRM items reference records by `target_type` (`people.client`, `people.contact`, `people.student`, `people.tutor`) + `target_id`, not Django generic FKs. Apps register targets in `crm.targets` with the record's view permission, and every CRM read and write checks that the viewer can see the target through `scope_queryset`. A note on a record you cannot see is a 404. See ADR 0005.
- **Subjects are free text** (`{subject, level}`) until E06 introduces the subject catalogue. E06 migrates them.
- **Computed list fields** (balance, next lesson, last lesson, hours this term) are placeholders in `people.selectors.client_summary` until E08/E10 provide the data. Custom-field filters (`cf_<key>`), tags, `missing_required` and `include_archived` work now.
- **Tutor `own` scope.** Tutors see their own profile and tasks. Students and clients on "my active jobs" arrive with E07 (`NoOwnScopeMixin` returns nothing until then).
- **Notes.** HTML is sanitised server-side with `nh3` (allow-list of simple formatting, links limited to http/https/mailto). Mentions are `<span data-mention="<user id>">` and only active members are kept. Without `crm.note.view_staff_only`, staff-only notes and documents are hidden, and a new note asking for staff-only is downgraded to staff-and-tutors. Safeguarding notes (`crm.note.safeguarding`) wait for E29 Part 2.
- **Validation errors** from custom fields are 400 problem responses with per-key messages under `errors.custom_fields`.
- **Bulk actions.** `POST /bulk/{entity}/{action}` creates a `BulkJob` covering only the IDs the user can see, then runs it in Celery. Each record goes through the normal service, so it is audited and emits events. Failures are recorded per record in `errors`. Actions: tag/untag (all), archive, set_status and assign_manager (clients), set_status and archive (students), set_status (tutors).
- **Search** uses `pg_trgm` similarity (GIN trigram indexes) across clients, contacts, students and tutors, scoped by permission. Full-text ranking can be added when notes become searchable.
- **OpenAPI.** Field-permission-gated fields (contact phone/email, tutor pay rate, etc.) are now documented in the schema. They are still removed per viewer at runtime.
- **Exports** are CSV (formula-injection safe, audited, mass-export alerting). XLSX is deferred.
- **Not built:** merge tool (Phase 2), map view (T12, Phase 2), sole-trader merged family page variant (the family page already shows client and students together).
- **Frontend:** client/student/tutor lists with search and status filters, family page, student and tutor pages (status change, subject approval), quick-add family, notes/tasks/timeline tabs on each record, "My tasks", and ⌘K global search.

## Phase 2b implementation notes (as built 2026-10-14)
- **T12 map view (FR-05-11).** `GET /api/v1/people/map?kind=all|student|tutor&status&branch&subject` returns geocoded students (their lesson address, else the family's billing address) and tutors (their address) that the viewer may see (`scope_queryset` on `people.student.view` / `people.tutor.view`; tutors see themselves and the students on their jobs). Points are rounded to 3 decimal places (about 100 m) and carry the postcode district (`core.geo.area_of`, moved from matching), never a street address. People without coordinates are counted, and `POST /people/map/geocode` queues the E05-T03 Celery geocoding task for the addresses the user may edit.
- **Geocoding providers.** `core.geo` gains `FakeGeocoder` (stable made-up points around London from a hash of the address: no network; the local default in `.env.example`) and `MapboxGeocoder` (`MAPBOX_ACCESS_TOKEN`) next to Google. Real providers are only reached through `core.net.safe_urlopen`. Keys come from the environment; none are committed. Coordinates stay on `people.Address.lat/lng` (E05-T03).
- **Frontend (deviation).** The admin app has no map library (matching uses a schematic plot), so `/people/map` is an accessible SVG "map": an equirectangular projection of the rounded points with keyboard-focusable markers (students as circles, tutors as squares, so colour is not the only cue), optional travel-radius rings, and a list view (a table sorted by area) carrying the same information (WCAG 1.1.1/1.3.1/2.1.1). Tiles (Mapbox/Google) can sit behind the same API later without backend changes.
- **Not built:** the merge tool (T10 remainder) stays a later phase.

## Gap backlog (as built 2026-10-14)
Gap batch G1 (`docs/05-gap-backlog.md`): the FRs deferred inside the ticked tickets.
- **Merge tool (FR-05-13; ADR 0035).** `GET /api/v1/merge/{clients|contacts|students}/preview?source=&target=` shows both records' values side by side (with the default choice: the survivor's value, or the duplicate's where the survivor's is empty; values behind a field permission are hidden and can't be chosen), what moves (per app, with counts), problems that block the merge and warnings. `POST /api/v1/merge/{entity}` with `{source, target, choices: {field: "source"|"target"}, confirm: true}` merges in one transaction. Every app re-points its own rows through its own `<app>/merge.py` provider (registry in `people/merging.py`, autodiscovered): people (contacts/students move to the surviving family, primary/billing contact, adult-learner link, portal login, preferred/excluded tutors, earlier tombstones, workflow links), jobs, scheduling (attendances, booking holds, iCal feeds), delivery (makeup credits, feedback, client cancellation policies), billing, payments, catalogue (discounts, promo uses, price lists), payroll (expenses), leads (enquiries incl. the students M2M, waitlist, proposals), matching (shared shortlists), comms (messages, threads/participants/authors, preferences, broadcast recipients), courses, growth, learning, crm (notes, tasks, documents, tags; a tag on both is kept once), privacy (consent records, data subject requests, safeguarding concerns), identity (portal invitations), calendar_sync, automations (runs; a clashing run key is suffixed), ai, migration (external refs, import rows), accounting and reporting (facts). After the providers, the engine checks every FK to the model (via model meta) and every declared generic reference; anything left rolls the merge back.
- **Deviation: the duplicate is kept as a tombstone**, not deleted (hard delete stays GDPR-only, FR-05-14): archived, `merged_into` → the survivor, `merged_at` (migration `people/0005`). Lists hide it; its page says it was merged and links to the survivor. Privacy expansion includes tombstones, so erasure/DSAR of the survivor covers them.
- **Money.** Invoices, credit notes, charges, payment requests, packages, plans, collections cases, split shares and payments are re-pointed with amounts untouched. Ledger entries and commission items are immutable, so they stay on the tombstone as history; billing moves the balance with a pair of `adjustment` ledger entries per currency ("Balance moved to/from …"). When both clients are customers of the same payment provider account the duplicate's saved methods are retired (they can't be charged under another customer) and staff are told; otherwise methods, consents and setup links move. Accounting-system contacts are **not** merged: the duplicate's contact link is left as it is and a staff note on the survivor says which ledger contact to merge by hand.
- **Rules.** Contacts and students merge only within one family (merge the families first). Blocked by: a legal hold on either record (or anyone in either family), both students on the same lesson, live places in the same class or the same makeup session, makeup credit/feedback clashes, homework/assessment/progress-report clashes, both families referred (or one referred the other), both attributed to an affiliate or a tutor referral, both mid-way through a provider migration. Other unique clashes keep the survivor's row (tags, price lists, job links, topic mastery, preferences, thread places, broadcast rows). Audit: a `merge` entry on the survivor with both ids, the name, the resolved choices and the move counts, plus a `merged_into` entry on the tombstone; events `client.merged` / `contact.merged` / `student.merged` (subject = survivor, `merged_id`, `moved`). Permission **`people.merge`** replaces the unused `people.client.merge`/`people.student.merge` codenames; owners and admins hold it, coordinators and branch managers are denied it.
- **Duplicates list.** `GET /api/v1/people/duplicates/pairs?type=client|contact|student` (permission `people.merge`, scoped by view permissions): contacts with the same email or phone (last 9 digits), families sharing a contact email/phone or a name, students with the same name (and the same date of birth when both have one). The older record is suggested as the one to keep. Admin: `/people/duplicates` (tabs per kind, "Review and merge"), `/people/merge/{entity}/{source}[/{target}]` (target picker, side-by-side radio choices, what moves, problems and warnings, swap, an "I understand that merging can't be undone" checkbox), "Merge with another record" on family and student pages, and "Merge the two selected" in the list bulk bar.
- **Exports (FR-05-11).** Client, contact, student and tutor exports take `?file_format=csv|xlsx` and `?ids=a,b,c` (selected rows). XLSX reuses `reporting.exports.xlsx_bytes` (SpreadsheetML, no new dependency; numbers are number cells, formula-like text is neutralised). Exports are audited with the format and count towards mass-export alerts. Contact exports leave out email/phone without the contact field permissions.
- **Computed list fields (FR-05-1/4/11).** `people.selectors.with_client_figures/with_student_figures/with_tutor_figures` annotate with subqueries, each only when the viewer may see that area: client `balance` (ledger balance in the client's currency; `billing.invoice.view`), `next_lesson_at`, `last_lesson_at`, `hours_this_term` (booked or delivered lesson hours in the E20 term running today; absent when there's no current term) (`scheduling.lesson.view`); students the same lesson figures; tutors `hours_this_month` (org timezone) and `report_sla` (% of reports due in the last 90 days submitted on time; `delivery.report.view`). Filters: `balance_min/max`, `next_lesson_before`, `last_lesson_before/after`, `has_upcoming_lesson`, `hours_this_term_min`, `hours_this_month_min`, `report_sla_below` (ignored without the permission). `?ordering=` accepts the computed fields; next/last lesson and SLA sort on never-null keys so cursor pagination works. `client_summary` now returns real figures. **Deviation:** tutor `utilisation` (booked minutes this month ÷ weekly availability, reusing the E26 availability calculation) is computed per page, so it is shown but can't be sorted or filtered on.
- **Timeline (FR-05-10).** Scheduling, billing and payments register timeline providers (`lesson`, `invoice`, `payment`) like comms does for messages. A client's (and a contact's) timeline shows the family's lessons, issued invoices and payments; a student's their lessons; a tutor's the lessons they teach. Each provider checks its own view permission and data scope.
- **Search (FR-05-11).** ⌘K search also finds jobs (reference, name; `jobs.job.view`, own scope for tutors) and invoices (number, PO number; `billing.invoice.view`). The palette opens `/jobs/{id}` and `/invoices/{id}`.
- **Bulk actions (FR-05-12).** New actions `send_message` (clients, contacts, students, tutors; needs `comms.broadcast.send`) and `invite_portal` (clients' main contact, contacts; `people.{entity}.edit`). `send_message` params (`channel` email|sms, `purpose` service|marketing, `subject`, `body`, with `{{ recipient.first_name }}`) are validated when the job starts; each record's person (a contact or tutor themselves; a family's primary, else billing contact) gets the message through `comms.direct` with the broadcast rules: suppressions, marketing consent (E29, or the "receives marketing" flag without a consent type) and the marketing preference. Skips are reported per record. **Deviation:** "export" is not a background job: the bulk bar links to the export endpoint with `?ids=` (CSV or Excel). Admin lists gained row selection, a bulk bar with progress and the per-record report, sort and computed-field filters.
- **@mentions (FR-05-7).** A `crm` handler on `note.created` sends the `note_mention` notification (E13 registry; in-app by default, email optional; staff category) to each mentioned member who may read the note (note permission, staff-only visibility, the record's own scope). The author isn't notified; redelivered events don't notify twice.
- **Not built:** merging tutors (not in FR-05-13); merging contacts or students across families (merge the families first).
