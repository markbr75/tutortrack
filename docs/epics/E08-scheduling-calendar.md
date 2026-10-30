# E08 — Scheduling, Calendar & Availability

| | |
|---|---|
| **Phase** | MVP (rooms and self-booking in Phase 2) |
| **Depends on** | E05, E06, E07 |
| **Parity** | TutorCruncher calendar, recurring and group appointments, availability; TutorBird calendar, colour coding, filters, non-tutoring events, conflict prevention, student booking/cancel |

## 1. Summary
The heart of the product. Lessons (one-off and recurring, 1:1 and group), non-lesson events, tutor availability and time off, conflict detection (tutor, student, room), the calendar UI (day/week/month/agenda/resource views, drag and drop), rescheduling flows and client/student self-booking.

## 2. Functional requirements

### FR-08-1 Lesson model
- Fields: job (nullable), class session (E20, nullable), service, title (auto), start, end, timezone, status (`planned | completed | cancelled | missed`), location / room / online (meeting URL, provider, meeting id), tutors (LessonTutor), attendees (LessonAttendee), series (nullable), series index, is_exception (modified occurrence), notes (internal / for tutor / for client), colour (from service/category, overridable), created_via (`admin | tutor | client_booking | api | import | series`), lock state (`unlocked | invoiced | paid`), tags, custom fields.
- `LessonTutor`: tutor, pay snapshot (rate, units, amount, premiums), payable flag.
- `LessonAttendee`: student, charge snapshot (rate, amount, discounts, tax), chargeable flag, attendance (E09), package consumption (E10).
- Duration constraints: min 5 minutes, max 12h, in 5-minute increments (setting).

### FR-08-2 Recurrence (Lesson Series)
- RRULE-based: daily, weekly (multiple days), fortnightly, monthly (by date or by nth weekday), custom; end by date, by count, or never (generated on a rolling horizon, default 6 months, extended nightly).
- Skip dates: org/branch **holiday calendars** and term breaks (E20 terms) — option "skip holidays" per series.
- Editing semantics (Google Calendar style): *this lesson*, *this and following*, *all future unlocked lessons*. "This and following" splits the series.
- Lessons are materialised as rows (not virtual) so they can carry attendance, reports and finance. Exceptions are preserved when the series is edited ("keep my individual changes" prompt).
- **AC:** changing "all future" time from 16:00 to 17:00 updates future unlocked lessons, leaves completed and invoiced ones untouched, and preserves explicitly moved exceptions unless the user opts to overwrite.
- **AC:** DST: a weekly 16:00 Europe/London series remains at 16:00 local across the clock change; the tutor in America/New_York sees the correct shifted local time.

### FR-08-3 Group lessons
- Multiple attendees (capacity from service/class), optionally from different clients, with each attendee charged separately. Per-student pricing or a split of a group price (E06).
- Add/remove attendees on a single lesson or across the series.

### FR-08-4 Calendar events (non-lesson)
- Types: meeting, training, admin, blocked/unavailable, holiday (org-wide), custom. Optional pay (e.g. paid training hours → E12 pay item).
- Org-wide events (closures) show for everyone and can auto-cancel lessons in the range (with policy: non-chargeable).

### FR-08-5 Availability and time off
- Tutor weekly availability templates (multiple windows per day, per location/online flag), effective date ranges, and exceptions (extra availability, time off).
- Time-off requests (Phase 2: approval workflow by admin); approved time off flags conflicting lessons for cover (E19 cover requests).
- Student availability preferences (used by matching and booking).
- Location opening hours and room availability.
- **AC:** the availability API returns free slots for a tutor for a date range and duration, considering availability windows, existing lessons + buffer time (setting, e.g. 15 minutes travel), time off, synced external busy times (E22) and min-notice rules.

### FR-08-6 Conflict detection
- On create/edit, check: tutor double-booking (incl. external calendar busy blocks), student double-booking, room double-booking/capacity, outside tutor availability (warning), outside opening hours (warning), travel buffer (warning), exceeds tutor max weekly hours (warning), job hours cap (E07).
- **Hard** conflicts (tutor/room overlap) block unless the user has `scheduling.override_conflicts` and confirms. Enforce at DB level for rooms with a PG **exclusion constraint** on `tstzrange` where the room is not null and status ≠ cancelled.
- Series creation reports conflicts per occurrence with options: skip conflicting occurrences, create anyway, or adjust.

