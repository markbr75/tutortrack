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
- [ ] **E05-T01** Client, Contact and Student models, services and API; quick-add endpoint.
- [ ] **E05-T02** TutorProfile, TutorSubject and qualifications; link to membership and invitations.
- [ ] **E05-T03** Address model and async geocoding provider abstraction.
- [ ] **E05-T04** Custom field definitions and validation; integration into serializers and filters.
- [ ] **E05-T05** Tags, notes (visibility, mentions), tasks, documents (generic relations).
- [ ] **E05-T06** Activity timeline aggregator selector.
- [ ] **E05-T07** List filtering (incl. custom fields and computed fields), saved views, exports.
- [ ] **E05-T08** Global search (FTS + trigram).
- [ ] **E05-T09** Bulk actions framework (background job + progress).
- [ ] **E05-T10** Duplicate detection and merge.
- [ ] **E05-T11** Frontend: list grids, record pages, quick-add family, tutor profile pages.
- [ ] **E05-T12** (Phase 2) Map view.
