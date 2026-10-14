# E08 — Scheduling, calendar and availability: manual tests

**Scope.** Lessons (one-off and weekly series, 1:1 and group) priced through the E06 engine, series edits (this / following / all), calendar events and org-wide closures, tutor availability and time off, free-slot calculation, the conflict engine (hard and soft), the calendar UI (day/week/month/agenda/tutors/rooms views, filters, colour modes, drag to reschedule, quick view), lesson actions and bulk actions, locking, iCal feeds, and Phase 2: rooms with an exclusion constraint, reschedule requests, self-booking (portal and public widget) with holds and payment at booking, time-off approval with cover flagging, and the Temporal workflows `BookingHoldWorkflow`, `RescheduleRequestWorkflow` and `TimeOffApprovalWorkflow`. Spec: [E08](../epics/E08-scheduling-calendar.md).

**Built differently from the spec:** RRULEs are limited to daily/weekly/monthly; approved time off is a **hard** conflict; room double-booking is hard and **not overridable**; holds are hard conflicts (`slot_held`) for staff too; "skip holidays" uses org-wide closure events (and E06 holiday calendars marked skip); the calendar has no saved filter sets, secondary timezone, print/PDF timetable or bulk-action UI yet (the bulk API exists); the New lesson dialog only builds **weekly** series (other rules via `POST /api/v1/lesson-series`); series edits with a scope are API-only (`PATCH /api/v1/lesson-series/<id>` with `scope=this|following|all`); `booking.approved` is called `booking.confirmed`; the `cancellation_window_hours` booking setting is stored but not enforced; there is no website-builder booking block (the `<tt-booking>` widget exists).

**Common preconditions.** brightminds seed: Nia Adeyemi and Sam Clarke (if active) available Mon–Fri 15:00–20:00 Europe/London; Arjun's weekly **Tuesday 16:30** GCSE Maths series with Nia (60 min); org-wide **Christmas closure** 24 Dec–2 Jan; locations Leeds Centre / Online; course class "Saturday 10am" (E20). Workers running (Celery + Temporal). To avoid time-of-day surprises, schedule test lessons at fixed local times (e.g. 10:00 or 17:00 London, 5-minute steps) on a date at least 2 days ahead. Admin → **Calendar** (`/calendar`), **Availability** (`/availability`), **Requests** (`/requests`), **Online booking** (`/settings/booking`). Portal → **Book** (`/portal/book`), **Schedule** (`/portal/schedule`).