### FR-08-7 Calendar UI
- Views: day, week, month, agenda/list, **resource views** (tutors as columns/rows; rooms as columns), timeline.
- Filters: branch, tutor(s), student, client, service, subject, location, room, status, tags; saved filter sets.
- Colour by: service, tutor, status, location, subject (TutorBird-style).
- Drag to create, drag/resize to reschedule (with conflict check and "notify participants?" prompt), click for a quick-view popover (attendees, status, actions: complete, cancel, report, join link).
- Display in the viewer's tz with a secondary tz option; show lesson tz when different.
- Performance: virtualised rendering; the API returns a lightweight projection for ranges (`/calendar?start&end&fields=min`).
- Print/export view (PDF weekly timetable per tutor/student).

### FR-08-8 Rescheduling and change notifications
- Reschedule flows record `rescheduled_from` and reason; participants are notified per E13 templates (lesson changed), including updated ICS.
- **Reschedule requests** from clients/tutors (Phase 2): the request proposes new time(s) → the other party/admin approves → the lesson is moved. Policies: allowed up to N hours before, max reschedules per month.

### FR-08-9 Self-booking (Phase 2)
- Client portal and public booking widget (E24): choose service → tutor (or "any") → available slot → (new clients: details form) → payment or package deduction or "pay later" per setting → confirmation.
- Settings: min notice, max advance window, slot interval, buffer, which services/tutors are bookable, approval required vs instant, payment required at booking (Stripe), cancellation window.
- Trial lesson booking with special pricing (E06 discounts).
- Booking holds a slot for 10 minutes during payment (Redis lock + pending lesson).

### FR-08-10 Lesson actions
- Complete (E09), cancel (E09 cancellation flow), mark missed, duplicate, convert to series, add attendee, change tutor (single/series), add online meeting (E22), send reminder now, open report, view pricing trace.
- Bulk actions on the list view: complete, cancel, reassign tutor, change location, delete planned (if never notified), export.

### FR-08-11 iCal feeds
- Per-user secret iCal URL (tutor schedule, client/household schedule, student schedule), revocable. Read-only. (Full two-way sync in E22.)

### FR-08-12 Lesson locking
- Lessons included in an issued invoice or a paid pay run are locked for the financial fields and time. Editing a locked lesson requires `scheduling.edit_locked` and generates financial adjustments (credit note / pay adjustment) via E10/E12 services.

## 3. Data model
`Lesson`, `LessonTutor`, `LessonAttendee`, `LessonSeries(rrule, dtstart_local, tz, duration, until, count, horizon_generated_until, skip_holidays, template JSON of tutors/attendees/location)`, `CalendarEvent`, `CalendarEventParticipant`, `AvailabilityTemplate`, `AvailabilityWindow(weekday, start_time, end_time, location_mode)`, `AvailabilityException(date range, type: extra|off, reason, status)`, `BookingSettings`, `BookingHold`, `RescheduleRequest`, `ICalFeedToken`.
Indexes: `(organisation_id, start)`, GIN on tstzrange; exclusion constraint for rooms.

## 4. API
- `/api/v1/lessons` CRUD + `?start&end&tutor&student&...`
- `/api/v1/calendar` (range projection across lessons + events + external busy)
- `/api/v1/lesson-series` CRUD with `scope=this|following|all` on update
- `/api/v1/lessons/{id}/{complete,cancel,reschedule,duplicate}`
- `/api/v1/conflicts/check` (dry-run)
- `/api/v1/availability/{tutor_id}` (+ `/slots?service&duration&from&to`)
- `/api/v1/time-off`, `/api/v1/events`
- `/api/v1/booking/*` (public, token/tenant-scoped) for self-booking
- `/ical/{token}.ics`

## 5. Events
`lesson.scheduled`, `lesson.updated`, `lesson.rescheduled`, `lesson.cancelled`, `lesson.completed`, `lesson.missed`, `lesson_series.created/updated/ended`, `availability.updated`, `time_off.requested/approved`, `booking.requested/confirmed/declined`, `reschedule.requested/approved/declined`.

## 6. Permissions
`scheduling.lesson.{view,create,edit,cancel,complete}` with scopes; `scheduling.override_conflicts`; `scheduling.edit_locked`; `scheduling.availability.manage_others`; `scheduling.booking.settings`.

