# E07 — Jobs & Tutor Assignment

| | |
|---|---|
| **Phase** | MVP |
| **Depends on** | E05, E06 |
| **Parity** | TutorCruncher Service/Job (rates, tutors, recipients, status, labels, job board) |

## 1. Summary
A **Job** is the ongoing engagement for a client's student(s): what's being taught, by whom, at what charge and pay rates, how it's billed, and the default schedule. Lessons hang off jobs. Jobs give agencies margin control and give sole traders a simple "Student X does Maths weekly at £40" setup.

## 2. Functional requirements

### FR-07-1 Job record
- Fields: reference (`JOB-000123`), name (auto: "GCSE Maths – Sam Patel"), client, students (≥1; ≤ service max), service, subject/level (override of service), branch, status (`draft | seeking_tutor | active | paused | completed | cancelled`), tutors (JobTutor: role `lead | assistant`, pay rate override, start/end dates, status), charge rate (override; per student optionally), billing method (`pay_as_you_go | prepaid_credit | package | recurring_fixed`), linked package (optional), PO number, default duration, default location / online, default meeting link provider (E22), start date, expected end date, expected lessons per week / total hours (for pipeline and forecasting), goals, notes (internal / for tutor / for client), tags, custom fields, account manager.
- Computed: lessons completed/planned, hours delivered, revenue, tutor cost, **margin** (£ and %), next lesson, balance on job (for prepaid), report compliance.
- **AC:** Tutors never see job charge rates or margins; clients never see pay rates.

### FR-07-2 Job creation flows
- **Quick job (solo mode):** from a student page, "Set up lessons" → service, rate, day/time, recurrence → creates job + series in one step.
- **Agency flow:** create job in `seeking_tutor` from an enquiry (E17), then use matching (E19) to assign a tutor → `active`.
- Duplicate job (e.g. a new academic year).

### FR-07-3 Tutor assignment
- Add/remove/replace tutors with effective dates. On replacement, future unlocked lessons are reassigned (with a preview of affected lessons and conflict check) and pay rates re-resolved.
- Assignment notifications to tutors (with job brief: student needs, goals, location, schedule) and optional client intro email (tutor profile card).
- Optional tutor acceptance step: assignment is `offered` until the tutor accepts (E19 job offers).

### FR-07-4 Job status lifecycle
- `paused`: future lessons optionally cancelled (non-chargeable) or kept; billing stops for recurring_fixed.
- `completed`/`cancelled`: future lessons cancelled with reason; prepaid balance handling prompt (refund, keep as client credit, transfer to another job).
- Auto-complete jobs with no lessons for N days (setting) → `dormant` prompt task.

### FR-07-5 Job-level rules
- Max hours per period (e.g. local authority funding cap: 20 hours) with warnings at 80% and block at 100% (setting).
- Funding/third-party payer: the job bills a different Client than the student's (e.g. a school pays for a student's tuition). Bill-to client override.
- Cancellation policy override (E09).
- Required lesson report template override (E09).

### FR-07-6 Job list and board
- Grid with filters (status, tutor, service, branch, margin range, seeking tutor for > N days).
- Kanban board by status for coordinators.
- "Jobs needing attention": seeking tutor, no upcoming lessons, low prepaid balance, overdue reports.

## 3. Data model
`Job`, `JobStudent(job, student, charge_rate_override, active_from, active_to)`, `JobTutor(job, tutor, role, pay_rate_override, status: offered|active|ended|declined, start_date, end_date)`, `JobStatusHistory`.

## 4. API
`/api/v1/jobs` CRUD; `/jobs/{id}/tutors` (add, replace with preview `?dry_run=true`, remove); `/jobs/{id}/students`; `/jobs/{id}/status` transitions; `/jobs/{id}/summary` (financials, permissioned); `/jobs/quick-setup`.

## 5. Events
`job.created`, `job.updated`, `job.status_changed`, `job.tutor_assigned`, `job.tutor_removed`, `job.tutor_replaced`, `job.hours_cap_reached`.