## Lessons and series

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E08-001 | Schedule a one-off lesson | Coordinator | — | 1. Calendar → click an empty slot (or **New lesson**): Service GCSE Maths 1:1, Tutor Nia Adeyemi, Student 1 Maya Patel, 60 minutes, next Wednesday 17:00 → **Schedule lesson**. | Lesson appears in the week view at 17:00 with the service colour; quick view shows Nia, Maya, Planned, price trace. | P1 | backend: `tutortrack/scheduling/tests/test_scheduling.py` | |
| TP-E08-002 | Schedule a weekly series | Coordinator | — | 1. **New lesson** → tick **Repeat weekly**, On Mon and Thu, Ends **After a number of lessons** 6 → **Schedule series**. | 6 lessons created on Mondays and Thursdays at the chosen time; "Created 6 lessons; 0 skipped…". | P1 | backend: `tutortrack/scheduling/tests/test_scheduling.py`; e2e: `e2e/jobs-scheduling.spec.ts` | |
| TP-E08-003 | Series ending on a date / rolling horizon | Coordinator | — | 1. Series ending **On a date** in 3 months.<br>2. Series with no end via API (`until` empty). | 1: lessons up to the last date. 2: lessons up to 6 months ahead (`scheduling.series_horizon_months`), extended nightly by `extend_all_series_horizons`. | P2 | backend: `tutortrack/scheduling/tests/test_scheduling.py` | |
| TP-E08-004 | Series skips closures | Coordinator | Christmas closure | 1. Weekly series across late December with skip holidays. | No lessons between 24 Dec and 2 Jan; the result reports the skipped dates. | P1 | backend: `tutortrack/scheduling/tests/test_scheduling.py` | |
| TP-E08-005 | DST: local time is kept | Coordinator | Weekly 16:00 series spanning the last Sunday of October | 1. Look at lessons before and after the change. | All at 16:00 Europe/London. A user with timezone America/New_York sees 11:00 / 12:00 correctly shifted. | P1 | backend: `tutortrack/scheduling/tests/test_scheduling.py` | |
| TP-E08-006 | Duration rules | Coordinator | — | 1. Try 3 minutes, 13 hours, 62 minutes. | Refused: min 5 min, max 12 h, 5-minute steps. | P2 | backend: `tutortrack/scheduling/tests/test_scheduling.py` | |
| TP-E08-007 | Group lesson capacity | Coordinator | 11+ group class (max 8) | 1. Schedule a lesson with 3 students from different families.<br>2. Try a 9th student. | 3 attendees, each charged £20 separately; 9th refused. | P1 | backend: `tutortrack/scheduling/tests/test_scheduling.py` | |
| TP-E08-008 | Lesson from a job uses job rates and people | Coordinator | Arjun's job | 1. Schedule a lesson from the job (or check a series lesson). | Tutor, student and job rate copied; snapshot stored on attendee/tutor lines. | P1 | backend: `tutortrack/scheduling/tests/test_scheduling.py` | |
| TP-E08-009 | Edit "this lesson" only | Coordinator | Arjun's series | 1. `PATCH /api/v1/lesson-series/<id>` scope `this` on one occurrence moving it to 17:30 (or reschedule it from the quick view). | Only that lesson moves and is marked as an exception. | P1 | backend: `tutortrack/scheduling/tests/test_scheduling.py` | |
| TP-E08-010 | Edit "all future": 16:30 → 17:00 (AC) | Coordinator | One lesson completed, one invoiced (locked), one moved exception | 1. PATCH the series scope `all` with start time 17:00. | Future unlocked lessons move to 17:00; completed and invoiced ones untouched; the moved exception is kept unless `overwrite_exceptions`. | P1 | backend: `tutortrack/scheduling/tests/test_scheduling.py` | |
| TP-E08-011 | Edit "this and following" splits the series | Coordinator | — | 1. PATCH scope `following` from the 4th occurrence, new weekday. | The old series ends the day before; a new series carries the rest. | P2 | backend: `tutortrack/scheduling/tests/test_scheduling.py` | |
| TP-E08-012 | Invalid RRULE refused | Coordinator | Swagger | 1. `POST /api/v1/lesson-series` with `FREQ=HOURLY` or `BYHOUR`. | 400 with a clear message. | P3 | backend: `tutortrack/scheduling/tests/test_scheduling.py` | |
| TP-E08-013 | A year of weekly lessons is fast | Coordinator | — | 1. Create a weekly series for 52 weeks. | Created in well under a second (one batch). | P3 | backend: `tutortrack/scheduling/tests/test_scheduling.py` | |

## Conflicts

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E08-014 | Tutor double-booking is hard | Coordinator | Nia's lesson next Tuesday 16:30 | 1. Schedule another lesson for Nia next Tuesday 16:45. | **Scheduling conflict** listing the clash; not saved. | P1 | backend: `tutortrack/scheduling/tests/test_scheduling.py` | |
| TP-E08-015 | Override a hard conflict | Owner | As above | 1. Press **Schedule anyway**. | Saved: Owner, Admin and Coordinator hold `scheduling.override_conflicts`; tutors never get the option. | P2 | backend: `tutortrack/scheduling/tests/test_scheduling.py` | |
| TP-E08-016 | Soft conflicts warn | Coordinator | — | 1. Schedule Nia at 21:00 (outside availability).<br>2. Schedule Arjun with Sam at the same time as his Nia lesson. | Warnings (outside availability, student clash) but saving is allowed. | P1 | backend: `tutortrack/scheduling/tests/test_scheduling.py` | |
| TP-E08-017 | Conflict dry run | Coordinator | Swagger | 1. `POST /api/v1/conflicts/check` for a clashing time. | Lists hard and soft conflicts without saving. | P3 | backend: `tutortrack/scheduling/tests/test_scheduling.py` | |
| TP-E08-018 | Series reports clashes per occurrence | Coordinator | Series overlapping an existing lesson once | 1. Create via API with `conflict_mode` skip, then create, then fail. | skip: clashing date skipped and reported; create: all created; fail: nothing created, 422 with conflicts. | P2 | backend: `tutortrack/scheduling/tests/test_scheduling.py` | |
| TP-E08-019 | Blocked event makes the tutor busy | Coordinator | — | 1. Add a Blocked event for Nia next Wednesday 16:00–18:00 (`POST /api/v1/events`).<br>2. Schedule her at 17:00 that day. | Hard conflict. | P2 | backend: `tutortrack/scheduling/tests/test_scheduling.py` | |
| TP-E08-020 | Location opening hours warning | Coordinator | Leeds Centre opening hours 09:00–18:00 | 1. Schedule at Leeds Centre 19:00. | Soft warning "outside opening hours". | P3 | backend: `tutortrack/scheduling/tests/test_scheduling.py` | |