## 7. Non-functional
- Week view for 200 tutors / 2,000 lessons renders under 1.5s.
- Series generation for 1 year weekly < 300ms (bulk insert).

## 8. Delivery plan
- [x] **E08-T01** Lesson, LessonTutor and LessonAttendee models; create/update services using the E06 rate engine snapshot.
- [x] **E08-T02** Lesson series: RRULE expansion in local tz, horizon generation task, holiday skipping.
- [x] **E08-T03** Series edit semantics (this / following / all) with exception preservation; tests for DST and splits.
- [x] **E08-T04** Calendar events and org-wide closures.
- [x] **E08-T05** Availability templates, exceptions, free-slot calculator.
- [x] **E08-T06** Conflict engine (hard and soft), dry-run API, series conflict report.
- [x] **E08-T07** Calendar range projection API, optimised queries and indexes.
- [x] **E08-T08** Frontend calendar: views, filters, colour modes, drag/drop, quick-view, resource view.
- [x] **E08-T09** Lesson actions and bulk actions; change notifications hook (E13).
- [x] **E08-T10** Tutor replacement integration with E07; locking rules.
- [x] **E08-T11** iCal feeds.
- [x] **E08-T12** (Phase 2) Rooms with exclusion constraint; room resource view.
- [x] **E08-T13** (Phase 2) Reschedule requests and policies.
- [x] **E08-T14** (Phase 2) Self-booking engine, holds, booking settings, payment-at-booking hook (E11).
- [x] **E08-T15** (Phase 2) Time-off approval workflow and cover flagging.

## Temporal workflows (E32)

Implement these processes as Temporal workflows following the rules in [E32](E32-workflow-orchestration-temporal.md) (deterministic workflow code, side effects in tenant-scoped activities that call services, tenant-prefixed workflow IDs, signals for human decisions). Where the requirements above mention sweeper tasks, `next_*_at` / `resume_at` columns or retry schedules, the workflow replaces them.

- [x] **E08-TW1** Booking, reschedule and time-off workflows (requires E32). *(Built with T13–T15 in Phase 2.)*

| Workflow | Started by | Steps, timers and signals | Replaces |
|---|---|---|---|
| `BookingHoldWorkflow` `booking-hold:{org}:{hold_id}` | Self-booking slot selected (FR-08-9) | Hold slot → wait for signal `paid` / `confirmed` up to **10 min** → confirm lesson, or release slot on timeout | Redis hold + expiry job |
| `RescheduleRequestWorkflow` | `reschedule.requested` | Notify approver → wait for `approve`/`decline` until the policy deadline → apply move or auto-decline; reminders at 50% of window | Status polling |
| `TimeOffApprovalWorkflow` | `time_off.requested` | Wait for admin decision → on approval flag conflicting lessons and start `CoverRequestWorkflow` (E19) | Manual follow-up |

