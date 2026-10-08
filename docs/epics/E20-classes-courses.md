# E20 — Group Classes, Courses & Term Enrolment

| | |
|---|---|
| **Phase** | Scale (Phase 3) — pull earlier if targeting learning centres |
| **Depends on** | E06, E08, E09, E10, E11, E17 (waitlist) |
| **Differentiator** | Learning-centre capability (Jackrabbit/Teach 'n Go-style) that TutorCruncher and TutorBird do only partially |

## 1. Summary
Support centre-style operations: Courses (products like "Year 6 11+ Prep"), Classes (scheduled cohorts with capacity, teacher(s), room), Terms (date ranges with holidays), Enrolment (incl. online enrolment with payment), waitlists, registers, and term/monthly tuition billing with proration.

## 2. Functional requirements

### FR-20-1 Terms and academic calendar
- Academic years and terms per branch (name, start/end, half-term/holiday breaks, enrolment open/close dates). Breaks feed into series skip logic (E08) and billing proration.

### FR-20-2 Courses
- Fields: name, description (public), subject/level, age/year range, prerequisites, duration (weeks/sessions), delivery mode, default capacity, pricing model (per term, per month, per session, full-course upfront, instalments), registration fee, materials fee, image, public visibility.

### FR-20-3 Classes (cohorts)
- Class = course instance: term, schedule (RRULE, e.g. Saturdays 10:00–11:30), location/room or online, teacher(s) + assistants, capacity, min viable size, status (`draft | open | full | running | completed | cancelled`), waitlist on/off, age gating.
- Sessions generated as Lessons (E08) with `class_session` link; class roster drives attendees automatically.
- **AC:** enrolling a student mid-term adds them as an attendee to all future sessions of that class (not past ones), and billing prorates per the course pricing rules.

### FR-20-4 Enrolment
- Staff enrol students; clients enrol via portal/public catalogue (E24 widget) with eligibility checks (age/year), capacity check with lock, payment at enrolment (full, deposit, or set up recurring/instalments via E11 auto-pay), terms acceptance.
- Enrolment status: `pending_payment | enrolled | trial | withdrawn | completed | transferred`.
- Transfers between classes (with prorated adjustments), withdrawals (refund policy), re-enrolment for next term (bulk "roll over" with opt-out/confirm flow for parents).
- Sibling discounts and multi-class discounts (E06).

### FR-20-5 Waitlist
- When full: join waitlist (E17 FR-17-6); auto-offer on vacancy (time-limited); position visible to client.

### FR-20-6 Registers and attendance
- Class register per session (E09 attendance), bulk mark; absence reasons; makeup sessions in another class of the same course (capacity permitting) using makeup credits (E09).

### FR-20-7 Class billing
- Term fee invoices generated at enrolment or term start; monthly tuition via E10 billing plans; per-session pay-as-you-go also possible.
- Proration: by remaining sessions or remaining weeks (setting); holiday weeks excluded.
- Teacher pay: per session, per student headcount tiers, or fixed per class (E12 pay items from class session completion).

### FR-20-8 Class catalogue
- Public catalogue page/widget with filters (age, subject, day, location), availability indicator ("3 places left"), enrol button.

## 3. Data model
`AcademicYear`, `Term`, `TermBreak`, `Course`, `Class(course, term, schedule series, capacity, teachers, room, status)`, `ClassTeacher`, `Enrolment(class, student, client, status, start_date, end_date, price snapshot, billing plan)`, `EnrolmentTransfer`, `ClassSession` (one-to-one with Lesson).

## 4. API
`/api/v1/terms`, `/courses`, `/classes` (+ `/roster`, `/sessions`, `/register`), `/enrolments` (+ transfer, withdraw), `/enrolments/rollover`, `/public/catalogue`, `/public/enrol`.

## 5. Events
`enrolment.created/withdrawn/transferred/completed`, `class.full`, `class.below_minimum`, `class.cancelled`, `term.rollover_started`.

## 6. Delivery plan
- [ ] **E20-T01** Academic years, terms, breaks; integration with series skip logic.
- [ ] **E20-T02** Courses and classes; session generation as lessons with roster-driven attendees.
- [ ] **E20-T03** Enrolment service with capacity locks, eligibility, mid-term joins.
- [ ] **E20-T04** Class billing: term invoices, monthly plans, proration engine (Hypothesis tests).
- [ ] **E20-T05** Transfers, withdrawals, refunds.
- [ ] **E20-T06** Waitlist integration and auto-offers.
- [ ] **E20-T07** Registers and makeup sessions.
- [ ] **E20-T08** Term rollover flow with parent confirmation.
- [ ] **E20-T09** Public catalogue and online enrolment with payment.
- [ ] **E20-T10** Frontend admin: courses/classes/roster/register UIs.

## Temporal workflows (E32)

Implement these processes as Temporal workflows following the rules in [E32](E32-workflow-orchestration-temporal.md) (deterministic workflow code, side effects in tenant-scoped activities that call services, tenant-prefixed workflow IDs, signals for human decisions). Where the requirements above mention sweeper tasks, `next_*_at` / `resume_at` columns or retry schedules, the workflow replaces them.

- [ ] **E20-TW1** Term rollover and enrolment payment workflows (requires E32).

| Workflow | Started by | Steps, timers and signals | Replaces |
|---|---|---|---|
| `TermRolloverWorkflow` `rollover:{org}:{term}` | Admin starts rollover | Send confirm/opt-out requests to families → reminders → deadline timer → enrol confirmed students, release unconfirmed places to waitlists, bill term fees | Batch job + manual reminders |
| `EnrolmentPaymentWorkflow` | Online enrolment with payment | Hold the place → wait for `paid` signal until timeout → confirm enrolment, or release the place | Pending-payment sweeper |