## Calendar UI

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E08-021 | Views and navigation | Coordinator | — | 1. Switch **Day**, **Week**, **Month**, **Agenda**, **Tutors**, **Rooms**.<br>2. Use **Previous**, **Next**, **Today**. | Each view renders; Month shows "+N more" overflow; Tutors view shows tutors as columns; "Nothing scheduled." for empty ranges. | P1 | e2e: `e2e/jobs-scheduling.spec.ts` | |
| TP-E08-022 | Filters and colour modes | Coordinator | — | 1. Filter Tutor = Nia, Status = Planned.<br>2. **Colour by** Service, Tutor, Status, Location. | Only matching items; colours change with a legend; status never relies on colour alone. | P2 | No | |
| TP-E08-023 | Quick view actions | Coordinator | A planned lesson | 1. Click the lesson.<br>2. Check **How this was priced**, **Open the job**.<br>3. **Mark completed** on a past lesson; **Mark missed** on another. | Popover with tutors, students, where, status; trace shown; status updates on the calendar. | P1 | e2e: `e2e/delivery.spec.ts` | |
| TP-E08-024 | Cancel a lesson | Coordinator | Future lesson | 1. Quick view → **Cancel lesson**, Reason "Illness", untick **Charge for this cancellation** → **Cancel lesson**. | Status Cancelled; not chargeable; family/tutor notified (E13); the time is free again. | P1 | backend: `tutortrack/scheduling/tests/test_scheduling.py` | |
| TP-E08-025 | Reschedule from the quick view (keyboard) | Coordinator | Future lesson | 1. **Reschedule** → Date, From, To → **Move lesson**. | Lesson moves; conflicts checked; `rescheduled_from` recorded; notification with updated ICS. Works without a mouse (WCAG 2.5.7). | P1 | No | |
| TP-E08-026 | Drag to reschedule | Coordinator | Week view | 1. Drag a lesson to another slot. | Moves after conflict check; drag is disabled in the Rooms view. | P2 | No | |
| TP-E08-027 | Calendar range limit and tutor scope | Tutor | tutor@ via API | 1. `GET /api/v1/calendar?start=…&end=…` for 70 days.<br>2. For 7 days. | 70 days refused (max 62); 7 days returns only Nia's lessons and her events, no charge fields. | P2 | backend: `tutortrack/scheduling/tests/test_scheduling.py` | |
| TP-E08-028 | Locked lesson banner | Coordinator | Invoiced lesson | 1. Open its quick view. | "This lesson is invoiced or paid…"; financial fields and time can't be changed by a coordinator. | P1 | backend: `tutortrack/scheduling/tests/test_scheduling.py` | |
| TP-E08-029 | Editing a locked lesson emits an adjustment | Owner | Invoiced lesson | 1. Change its duration (owner has `scheduling.edit_locked`). | Saved; `lesson.locked_edited` with before/after totals (E10 credit note / E12 pay adjustment). | P2 | backend: `tutortrack/scheduling/tests/test_scheduling.py` | |
| TP-E08-030 | Bulk actions (API) | Coordinator | Three planned lessons | 1. Bulk cancel via the lessons bulk endpoint. | All three cancelled; per-lesson errors reported. | P3 | backend: `tutortrack/scheduling/tests/test_scheduling.py` | |