## Implementation notes (as built 2026-10-09)
- **App:** `scheduling` with `Lesson` (branch-scoped, customisable, CRM target `scheduling.lesson`), `LessonTutor`, `LessonAttendee`, `LessonSeries`, `CalendarEvent` (+ participants), `AvailabilityTemplate`/`AvailabilityWindow`, `AvailabilityException` and `ICalFeedToken`. RLS covers all of them. Indexes are `(organisation, start)`, `(organisation, end)` and `(job, start)`. Btree range queries replace the GIN/tstzrange index (room exclusion constraints come with T12).
- **Pricing snapshots:** every lesson is priced through the E06 engine with job rates, job student/tutor overrides and lesson overrides. Amounts and the trace are stored on attendees and tutors. They are re-resolved on edit while unlocked. Attendees are charged to the job's bill-to client when set.
- **Series:** RRULE parts are limited to daily, weekly and monthly (`FREQ`, `INTERVAL`, `BYDAY`, `BYMONTHDAY`, `BYSETPOS`, `WKST`). UNTIL/COUNT are separate fields. Occurrences are expanded as local wall-clock times in the series timezone and converted to UTC (DST-safe; covered by tests). Each lesson stores its `occurrence_date`, unique per series, which is how regeneration recognises existing dates. Generation prices the first occurrence once and bulk-inserts the rest. A year of weekly lessons is one batch (performance test included). A nightly Celery beat task (`extend_all_series_horizons`) extends series to the rolling horizon (`scheduling.series_horizon_months`, default 6).
- **Holidays:** "skip holidays" uses organisation-wide closure events (`CalendarEvent` type `holiday`, optionally per branch). E06 holiday calendars (Phase 2) can feed the same events.
- **Edits:** `this` marks the lesson as an exception. `following` splits the series (the old one ends the day before, the new one carries the remaining count). `all` applies from now. Time or rule changes rebuild affected future lessons. Other changes update them in place. Completed, cancelled and locked lessons never change. Exceptions are kept unless `overwrite_exceptions`.
- **Conflicts:** *hard* means a tutor is double-booked, busy at a calendar event or on approved time off, or the job's hours cap would be exceeded (when blocking). Time off is treated as hard (the spec lists only tutor/room overlap). *Soft* covers student clashes, outside availability, travel buffer, max weekly hours, closures and location opening hours. Hard conflicts return 422 with `conflicts` unless the user has `scheduling.override_conflicts` and sends `override_conflicts`. Series creation skips, creates anyway, or fails per `conflict_mode`. Series checks use one prefetched busy map instead of per-occurrence queries.
- **Availability:** weekly templates with effective dates (a new template closes the previous one), extra availability and time off. Time off is auto-approved; the approval workflow is T15/Phase 2. Free slots consider windows, lessons plus the travel buffer, events, time off, closures and minimum notice. External calendar busy times come with E22.
- **Calendar API:** `/calendar?start&end` (max 62 days) returns lessons and events in a light projection, filterable by tutor, student, client, service, job, location, branch and status. Tutors see their own lessons. Charge and pay fields on lessons follow `billing.rates.view_*`.
- **Locking:** `services.set_lock` is for E10/E12. Editing financial fields of a locked lesson needs `scheduling.edit_locked` (coordinators are denied it) and emits `lesson.locked_edited` with before/after totals for credit notes and pay adjustments.
- **E07 integration (T10):** scheduling registers the jobs `LessonsProvider` (stats, hours scheduled, replacement preview with clash check). Handlers: `job.created` with a default schedule creates weekly series; `job.tutor_replaced` moves future unlocked lessons and re-prices them; `job.tutor_assigned` fills tutorless future lessons; `job.status_changed` with `future_lessons=cancel` cancels future lessons (not chargeable) and ends series on completion or cancellation.
- **iCal:** per-user secret feeds for a tutor, a client (household) or a student. Only a SHA-256 hash is stored, and the URL is shown once. Creating a new feed revokes the previous one for the same subject. Served at `/ical/<token>.ics` on the organisation host (the last 60 days and onwards, UTC times, RFC 5545 line folding).
- **Notifications:** reschedule, cancel and update events carry `notify`. E13 sends the messages and updated ICS.
- **Frontend:** the calendar has day, week, month, agenda and tutor-resource views, filters (tutor, status), colour by service, tutor, status or location, click-to-create and drag-to-reschedule. Every lesson is a button that opens a quick view with complete/missed/cancel/reschedule (the keyboard alternative to dragging, WCAG 2.5.7), pricing trace and job link. There is a new lesson/weekly series dialog with conflict override. The availability page covers weekly windows, time off/extra availability and the calendar feed link. Saved filter sets, the secondary timezone display, the print/PDF timetable and bulk actions in the UI are follow-ups; the bulk API exists.
- **Fix:** OpenAPI component descriptions no longer inherit the serializer mixins' docstrings (`GET_LIB_DOC_EXCLUDES`).
- **Deferred (Phase 2):** rooms and exclusion constraint (T12), reschedule requests (T13), self-booking with holds and payment (T14), time-off approval and cover (T15), and the TW1 workflows for them.

## Phase 2 implementation notes (as built 2026-10-12)

Decisions: [ADR 0021](../adr/0021-phase-2-roles-pricing-rules-and-booking.md).

