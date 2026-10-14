# E16 — Tutor portal and mobile (PWA): manual tests

**Scope.** The tutor shell in the portal app (`/portal/tutor`): Today, Lessons (agenda), lesson page with register and report, Students, Availability and time off, Earnings and expenses, Profile and public profile, Checks (compliance), Jobs (offers, board, cover), Calendar and video, Notifications; Phase 2 PWA install, offline pack, outbox and background sync with conflict review, and Web Push. Phase 3 (E16-T11 Capacitor native shells and white-label apps) is being built now. Spec: [E16](../epics/E16-tutor-portal-mobile.md).

**Built differently from the spec (Implementation notes win):**
- The tutor shell lives in the portal app and is chosen by role; tutors who open the admin app are redirected to `/portal/tutor`.
- Agenda covers yesterday plus two weeks. Creating or rescheduling lessons from the tutor shell, conflict feedback, voice input, the previous report on the lesson page and full per-student lesson history are not built.
- The service worker is registered **in production builds only**: test offline and install against `pnpm --filter @tutortrack/portal build` + `vite preview` (port 5174), not the dev server. The family portal is online-only (offline banner, no cached API reads).
- Push needs VAPID keys (`cd backend && uv run python manage.py generate_vapid_keys`, put them in `.env`); without the private key `FakePush` records pushes instead of sending. Browsers need a secure context: `localhost`/`*.localhost` count as secure in Chrome.
- No push type for family contacts.

**Common preconditions.** Seed loaded; sign in as tutor@tutortrack.localhost (Nia Adeyemi) at http://brightminds.localhost:5174/portal/ (magic link) or at the admin `/login` with the seed password (redirects to the tutor shell). Nia has weekly Tuesday 16:30 GCSE Maths lessons with Arjun Patel and availability 15:00–20:00 on weekdays. Chrome DevTools → Application (Service workers, IndexedDB, Manifest) and Network → Offline are used for PWA cases.

## Tutor shell, Today and schedule (FR-16-1, FR-16-2, T01, T02)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E16-001 | Tutor lands on Today | Tutor (tutor@) | — | 1. Sign in. | Tutor shell with **Tutor menu** (Today, Lessons, Students, Availability, Earnings, Expenses, Profile, Getting started, Checks, Jobs, Calendar and video, Notifications). Today shows lessons, **Reports to write**, **Job offers**, **New notifications**, **Earned this month**. | P1 | backend: `test_today_students_and_earnings` | |
| TP-E16-002 | Tutor opening the admin app is redirected | Tutor | — | 1. Open http://brightminds.localhost:5173/. | Redirected to `/portal/tutor`. | P1 | e2e: `e2e/roles.spec.ts` | |
| TP-E16-003 | No lessons today | Tutor | A day with no lessons | 1. Open Today. | "No lessons today." | P3 | No | |
| TP-E16-004 | Lessons agenda | Tutor | — | 1. **Lessons**. | Yesterday plus the next two weeks of Nia's own lessons only. | P1 | backend: `test_tutors_only_reach_their_own_lessons` | |
| TP-E16-005 | Staff without a tutor profile | Coordinator | — | 1. Open `/portal/tutor`. | "There's no tutor profile for this login yet." API refuses. | P2 | backend: `test_staff_without_a_tutor_profile_are_refused` | |

## Lesson workflow (FR-16-3, T03)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E16-006 | Complete and write report in under 30 seconds | Tutor | Today's lesson already started | 1. Today → **Open and complete**.<br>2. **Register**: Arjun Present.<br>3. **Complete and write report**.<br>4. Fill fields, **Submit report**. | "Report submitted. Thank you!"; lesson Completed; whole flow takes under 30 s on a phone. | P1 | e2e: `e2e/portal-tutor.spec.ts` | |
| TP-E16-007 | Late arrival on the register | Tutor | — | 1. Set **Attendance for Arjun** Late, **Minutes late** 10. | Saved with 10 minutes. | P2 | No | |
| TP-E16-008 | Join link on the lesson page | Tutor | Online lesson with a meeting link (E22) | 1. Open the lesson. | Join link shown; notes for the tutor shown. | P2 | No | |
| TP-E16-009 | Tutor cancels with policy | Tutor | Tutor cancellation allowed (E03 tutor access toggle) | 1. **Cancel lesson** with a reason. | "The family and the office will be told."; cancelled by tutor; tutor policy applies (no charge, makeup credit if set). | P2 | No | |
| TP-E16-010 | Report renders every field type on a phone | Tutor | Template with all field types (E09 TP-E09-026) | 1. Open the report at 375 px width. | All fields usable; **Save draft** and **Submit report** work; topics/homework use "Separate items with commas". | P2 | No | |
| TP-E16-011 | AI drafts in the report | Tutor | AI features on (fake provider) | 1. Use the AI draft action in the report. | A draft appears for editing (E31). | P3 | No | |

