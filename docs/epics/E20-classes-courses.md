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
- [x] **E20-T01** Academic years, terms, breaks; integration with series skip logic.
- [x] **E20-T02** Courses and classes; session generation as lessons with roster-driven attendees.
- [x] **E20-T03** Enrolment service with capacity locks, eligibility, mid-term joins.
- [x] **E20-T04** Class billing: term invoices, monthly plans, proration engine (Hypothesis tests).
- [x] **E20-T05** Transfers, withdrawals, refunds.
- [x] **E20-T06** Waitlist integration and auto-offers.
- [x] **E20-T07** Registers and makeup sessions.
- [x] **E20-T08** Term rollover flow with parent confirmation.
- [x] **E20-T09** Public catalogue and online enrolment with payment.
- [x] **E20-T10** Frontend admin: courses/classes/roster/register UIs.

## Temporal workflows (E32)

Implement these processes as Temporal workflows following the rules in [E32](E32-workflow-orchestration-temporal.md) (deterministic workflow code, side effects in tenant-scoped activities that call services, tenant-prefixed workflow IDs, signals for human decisions). Where the requirements above mention sweeper tasks, `next_*_at` / `resume_at` columns or retry schedules, the workflow replaces them.

- [x] **E20-TW1** Term rollover and enrolment payment workflows (requires E32).

| Workflow | Started by | Steps, timers and signals | Replaces |
|---|---|---|---|
| `TermRolloverWorkflow` `rollover:{org}:{term}` | Admin starts rollover | Send confirm/opt-out requests to families → reminders → deadline timer → enrol confirmed students, release unconfirmed places to waitlists, bill term fees | Batch job + manual reminders |
| `EnrolmentPaymentWorkflow` | Online enrolment with payment | Hold the place → wait for `paid` signal until timeout → confirm enrolment, or release the place | Pending-payment sweeper |

