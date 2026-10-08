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
- [ ] **E07-T01** Job, JobStudent and JobTutor models, services, status machine, reference numbers.
- [ ] **E07-T02** Job API with field-permission filtering of rates and margin.
- [ ] **E07-T03** Tutor replace/assign with future-lesson preview (stub until E08 is in; complete the integration in E08-T10).
- [ ] **E07-T04** Bill-to override, hours cap, policy overrides.
- [ ] **E07-T05** Computed financial summary selector.
- [ ] **E07-T06** Quick job setup endpoint (job + series).
- [ ] **E07-T07** Frontend: job list, board, job page, quick setup modal.