## Students, availability, earnings, profile (FR-16-4 to FR-16-8, T04–T07)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E16-012 | My students | Tutor | — | 1. **Students**. | Arjun with "Next lesson: <when>"; no students from Sam Clarke's jobs. | P1 | backend: `test_today_students_and_earnings` | |
| TP-E16-013 | Edit weekly availability | Tutor | — | 1. **Availability** → **Weekly availability** → **Add a time** Saturday 09:00–12:00 → **Save availability**. | Saved; admin availability for Nia shows it; matching/booking uses it. | P1 | No | |
| TP-E16-014 | Add time off | Tutor | — | 1. **Time off**: **First day**, **Last day** → **Add time off**. | "Time off added."; lessons in that range flagged in admin. | P2 | No | |
| TP-E16-015 | Earnings this month | Tutor | Completed lessons | 1. **Earnings**: choose **Month**. | Per-lesson pay and "Total: £…"; provisional note; E12 statements once paid. | P1 | backend: `test_today_students_and_earnings` | |
| TP-E16-016 | Expense with camera receipt | Tutor | Phone or DevTools device mode | 1. **Expenses** → **New claim** → **Receipt photo** (camera opens on mobile). | Photo attached; claim sent (see E12). | P2 | No | |
| TP-E16-017 | Public profile edit needs approval | Tutor | — | 1. **Profile** → **Public profile**: **Headline**, **About me**, photo → **Save and submit**. | "Saved. Your changes will show once approved."; status "Waiting for approval" until staff approve (E24). | P2 | No | |
| TP-E16-018 | Compliance uploads with expiry | Tutor | — | 1. **Checks** → upload a DBS certificate with an expiry date. | Uploaded and pending review (E18). | P2 | No | |
| TP-E16-019 | Stripe payout setup entry point | Tutor | Method Stripe | 1. Earnings → Pay details → **Set up payouts with Stripe**. | Opens (fake) Express onboarding (E12). | P3 | No | |

## Jobs (FR-16-7, T10)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E16-020 | Accept a job offer | Tutor | Coordinator offers Ada's Physics job to Nia (E19) | 1. **Jobs** → **Job offers** → "Waiting for your answer, answer by …" → **Accept** with a message. | "You accepted"; coordinator notified; job updated. | P1 | No | |
| TP-E16-021 | Decline with a reason | Tutor | Another offer | 1. **Decline**, **Reason (optional)**. | "You declined". | P2 | No | |
| TP-E16-022 | Apply on the job board | Tutor | Posted job | 1. **Job board** → **Apply**. | "You've applied"; later "You got the job" / "Another tutor was chosen". | P2 | No | |
| TP-E16-023 | Take a cover request | Tutor | Cover request for Sam's lesson | 1. **Cover** → **I'll cover it**. | Nia assigned; status Covered. | P2 | No | |

## PWA, offline and sync (FR-16-3 offline, T08)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E16-024 | Install the PWA | Tutor | Production build served by `vite preview`; Chrome | 1. DevTools → Application → Manifest.<br>2. Install the app. | Manifest valid (name, icons 192/512 and maskable, "Today" shortcut, theme colour); installs even without a brand kit. Lighthouse PWA checks pass. | P1 | backend: `test_manifest_is_installable_without_a_brand_kit` | |
| TP-E16-025 | Offline pack caches next 7 days | Tutor | Signed in online for at least one load | 1. DevTools → Network → Offline.<br>2. Reload; open Lessons and a lesson 5 days ahead. | Shell loads; banner "You're offline."; lessons for yesterday and the next 7 days open with report forms; a lesson 10 days ahead shows "This lesson isn't saved on this phone." | P1 | backend: `test_offline_pack_has_the_next_week_with_report_forms`, `test_lessons_a_week_ahead_are_offline_but_not_the_past` | |
| TP-E16-026 | Complete and report offline, then sync | Tutor | Offline | 1. Complete a lesson offline.<br>2. Write and submit its report.<br>3. Go back online (or **Sync now**). | "Completed on this phone. It will sync…", "1 change is waiting to sync."; after reconnecting the lesson is completed and the report submitted once on the server. | P1 | backend: `test_replayed_completion_is_recorded_once`; frontend: `frontend/apps/portal/src/offline/outbox.test.ts` | |
| TP-E16-027 | Background sync with the app closed | Tutor | Offline change queued | 1. Close the tab; reconnect; wait. | Background Sync (`tutortrack-outbox`) replays it; admin shows the change. | P2 | No | |
| TP-E16-028 | Conflict needs review | Tutor, Coordinator | Report opened offline; coordinator edits the same report online | 1. Tutor edits offline and reconnects. | "Your changes need review" with the reason, **Open the lesson**, **Try again**, **Discard** (server returned 412). | P1 | backend: `test_reports_saved_offline_fail_on_conflict`, `test_completion_by_someone_else_needs_review` | |
| TP-E16-029 | Session expired while offline | Tutor | Queue a change, then sign out elsewhere/expire the session | 1. Reconnect. | "Sign in again to sync 1 change." Changes kept until sign-in. | P2 | No | |
| TP-E16-030 | Sign-out clears offline data | Tutor | Data cached | 1. Sign out.<br>2. Inspect IndexedDB and Cache Storage. | Outbox and API cache cleared; a different user signing in never sees Nia's data. | P1 | No | |
| TP-E16-031 | Offline pack is for tutors only | Parent | — | 1. GET `/api/v1/tutor/offline` as parent. | 403. Family portal offline shows "Reconnect to see the latest lessons…". | P2 | backend: `test_offline_pack_is_for_tutors_only` | |