## Events and closures

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E08-031 | Org-wide closure cancels lessons | Owner | Lessons on a future date | 1. Create a Holiday (closure) event, org-wide, covering that date (API `/api/v1/events`). | Shows for everyone as **Closure**; lessons in range cancelled as not chargeable. | P1 | backend: `tutortrack/scheduling/tests/test_scheduling.py` | |
| TP-E08-032 | Meeting / training events | Owner | — | 1. Add a paid Training event with Nia as participant. | Shows in her calendar as Training; pay item available to payroll (E12). | P3 | No | |

## Availability and time off

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E08-033 | Set weekly availability | Tutor | tutor@ (portal **Availability** or admin `/availability`) | 1. **Add a time** Saturday 09:00–12:00, How: Online only.<br>2. Applies from next Monday → **Save availability**. | "Availability saved."; the previous template closes the day before. | P1 | backend: `tutortrack/scheduling/tests/test_scheduling.py` | |
| TP-E08-034 | Free slots respect lessons, buffer and time off | Coordinator | Nia with a 16:30 lesson, travel buffer 15 min | 1. `GET /api/v1/availability/<Nia>/slots?duration=60&from=…&to=…`. | Slots exclude 16:15–17:45 around the lesson, time off and closures, and anything inside minimum notice. | P1 | backend: `tutortrack/scheduling/tests/test_scheduling.py` | |
| TP-E08-035 | Staff-entered time off is approved at once | Coordinator | — | 1. Availability → **Time off and extra availability** for Nia: Type Time off, next Friday → **Add**. | Approved; "N planned lessons clash" shown; those lessons flagged for cover. | P1 | backend: `tutortrack/scheduling/tests/test_phase2.py` | |
| TP-E08-036 | Tutor time off waits for approval | Tutor, Coordinator | `scheduling.time_off_approval` on (default) | 1. As tutor@ request time off next Thursday.<br>2. As coordinator@ open **Requests** → **Time off to approve** → **Approve**. | Request listed with "Approving flags this tutor's lessons…"; on approval lessons are flagged and (with `scheduling.time_off_cover`) a cover request opens (E19). Workflow `time-off:<org>:<id>` completes. | P1 | backend: `tutortrack/scheduling/tests/test_workflows.py` | |
| TP-E08-037 | Undecided time off is declined when it starts | Tutor | Request for tomorrow left undecided | 1. Check Temporal UI for the workflow and its reminder timer. | Reminder at half the time to the start; declined automatically at the start (verify via timer in the UI or the replay test). | P3 | backend: `tutortrack/scheduling/tests/test_workflows.py` | |
| TP-E08-038 | Staff can't approve their own time off | Coordinator | coordinator@ with a tutor profile | 1. Try to decide own request. | Refused. | P3 | backend: `tutortrack/scheduling/tests/test_phase2.py` | |

## Rooms (Phase 2)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E08-039 | Room double-booking is refused | Owner | Room 1 at Leeds Centre (E06) | 1. Book two overlapping lessons in Room 1.<br>2. Try **Schedule anyway** as owner. | Hard conflict `room_double_booked`, not overridable (the database constraint refuses it too). | P1 | backend: `tutortrack/scheduling/tests/test_phase2.py` | |
| TP-E08-040 | Room capacity is a warning | Coordinator | Room capacity 2 | 1. Book a group lesson with 3 students in it. | Soft warning `room_capacity`; saved. | P2 | backend: `tutortrack/scheduling/tests/test_phase2.py` | |
| TP-E08-041 | Room sets the location | Coordinator | — | 1. Choose Room 1, then switch the lesson to Online. | Location becomes Leeds Centre; switching online drops the room. | P3 | backend: `tutortrack/scheduling/tests/test_phase2.py` | |
| TP-E08-042 | Rooms view | Coordinator | Lessons in rooms | 1. Calendar → **Rooms**. | Rooms as columns with their lessons; drag is off. | P2 | backend: `tutortrack/scheduling/tests/test_phase2.py` | |

