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
- [ ] **E16-T01** Tutor shell, navigation, Today screen.
- [ ] **E16-T02** Schedule views and permission-aware lesson actions.
- [ ] **E16-T03** Complete-lesson flow (attendance, report, expenses) optimised for mobile.
- [ ] **E16-T04** Students and lesson history views.
- [ ] **E16-T05** Availability editor and time-off requests.
- [ ] **E16-T06** Earnings, statements, expenses with camera upload.
- [ ] **E16-T07** Profile and compliance uploads; Stripe Connect onboarding entry point.
- [ ] **E16-T08** (Phase 2) PWA manifest, service worker, offline cache + background sync for completions/reports.
- [ ] **E16-T09** (Phase 2) Web Push subscriptions and delivery channel in E13.
- [ ] **E16-T10** (Phase 2) Job offers inbox and job board (with E19).
- [ ] **E16-T11** (Phase 3) Capacitor native shells and white-label build pipeline.