- **Rooms (T12):** `Lesson.room` (nullable) with the Postgres exclusion constraint `lesson_room_no_overlap` (`EXCLUDE USING gist (room_id WITH =, tstzrange(start, "end", '[)') WITH &&) WHERE room_id IS NOT NULL AND status <> 'cancelled'`). Expand/contract: migration 0003 adds the column (no backfill: existing lessons have no room), 0004 creates `btree_gist` (a trusted extension) and the constraint. The conflict engine reports `room_double_booked` (hard, and **not overridable**: the database would refuse it anyway) and `room_capacity`/`room_inactive` (soft); a constraint violation from a race becomes the same 422 conflict. A room sets the lesson's location (and must match it); moving to another location or online drops the room. Series accept `room` and skip occurrences whose room is taken. `/api/v1/calendar/rooms` and a **Rooms** calendar view (rooms as columns; drag is off there). Calendar items carry `room`/`room_name`; `/calendar` filters by `room`.
- **Reschedule requests (T13):** `RescheduleRequest` (lesson, requester client/tutor/staff/calendar, up to three proposed times, deadline, chosen option). One pending request per lesson (partial unique constraint). Policies (org settings): `scheduling.reschedule_requests`, `reschedule_min_notice_hours` (24), `reschedule_max_per_month` (2 per student, or per tutor for tutor requests; staff and calendar requests are exempt), `reschedule_decision_hours` (48). Deadline = earliest of now + window, the lesson start and the earliest proposed time. Approving moves the lesson through `update_lesson` (conflict checks; staff may override non-room conflicts). Who answers: staff with `scheduling.lesson.edit`, the lesson's tutor for a family's request, the family (portal) for a tutor's request; the requester can't answer their own. API: `POST /lessons/{id}/reschedule-requests` (tutor or staff), `/reschedule-requests` (list, decide, cancel); portal `POST /portal/lessons/{id}/reschedule`, `/portal/reschedule-requests` (+ decide, cancel).
- **E22 switch:** a lesson moved in a tutor's Google/Microsoft calendar without permission now becomes a reschedule request (`requester="calendar"`, staff decide) instead of a CRM task; the CRM task stays as the fallback when the request can't be made (one already pending, off-grid time, lesson started). See the updated E22 notes and ADR 0015.
- **Self-booking (T14):** `BookingSettings` (one row per org: enabled, new families allowed, minimum notice, maximum advance, slot interval, buffer, approval required, payment `none`/`at_booking`, hold minutes, cancellation window, offered tutors, location) and `BookingHold` (service, tutor, branch, time, student or new-family contact, promo code, price quote, status held → awaiting_payment / awaiting_approval → confirmed, or declined/expired/cancelled). Slots: the tutor's free slots (E08-T05) with the booking interval, buffer and notice, within the advance window, minus active holds; tutors are those offered and teaching the service's subject. Holding locks the candidate tutors' rows and re-checks the slot, so two people can't hold the same time; holds are **hard conflicts** (`slot_held`, not overridable) for staff scheduling too. "Any tutor" takes the first free one. Pressing **Book**: instant → the lesson is created (`created_via=client_booking`, the promo code kept on the attendee and redeemed once); approval → staff decide (`/booking/holds/{id}/decide`); payment at booking → the E11 hook `payments.services.request_booking_payment` (a payment request for the quoted price and the pay-page link; its `payment_request.paid` event signals the workflow). **Collections (E10 hook):** `billing.selectors.booking_block(client_id)` is checked when holding and when pressing Book: a `hard` block refuses online booking with a message to contact the organisation; `soft` or `hard` adds a soft `client_in_collections` warning when staff schedule. New families from the widget become a client, contact and student (`people.quick_add_family`) when the booking is paid for or confirmed. Trial pricing is the E06 first-lesson discount. Declined or expired holds cancel an unpaid payment request; money already paid stays as client credit (refunds stay a payments decision). The `cancellation_window_hours` setting is stored for E09/E15 policies but not yet enforced by them.
- **Booking APIs:** admin `/booking/settings`, `/booking/holds` (list, decide, cancel); portal `/portal/booking/{services,slots,holds,holds/{id}/submit,holds/{id}/cancel}`; public (website widget, tenant from the host, CORS from E24) `/public/booking/{services,slots,holds}`, `/public/booking/holds/{id}?token=` (+ `/submit`, `/cancel`). The token is returned once at hold time and stored hashed.
- **Time-off approval (T15):** a tutor asking for their own time off (with `scheduling.time_off_approval`, default on) creates a `requested` exception and `time_off.requested`; staff entering it approve it at once. Staff decide at `POST /time-off/{id}/decide` (not their own). Approval flags the tutor's planned future lessons in the period (`Lesson.cover_flagged_at`) and, with `scheduling.time_off_cover`, opens an E19 cover request (`matching.create_cover`, which starts `CoverRequestWorkflow`); if E19 refuses (too late, cover already being found) the lessons stay flagged for staff. `time_off.cover_flagged` reports it.
- **TW1 (Temporal):** `BookingHoldWorkflow` `booking-hold:{org}:{hold}` (started by `booking.held`; signals `submitted`, `paid` from `payment_request.paid`, `decided`, `cancelled`; releases at the hold expiry, re-checking the payment request in case the signal was missed; declines unapproved bookings at the lesson start or 48 hours), `RescheduleRequestWorkflow` `reschedule:{org}:{request}` (started by `reschedule.requested`; reminder to staff at half the window; declined at the deadline; signal `answered`) and `TimeOffApprovalWorkflow` `time-off:{org}:{exception}` (started by `time_off.requested`; reminder at half the time to the start; declined if still undecided when it starts; on approval runs `flag_cover`). Tests cover happy path, signals and timers, with recorded replay histories.
- **Notifications:** staff alerts `staff_time_off_requested`, `staff_reschedule_requested`, `staff_booking_requested` are registered from `scheduling/notifications.py` on the E13 registry. Family and tutor messages follow the lesson events E13 already sends. On-commit hooks capture the organisation id when registered.
- **Settings and events:** new org settings above; events `time_off.requested/approved/declined/cover_flagged`, `reschedule.requested/approved/declined`, `booking.held/submitted/requested/confirmed/declined` (the spec's `booking.approved` is `booking.confirmed`).
- **E24/E15 wiring:** the `booking` widget kind (`<tt-booking>`, options: services, tutor, show prices, days) is registered from `scheduling/widgets.py` and available when booking is enabled; the Lit widget books for new families (and shows the pay link). The client portal has a **Book** page and **Ask to move** on lessons, plus tutor requests to answer. Not built: a `booking` block for the website builder (sites still lists it as a future block).
- **Admin frontend:** **Requests** page (`/requests`: moves, bookings to approve, time off to approve), **Online booking** settings (`/settings/booking`), the Rooms calendar view.

## Gap backlog (as built 2026-10-14)

Batch G3 of `docs/05-gap-backlog.md`; design in [ADR 0037](../adr/0037-gap-batch-g3-scheduling-billing-payments-payroll.md).

- **Calendar (FR-08-7, FR-08-10; E08:144):** saved filter sets use the E05 saved views (`entity_type = "calendar"`: view, tutor, status, colour mode), private by default; a second time zone (viewer's choice, kept in the browser) adds an hour column to day/week/resource views and a second time in the agenda; **Print timetable** opens `GET /api/v1/calendar/timetable?start&end&tutor|student&timezone` (WeasyPrint PDF, at most 31 days, lessons by local day, no prices; a lesson in another zone also shows its own time); the agenda view has **Select lessons** with a bulk bar (complete, cancel, give to another tutor, change location, delete planned, export CSV with formula-safe cells) on the existing `/lessons/bulk`; lessons that fail stay selected.
- **Booking cancellation window (FR-08-9; E08:155):** `BookingSettings.cancellation_window_hours` is now enforced: a family can cancel a lesson they **booked online** (`created_via = client_booking`) in the portal only until that many hours before it starts (0 = until it starts); later, `POST /portal/lessons/{id}/cancel` refuses with `code = cancellation_window_closed` and the portal says to contact the organisation. `PortalLesson.cancel_online_until` gives the deadline. Staff-booked lessons and staff cancellations aren't limited (the cancellation policy still decides the fee). Deviation: reschedule requests aren't limited by this window (they have their own policy).
- **Website `booking` block (FR-24-4; E08:161):** registered from `scheduling/widgets.py` (heading, intro, days); renders `<tt-booking days=…>` when online booking is on (the page loads the widgets script; `BlockType.widget` now marks widget blocks, which also fixes the class catalogue block not loading it) and a "contact us" note otherwise, with the bookable services in `<noscript>`.
- **Release test fix (2026-10-30, TP-E08-025).** `lesson_booked`, `lesson_changed` and `lesson_cancelled` emails attach `lesson.ics` (`scheduling.ical.lesson_attachment`), with the same UID as the iCal feeds so the recipient's calendar updates the event it holds.