## Implementation notes (as built 2026-10-13)
- **App:** `courses` (all tables with RLS): `AcademicYear`, `Term`, `TermBreak`, `Course`, `GroupClass` (the spec's `Class`; called "class" in the API and UI), `ClassTeacher`, `ClassSession` (one-to-one with an E08 `Lesson`), `Enrolment`, `EnrolmentTransfer`, `MakeupBooking`, `TermRollover` and `RolloverOffer`. See ADR 0024.
  - Settings: proration basis (sessions or teaching weeks), prorating mid-term joins, fee timing (invoice at enrolment, or charge from term start for the next invoice run), withdrawal refund (credit unused sessions, or none), online payment (none, full or deposit), payment hold minutes, waitlist auto-offer and offer hours, makeup credit days, whether breaks also pause one-to-one lessons, and enrolment terms.
- **Terms (T01):** academic years and terms per branch, with breaks and enrolment open and close dates. Terms can't overlap or fall outside their year.
  - Breaks feed the E08 series skip logic through a new hook (`scheduling.services.register_skip_dates`). Class series always skip them; other series skip them only with `courses.breaks_skip_all_lessons`. Changing breaks re-plans the classes' future sessions.
  - E10 termly plans now follow the branch's terms (`billing.plans.register_term_calendar`): each term is a period, and the holidays between terms aren't billed. An open-ended termly plan past the last known term waits (paused) until a new term is saved, because `term_dates_changed` signals its workflow. Without terms it stays four-monthly. E10's note is updated.
- **Classes (T02):** a class is a course in a term. It has an RRULE (weekly on chosen days), a start time, a length, a room, location or online, a capacity, a minimum size, teachers and assistants, age and year gating, and a status (`draft | open | full | running | completed | cancelled`).
  - Capacity is checked against the service's maximum students and the room's capacity.
  - Creating a class creates an E08 lesson series with no students (new `allow_empty_roster`) and every session up to the class end, each linked by `ClassSession`.
  - The roster drives attendees. `scheduling.services.sync_group_roster` (new) adds and removes attendees and teachers on future, planned, unlocked sessions only. People who stay aren't touched, so absence notices survive. It re-prices and publishes `lesson.updated` without notifications.
  - Teacher pay (FR-20-7) is one of: the usual service and tutor rates, a fixed amount per session, headcount tiers (by the roster at each sync), or a fixed total split exactly over the sessions. An assistant can have their own amount per session. These become the lesson tutors' pay overrides, so E12 pay items follow on completion.
  - Status: open ⇄ full as places are taken or freed (`class.full`); running after the first session is delivered; completed (with its enrolments) after the last.
  - `class.below_minimum` is published when a withdrawal or transfer takes a class below its minimum. It isn't checked on a timer.
- **Enrolment (T03):** every enrolment locks the class row (`select_for_update`), so the last place can't be taken twice.
  - Places taken = active enrolments (pending payment, enrolled, trial) + waitlist offers that are out, or accepted but not yet enrolled.
  - Eligibility: age on the class start date and year group (the class's settings, else the course's). Staff can skip it and override capacity.
  - Mid-term joiners start from today and join future sessions only (AC). Trials attend free and are billed from conversion.
- **Billing (T04):** a pure engine (`courses.pricing`, tested with Hypothesis):
  - Sibling and multi-class discounts follow the E06 stacking rules. There is a new `multi_class` discount kind with `min_classes`. Siblings count in the order the children first enrolled that term.
  - Proration is by sessions or by teaching weeks (7-day blocks from the class start; weeks fully inside breaks don't count).
  - Instalments and teacher pay splits add up exactly.
- **Fees by pricing model (T04):**
  - Per term and full course: one `course` charge (a new E10 charge kind) for the prorated fee.
  - Instalments: monthly charges that add up exactly; the first is billed now.
  - Per month: an E10 monthly `BillingPlan` from the start date to the class end (E10 prorates part months).
  - Per session: each session's attendee is priced at the enrolment's per-session price, so E10 charges each delivered session. Every other model zero-rates the sessions.
  - Registration fee: once per student and academic year. Materials fee: per enrolment.
  - With fees at enrolment, everything is invoiced together straight away. Otherwise the charges are dated from the start, and the next invoice run picks them up.
  - New billing service helpers: `charge_fee` (idempotent per source key, split by the E10-T15 payers) and `adjust_fee`.
  - Deviation: pay-as-you-go courses need a service priced per lesson or per hour where each student pays the rate (not split). Their discounts apply when enrolling, because the price is the lesson override, which the rate engine treats as final.
- **Transfers and withdrawals (T05):**
  - Withdrawing from a date removes the student from the sessions from then on. With the refund setting, fees are cut to the units the student had: unpaid invoices owe less, and paid ones become client credit (credit notes; refunds to card stay a payments decision). Monthly plans end the day before.
  - Transfers enrol the student in the new class (prorated, with no one-off fees for the same course) and always credit the old fee's unused share. `EnrolmentTransfer` records both sides.
  - Cancelling a class withdraws everyone with the unused sessions credited and cancels its future sessions.
- **Waitlist (T06):** class waitlists are E17 `WaitlistEntry` rows with a new `group_class_id`; positions count per class.
  - When a place frees (`class.places_freed`), or an offer expires or is declined, the class offers it to the next family (a time-limited E17 offer run by `WaitlistOfferWorkflow`). E17's subject cascade skips class entries.
  - Accepting (`waitlist.place_accepted`) enrols the student, or holds the place for payment.
- **Registers and makeups (T07):**
  - The register marks everyone at once through E09 (`complete_lesson`, or `record_attendance` after completion), so policies, charges and pay follow. Absence reasons are kept on the session.
  - Makeups go to a future session of another class of the same course that has room. They use the student's E09 makeup credit, or issue one for the missed session. Makeup attendees aren't charged.
- **Rollover (T08):** staff start re-enrolment from one term to the next, with a deadline and a mode: families confirm, or places roll over unless families opt out.
  - Each class continues in its `next_class`, else in the class with the same course and name.
  - Families answer from an email link (`/re-enrol/{token}`; an HMAC token, nothing stored raw) or in the portal.
- **Online enrolment (T09):**
  - `/api/v1/public/catalogue` lists classes with places left (filters: subject, age, weekday, location, course). `/api/v1/public/enrol` enrols new families: eligibility is checked before the family is created, full classes take waitlist sign-ups, and a CAPTCHA applies when Turnstile is configured. A token opens the enrolment's status.
  - The E24 registries gain the `class_catalogue` widget (`<tt-class-catalogue>`, gated by the `courses` plan feature) and website block. Course images become public assets.
  - Payment at enrolment uses E11's `request_booking_payment` and holds the place. Staff, rollovers and transfers never take payment up front.
- **Portal:** `/portal/classes` lists the household's classes (pay for a held place, or give it up), waitlist positions and next term's questions, and lets families enrol their children. It needs `portal.client.enrol` (clients hold it through `portal.client.*`) and shows with a `classes` portal feature flag.
- **Frontend (T10):** admin `/courses` (classes, courses, terms with breaks, next-term rollover), `/classes/$id` (places, roster with withdraw and transfer, enrolment with a live quote, sessions, waitlist), `/class-sessions/$id/register`, and the public `/re-enrol/$token` page. The catalogue's discount form gains the multi-class kind, and the widget builder gains the class catalogue options.
- **Workflows (TW1):**
  - `EnrolmentPaymentWorkflow` `enrolment-payment:{org}:{enrolment}` is started by `enrolment.created` for a held place. It waits for `payment_received` (from `payment_request.paid`) until the hold expires. Then it confirms the place (sessions and fees, with the payment settling the invoice as credit) or releases it to the waitlist. `cancelled` ends it. A payment whose signal was missed is found at the timeout and confirms the place instead.
  - `TermRolloverWorkflow` `rollover:{org}:{rollover}` sends the requests and reminds families who haven't answered half way to the deadline. It finishes at the deadline, when every family has answered (checked on each `responded`), or when staff finish it (`finalise`); `cancel` stops it. Deviation: the id uses the rollover rather than the term, so a cancelled rollover can be run again (completed workflow ids can't be reused).
  - Replay histories are in `backend/tests/workflow_histories/` (paid, released and retried; deadline and answered).
- **Events:** `enrolment.created/confirmed/released/withdrawn/transferred/completed`, `class.full/below_minimum/cancelled/places_freed`, `term.rollover_started/rollover_responded/rollover_finalised`. Enrolment and class events are offered as webhooks.
- **Notifications:** `class_enrolment_confirmed`, `term_rollover_invite` (with reminders), and staff alerts for full and under-minimum classes.
- **Dev seed:** an academic year, this term with half term, an 11+ course and an open Saturday class.
- **Limits:** "running" classes still accept mid-term enrolment (the status is informational). Instalments are fixed monthly charges from enrolment, not E11 auto-pay schedules (auto-pay applies to each invoice as usual). Absence reasons are free text, not a catalogue.
- **Release test fix (2026-10-30, TP-E20-008).** The admin *New course* form has *Usual class size* (`default_capacity`), filled in from the service's `max_students` (at most 10). Without it, a new course's capacity defaults to the smaller of 10 and the service's limit, so courses on small group services are no longer refused.