## Reschedule requests (Phase 2)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E08-043 | Family asks to move; staff approve | Parent, Coordinator | parent@; Arjun's lesson more than 24 h away | 1. Portal → Schedule → **Ask to move** → New time (up to three) → **Send request**.<br>2. Admin → **Requests** → "asked by the family" → **Approve** (Move to …). | "Request sent."; staff see the deadline "Declined automatically at …"; approving moves the lesson through the normal conflict checks. Workflow `reschedule:<org>:<id>` ends. | P1 | backend: `tutortrack/scheduling/tests/test_phase2.py` | |
| TP-E08-044 | Tutor answers a family request | Tutor | Request on Nia's lesson | 1. As tutor@ approve in the portal. | Lesson moved; the family can't answer its own request. | P2 | backend: `tutortrack/scheduling/tests/test_phase2.py` | |
| TP-E08-045 | Tutor asks; the family answers | Tutor, Parent | — | 1. As tutor@ request a move.<br>2. As parent@ portal → "Your tutor asks to move…" → **Accept**. | Lesson moved. **Decline** leaves it unchanged. | P2 | backend: `tutortrack/scheduling/tests/test_phase2.py` | |
| TP-E08-046 | Policies: notice and monthly limit | Parent | `reschedule_min_notice_hours` 24, `reschedule_max_per_month` 2 | 1. Ask to move a lesson starting in 12 hours.<br>2. Make a third request this month for Arjun. | Both refused with the policy reason; only one pending request per lesson. | P2 | backend: `tutortrack/scheduling/tests/test_phase2.py` | |
| TP-E08-047 | Unanswered request is declined at the deadline | Parent | Request near its deadline | 1. Watch Temporal UI / wait for the deadline. | Reminder to staff at half the window; declined at the deadline; requester notified. | P3 | backend: `tutortrack/scheduling/tests/test_workflows.py` | |

## Self-booking (Phase 2)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E08-048 | Configure online booking | Owner | — | 1. **Online booking** → **Turn on online booking**, Minimum notice 24, Book up to 30 days, Start times every 30, Gap 15, Hold 10 min, Payment **Pay later** → **Save**. | "Saved."; the portal shows **Book**; the `booking` widget kind becomes available. | P1 | backend: `tutortrack/scheduling/tests/test_phase2.py` | |
| TP-E08-049 | Instant booking from the portal | Parent | Booking on, no approval, pay later | 1. Portal → **Book** → Lesson GCSE Maths 1:1, Tutor **Any tutor**, Show times from next week → pick a time → **Book**. | "Held for you"/"We're holding this time…" then "You're booked. We've added it to…"; lesson created with `created_via=client_booking`; the slot disappears for others. | P1 | backend: `tutortrack/scheduling/tests/test_phase2.py` | |
| TP-E08-050 | Booking needing approval | Parent, Coordinator | **Bookings need our approval** on | 1. Book as parent@.<br>2. Admin **Requests** → **Online bookings to approve** → **Approve**. | Parent sees "Thanks! We'll confirm your booking…"; after approval "You're booked"; decline shows "Sorry, we couldn't accept this booking". | P1 | backend: `tutortrack/scheduling/tests/test_phase2.py` | |
| TP-E08-051 | Pay at booking (fake Stripe) | Parent | Payment **Pay when booking**; fake payments provider (E11) | 1. Book → **Pay now** → complete the fake payment on `/pay/<token>`. | Status "Please pay to confirm your booking" until paid, then confirmed; the hold workflow receives `paid`. | P1 | backend: `tutortrack/scheduling/tests/test_workflows.py` | |
| TP-E08-052 | Unpaid hold expires | Parent | Hold 10 minutes | 1. Book with pay-at-booking and don't pay for 10+ minutes. | "The time we held has run out."; the slot is free again; the payment request is cancelled. | P2 | backend: `tutortrack/scheduling/tests/test_workflows.py` | |
| TP-E08-053 | Two people can't hold the same time | Parent, Coordinator | A held slot | 1. As coordinator@ schedule a lesson for that tutor at that time. | Hard conflict `slot_held`, not overridable. | P2 | backend: `tutortrack/scheduling/tests/test_phase2.py` | |
| TP-E08-054 | Public widget booking for a new family with a promo code | Anonymous | **New families can book from the website** on; widget dev server (`pnpm --filter @tutortrack/widgets dev`, :5175) with a `<tt-booking>` embed | 1. Pick a service and time, enter family details and promo code SPRING10, **Book**. | New client, contact and student created when confirmed (or paid); promo applied once. | P2 | backend: `tutortrack/scheduling/tests/test_phase2.py` | |
| TP-E08-055 | Families in collections can't book online | Parent | Patel family under a hard collections block (E10) | 1. Try to book. | Refused with "contact the organisation"; staff scheduling shows a soft `client_in_collections` warning. | P2 | backend: `tutortrack/scheduling/tests/test_phase2.py` | |
| TP-E08-056 | Booking disabled offers nothing | Parent | Booking off | 1. Open **Book**. | "Online booking isn't available yet…". | P3 | backend: `tutortrack/scheduling/tests/test_phase2.py` | |

