# End-to-end business journeys

These journeys follow real work across several epics. Each one checks that the hand-offs between modules work: events, workflows, money and permissions. Run them after the per-epic P1 cases pass, on a freshly seeded stack with the Celery and Temporal workers running (see [README.md](README.md)).

- **Steps** cite the per-epic cases they exercise. Open that case for the detailed steps and expected result. The journey adds the checkpoints between the cases.
- **Result:** record one result per journey (Pass, Fail, Blocked or N/A, with initials and date) in the table at the end, and the failing step number if it fails.
- **Automated** names the Playwright spec that covers part of the journey. No spec covers a whole journey, so run each one by hand before a release.
- Use a new, uniquely named family or tutor for each run (for example add today's date to the surname). Then runs don't collide with seed data.

| ID | Journey | Priority |
|---|---|---|
| J01 | New business: signup to first paid invoice and tutor pay | P1 |
| J02 | Enquiry to active job: form, pipeline, proposal, matching | P1 |
| J03 | Lesson delivered: register, report, feedback, invoice, payment | P1 |
| J04 | Tutor pay run to accounting sync | P1 |
| J05 | Group classes: term, enrolment, register, rollover | P1 |
| J06 | Safeguarding concern, data request and erasure | P1 |
| J07 | Broadcast, inbox reply and AI suggested reply | P2 |
| J08 | Move from a competitor: import, reconcile, cutover | P1 |
| J09 | Custom domain website and widgets | P2 |
| J10 | Our subscription: trial, paid, dunning, recovery | P1 |
| J11 | Platform operations: health, support and SaaS metrics | P2 |
| J12 | Tutor recruitment to active tutor | P1 |
| J13 | Reviews, referrals and affiliate commission | P2 |
| J14 | Reporting and a scheduled report | P2 |
| J15 | Public API key and webhooks | P2 |
| J16 | Automation rule end to end | P2 |
| J17 | Tenant isolation sweep | P1 |
| J18 | Phase 3 features | P2 |

---

## J01 — New business: signup to first paid invoice and tutor pay

**Goal:** a new tutoring business can sign up, set up and get paid in one sitting (Phase 1 exit criteria).
**Roles:** new owner, new tutor (invited), parent (portal).
**Preconditions:** Mailpit open; Celery and Temporal workers running; no existing account for the emails you use.

1. Sign up "Riverside Tutors" with a new email; verify the email from Mailpit (TP-E02-001, TP-E02-002).
2. Complete the setup wizard: country GB, services, a tutor invitation (TP-E02-011, TP-E02-012, TP-E02-013). Check the trial: Agency plan, 30 days (TP-E04-001).
3. In the catalogue, create a per-hour service with charge and pay rates and check a price (TP-E06-006, TP-E06-007, TP-E06-020).
4. The invited tutor accepts the invitation and sets availability (TP-E03-033, TP-E08-033).
5. Add a family with one student (TP-E05-001), then **Set up lessons** with the tutor on a weekly slot (TP-E07-001, TP-E08-002).
6. Invite the parent to the portal; the parent signs in by magic link (TP-E05-009, TP-E15-002).
7. The tutor completes the first lesson and writes the report (TP-E16-006, TP-E09-030).
8. Run **Invoice now** for the family and issue the invoice (TP-E10-010, TP-E10-016). The email arrives in Mailpit with the PDF (TP-E10-018).
9. Connect PayPal (fake) (TP-E11-007), then the parent pays in the portal (TP-E15-021, TP-E11-022).
10. The lesson's pay item appears; create, approve and mark paid a pay run (TP-E12-006, TP-E12-021, TP-E12-024).

**Checkpoints:**
- After step 7, the lesson is Completed and one charge exists (TP-E10-001).
- After step 9, the invoice is Paid, the ledger balance is £0.00 and the portal shows the payment.
- After step 10, the tutor sees the statement on **Earnings** (TP-E12-031).
- The audit log shows every change (TP-E01-023).

**Automated (in part):** `e2e/catalogue.spec.ts`, `e2e/people.spec.ts`, `e2e/jobs-scheduling.spec.ts`, `e2e/delivery.spec.ts`, `e2e/billing.spec.ts`, `e2e/portal-parent.spec.ts`.

## J02 — Enquiry to active job: form, pipeline, proposal, matching

**Goal:** a family's enquiry becomes an active job with the right tutor.
**Roles:** prospective parent (public), coordinator (coordinator@), tutor (tutor@ / Nia).
**Preconditions:** an enquiry form exists (TP-E17-001). Nia's Maths GCSE subject is approved and she is active (TP-E05-017, TP-E18-037).

1. Submit the public form at `/f/<slug>` (or through the enquiry form widget, TP-E24-023); the family and enquiry are created (TP-E17-003). The acknowledgement and owner notice arrive (TP-E17-004).
2. On the pipeline board, move the card with "Move to" (keyboard) (TP-E17-020). Book and record a free trial lesson (TP-E17-027, TP-E17-029).
3. Draft and send a proposal; open the public proposal page; accept with a chosen tutor and pay the deposit (fake provider) (TP-E17-044, TP-E17-047, TP-E17-048, TP-E17-049).
4. Convert to a client if not already converted (TP-E17-030); check the job.
5. From the job, **Find a tutor**: search, shortlist, share the shortlist with the family, and the family chooses (TP-E19-001, TP-E19-014, TP-E19-035, TP-E19-037). Or send a sequential offer that Nia accepts in the portal (TP-E19-015, TP-E19-018, TP-E16-020).
6. The job becomes Active and the weekly lessons appear on the calendar (TP-E07-008, TP-E08-008).

**Checkpoints:**
- No internal fields (pay rates, notes) appear on the public proposal or shortlist pages.
- The enquiry is "Won", and the funnel report counts it (TP-E17-053).
- The family has exactly one client record, with no duplicate (TP-E17-011).

**Automated (in part):** `e2e/leads.spec.ts`, `e2e/jobs-scheduling.spec.ts`.

## J03 — Lesson delivered: register, report, feedback, invoice, payment

**Goal:** a delivered lesson flows through to money in, with the family informed.
**Roles:** tutor (tutor@), coordinator, finance (finance@), parent (parent@).
**Preconditions:** a past planned lesson for Arjun with Nia (or create one). Feedback requests turned on (TP-E09-049) with a short delay.

1. The tutor opens **Today** in the portal, completes the lesson and writes the report (TP-E16-001, TP-E16-006, TP-E09-029, TP-E09-030).
2. If approval is on, the coordinator approves and shares the report (TP-E09-034); the parent sees the shared fields only (TP-E15-017, TP-E09-035).
3. The feedback request email arrives; answer the public feedback page; a low score alerts staff (TP-E09-050, TP-E09-051, TP-E09-053).
4. Finance runs the monthly invoice run, reviews and issues (TP-E10-011, TP-E10-014, TP-E10-016).
5. The parent pays: in the portal with fake PayPal (TP-E15-021), by a simulated Stripe `payment_intent.succeeded` webhook (TP-E11-024), or by GoCardless with the confirming webhook (TP-E11-023, TP-E11-016).
6. Record an overpayment as a bank transfer and check it becomes credit (TP-E11-028, TP-E11-029).

**Checkpoints:**
- One charge per lesson, and totals are the sum of the rounded lines (TP-E10-019).
- Re-running the same period creates no duplicate invoices (TP-E10-012).
- Payment is recorded once, even when the webhook is replayed (TP-E11-004).
- Dunning stops once the invoice is paid (TP-E10-045).

**Automated (in part):** `e2e/delivery.spec.ts`, `e2e/portal-tutor.spec.ts`, `e2e/billing.spec.ts`, `e2e/portal-parent.spec.ts`.

## J04 — Tutor pay run to accounting sync

**Goal:** tutor pay and client money reach the accounting ledger correctly.
**Roles:** tutor, finance (finance@), owner.
**Preconditions:** J03 done (completed lessons, a paid invoice); Xero connected to the fake ledger with mappings complete (TP-E23-001, TP-E23-004).

1. The tutor claims an expense with a receipt; finance approves it as rebillable (TP-E12-015, TP-E12-016).
2. Create a pay run; review its warnings; approve it (dual approval above the threshold); export the bank file; mark it paid (TP-E12-021, TP-E12-022, TP-E12-025, TP-E12-027, TP-E12-024).
3. Check the accounting sync: the invoice syncs after its contact; the payment, refund and payout keep balances in step; the tutor bills and bill payments arrive (TP-E23-009, TP-E23-010, TP-E23-016).
4. Set a lock date in the fake ledger and post a late change (TP-E23-025). Archive a mapped account and see the readable error (TP-E23-019).
5. Record a payment directly in the fake ledger and check the read-back (TP-E23-036, TP-E23-037).

**Checkpoints:**
- Pay items and ledger amounts match to the penny.
- Nothing is pushed twice, and nothing imported is pushed back.
- The coordinator cannot see payroll (TP-E12-038).

**Automated:** backend only (see the epic files).

## J05 — Group classes: term, enrolment, register, rollover

**Goal:** a term of group classes runs from enrolment to next term.
**Roles:** admin (office@), coordinator, tutor (tutor@), parent (parent@).
**Preconditions:** a Year 6 student added to the Patel family (the seeded students are not eligible for the 11+ class; see E20).

1. Check the seeded year and term, and add a term with a break (TP-E20-001, TP-E20-002, TP-E20-004).
2. Enrol the student in "Saturday 10am" as staff (TP-E20-016). Check eligibility and capacity (TP-E20-018, TP-E20-019).
3. A second family enrols online from the public catalogue and pays; an unpaid place is released (TP-E20-050, TP-E20-051, TP-E20-052). The parent enrols in the portal (TP-E20-055, TP-E15-038).
4. Fill the class, join the waitlist, free a place and accept the offer (TP-E20-035, TP-E20-036).
5. The tutor takes the register (TP-E20-039). Transfer one student and withdraw another with credit (TP-E20-033, TP-E20-029).
6. Start re-enrolment for next term; families answer by email link and in the portal; the rollover finishes at the deadline or early (TP-E20-043, TP-E20-044, TP-E20-045, TP-E20-046, TP-E20-048, TP-E32-052).

**Checkpoints:**
- Proration leaves out breaks (TP-E20-028).
- Fees appear on the next invoice run (TP-E20-027).
- Sessions keep their local time across the clock change (TP-E20-061).

**Automated (in part):** `e2e/courses.spec.ts`.

## J06 — Safeguarding concern, data request and erasure

**Goal:** sensitive cases are handled by the right people and personal data is exported or erased correctly.
**Roles:** tutor (tutor@), coordinator, owner (admin@, the DSL), parent (parent@).
**Preconditions:** none beyond the seed.

1. The tutor raises a concern from the lesson page; staff raise one from the student page (TP-E29-044, TP-E29-043).
2. Only the DSL sees and manages the case; access is audited (TP-E29-045, TP-E29-047, TP-E29-048). Make the coordinator a DSL with a custom role and check access (TP-E29-046).
3. A tutor message to the child with a phone number is blocked and flagged (TP-E29-050, TP-E29-052); the conversation gets no AI help (TP-E31-010).
4. Work the seeded access request from Priya: verify identity, review and redact the export, deliver by secure link (TP-E29-018, TP-E29-021, TP-E29-022, TP-E29-023). The export holds no safeguarding cases (TP-E29-029).
5. The parent asks for erasure of a child in the portal (TP-E29-028). Preview and approve it (TP-E29-030), then check the erased student (TP-E29-031) and the portal login (TP-E29-033).
6. Place a legal hold on another record and run a retention dry run and purge (TP-E29-034, TP-E29-040, TP-E29-041).

**Checkpoints:**
- Invoices keep the details they must keep (TP-E29-032).
- Nothing about the case appears in the general audit log.
- Northside sees none of it (TP-E29-072).

**Automated:** backend only.

## J07 — Broadcast, inbox reply and AI suggested reply

**Goal:** office staff talk to families at scale and one-to-one.
**Roles:** coordinator (coordinator@), parent (parent@), tutor.
**Preconditions:** the seeded segment, draft broadcast and conversation.

1. Open the draft broadcast "Half-term timetable"; check who it reaches; send now (TP-E13-019, TP-E13-020). The emails arrive in Mailpit with the family's first name.
2. Draft a marketing broadcast with AI; check that it needs consent and has an unsubscribe link (TP-E31-035, TP-E13-023, TP-E13-024).
3. The parent sends a portal message; the coordinator replies with a canned reply and adds an internal note (TP-E15-039, TP-E13-031, TP-E13-032).
4. On "Thursday's lesson", use **Suggest reply** and **Summarise**; the reschedule is proposed and confirmed (TP-E13-041, TP-E31-022, TP-E31-024, TP-E31-027).
5. Assign, snooze, close and reopen the conversation (TP-E13-033). Simulate an inbound SMS (TP-E13-037).

**Checkpoints:**
- Internal notes never reach the family.
- The tutor sees only their own conversations (TP-E13-049).
- AI requests appear in the usage log (TP-E31-008).

**Automated (in part):** `e2e/inbox.spec.ts`.

## J08 — Move from a competitor: import, reconcile, cutover

**Goal:** an agency moves its data from TutorCruncher (or CSVs) and starts trading.
**Roles:** owner (admin@), admin (office@).
**Preconditions:** a new organisation (sign up as in J01), so the seed data does not mix in.

1. Start a TutorCruncher migration with any key (fake) (TP-E28-031); steps wait for their imports (TP-E28-033).
2. Alternatively upload CSVs: auto-match columns, validate, dry-run, confirm (TP-E28-002, TP-E28-007, TP-E28-008). Import households, students, tutors (no invitations), lessons and opening balances (TP-E28-019, TP-E28-020, TP-E28-022, TP-E28-024, TP-E28-025).
3. Read the reconciliation report (TP-E28-035). Roll back one batch within the window; money is reversed, not deleted (TP-E28-010, TP-E28-030).
4. Cut over: record payments after the cutover date (TP-E28-027); invite users (TP-E28-036).
5. The owner requests a full export and downloads it after re-entering the password (TP-E28-043, TP-E28-044, TP-E28-045).

**Checkpoints:**
- Re-importing the same file changes nothing (TP-E28-013).
- Malicious files are refused (TP-E28-016).
- An admin can import but cannot export everything (TP-E28-049).

**Automated:** backend only.

## J09 — Custom domain website and widgets

**Goal:** the business publishes its brand, website and widgets on its own domain.
**Roles:** owner, admin.
**Preconditions:** `custom_domain` and `white_label` entitlements granted from the platform console; a hosts-file entry for the test domain.

1. Edit the brand kit; check contrast warnings; the portal, emails and PDFs carry the brand (TP-E24-001, TP-E24-003, TP-E24-005, TP-E24-006).
2. Edit a website page with blocks, preview, publish and restore a version (TP-E24-036, TP-E24-038); the seeded site is live (TP-E24-035).
3. Add a custom domain; the fake DNS verifies it and the certificate goes active (TP-E24-012, TP-E24-013). Check the app-domain email links, then remove the domain (TP-E24-015).
4. Create widgets and embed them on the :5175 playground: tutor directory, enquiry form (TP-E24-021, TP-E24-022, TP-E24-023). CORS allows only configured origins (TP-E24-029).
5. Submit an enquiry through the widget and find it on the pipeline (TP-E17-003).

**Checkpoints:**
- Analytics run only after cookie consent (TP-E24-043).
- Widgets never show Northside's data (TP-E24-055).

**Automated:** backend only (widgets and site are manual).

## J10 — Our subscription: trial, paid, dunning, recovery

**Goal:** TutorTrack bills its own customers correctly.
**Roles:** owner of a new organisation, platform staff (platform@).
**Preconditions:** a newly signed-up organisation (J01 step 1).

1. Check the trial notice and banner (TP-E04-009, TP-E04-010). Add a card during the trial (fake Stripe Billing) and choose a plan (TP-E04-005, TP-E04-006).
2. Hit a plan limit (second tutor on Solo) and upgrade with proration (TP-E04-013, TP-E04-020).
3. Simulate `invoice.payment_failed`: the subscription is past due and the banner shows (TP-E04-026). Simulate `invoice.paid`: access restores at once (TP-E04-027). Replay a webhook: it is processed once (TP-E04-029).
4. Platform staff extend a trial for another organisation (TP-E04-012, TP-E30-006).
5. Cancel with the exit survey and reactivate (TP-E04-024, TP-E04-025).

**Checkpoints:**
- Only the owner manages the plan; the admin can view it (TP-E04-037, TP-E04-038).
- A webhook for one customer touches only its organisation (TP-E04-040).

**Automated:** backend only.

## J11 — Platform operations: health, support and SaaS metrics

**Goal:** TutorTrack staff can run the platform safely.
**Roles:** platform staff (platform@ or admin@), owner (admin@).
**Preconditions:** platform 2FA set up, or `PLATFORM_REQUIRE_MFA=false` locally.

1. Organisation users can't open the console; platform staff can (TP-E30-001, TP-E30-002).
2. List organisations; open Bright Minds; grant and remove an entitlement override (TP-E30-004, TP-E30-005, TP-E30-007).
3. Health worklist; Recalculate now (TP-E30-048, TP-E30-049). SaaS metrics show six months of history (TP-E30-055).
4. The owner starts a support chat; platform staff answer (TP-E30-039, TP-E30-040).
5. "View as" with a reason and a support-access grant, read-only by default (TP-E30-022, TP-E30-023, TP-E30-027).
6. Replay a dead-lettered event and post an outage banner (TP-E30-017, TP-E30-018).

**Checkpoints:**
- Tenant actions land in the tenant's audit log (TP-E30-058).
- Support chats stay in their organisation (TP-E30-057).

**Automated (in part):** `e2e/platform.spec.ts`.

## J12 — Tutor recruitment to active tutor

**Goal:** a tutor applies, is vetted, onboarded and starts teaching.
**Roles:** applicant (public), admin, referee (public), the new tutor (portal).
**Preconditions:** none.

1. Create and publish a job opening; apply as a tutor at `/vacancies` (TP-E18-001, TP-E18-002).
2. Move through stages; invite to interview; the applicant picks a slot (TP-E18-008, TP-E18-009).
3. The referee submits a reference from the emailed link (TP-E18-011).
4. Approve: an onboarding tutor is created; the tutor completes the checklist and uploads a DBS certificate in the portal (TP-E18-018, TP-E18-019, TP-E18-022).
5. Staff verify the record; the tutor auto-activates (TP-E18-023, TP-E18-020). Approve the claimed subject (TP-E18-037).
6. The tutor appears in matching and can be assigned (TP-E18-038, TP-E19-001).
7. Let the DBS expire (set the expiry to today): the tutor is restricted and can't be assigned; renewal lifts it (TP-E18-026, TP-E18-027, TP-E18-030).

**Checkpoints:**
- Tutors can't verify their own records (TP-E18-025).
- Reference numbers are encrypted (TP-E18-034).

**Automated:** backend only.

## J13 — Reviews, referrals and affiliate commission

**Goal:** growth features reward the right people exactly once.
**Roles:** coordinator, parent (parent@), affiliate (affiliate@), finance.
**Preconditions:** the seeded referral programme, reviews and affiliate.

1. Moderate the pending review; send a review request; submit through the public page; the link works once (TP-E25-001, TP-E25-002, TP-E25-007, TP-E25-008, TP-E25-009).
2. Show an approved review on the website, with consent (TP-E25-020, TP-E25-022).
3. The parent shares "Refer a friend"; an enquiry with the code creates a referral; the first payment rewards both families (TP-E25-028, TP-E25-031, TP-E25-033).
4. An enquiry through the affiliate link is attributed; the partner portal shows a privacy-limited list (TP-E25-046, TP-E25-048, TP-E25-049).
5. Check the commission: 10% of £200 = £20; a £50 refund claws back £5 (TP-E25-052, TP-E25-053). Issue statements, export the bank file and mark paid (TP-E25-059, TP-E25-061).

**Checkpoints:**
- A redelivered payment does not reward twice (TP-E25-041).
- Commission items can't be edited (TP-E25-058).

**Automated:** backend only.

## J14 — Reporting and a scheduled report

**Goal:** figures follow the activity, and reports reach the right people.
**Roles:** owner, finance, coordinator, tutor.
**Preconditions:** J03 done, so the period has lessons, invoices and payments.

1. Completing a lesson and issuing and paying an invoice update the reports (TP-E26-001, TP-E26-002).
2. Check the role dashboards (TP-E26-011, TP-E26-012), then customise and save one (TP-E26-016).
3. Run revenue by tutor and service, the invoices register, aged debtors and margin (TP-E26-022, TP-E26-023, TP-E26-025). Export CSV, Excel and PDF (TP-E26-032).
4. Build a custom lessons report, save it and share it (TP-E26-043, TP-E26-050).
5. Schedule an emailed report; trigger the Schedule in the Temporal UI; the file arrives in Mailpit (TP-E26-038, TP-E26-039).
6. Ask the copilot a question about the report (TP-E31-031).

**Checkpoints:**
- Recipients must hold the permission (TP-E26-040).
- Tutors see only their own figures (TP-E26-058).
- Formula injection is neutralised (TP-E26-033).

**Automated:** backend only.

## J15 — Public API key and webhooks

**Goal:** an integrator can read data and receive signed events.
**Roles:** owner, an external client (curl or Postman).
**Preconditions:** internet access for a public HTTPS webhook receiver (for example webhook.site).

1. Read clients with the seeded demo key; a missing scope is refused; read-only can't write (TP-E27-001, TP-E27-002, TP-E27-003).
2. Create a key; the secret is shown once; revoke it (TP-E27-010, TP-E27-012).
3. Create a webhook endpoint; the SSRF guard refuses private URLs; send a test event (TP-E27-021, TP-E27-022, TP-E27-024).
4. Complete a lesson; verify the `lesson.completed` signature; point the endpoint at a 500 and watch the retries (TP-E27-025, TP-E27-026, TP-E32-060).
5. Register an OAuth app and run the authorisation code + PKCE flow (TP-E27-037, TP-E27-038).

**Checkpoints:**
- A key works only on its own organisation's host (TP-E27-054, TP-E27-055).
- Idempotency-Key replays financial POSTs (TP-E27-008).

**Automated:** backend only.

## J16 — Automation rule end to end

**Goal:** a no-code rule acts on real events safely.
**Roles:** admin (office@).
**Preconditions:** none.

1. Install the "New enquiry" recipe and every other recipe (TP-E14-024, TP-E14-025).
2. Create an event automation with conditions; dry-run it with a record (TP-E14-001, TP-E14-003, TP-E14-005).
3. Trigger it (submit an enquiry); it creates a task, adds a tag and sends a signed webhook (TP-E14-002, TP-E14-008, TP-E14-010).
4. Add "wait then branch"; check the run in the Temporal UI (TP-E14-015, TP-E32-042).
5. Edit the rule (new version) while a run is in flight; retry a failed step (TP-E14-006, TP-E14-019).

**Checkpoints:**
- Loop detection and the per-record daily limit hold (TP-E14-016, TP-E14-017).
- The coordinator and finance can't see automations (TP-E14-027).

**Automated:** backend only.

## J17 — Tenant isolation sweep

**Goal:** no data crosses between organisations anywhere.
**Roles:** coordinator@ (Bright Minds), owner@northside.localhost (Northside).
**Preconditions:** both organisations seeded.

1. As each organisation, search people, jobs, invoices, enquiries, reports and the inbox for the other's names (TP-E02-045, TP-E05-055, TP-E07-032, TP-E10-077, TP-E17-060, TP-E26-061, TP-E13-052).
2. Paste a Bright Minds record URL (client, invoice, report) into the Northside host and the reverse: you get "not found" (TP-E02-046, TP-E05-056).
3. Sign in to the other organisation's host with your account: no access (TP-E02-047, TP-E15-044, TP-E16-044).
4. Use the demo API key on the Northside host (TP-E27-054). Open a Bright Minds feedback or review link on the Northside host (TP-E09-063, TP-E25-010).
5. Check that widgets, files and AI answers stay in their organisation (TP-E24-055, TP-E01-032, TP-E31-044).

**Checkpoints:** every step shows nothing from the other organisation, and no error leaks its names or IDs.

**Automated (in part):** `e2e/roles.spec.ts`.

## J18 — Phase 3 features

**Goal:** the Phase 3 / Enterprise tickets work together (checked against the merged build on 2026-10-14; the linked cases give the exact screens and fakes).
**Roles:** finance, admin, tutor.
**Preconditions:** each feature's entitlement granted; the dev fakes for Wise, the check providers, video and the accounting systems (see each case).

1. **Payroll:** pay a tutor through Wise (one transfer per payout); finalise the year and export 1099-NEC data; the tutor's US tax section in the portal; commission-based pay (TP-E12-033, TP-E12-034, TP-E12-035, TP-E12-036).
2. **Background checks:** start an online UK check (fake provider), a DBS Update Service status check and a US Checkr check; webhook security (TP-E18-040, TP-E18-041, TP-E18-042, TP-E18-044).
3. **Video:** attendance pre-filled from video events; a recording linked to the lesson, with retention and consent (TP-E22-045, TP-E22-047, TP-E22-048, TP-E22-049).
4. **Accounting:** Sage and FreeAgent sync; Xero Payroll for employed tutors (TP-E23-041, TP-E23-042, TP-E23-043, TP-E23-044, TP-E23-045).
5. **Warehouse:** configure a destination; the nightly export writes the documented schemas (TP-E26-053, TP-E26-054).
6. **Native apps:** the generic native app with the organisation picker, and in-app notifications (native push and deep links were not built) (TP-E16-039, TP-E16-040). The apps load the hosted https portal, so they can't be tested against localhost; store signing isn't set up (see [traceability.md](traceability.md)).

**Checkpoints:** each feature is hidden without its entitlement (for example TP-E26-056), and provider webhooks are authenticated (TP-E22-051).

**Automated:** none yet.

---

## Journey results

| Journey | Result | Failing step / issue | Tester and date |
|---|---|---|---|
| J01 | | | |
| J02 | | | |
| J03 | | | |
| J04 | | | |
| J05 | | | |
| J06 | | | |
| J07 | | | |
| J08 | | | |
| J09 | | | |
| J10 | | | |
| J11 | | | |
| J12 | | | |
| J13 | | | |
| J14 | | | |
| J15 | | | |
| J16 | | | |
| J17 | | | |
| J18 | | | |
