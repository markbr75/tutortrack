# 03 — Domain Model & Glossary

This is the shared vocabulary for all epics. Epics may add fields, but **must not rename or redefine** these concepts without an ADR.

## 1. Glossary

| Term | Definition |
|---|---|
| **Organisation** | The tenant: a tutoring business subscribed to TutorTrack. Owns all data. |
| **Branch** | A sub-unit of an Organisation (location, brand or region). Every org has at least one (default) Branch. Can have its own currency, timezone, branding, payment accounts and staff. |
| **User** | A global login identity (email + auth). One User may have Memberships in several Organisations (e.g. a tutor working for two agencies). |
| **Membership** | Link between a User and an Organisation, with Roles and branch scope. |
| **Client** | The **billing account**: a household/family, an individual adult learner, or an organisation (school, local authority). Has a ledger and balance. |
| **Contact** | A person attached to a Client (parent, guardian, finance contact). May have a portal login. One Contact is the primary bill payer. |
| **Student** | A learner who receives lessons. Belongs to exactly one Client (an adult learner's Client is themselves). May have a portal login. |
| **Tutor** | A person who delivers lessons (employed or self-employed contractor). Has a profile, skills, availability, pay settings and compliance records. Linked to a Membership. |
| **Staff** | Non-tutoring Membership (admin, coordinator, finance). A person can be both staff and tutor. |
| **Subject / Level** | Taxonomy of what is taught (e.g. Maths → GCSE Higher). Org-customisable, seeded from defaults. |
| **Service** | A catalogue item that defines a type of tuition: subject/level (optional), delivery mode (in-person/online/hybrid), format (1:1 or group), default duration, default charge rate and default pay rate. |
| **Rate Card / Price List** | Rules that produce the **charge rate** (what the client pays) and **pay rate** (what the tutor earns) for a lesson. Supports overrides by job, student, tutor pay tier, time-of-day premiums, location and travel. |
| **Pay Tier** | A tutor grade (e.g. Junior/Senior/Expert) that changes pay rate (and optionally charge rate) for the same Service. |
| **Job** | An **ongoing engagement** between a Client (one or more Students) and one or more Tutors for a Service, with agreed rates, billing method and schedule. The container for Lessons. (TutorCruncher calls this a "Service/Job"; TutorBird has no explicit equivalent.) |
| **Lesson** | A single scheduled session (appointment) with a start, end, timezone, location or online link, tutors and attendees. Can belong to a Job, a Class (E20) or be standalone. |
| **Lesson Series** | Recurrence definition (RRULE) that generates Lessons. |
| **Event (calendar)** | A non-lesson calendar block (meeting, training, blocked time). |
| **Attendance** | Per-student outcome of a lesson: present, absent (notified), absent (no-show), late, cancelled-by-client, cancelled-by-tutor. |
| **Lesson Report** | Tutor's post-lesson notes and structured feedback; can be shared with clients. |
| **Charge** | A billable item on a Client's ledger: lesson charge, ad hoc charge, package sale, registration fee, late fee, cancellation fee. |
| **Invoice** | A legal document grouping Charges for a period. Immutable once issued (corrected via Credit Note). |
| **Payment Request** | A request for prepayment (TutorCruncher "credit request"/proforma). When paid, it tops up client credit. Not a tax invoice. |
| **Client Ledger** | Append-only list of financial entries for a Client; the balance is derived from it. |
| **Credit** | A positive client balance (prepaid or overpaid) available to settle future charges. |
| **Package** | A prepaid bundle (e.g. 10 hours of GCSE Maths, expires in 6 months) consumed by lessons. |
| **Payment** | Money received from a client (card, direct debit, PayPal, bank transfer, cash, cheque). Allocated to invoices or held as credit. |
| **Pay Item** | A tutor earnings line (lesson pay, expense reimbursement, bonus, deduction). |
| **Pay Run** | A batch of approved Pay Items for a period, producing payslips or self-billing statements and Payouts. |
| **Payout** | The transfer of money to a tutor (Stripe Connect, bank file, manual). |
| **Enquiry / Lead** | A prospective client request entering the sales Pipeline. |
| **Application** | A prospective tutor's application, entering the recruitment pipeline. |
| **Compliance Requirement** | A document or check a tutor must hold (DBS/background check, right to work, ID, qualification, safeguarding training) with expiry. |
| **Class / Course / Term** | Group-teaching constructs: Course (curriculum product) → Class (scheduled cohort with capacity) → Term (date range for enrolment and billing). |
| **Enrolment** | A Student's place in a Class for a Term. |
| **Affiliate** | A referrer earning commission on referred clients' revenue. |
| **Automation** | A tenant-defined rule: Trigger (event or schedule) → Conditions → Actions. Each run executes as a Temporal workflow (E14/E32). |
| **Workflow (process)** | A durable, long-running business process run on Temporal (E32), e.g. an invoice's dunning or a pay run's approval. Linked to its subject record and shown as a process timeline. Workflows act with actor type `workflow` in audit and events. |

## 2. Core entity relationships

```
Organisation 1─* Branch
Organisation 1─* Membership *─1 User
Membership 1─0..1 TutorProfile ; Membership *─* Role ; Membership *─* Branch (scope)

Client 1─* Contact (0..1 User login each)
Client 1─* Student (0..1 User login each)
Client 1─1 ClientLedger(derived) ; Client 1─* PaymentMethod

Service *─0..1 Subject/Level ; Service 1─* RateRule
Job *─1 Client ; Job *─* Student (JobStudent) ; Job *─* Tutor (JobTutor: pay overrides) ; Job *─1 Service
Job 1─* LessonSeries 1─* Lesson
Lesson *─* Tutor (LessonTutor: pay_rate, pay_amount)
Lesson *─* Student (LessonAttendee: attendance, charge_rate, charge_amount)
Lesson 0..1─* LessonReport
Lesson *─0..1 Location/Room ; Lesson 0..1─1 OnlineMeeting

LessonAttendee ─► Charge (on completion/cancellation-with-fee)
LessonTutor ─► PayItem
Charge *─0..1 InvoiceLine *─1 Invoice
Payment 1─* PaymentAllocation *─1 Invoice
PackagePurchase 1─* PackageConsumption *─1 LessonAttendee
PayItem *─0..1 PayRun 1─* Payout
```

## 3. Status lifecycles

**Job:** `draft → pending_tutor (seeking tutor) → active → paused → completed | cancelled`

**Lesson:** `planned → completed | cancelled | missed`. Sub-reasons live on attendance. Edits are allowed until locked by billing (invoiced) or payroll (paid). After that, corrections are made via adjustments.

**Attendance:** `scheduled → present | late | absent_notified | no_show | cancelled_client | cancelled_tutor | cancelled_admin`. Each outcome maps to *chargeable?* and *payable?* per the org's cancellation policy (E09).

**Invoice:** `draft → issued (open) → partially_paid → paid | void | written_off`. Overdue is a derived flag.

**Payment Request:** `draft → sent → paid | cancelled`.

**Payment:** `pending → succeeded | failed | refunded | partially_refunded | disputed`.

**Pay Item:** `pending (lesson not complete) → ready → approved → in_pay_run → paid`.

**Pay Run:** `draft → approved → processing → paid | failed (partial)`.

**Enquiry:** `new → contacted → qualified → proposal → won (converted to Client/Job) | lost`. Stages are configurable per org; outcome is fixed.

**Tutor Application:** `submitted → screening → interview → references/checks → approved → onboarded | rejected | withdrawn`. Configurable stages.

**Tutor status:** `applicant → onboarding → active → inactive → archived`. Compliance can set `restricted` (can't be assigned new lessons).

**Client status:** `prospect → active → dormant (no lessons for N days) → archived`.

**Student status:** `lead → trial → active → waiting (waitlist) → paused → finished → archived` (from TutorBird statuses).

## 4. Common fields

Every tenant model: `id (uuid7)`, `organisation_id`, `created_at`, `updated_at`, `created_by_id`, `updated_by_id`. Branch-scoped models add `branch_id`. People models add `archived_at`. Financial models are never hard-deleted.

Every "customisable" entity (Client, Contact, Student, Tutor, Job, Lesson, Enquiry, Application) supports:
- `custom_fields JSONB` validated against `CustomFieldDefinition` (E05)
- `tags` (M2M to Tag; TutorCruncher "labels")
- notes, tasks, documents and history (E05 generic relations)

## 5. Domain event catalogue (initial)

Naming: `<aggregate>.<past_tense_verb>`. Each epic lists its events; this table is the master list.

| Event | Emitted by |
|---|---|
| `organisation.created`, `organisation.updated`, `organisation.settings_updated`, `organisation.suspended`, `organisation.reactivated`, `organisation.closed`, `branch.created`, `branch.updated`, `branch.archived`, `onboarding.step_completed`, `onboarding.completed`, `organisation.export_requested`, `organisation.deletion_due` | E02 |
| `user.invited`, `user.joined`, `user.logged_in`, `user.mfa_enabled`, `membership.role_changed`, `membership.deactivated`, `impersonation.started`, `impersonation.ended` | E03 |
| `subscription.started`, `subscription.changed`, `subscription.past_due`, `subscription.cancelled` | E04 |
| `client.created/updated/archived`, `contact.created/updated`, `student.created/updated/status_changed`, `tutor.created/updated/status_changed`, `note.created`, `task.created/assigned/completed`, `document.uploaded` | E05 |
| `service.created`, `service.updated` (with `rate_changed`) | E06 |
| `job.created/updated/status_changed`, `job.tutor_assigned/removed/replaced`, `job.hours_cap_reached` | E07 |
| `lesson.scheduled`, `lesson.rescheduled`, `lesson.updated`, `lesson.cancelled`, `lesson.completed`, `lesson.missed`, `lesson.locked_edited`, `lesson_series.created/updated/ended`, `availability.updated`, `booking.requested/approved/declined` (Phase 2) | E08 |
| `attendance.recorded`, `lesson_report.submitted`, `lesson_report.overdue`, `lesson_report.shared` | E09 |
| `charge.created`, `invoice.drafted/issued/sent/paid/overdue/voided`, `credit_note.issued`, `payment_request.sent/paid`, `client.balance_low`, `package.purchased/depleted/expiring` | E10 |
| `payment.succeeded/failed/refunded/disputed`, `payment_method.added/expiring/removed`, `mandate.created/cancelled` | E11 |
| `pay_item.created`, `pay_run.approved/paid`, `payout.paid/failed`, `expense.submitted/approved/rejected` | E12 |
| `message.sent/delivered/bounced/received` | E13 |
| `enquiry.received`, `enquiry.stage_changed`, `enquiry.won/lost` | E17 |
| `application.submitted/stage_changed/approved/rejected`, `compliance.document_expiring/expired/verified` | E18 |
| `job_offer.sent/accepted/declined`, `job_posting.application_received` | E19 |
| `enrolment.created/cancelled`, `waitlist.place_offered`, `class.full` | E20 |
| `homework.assigned/submitted/graded`, `goal.achieved` | E21 |
| `review.submitted`, `referral.converted`, `commission.earned` | E25 |
| `consent.granted`, `consent.withdrawn`, `security.alert` | E29 |
