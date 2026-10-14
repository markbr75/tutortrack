# E15 — Client and student portal: manual tests

**Scope.** The family and student portal at `/portal/`: access by invitation and magic link, household scoping, dashboard, schedule and ICS, policy-aware cancellation and absence, reports feed with replies, billing (invoices, pay, payment methods, auto-pay, statements, packages), profile and sensitive edits, news posts, org portal settings, and Phase 2 booking, reschedule requests, makeup credits and messaging. Spec: [E15](../epics/E15-client-portal.md).

**Built differently from the spec (Implementation notes win):**
- The portal is one SPA at `/portal/` on the organisation's host (dev: http://brightminds.localhost:5174/portal/), sharing the session with the admin app. Staff users with the client or student role who open the admin app are redirected to `/portal/`.
- Sign-in on the portal page is a magic link ("Email me a sign-in link"; the link is in Mailpit). Seeded portal users can also sign in with a password at the admin `/login` page and are redirected to the portal.
- Not built: guardian-managed under-13 logins, household switcher UI, passkeys for portal users, inviting another guardian, document signing in the portal.
- Portal settings (`portal.*`: enabled, cancellations, absences, invoices, reports, profile edits, tutor contact, prices, welcome text, help and terms links, `allow_messaging`, `allow_messaging_tutors`, `allow_student_messaging`, `show_package_balances`) have **no admin screen**: use `PATCH /api/v1/settings/portal`.
- Branding uses the org name and primary colour (logo and custom domain via E24).

**Common preconditions.** Seed loaded with portal accounts: parent@tutortrack.localhost (Priya Patel: Arjun Year 10, Maya Year 7), student@tutortrack.localhost (Arjun). Arjun has weekly Tuesday 16:30 GCSE Maths lessons with Nia. Okafor family has its own lessons and invoices (for isolation checks). Screens: `/portal/` (Home), `/portal/schedule` (Lessons), `/portal/reports`, `/portal/billing` (Payments), `/portal/profile` (Details), `/portal/book`, `/portal/classes`, `/portal/messages`, `/portal/learning`, `/portal/referrals`, `/portal/privacy`; admin `/announcements` (News).

## Access and household scoping (FR-15-1, T01)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E15-001 | Invite a contact to the portal | Coordinator (coordinator@) | Okafor contact Tom without a login | 1. Client Okafor → Tom → **Invite to portal**.<br>2. Open the email in Mailpit; accept with a password. | "Invitation sent." Accepting creates a login linked to Tom; he lands on `/portal/`. | P1 | backend: `test_invite_links_the_login_to_the_contact` | |
| TP-E15-002 | Magic-link sign-in | Parent (parent@) | — | 1. Open `/portal/`, enter the email, **Email me a sign-in link**.<br>2. Open the link from Mailpit. | "Check your email: we sent a sign-in link to …"; the link signs in to the Home page. | P1 | No | |
| TP-E15-003 | Password sign-in redirects to the portal | Parent | — | 1. Admin `/login` with parent@ and the seed password. | Redirected to `/portal/`. | P1 | e2e: `e2e/roles.spec.ts` | |
| TP-E15-004 | Households can't see each other (guessed ids) | Parent | Okafor lesson, invoice and report ids | 1. Call `/api/v1/portal/...` endpoints with Okafor ids. | 404 every time. | P1 | backend: `test_households_cannot_see_each_other` | |
| TP-E15-005 | Student sees only themselves | Student (student@) | — | 1. Sign in; open Lessons and Reports. | Only Arjun's lessons and reports (not Maya's); no Payments menu. | P1 | backend: `test_student_logins_see_only_themselves` | |
| TP-E15-006 | Staff APIs closed to portal roles | Parent | — | 1. Call `/api/v1/clients` and `/api/v1/invoices`. | 403. | P1 | backend: `test_households_cannot_see_each_other`; e2e: `e2e/roles.spec.ts` | |
| TP-E15-007 | Staff opening the portal | Coordinator | — | 1. Open `/portal/` as a coordinator. | "This area is for families and students." with **Go to the main app** (tutors get the tutor shell, E16). | P2 | No | |
| TP-E15-008 | Portal switched off | Owner | `portal.enabled` false | 1. Parent opens the portal. | Portal unavailable message; API refuses. | P2 | backend: `test_announcements_and_portal_switch` | |