## Web Push (FR-16-9, T09)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E16-032 | Turn on push for this device | Tutor | VAPID keys set | 1. **Notifications** → **Turn on notifications** → allow.<br>2. **Send a test notification**. | "Push notifications are on for this device."; "Sent to 1 device." and the notification appears. | P1 | backend: `test_subscribe_stores_the_endpoint_and_keys_encrypted`, `test_test_push_reaches_each_device` | |
| TP-E16-033 | Lesson change pushes to the tutor | Coordinator, Tutor | Device subscribed | 1. Coordinator moves Nia's lesson. | Push "lesson moved" opens the lesson in the portal. Also for job offer, cover request, report due/overdue, report comment and "Pay sent". | P1 | backend: `test_lesson_change_pushes_to_the_tutors_phone`, `test_pay_sent_pushes_to_the_tutor` | |
| TP-E16-034 | Per-category preferences | Tutor | — | 1. **What you hear about, and how**: turn Push off for Lesson reports. | No push for report reminders; other categories still push. | P2 | backend: `test_tutor_can_turn_push_off_per_category` | |
| TP-E16-035 | Devices list and removal | Tutor | Two devices | 1. **Devices with notifications on** → **Remove** one. | Removed; only own devices visible. | P2 | backend: `test_people_only_see_and_remove_their_own_devices` | |
| TP-E16-036 | Blocked, unsupported and iOS guidance | Tutor | Notifications blocked; Safari on iOS outside Home Screen | 1. Open Notifications. | "Notifications are blocked for this site…" / "This browser can't show push notifications." / "Add the app to your Home Screen first". | P3 | No | |
| TP-E16-037 | Push not configured | Tutor | No VAPID keys | 1. Open Notifications. | "Push notifications aren't available here yet." (FakePush records server-side). | P3 | backend: `test_config_gives_the_vapid_public_key` | |
| TP-E16-038 | Endpoints are secret and safe | Security reviewer | — | 1. Subscribe with a non-https or unknown push host via the API.<br>2. Read logs. | Refused; endpoints never logged or returned. Expired devices (404/410) removed. | P1 | backend: `test_only_known_push_services_are_accepted`, `test_endpoints_are_never_logged`, `test_expired_devices_are_forgotten` | |

## Phase 3 (E16-T11) — verify after the Phase 3 merge

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E16-039 | Generic native app with org picker (verify after the Phase 3 merge) | Tutor | Capacitor Android/iOS debug build | 1. Install the debug build; choose "Bright Minds Tutoring" in the org picker; sign in. | Tutor shell loads inside the native shell; same features as the PWA. | P2 | No (Phase 3) | |
| TP-E16-040 | Native push and deep links (verify after the Phase 3 merge) | Tutor | Native build | 1. Move a lesson; tap the notification. | Opens the lesson in the app. | P2 | No (Phase 3) | |
| TP-E16-041 | Offline in the native shell (verify after the Phase 3 merge) | Tutor | Native build, airplane mode | 1. Complete a lesson offline; reconnect. | Same outbox behaviour as TP-E16-026. | P2 | No (Phase 3) | |
| TP-E16-042 | White-label build pipeline (verify after the Phase 3 merge) | Platform staff | Enterprise tenant with brand assets | 1. Run the white-label pipeline for Bright Minds. | App built with the tenant's name, icon and colours; no TutorTrack branding; store signing needs real credentials (see traceability). | P3 | No (Phase 3) | |

## Permissions and tenant isolation

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E16-043 | Tutors reach only their own lessons | Tutor | Sam's lesson id | 1. Open `/portal/tutor/lessons/<Sam's lesson>`. | Not found. | P1 | backend: `test_tutors_only_reach_their_own_lessons` | |
| TP-E16-044 | Tutor login on another org's host | Tutor | — | 1. Open http://northside.localhost:5174/portal/tutor. | No Bright Minds data; no tutor profile message. | P1 | No | |

## Non-functional, accessibility and time zones

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E16-045 | Sync indicator is accessible | Tutor | Offline with queued changes | 1. Use a screen reader; check contrast. | Polite live region announces "You're offline" and counts; state in text not only colour; AA contrast; targets ≥ 32 px. | P1 | No | |
| TP-E16-046 | Time to interactive on mid-range Android | QA | Moto G class device or throttled Chrome (4G) | 1. Load Today. | Interactive in < 2.5 s. | P2 | No | |
| TP-E16-047 | Dark mode and large tap targets | Tutor | OS dark mode | 1. Use Today and a lesson. | Readable dark theme; tap targets large enough. | P3 | No | |
| TP-E16-048 | Lesson times in the tutor's zone | Tutor | Set Nia's timezone to Europe/Paris | 1. Open Today. | Times shown in Paris time; the 16:30 London lesson shows as 17:30. | P2 | No | |
