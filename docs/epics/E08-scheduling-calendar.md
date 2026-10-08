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
- [ ] **E08-T01** Lesson, LessonTutor and LessonAttendee models; create/update services using the E06 rate engine snapshot.
- [ ] **E08-T02** Lesson series: RRULE expansion in local tz, horizon generation task, holiday skipping.
- [ ] **E08-T03** Series edit semantics (this / following / all) with exception preservation; tests for DST and splits.
- [ ] **E08-T04** Calendar events and org-wide closures.
- [ ] **E08-T05** Availability templates, exceptions, free-slot calculator.
- [ ] **E08-T06** Conflict engine (hard and soft), dry-run API, series conflict report.
- [ ] **E08-T07** Calendar range projection API, optimised queries and indexes.
- [ ] **E08-T08** Frontend calendar: views, filters, colour modes, drag/drop, quick-view, resource view.
- [ ] **E08-T09** Lesson actions and bulk actions; change notifications hook (E13).
- [ ] **E08-T10** Tutor replacement integration with E07; locking rules.
- [ ] **E08-T11** iCal feeds.
- [ ] **E08-T12** (Phase 2) Rooms with exclusion constraint; room resource view.
- [ ] **E08-T13** (Phase 2) Reschedule requests and policies.
- [ ] **E08-T14** (Phase 2) Self-booking engine, holds, booking settings, payment-at-booking hook (E11).
- [ ] **E08-T15** (Phase 2) Time-off approval workflow and cover flagging.