## Dashboard, schedule and cancellations (FR-15-2 to FR-15-4, T02, T03)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E15-009 | Home dashboard | Parent | Upcoming lessons, an unpaid invoice, a shared report, a news post | 1. Open Home. | **Next lesson** (time in the viewer's zone, tutor), **This week**, "You owe £…" with **Pay now**, **Latest reports**, **News**. | P1 | backend: `test_me_and_dashboard` | |
| TP-E15-010 | Join button for online lessons | Parent | Online lesson starting in 15 min (E22 meeting link) | 1. Open Home. | "Join opens at <time>" until 10 min before, then **Join the lesson** is active. | P2 | No | |
| TP-E15-011 | Schedule for all students with a filter | Parent | Lessons for Arjun and Maya | 1. Lessons page; filter by Maya. | Both students by default; filter shows only Maya. No internal notes or tutor pay. | P1 | backend: `test_me_and_dashboard`; e2e: `e2e/portal-parent.spec.ts` | |
| TP-E15-012 | Add to calendar (ICS) | Parent | — | 1. **Add to calendar** on a lesson. | An `.ics` downloads with the correct local time and timezone. | P2 | No | |
| TP-E15-013 | Tutor contact details hidden by default | Parent | `portal.show_tutor_contact` off, then on | 1. Open a lesson. | Off: no tutor email/phone. On: shown. | P2 | No | |
| TP-E15-014 | Cancel with the policy preview | Parent | 24 h policy; lesson in ~10 h | 1. Lessons → lesson → **Cancel lesson**.<br>2. Read the fee, **Confirm cancellation** (or **Keep the lesson**). | Fee shown before confirming; lesson Cancelled; late cancellation charge created (E09 AC). | P1 | backend: `test_cancel_with_policy_preview` | |
| TP-E15-015 | Report an absence in a group lesson | Parent | Arjun in a group class session | 1. **Can't make it** → **Who can't come** Arjun → note → **Tell the tutor**. | Arjun marked Absent (told us) with the policy charge; the register starts with that outcome; tutor notified. | P2 | backend: `test_absence_in_a_group_lesson_carries_into_the_register` | |
| TP-E15-016 | Cancellations turned off | Parent | `portal.allow_cancellations` off | 1. Open a lesson. | No **Cancel lesson** button; API refuses. | P2 | No | |

## Reports (FR-15-6, T04)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E15-017 | Reports feed shows shared fields only | Parent | Shared report with staff-only Private notes | 1. Reports page. | Client-visible fields only; private notes never shown. "No reports yet." when empty. | P1 | backend: `test_reports_feed_hides_staff_fields_and_takes_replies`; e2e: `e2e/portal-tutor.spec.ts` | |
| TP-E15-018 | Reply to the tutor | Parent | Shared report | 1. **Reply to the tutor** → text → **Send reply**. | Reply appears; Nia is notified (`report_comment`); staff see it as a client-visible comment. | P2 | backend: `test_reports_feed_hides_staff_fields_and_takes_replies` | |
| TP-E15-019 | Progress and homework (E21) | Parent, Student | Seed homework "Fractions worksheet", goal "Grade 7 in GCSE Maths" | 1. Open `/portal/learning`. | Homework due, goal and milestones, mock result shown for Arjun. | P2 | No | |