## iCal feeds

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E08-057 | Create and subscribe to a tutor feed | Tutor | tutor@ | 1. Availability → **Calendar feed** → **Create feed link**.<br>2. Open the URL (`/ical/<token>.ics`) or add it to a calendar app. | Valid ICS with Nia's lessons from the last 60 days on, in UTC; the URL is shown once. | P2 | backend: `tutortrack/scheduling/tests/test_scheduling.py` | |
| TP-E08-058 | Creating a new feed revokes the old one | Tutor | Existing feed | 1. Create a new link; open the old URL. | Old URL 404; new one works. | P2 | backend: `tutortrack/scheduling/tests/test_scheduling.py` | |
| TP-E08-059 | Household and student feeds | Parent | parent@ | 1. Create a feed from the portal (if offered) or `POST /api/v1/ical-feeds` for the household. | Only the Patel family's lessons. | P3 | No | |

## Permissions

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E08-060 | Tutor sees only their own lessons | Tutor | tutor@ | 1. Open the tutor schedule (portal) and `GET /api/v1/lessons`.<br>2. `GET /api/v1/lessons/<a Sam lesson id>`. | Only Nia's lessons; Sam's lesson 404. | P1 | backend: `tutortrack/scheduling/tests/test_scheduling.py`; e2e: `e2e/portal-tutor.spec.ts` | |
| TP-E08-061 | Tutor toggles for create/cancel | Tutor | Defaults (create off, cancel off, reschedule on) | 1. Try to create and cancel a lesson as tutor@; then move one. | Create and cancel refused; move allowed. | P1 | backend: `tutortrack/identity/tests/test_rbac.py` | |
| TP-E08-062 | Coordinators can't edit locked lessons | Coordinator | Invoiced lesson | 1. Change its time. | 403 (`scheduling.edit_locked` denied). | P1 | backend: `tutortrack/scheduling/tests/test_scheduling.py` | |
| TP-E08-063 | Booking settings need permission | Coordinator, Finance | — | 1. Open `/settings/booking` as each. | Coordinator (`scheduling.*`) allowed; Finance has no Calendar or Online booking nav and the API 403. | P2 | No | |
| TP-E08-064 | Charge fields follow rate permissions | Tutor, Coordinator | — | 1. Compare `/api/v1/calendar` items as tutor@ and coordinator@. | Tutor: no charge amounts. Coordinator: charge but no pay amounts. | P1 | backend: `tutortrack/scheduling/tests/test_scheduling.py` | |

## Tenant isolation

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E08-065 | Calendar shows only own organisation | Owner | A northside lesson for Noah | 1. Open the brightminds calendar for that week. | Not shown; `GET /api/v1/lessons/<northside lesson>` is 404. | P1 | No | |
| TP-E08-066 | Public booking resolves the tenant from the host | Anonymous | — | 1. Call `/api/v1/public/booking/services` on brightminds and northside hosts. | Each returns only its own bookable services. | P2 | No | |

## i18n and edge cases

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E08-067 | Viewer timezone vs lesson timezone | Coordinator | Account timezone Australia/Sydney | 1. Open the week with Arjun's Tuesday 16:30 London lesson. | Shown at the correct Sydney time (next day early morning); the lesson's own timezone is shown when different. | P1 | No | |
| TP-E08-068 | Week start follows the organisation | Owner | US org (Sunday start) vs GB (Monday) | 1. Open Week view. | Week starts on the org's week start day; dates in the locale format. | P3 | No | |
| TP-E08-069 | Nonexistent local time at the spring change | Coordinator | Weekly series at 01:30 London across the last Sunday in March | 1. Look at the clock-change Sunday. | That occurrence moves forward to 02:30 BST (01:30 does not exist that night); it is not dropped. | P3 | backend: `tutortrack/core/tests/test_time.py` | |
