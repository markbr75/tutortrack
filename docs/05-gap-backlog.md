# 05 — Gap backlog (deferred inside completed tickets)

Every delivery-plan ticket in `docs/epics/` is ticked, but the epics' *Implementation notes* record spec functionality (FRs) that was deferred, simplified to a seam, or left as a follow-up inside those tickets. A survey of all 32 epics on 2026-10-14 (notes + code grep) found the gaps below. They are grouped into batches by area so that batches can be built in parallel with few conflicts.

Tick an item when it is built, and record the as-built details in the owning epic's notes. References are `epic:line` in `docs/epics/`.

## Batch G1 — People, CRM and search (E05)
- [x] **E05 merge tool** for clients, contacts and students: choose surviving values, re-point lessons, invoices, notes, files etc. through each app's services, audited, confirmation required, not reversible (FR-05-13; E05:102, E05:118, E05:125). *L*
- [x] XLSX export from list grids (FR-05-11; E05:117). *S*
- [x] Computed list fields and filters: client balance, next/last lesson, hours this term; tutor hours, utilisation, SLA (FR-05-1/4/11; E05:110). *S–M*
- [x] Record timeline includes lessons, invoices and payments (FR-05-10). *S–M*
- [x] Global search covers jobs and invoices (FR-05-11). *S*
- [x] Bulk actions: send message, invite to portal, export (FR-05-12). *S–M*
- [x] @mentions notify the mentioned staff (FR-05-7/FR-13-2). *S*

## Batch G2 — Identity, portal households and demo data (E02, E03, E15)
- [x] In-product demo data: `@demo_provider` sample data for the main apps (people, catalogue, scheduling, delivery, billing, payments, leads, courses, growth…) so "Explore with demo data" and E27 sandboxes have records (FR-02-6, FR-27-6; E02:135, E25:120). *M*
- [x] Apple sign-in against a fake, like Google/Microsoft (FR-03-2; E03:123, E03:159). *S–M*
- [x] Change-email flow: verify the new address, notify the old one (FR-03-9). *S*
- [x] Portal household switcher (FR-15-1; E15:78). *S*
- [x] Invite another guardian from the portal (FR-15-8; E15:83). *S*
- [x] Guardian-managed logins for under-13 students (FR-15-1; E15:78). *M*
- [x] Document e-signing: click-to-sign with audit, for client documents, portal and tutor agreements (FR-05-9, FR-15-8, FR-18-5; E15:83, E18:100). *M*

## Batch G3 — Scheduling, delivery, billing, payments and payroll (E06–E12)
- [x] `pricing.discount_display=separate` shows discounts as separate invoice lines (FR-06-7, FR-10-3; E06:129). *S*
- [x] Jobs-needing-attention: no upcoming lessons, low prepaid balance, overdue reports (FR-07-6; E07:77). *S*
- [x] Calendar: saved filter sets, secondary timezone, print/PDF timetable, bulk-action UI (FR-08-7, FR-08-10; E08:144). *M*
- [x] Enforce the booking cancellation window (FR-08-9; E08:155). *S*
- [x] Website builder `booking` block (FR-24-4; E08:161, E24:107). *S*
- [x] "Max free cancellations per term" using E20 terms (FR-09-3; E09:106). *S*
- [x] Report-template attachment field with real uploads (FR-09-4; E09:108). *S*
- [x] UI for branch/service/job/client delivery policy and template overrides (FR-09-3/4; E09:113). *S*
- [x] Tutor pre-review of draft invoices (FR-10-3; E10:144, E10:153). *M*
- [x] Credit-note PDFs (FR-10-4/5; E10:153). *S*
- [x] Scheduled, emailed client statements (FR-10-9; E10:148). *S*
- [x] Package deferred revenue: accounting journals and the "package liabilities" report (FR-26-2, FR-23-2; E10:162, E26:87). *M*
- [x] Payment methods enabled per branch; card surcharges (FR-11-1; E11:116). *M*
- [x] Expiring-card notices; "auto-pay N days before due"; bulk payment-entry grid (FR-11-2/3/5). *S each*
- [x] Re-authenticate before showing full bank details (E12 permissions; E12:113, E12:132). *S*
- [x] Edit individual items in the pay-run UI (FR-12-5; E12:132). *S*
- [x] Annual earnings summary for tutors (FR-12-9). *S*

## Batch G4 — Communications, automations and the tutor app (E13, E14, E16)
- [x] Realtime in-app notifications over SSE (FR-13-1/8; E13:108). *M*
- [x] Template overrides per locale and per branch (FR-13-3; E13:104). *S–M*
- [x] A direct channel to students (FR-13-2/5; E13:103, E13:116). *M*
- [x] Digests: daily tutor agenda, weekly client schedule, message digests (FR-13-2/7; E13:103, E13:129). *M*
- [x] Identity and account emails on branded, editable comms templates (E02:133, E03:138). *S–M*
- [x] Mailchimp/Brevo unsubscribes flow back as suppressions/consent (FR-13-9; E13:135). *S*
- [x] Missing notification types: card expiring, statement, low attendance, expense approved/rejected, booking declined (FR-13-2). *S*
- [x] Automation actions: send feedback survey, add to broadcast/Mailchimp list, WhatsApp, message from saved template (FR-14-3; E14:122). *M*
- [x] Package triggers (`package.low`) and the "package < 2 hours" recipe (FR-14-1/6; E14:130). *S*
- [x] Tutor app: create and reschedule lessons with conflict feedback (FR-16-2; E16:66). *M*
- [x] Tutor app: previous report on the lesson page; full lesson history per student (FR-16-3/4; E16:66-67). *S–M*
- [x] Tutor app: browser voice-to-text for report fields (FR-16-3; E16:66, E16:86). *S*
- [x] Push notifications for tutor messages (FR-16-9; E16:86). *S*