## Billing (FR-15-7, T05)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E15-020 | Balances and invoices | Parent | Issued, paid and draft invoices; a voided one | 1. Payments page. | **Owed**, **Overdue**, **Credit**; invoices Unpaid / Partly paid / Paid / Closed with **PDF** and **Pay**; drafts and voids never shown. | P1 | backend: `test_billing_payment_methods_and_statement`; e2e: `e2e/portal-parent.spec.ts` | |
| TP-E15-021 | Pay an invoice from the portal (fake PayPal) | Parent | PayPal connected (fake, see E11) | 1. **Pay** on an unpaid invoice.<br>2. Complete on the pay page. | Returns "Thank you – your payment has been received."; invoice Paid in the portal and admin. | P1 | e2e: `e2e/portal-parent.spec.ts` | |
| TP-E15-022 | Statement PDF and credit notes | Parent | History | 1. **Download a statement (PDF)**; view **Credit notes**. | PDF matches the admin statement; credit notes listed. | P2 | backend: `test_billing_payment_methods_and_statement` | |
| TP-E15-023 | Payment methods and auto-pay | Parent | Stripe or GoCardless connected | 1. **Add a card or direct debit** (opens the E11 setup page).<br>2. **Make default**; **Stop paying automatically**. | Method listed; "Invoices are paid automatically (since …)" then "Invoices are not paid automatically." | P2 | backend: `test_billing_payment_methods_and_statement` | |
| TP-E15-024 | Top-up requests | Parent | Open payment request | 1. **Top-up requests** → **Pay**. | Opens the pay page for the request. | P2 | No | |
| TP-E15-025 | Buy a package | Parent | Package "10 hours of tuition" bookable online; `portal.show_package_balances` on | 1. **Buy a package** → choose → **For** Arjun → **Buy**. | Invoice created and the pay page opens; package "awaiting payment" until paid, then "10 of 10 hours left, expires …". | P2 | backend: `test_portal_shows_and_sells_packages` | |
| TP-E15-026 | Invoices hidden by setting | Parent | `portal.show_invoices` off | 1. Open Payments. | Invoices hidden. | P3 | No | |

## Profile, news and settings (FR-15-8, FR-15-10, T06–T08)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E15-027 | Edit contact details and what to receive | Parent | — | 1. Details → change **Mobile**; untick **News and offers** → **Save**. | "Saved."; admin contact shows the change (audited). | P1 | backend: `test_profile_edits_and_sensitive_alert` | |
| TP-E15-028 | Sensitive support needs alert staff | Parent | — | 1. Edit Arjun's **Learning needs, medical or support information** → Save. | Saved; staff get `staff_profile_change`; only staff and Arjun's tutors see the field. | P1 | backend: `test_profile_edits_and_sensitive_alert` | |
| TP-E15-029 | Profile edits turned off | Parent | `portal.allow_profile_edits` off | 1. Open Details. | Fields read-only. | P3 | No | |
| TP-E15-030 | Consents with history | Parent | — | 1. `/portal/privacy`: change marketing consent. | New consent record with version; history kept (E29). | P2 | No | |
| TP-E15-031 | Publish a news post | Coordinator | — | 1. `/announcements` → **New post**: **Title**, **Message**, **Who sees it** Families, publish date today, expiry next week → **Publish**. | Shown on the parent's Home under News; not in the tutor shell. After expiry it disappears. | P2 | backend: `test_announcements_and_portal_switch` | |
| TP-E15-032 | Welcome text, help and terms links | Owner | Set `portal.welcome_text`, help and terms URLs | 1. Open the portal. | Welcome text and **Help** / **Terms** links shown. | P3 | No | |
| TP-E15-033 | Branding | Owner | Primary colour set in E24 brand kit | 1. Open the portal. | Org name and colour applied; "Powered by" footer. | P3 | No | |

