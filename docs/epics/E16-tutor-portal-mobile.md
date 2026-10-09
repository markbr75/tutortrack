# E16 — Tutor Portal & Mobile Experience

| | |
|---|---|
| **Phase** | MVP (responsive web portal); Phase 2 (PWA push, offline, camera receipts); Phase 3 (native shells, white-label apps) |
| **Depends on** | E03, E05, E08, E09, E12, E13 |
| **Differentiator** | TutorBird has no app/push; TutorCruncher's mobile experience is limited |

## 1. Summary
The tutor's daily tool, optimised for phones: today's schedule, one-tap join/complete, attendance, lesson reports (offline-capable), availability and time off, student info (permission-limited), earnings and expenses, job offers, compliance uploads and messages. Delivered as an installable PWA shared with the client portal (role shell "Tutor").

## 2. Functional requirements

### FR-16-1 Tutor home ("Today")
- Today's lessons timeline with status chips, travel gaps, join button, "Complete" quick action, reports due count, unread messages, pending job offers, compliance alerts, this-month earnings.

### FR-16-2 Schedule
- Day/week/agenda views of own lessons and events; create/reschedule/cancel subject to E03 FR-03-6 permissions; conflict feedback; iCal subscribe; external calendar busy display (E22).

### FR-16-3 Lesson workflow
- Lesson detail: students (photo, key needs/SEN highlights if permitted), goals, previous report, homework status, materials, location (map deep link) or join link.
- Complete flow: attendance → duration adjust → report (template) → expenses → submit. Under 30 seconds for a simple lesson.
- **Offline:** lessons for the next 7 days cached; completion and reports can be done offline and queued (IndexedDB + background sync); conflicts are resolved server-side with a "your changes need review" message.
- Voice-to-text for report fields (browser speech API) and AI draft (E31).

### FR-16-4 Students
- My students list (active jobs), student profile (limited fields), lesson history, reports, progress (E21), message guardian (if allowed).

### FR-16-5 Availability and time off
- Weekly availability editor (tap/drag), exceptions, time-off requests with status.

### FR-16-6 Earnings and expenses
- E12 FR-12-9 views; expense claim with camera receipt capture; mileage claim with suggested distance.

### FR-16-7 Jobs marketplace
- Job offers inbox (accept/decline with reason), job board listings to apply for (E19), cover requests.

### FR-16-8 Profile and compliance
- Edit public profile (bio, photo, subjects: changes may require approval), qualifications, upload compliance documents (E18) with expiry, payout setup (Stripe Connect onboarding), bank details, tax info, self-billing agreement.

### FR-16-9 Push notifications (Phase 2)
- Web Push via VAPID for: lesson changes, new job offers, messages, report reminders, pay run paid. Per-category preferences. iOS 16.4+ home-screen PWA support with install guidance.

### FR-16-10 Native shells (Phase 3)
- Capacitor-wrapped apps for App Store / Play Store (generic "TutorTrack" app with org picker), then optional **white-label apps** per tenant (Enterprise add-on) built from a pipeline with tenant assets.

## 3. Non-functional
- PWA installable; Lighthouse PWA checks pass; offline shell; time to interactive < 2.5s on mid-range Android over 4G.
- Accessibility AA; large tap targets; dark mode.

## 4. Delivery plan
- [x] **E16-T01** Tutor shell, navigation, Today screen.
- [x] **E16-T02** Schedule views and permission-aware lesson actions.
- [x] **E16-T03** Complete-lesson flow (attendance, report, expenses) optimised for mobile.
- [x] **E16-T04** Students and lesson history views.
- [x] **E16-T05** Availability editor and time-off requests.
- [x] **E16-T06** Earnings, statements, expenses with camera upload.
- [x] **E16-T07** Profile and compliance uploads; Stripe Connect onboarding entry point.
- [ ] **E16-T08** (Phase 2) PWA manifest, service worker, offline cache + background sync for completions/reports.
- [ ] **E16-T09** (Phase 2) Web Push subscriptions and delivery channel in E13.
- [ ] **E16-T10** (Phase 2) Job offers inbox and job board (with E19).
- [ ] **E16-T11** (Phase 3) Capacitor native shells and white-label build pipeline.

## Implementation notes (as built 2026-10-10)
- **Shell (T01):** the tutor shell lives in the portal app (`/portal/tutor`), picked by the signed-in member's role (`/api/v1/me`). Tutors who open the admin app are redirected there. Today shows lessons with join and "open and complete", and counts of reports to write, job offers, unread notifications and this month's earnings (`/api/v1/tutor/today`).
- **Schedule and lesson actions (T02/T03):** the agenda covers yesterday plus the next two weeks from the calendar API, filtered to the tutor. The lesson page shows notes for the tutor and the join link. The complete flow is the register (outcome and minutes late per student), then "complete and write report", which opens the report straight away. Cancelling (when the tutor-access toggle allows it) records the tutor as the canceller, so the policy applies. Reports render every template field type on a phone, with draft and submit. Every action reuses the existing scheduling and delivery APIs, which already limit tutors to their own lessons (tested). Creating and rescheduling from the tutor shell, conflict feedback, voice input and the previous report on the lesson page are follow-ups.
- **Students (T04):** `/api/v1/tutor/students` lists students on the tutor's active jobs with their next lesson. A full lesson history per student is a follow-up.
- **Availability (T05):** weekly windows and time off, using the E08 APIs.
- **Earnings (T06):** `/api/v1/tutor/earnings` shows pay per delivered or paid-cancellation lesson for a month, provisional until payroll (E12) creates pay items. Expenses with receipt capture come with E12.
- **Profile (T07):** headline, phone and public bio. Compliance uploads (E18) and payout setup (E12) come with those epics.
- **Deferred:** PWA manifest, offline and background sync (T08), web push (T09), job offers inbox (T10, with E19), native shells (T11).
