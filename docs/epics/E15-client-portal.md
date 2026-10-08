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
- [ ] **E15-T01** Portal shell, auth (magic link), branding at runtime, household scoping and isolation tests.
- [ ] **E15-T02** Dashboard and schedule views; ICS.
- [ ] **E15-T03** Cancellation and absence reporting with policy preview.
- [ ] **E15-T04** Reports feed and comments.
- [ ] **E15-T05** Billing: invoices, pay, payment methods, auto-pay consent, statements.
- [ ] **E15-T06** Profile, household, consents, sensitive data edits with staff alerts.
- [ ] **E15-T07** Announcements (news posts) admin + portal.
- [ ] **E15-T08** Org portal configuration toggles.
- [ ] **E15-T09** (Phase 2) Booking, reschedule, packages purchase, messaging.