## Phase 2: booking, reschedule, makeups, messaging (FR-15-5, FR-15-9, T09)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E15-034 | Book a lesson | Parent | Online booking on (E08 `/settings/booking`); Nia free 15:00–20:00 weekdays | 1. **Book** → **Lesson** GCSE Maths 1:1 → **Tutor** Nia → pick a free time → **Book**. | "We're holding this time for you until …", then "You're booked. We've added it to your schedule." (or awaiting payment / approval per settings). | P1 | No | |
| TP-E15-035 | Book a makeup with a credit | Parent | Unused makeup credit for Arjun | 1. Book page → **Use a makeup credit** → "For <lesson> (use by …)". | Price shown as free; booking uses the credit; no charge. A used or other household's credit is refused. | P1 | backend: `test_a_makeup_lesson_is_free_and_uses_the_credit`, `test_credits_of_other_households_and_used_credits_are_refused` | |
| TP-E15-036 | Ask to move a lesson | Parent | — | 1. Lesson → **Ask to move** → **New time** → **Send request**. | "Request sent."; lesson stays until accepted; staff/tutor see the request (`/requests`). | P2 | No | |
| TP-E15-037 | Answer a tutor's move request | Parent | Nia asked to move a lesson | 1. **Requests to move a lesson** → **Accept** (or **Decline**). | Lesson moved or unchanged accordingly. | P2 | No | |
| TP-E15-038 | Enrol in a class | Parent | Course "Year 6 11+ Prep", class "Saturday 10am" open | 1. `/portal/classes` → enrol Maya. | Enrolment created (and invoice/payment per E20 settings). | P2 | No | |
| TP-E15-039 | Message the office with an attachment | Parent | `portal.allow_messaging` on | 1. Messages → **New message** → **To** The office, subject, text, **Attach files** → **Send**. | Thread appears in admin `/inbox`; attachment visible; staff reply appears in the portal. | P1 | backend: `test_families_message_the_business` | |
| TP-E15-040 | Message a tutor when allowed | Parent | `portal.allow_messaging_tutors` on | 1. New message → **To** Nia. | Thread with Nia; staff can see it. Off: Nia not offered. | P2 | backend: `test_families_and_tutors_message_each_other_when_allowed` | |
| TP-E15-041 | Students message only when allowed | Student | `portal.allow_student_messaging` off, then on | 1. Open Messages. | Off: "Messaging isn't available." On: can message. | P2 | backend: `test_students_message_only_when_allowed` | |
| TP-E15-042 | Messaging turned off | Parent | `portal.allow_messaging` off | 1. Open Messages. | Menu item hidden; API refuses. | P3 | backend: `test_messaging_can_be_turned_off` | |
| TP-E15-043 | Households can't see each other's conversations | Parent | Okafor thread id | 1. Open `/api/v1/portal/threads/<id>`. | 404. | P1 | backend: `test_households_cannot_see_each_others_conversations` | |

## Tenant isolation

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E15-044 | Portal login doesn't work on another org's host | Parent | — | 1. Open http://northside.localhost:5174/portal/ and sign in as parent@. | No household; no Bright Minds data; a clear "no access" message. | P1 | No | |
| TP-E15-045 | Northside family never sees Bright Minds data | Northside contact (invite Olivia Northside first) | — | 1. Sign in at Northside's portal; call portal endpoints with Bright Minds ids. | 404. | P1 | No | |

## i18n, time zones, mobile and performance

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E15-046 | Lesson times in the viewer's zone | Parent | Set Priya's timezone to America/New_York | 1. Open Home and Lessons. | Times shown in New York time with the zone visible; ICS has the right UTC instant. | P2 | No | |
| TP-E15-047 | Money and date formats | Parent | en-GB | 1. Check amounts and dates. | £ with two decimals; dates like 14 Oct 2026; no hard-coded formats. | P2 | No | |
| TP-E15-048 | Mobile layout | Parent | Phone width 375 px | 1. Use every portal page. | No horizontal scroll; menu "Portal menu" works; tap targets ≥ 24 px. | P1 | No | |
| TP-E15-049 | Lighthouse mobile ≥ 90 and small payload | QA | Production build | 1. Run Lighthouse (mobile) on Home.<br>2. Check `/api/v1/portal/dashboard` size. | Performance and accessibility ≥ 90; dashboard payload < 50 KB. | P2 | No | |
