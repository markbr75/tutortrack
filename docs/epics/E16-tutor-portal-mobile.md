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
- [x] **E16-T08** (Phase 2) PWA manifest, service worker, offline cache + background sync for completions/reports.
- [x] **E16-T09** (Phase 2) Web Push subscriptions and delivery channel in E13.
- [x] **E16-T10** (Phase 2) Job offers inbox and job board (with E19).
- [ ] **E16-T11** (Phase 3) Capacitor native shells and white-label build pipeline.

## Implementation notes (as built 2026-10-10)
- **Shell (T01):** the tutor shell lives in the portal app (`/portal/tutor`), picked by the signed-in member's role (`/api/v1/me`). Tutors who open the admin app are redirected there. Today shows lessons with join and "open and complete", and counts of reports to write, job offers, unread notifications and this month's earnings (`/api/v1/tutor/today`).
- **Schedule and lesson actions (T02/T03):** the agenda covers yesterday plus the next two weeks from the calendar API, filtered to the tutor. The lesson page shows notes for the tutor and the join link. The complete flow is the register (outcome and minutes late per student), then "complete and write report", which opens the report straight away. Cancelling (when the tutor-access toggle allows it) records the tutor as the canceller, so the policy applies. Reports render every template field type on a phone, with draft and submit. Every action reuses the existing scheduling and delivery APIs, which already limit tutors to their own lessons (tested). Creating and rescheduling from the tutor shell, conflict feedback, voice input and the previous report on the lesson page are follow-ups.
- **Students (T04):** `/api/v1/tutor/students` lists students on the tutor's active jobs with their next lesson. A full lesson history per student is a follow-up.
- **Availability (T05):** weekly windows and time off, using the E08 APIs.
- **Earnings (T06):** `/api/v1/tutor/earnings` shows pay per delivered or paid-cancellation lesson for a month, provisional until payroll (E12) creates pay items. Expenses with receipt capture come with E12.
- **Profile (T07):** headline, phone and public bio. Compliance uploads (E18) and payout setup (E12) come with those epics.
- **Deferred:** PWA manifest, offline and background sync (T08), web push (T09), native shells (T11). The job offers inbox (T10) arrived with E19: `/portal/tutor/jobs`.

## Phase 2 implementation notes (as built 2026-10-13)
See ADR 0023. T11 (Capacitor native shells, white-label apps) is Phase 3 and was not built.

