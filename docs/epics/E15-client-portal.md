# E15 — Client & Student Portal

| | |
|---|---|
| **Phase** | MVP (booking/rescheduling in Phase 2) |
| **Depends on** | E03, E05, E08–E11, E13 |
| **Parity** | TutorBird student portal (schedule, pay, notes, homework, book/cancel); TutorCruncher client dashboard (lesson reports, invoices, payments) |

## 1. Summary
A branded, mobile-first portal (same PWA as E16, role shell "Client" and "Student") where parents/bill-payers and students see schedules, join online lessons, read reports, pay invoices, manage payment methods, buy packages, book/reschedule/cancel within policy, message the business, and manage profiles and consents.

## 2. Functional requirements

### FR-15-1 Access
- Invitation from E05 (contact/student) or self-registration via the public enquiry/booking flow (E17/E24). Magic-link default; password/passkey optional.
- Household switcher if a contact has several clients (rare) or across orgs (multi-org user).
- Student logins: own data only; under-13 students only with guardian-managed credentials (setting) and limited features (no messaging unless allowed).
- Portal fully disabled-able per org; per-feature toggles (see FR-15-10).

### FR-15-2 Home dashboard
- Next lesson card (time in viewer tz, tutor, location/join button active 10 min before), upcoming week, balance/amount due with Pay now, latest reports, homework due (E21), messages, announcements (org news posts, TutorBird "news" parity).

### FR-15-3 Schedule
- List and calendar views of lessons for all students in the household; filters by student; add to calendar (ICS per lesson + subscribe feed); lesson detail (tutor, location map, join link, notes for client, materials).

### FR-15-4 Cancellations and rescheduling (policy-aware)
- Cancel a lesson: shows the policy outcome (fee or free, makeup credit) before confirming (E09).
- Reschedule request / instant reschedule into tutor's free slots (Phase 2, E08 FR-08-8).
- Notify absence ("Sam is ill today") → records `absent_notified` with policy.

### FR-15-5 Booking (Phase 2)
- Book additional lessons, trial lessons, makeup lessons (using makeup credits) and class enrolments (E20) via the E08 self-booking engine; payment at booking or package deduction.

### FR-15-6 Lesson reports and progress
- Reports feed (shared fields only), per-student filters, comment/reply on reports, progress dashboard (E21: goals, attendance %, assessments).

### FR-15-7 Billing
- Balance summary (amount due, credit, package hours remaining), invoices (view, PDF, pay), payment requests, credit notes, statements, receipts.
- Payment methods: add/remove card or DD mandate, set default, enable/disable auto-pay with consent text.
- Buy packages (E10) and top up credit (custom amount if allowed).

### FR-15-8 Profile and household
- Edit contact details, add another guardian (invite), student details (fields editable by client per custom field config), addresses, emergency contacts, medical/SEN info (writes to sensitive fields; staff notified of changes), communication preferences, consents (photo, data processing, marketing, terms) with version history, documents to sign (E05 FR-05-9).

### FR-15-9 Messaging
- Conversation with the business and (if allowed) tutors (E13 inbox), with attachments.

### FR-15-10 Org configuration
- Toggles: show tutor contact details, allow cancellations, allow reschedule requests, allow booking, show prices, show invoices, show lesson reports, allow messaging tutors, allow profile edits, show package balances, show charge breakdown.
- Custom welcome text, help links, terms URL.

### FR-15-11 Branding
- Tenant logo, colours, custom domain (`portal.brightminds.co.uk`, E24), favicon, app name in PWA manifest.

## 3. API
Portal endpoints are the standard `/api/v1/*` resources scoped by role (`own` household), plus convenience endpoints: `/api/v1/portal/dashboard`, `/portal/schedule`, `/portal/billing/summary`, `/portal/announcements`.

## 4. Permissions
Client role (household scope), Student role (self scope). All endpoints covered by isolation tests ensuring household A cannot access household B, including via guessed UUIDs.