*G4 built 2026-10-14 (ADR 0038); as-built notes in E02, E03, E13, E14 and E16. Realtime SSE needs ASGI in the deploy to scale (runbook `docs/runbooks/realtime-notifications.md`).*

## Batch G5 — Leads, recruitment, matching, learning, accounting and reporting (E17–E26)
- [x] File uploads on public forms: enquiry attachments, CV/video (FR-17-1, FR-18-1; E17:88, E18:111). *M*
- [ ] Waitlist suggestions when tutor capacity appears (FR-17-6; E17:104). *S–M*
- [x] Compliance dashboard export and bulk "request missing documents" (FR-18-8; E18:107). *S*
- [x] Probation reviews, performance notes, offboarding checklist (FR-18-9; E18:111). *M*
- [x] Interview booking through the slot engine with an automatic video link (FR-18-2; E18:95). *M*
- [x] Admin job-opening editor (FR-18-1; E31:117). *S–M*
- [x] UI for online tutor subject tests (FR-18-3; E21:102). *S*
- [ ] Matching criteria: gender preference, SEN tags, exam board (FR-19-1; E19:77). *S–M*
- [ ] Automatic termly/monthly progress-report generation on a schedule (FR-21-6; E21:95). *S*
- [ ] Send shared resources into video rooms (FR-21-8; E21:113) — check against the E22-T10 build. *M*
- [x] Payment read-back (E23-T09) for Sage and FreeAgent; today it is Xero and QuickBooks only, and the option is refused for other ledgers. *S–M*
- [x] Per-branch ledgers (FR-23-1; E23:216). *M–L*
- [x] Payment reallocations and lost disputes after sync (FR-23-2/3; E23:217-219). *M*
- [x] Summary journals in non-base currencies; bad-debt VAT adjustment; self-billing VAT in GL exports (FR-23-2/5; E23:220-225). *M*
- [ ] Referral, affiliate and review reports (FR-26-2; E25:121, E26:88). *S–M*
- [ ] Room utilisation per room; custom-field filters for students and tutors; tutor utilisation net of time off; scheduling custom reports (FR-26-2/4; E26:89-90, E26:114). *S each*

## Batch G6 — Public API, migration, privacy, platform, subscriptions and sites (E04, E24, E27–E30, E32)
- [x] **Consent ticked on public forms, enrolments, referrals and imports is written as E29 consent records** (FR-29-3; E29:106). *S–M*
- [x] Record acceptance of the platform Terms of Service at signup (FR-29-3; E29:108). *S*
- [x] Global account deletion; retention for login history; retention for dispatched outbox events (FR-03-9, FR-29-4/5; E29:135, E29:155-156). *M*
- [x] Platform "notify customers" tool for breach notices (FR-29-9; E29:145). *S*
- [x] Impossible-travel alerts from CDN country headers (GeoIP database optional) (FR-29-2; E29:104). *M*
- [x] Webhook catalogue offers the event types added after E27 (reviews, referrals, commission, proposals, shortlists, packages, bookings, broadcasts, threads, homework, lesson feedback…) (FR-27-3; E13:138, E25:116). *S*
- [x] Reviews and form submissions in the public API (FR-27-1; E27:84). *S*
- [x] Integrations marketplace shows live status for Xero, QBO, Google, Outlook, Zoom, Teams, Lessonspace and lists CalDAV, Meet, Mailchimp/Brevo, WhatsApp, Open Banking (FR-27-5; E27:134). *S*
- [x] TutorCruncher import of agents, reviews, proformas and ad hoc charges; Teachworks wage tiers → pay tiers (FR-28-3/5; E28:186-188). *M*
- [x] Console: plans and prices screen; integration status on tenant detail; MRR filter on the tenant list; support reply notifications by email/push (FR-30-1/5; E30:72, E30:86, E30:151). *S each*
- [x] Revenue-share MRR and reconciliation (FR-30-7; E30:137, E30:151). *M*
- [x] Console for failed or stuck workflows across tenants (terminate, reset, retry, Temporal UI links) (FR-32-10; E32:161, E32:174). *M*
- [x] In-app purchase of add-ons (custom domain, white-label, priority support) (FR-04-1; E04:93, E04:137). *M*
- [x] Blog/news pages in the website builder (FR-24-4). *M*

*G6 built 2026-10-14 (ADR 0034); as-built notes in E04, E24, E27, E28, E29, E30 and E32.*

## Needs real credentials, accounts or infrastructure (not code gaps)
- AWS deploy: Terraform not applied or validated; RDS BYPASSRLS role check; regional workspaces and DNS; ClamAV in the stack (E01:161, E02:151, E29:157, E32:163).
- Ops providers: status page (e.g. Instatus), alarms on workflow failures, read replica for async reports (E26:91, E30:83-86).
- GoCardless production redirect/relay and Open Banking consent (E11:131, E11:136); Stripe Connect platform for tutor and affiliate payouts (E12:127, E25:102).
- Live Xero/QBO testing; Zapier/Make app publishing (E23:226, E27:126).
- Speech-to-text provider for E31 voice notes (E31:119); Apple Developer account for Apple sign-in; Facebook/Google Lead Ads app review (E17:109); GeoIP licence if CDN headers aren't enough.
- ASGI in the deploy for realtime SSE; real keys for every provider that runs on a fake today.