## 6. Permissions
`jobs.job.{view,create,edit,manage_tutors,change_status}`; tutor scope `own` (jobs they're on; limited fields).

## 7. Delivery plan
- [x] **E07-T01** Job, JobStudent and JobTutor models, services, status machine, reference numbers.
- [x] **E07-T02** Job API with field-permission filtering of rates and margin.
- [x] **E07-T03** Tutor replace/assign with future-lesson preview (stub until E08 is in; complete the integration in E08-T10).
- [x] **E07-T04** Bill-to override, hours cap, policy overrides.
- [x] **E07-T05** Computed financial summary selector.
- [x] **E07-T06** Quick job setup endpoint (job + series).
- [x] **E07-T07** Frontend: job list, board, job page, quick setup modal.

## Implementation notes (as built 2026-10-09)
- **App:** `jobs` with `Job` (branch-scoped, customisable, CRM target `jobs.job`), `JobStudent`, `JobTutor` and `JobStatusHistory`. RLS covers all four. References come from the core sequence (`JOB-000001`). The auto name is `"<level> <subject> – <students>"` (falls back to the service name).
- **Status machine:** draft → seeking_tutor/active/cancelled; seeking_tutor → draft/active/cancelled; active → seeking_tutor/paused/completed/cancelled; paused → active/completed/cancelled; completed → active (reopen); cancelled is final. Activating needs an active tutor. Assigning a tutor (or an accepted offer) moves a seeking job to active. Removing the last tutor moves an active job back to seeking. Completing or cancelling declines open offers. `job.status_changed` carries `future_lessons` (`keep`/`cancel`), which E08 acts on (completing or cancelling always cancels).
- **Rates:** job charge rate, per-student overrides and per-tutor pay overrides are `RateField`s in the job's currency. `selectors.rate_context(job)` builds the E06 engine context: the bill-to client is charged, and lesson overrides are added by E08.
- **Visibility (AC):** tutors' `own` scope is the jobs they are offered or active on. Charge rates and student rate overrides need `billing.rates.view_charge`. Pay overrides need `billing.rates.view_pay`. Internal notes, bill-to, PO and policy overrides need `jobs.job.edit`. The summary endpoint needs `view_charge`, and pay and margin also need `view_pay`. Clients have no job API yet (portal in E15).
- **E05 follow-up:** tutors now see the students, clients and contacts reachable through their jobs (`own_scope_path`).
- **Fix:** field permissions now apply to nested serializers too (the check moved from `__init__` to `get_fields`). Previously a client's nested contacts showed phone and email to roles without those permissions. A regression test is added.
- **Lessons hook:** jobs need lesson data (stats, hours scheduled, future lessons) before scheduling exists. `jobs.lessons` defines a `LessonsProvider` that returns nothing until E08 registers the real one. Until then, the replace preview, the hours-cap usage and the delivered totals are empty. E08-T10 completes the integration.
- **Hours cap:** `hours_cap` + `hours_cap_period` (week/month/total). `services.check_hours` warns at 80% and blocks above 100% (the `jobs.block_at_hours_cap` setting can make that a warning only). `notify_hours` emits `job.hours_cap_reached` once per period and level.
- **Policy overrides** (cancellation policy, report template) are stored as JSON on the job for E09 to define and read.
- **Quick setup** creates the job (active with a tutor, else seeking a tutor) and stores the weekly slots in `default_schedule`. E08 creates the lesson series from them. Tutor notifications and the client intro email are events for E13.
- **"Needing attention"** currently means: seeking a tutor for more than 7 days, or an open tutor offer. No upcoming lessons, low prepaid balance and overdue reports are added by E08, E10 and E09.
- **Frontend:** a jobs list (search, status, needs attention), a board by status (cards move with a select, so no drag-and-drop is needed), and a job page. The job page shows details, students, tutors (assign/offer, replace with preview, remove), status changes with reason, economics and activity. The student page gains its jobs and "Set up lessons".