## 5. Non-functional
- Lighthouse mobile score ≥ 90 (performance, accessibility).
- Works on 3G: dashboard payload < 50KB.

## 6. Delivery plan
- [x] **E15-T01** Portal shell, auth (magic link), branding at runtime, household scoping and isolation tests.
- [x] **E15-T02** Dashboard and schedule views; ICS.
- [x] **E15-T03** Cancellation and absence reporting with policy preview.
- [x] **E15-T04** Reports feed and comments.
- [x] **E15-T05** Billing: invoices, pay, payment methods, auto-pay consent, statements.
- [x] **E15-T06** Profile, household, consents, sensitive data edits with staff alerts.
- [x] **E15-T07** Announcements (news posts) admin + portal.
- [x] **E15-T08** Org portal configuration toggles.
- [ ] **E15-T09** (Phase 2) Booking, reschedule, packages purchase, messaging.

## Implementation notes (as built 2026-10-10)
- **Where it lives:** the `apps/portal` SPA, served at `/portal/` on the organisation's host, so sign-in, sessions, magic links and tenant resolution are shared with the admin app. A CloudFront viewer-request function sends portal deep links to `/portal/index.html`. Admin users with the client or student role are redirected to `/portal/`. The tutor shell and PWA install come with E16. Backend app: `tutortrack.portal`.
- **Access (T01):** staff invite a contact (`POST /contacts/{id}/portal-invite`, client role) or a student (`/students/{id}/portal-invite` with an email, student role). Accepting links the login to the contact or student (`user.joined` → `people.link_portal_user`). Sign-in is the existing magic link (`next=/portal/`). Every portal endpoint starts from `household_for(user)`: a parent sees all clients their contact records belong to and those clients' students; a student sees only themselves. Anything outside is a 404 (isolation tests with guessed ids). Staff APIs stay closed to client and student roles. Guardian-managed under-13 logins, the household switcher UI and passkeys are follow-ups.
- **Dashboard and schedule (T02):** next lesson (join button from 10 minutes before), the week ahead, amount due with pay link, latest reports and news. The schedule covers all household students with a student filter, and lessons can be downloaded as ICS (subscription feeds already exist from E08). Families see no internal notes or pay; tutor email and phone only with `portal.show_tutor_contact`.
- **Cancel and absence (T03):** cancel with the E09 policy preview (cancelled by the client). "Can't make it" for one student: a lesson only for them is cancelled under the policy; in a group lesson they are marked `absent_notified` with the policy's charge (new `scheduling.set_expected_absence`), and the register starts with that outcome when the tutor completes. The tutor is told (`attendance.absence_notified` → comms).
- **Reports (T04):** shared reports only, with fields filtered for the client or student audience. Replies are client-visible comments, and the tutor is notified (`report_comment`).
- **Billing (T05):** balances per account, invoices (no drafts or voids) with PDF and pay links to the E11 pay page, top-up requests, credit notes, statement PDF, and payment methods (add opens the E11 setup page with auto-pay consent; default, remove, turn auto-pay off). Package purchase is Phase 2.
- **Profile (T06):** the parent edits their name, phone, mobile and what they receive (`receives_*`); students' preferred name, school, year group and support needs. Changing support needs alerts staff (`staff_profile_change`). Consents use the existing `/me/consents` (E29). Inviting another guardian and document signing are follow-ups.
- **News (T07):** `Announcement` (families, tutors or everyone; publish and expiry dates). Staff manage it at `/announcements` (admin "News"); the portal shows family and everyone posts.
- **Configuration (T08):** the `portal.*` settings: enabled, cancellations, absences, invoices, reports, profile edits, tutor contact, prices, welcome text, help and terms links. Branding currently uses the organisation's name and primary colour; logo, custom domains and the PWA manifest come with E16 and E24.
- **Infra fix:** CloudFront now also routes `/webhooks/*` and `/ical/*` to the API (they previously fell through to the SPA bucket).
- **Deferred (Phase 2):** booking, reschedule requests, package purchase and messaging (T09).