- **Manifest (T08):** the E24 tenant manifest (`/api/v1/public/manifest`) now has `id`, a description, `lang`, categories and a "Today" shortcut. The portal's own 192/512 and maskable icons are always listed after the brand kit's icon, so the app installs without a brand kit. `index.html` links the manifest and sets `theme-color` (the brand colour once branding loads), Apple meta tags and an apple-touch-icon.
- **Service worker (T08):** a small hand-written worker (`frontend/apps/portal/src/sw/sw.ts`), not Workbox. A Vite plugin builds it to `/portal/sw.js` with the precache list of the build and a version. It is registered in production builds only. It precaches the app shell and serves navigations network-first, with the cached shell when offline. Hashed assets and icons are cache-first. API reads are network-first with a 4-second timeout and a cached copy offline, but only for the tutor allowlist in `offline/routes.ts`: `/me`, `/tutor/*`, a lesson, its reports and join link, a report, `/calendar`, branding and push config. The family portal is online-only: its API reads are never cached, and it shows an offline banner. CloudFront has its own behaviour for `/portal/sw.js` with caching turned off.
- **Offline data (FR-16-3):** `GET /api/v1/tutor/offline` is the offline pack: yesterday's and the next 7 days' lessons, with attendees and the tutor's report (answers and `etag`). When no report is open yet, it has the fields of the template the report will use, so `open_report` is not called just to cache a form. The tutor shell warms the pack and each lesson's detail through the worker at most every 30 minutes.
- **Outbox and background sync (T08):** completions and report saves made offline, or whose request failed with no response, go to an IndexedDB outbox (`offline/outbox.ts`, shared by the page and the worker). They are replayed in order on start-up, on `online`, from "Sync now" and by Background Sync (`tutortrack-outbox`) in the worker when the app is closed. Replays are idempotent. Every request carries `Idempotency-Key` = the item id (the same key as the first online attempt), so a completion whose response was lost is answered from the stored response (`Idempotent-Replayed`) and recorded once (tested). Later changes for a lesson wait while its earlier change is still pending. Several report saves for one lesson merge into the latest answers. A report started offline is opened on the server (get-or-create) when it syncs.
- **Conflicts (FR-16-3):** report reads now return an `ETag`. `PUT /lesson-reports/{id}` and `POST …/submit` accept `If-Match` and return 412 when the report changed since (backward compatible: without the header nothing changes). The outbox sends the version the tutor started from. A 412, or any other refusal (for example a lesson already completed by the office), puts the change in "Your changes need review", with the server's reason, "Open the lesson", "Try again" and "Discard". A draft 412 whose answers the server already has counts as synced. 401, or a CSRF failure, keeps the changes and asks the tutor to sign in again. The worker replays with the CSRF token captured at queue time. The page uses the current cookie.
- **Indicator (T08, WCAG 2.2 AA):** under the tutor header, a polite live region shows "You're offline", "N changes are waiting to sync", the sign-in prompt and the review list. The state is in text, not colour alone. The amber-950 on amber-50/100 colours meet AA, and the targets are at least 32px. The lesson page shows "Completed on this phone" and hides the register while the completion waits.
- **Privacy:** sign-out clears the outbox and the API cache. If a different user signs in on the device, the previous user's offline data is cleared first (`tt-offline-user`).
- **Web Push (T09):** `comms.PushSubscription` stores the endpoint, `p256dh` and `auth` encrypted (`EncryptedField`), plus an `endpoint_hash` for upserts, the push service host and the device name. Endpoints are never returned, logged or put in errors. Endpoints must be https on a known push service (`WEB_PUSH["ALLOWED_HOSTS"]`: FCM, Mozilla, Windows, Apple) and are posted through `core.net.safe_urlopen`. `pywebpush==2.5.0` (aes128gcm encryption) and `py_vapid` (VAPID signing) are used only for crypto. VAPID keys are set in `VAPID_PUBLIC_KEY`/`VAPID_PRIVATE_KEY` (`manage.py generate_vapid_keys`). Without a private key, `FakePush` records pushes. API: `GET/POST /api/v1/push-subscriptions`, `GET/DELETE …/{id}` (own devices only), `GET …/config`, `POST …/test`.
- **Push channel in E13 (T09):** `push` is a channel wherever `in_app` is (`registry.register`). It is on by default for the FR-16-9 types: lesson moved or cancelled, job offer, cover request, report due or overdue, report comment, and the new `payout_paid` ("Pay sent", from `payout.paid`). A push is created only when the user has a device. It uses the in-app wording unless the organisation edits a push template. It opens the tutor's lesson or report in the portal. Devices that answer 404/410 are removed (`push_subscription.removed`, reason `expired`). Devices that fail 5 times in a row are removed too. Pushes about scheduling are sent with `Urgency: high`. A `Topic` collapses repeats.
- **Preferences (FR-16-9):** `GET/PUT /api/v1/communication-preferences/mine` lets the signed-in tutor (or staff user) choose channels per category. Channels the screen doesn't offer keep their old setting. The portal's `/tutor/notifications` page turns push on or off for this device, sends a test, lists and removes devices, and edits the category channels. On iOS outside the Home Screen app, it shows "Add to Home Screen" guidance (iOS 16.4+).
- **Deviations:** FR-16-9 "messages" has no push type yet, because there is no tutor messaging app. Family contacts don't get pushes, because contacts have no portal user on the notification recipient. Organisations that customised a type's channels before this release must add push themselves. Voice input and AI drafts (FR-16-3) are still follow-ups.
