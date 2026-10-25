# 04 — Roadmap & Build Order

## Phases

### Phase 1 — MVP: "A sole trader or small team can run their whole business"
Exit criteria: a solo tutor can sign up, configure services, add families and students, schedule recurring lessons, mark attendance, write reports, auto-invoice, take card payments with auto-pay, send reminders, and give parents a portal. A small team can add tutors with limited permissions.

| Order | Epic | Scope in Phase 1 |
|---|---|---|
| 1 | E01 Platform Foundations | Full |
| 2 | E02 Multi-Tenancy | Full (branches can be hidden behind a feature flag) |
| 3 | E03 Identity & Access | Email/password, magic link, Google SSO, TOTP 2FA, built-in roles. Custom roles → Phase 2 |
| 3b | E32 Workflow Orchestration (Temporal) | Runtime, worker, tenancy plumbing, bridge, codec, test harness. Build before E04/E09/E10, which start workflows |
| 4 | E29 Security/Privacy (part 1) | Audit log, encryption helpers, consent capture, cookie banner |
| 5 | E05 People & CRM | Full minus advanced deduplication |
| 6 | E06 Catalogue & Pricing | Services, subjects, default rates, tax rates. Pay tiers and premiums → Phase 2 |
| 7 | E07 Jobs | Full (a simplified "quick job" UI for solo mode) |
| 8 | E08 Scheduling | Full except rooms/resources and self-booking → Phase 2 |
| 9 | E09 Lesson Delivery | Full |
| 10 | E10 Client Billing | Ledger, invoices, calendar-based auto-invoicing, credit, payment requests, credit notes. Packages and late fees → Phase 2 |
| 11 | E11 Payments | Stripe (cards, auto-pay), manual payments. GoCardless and PayPal → Phase 2 |
| 12 | E13 Communications | Email and SMS templates, reminders, notification preferences |
| 13 | E15 Client & Student Portal | Schedule, invoices, pay, lesson reports, profile |
| 14 | E16 Tutor Portal | Responsive tutor web portal (PWA install, push → Phase 2) |
| 15 | E04 SaaS Subscriptions | Trials, Stripe Billing, plan entitlements |
| 16 | E30 Platform Admin (part 1) | Tenant list, impersonation, feature flags, health |

### Phase 2 — Agency: "A tutoring agency can migrate off TutorCruncher"
| Order | Epic |
|---|---|
| 17 | E12 Tutor Payroll, Expenses & Payouts |
| 18 | E17 Leads, Enquiries & Pipeline |
| 19 | E18 Tutor Recruitment & Compliance |
| 20 | E19 Tutor Matching & Job Marketplace |
| 21 | E14 Automation Engine |
| 22 | E22 Calendar Sync & Video |
| 23 | E23 Accounting Integrations |
| 24 | E24 Website, Widgets & White-label |
| 25 | E26 Reporting & Dashboards |
| 26 | E27 Public API & Webhooks |
| 27 | E28 Import & Migration |
| 28 | E03/E06/E08/E10/E11 Phase-2 remainders (custom roles, pay tiers, rooms, self-booking, packages, late fees, GoCardless, PayPal) |
| 29 | E16 PWA push and offline |

### Phase 3 — Scale & Differentiate
| Order | Epic |
|---|---|
| 30 | E20 Group Classes, Courses & Terms |
| 31 | E21 Learning Tools |
| 32 | E25 Reviews, Referrals & Affiliates |
| 33 | E31 AI Assistant |
| 34 | E29 Part 2 (data residency, SOC 2 readiness, advanced safeguarding) |
| 35 | E30 Part 2 (usage analytics, tenant health scoring, support tooling) |

## Dependency graph (simplified)

```
E01 ─► E02 ─► E03 ─► E32 (Temporal) ─► E04, E08–E14, E17–E20, E22, E23, E25, E28, E29 (their workflows)
E01 ─► E02 ─► E03 ─► E05 ─► E06 ─► E07 ─► E08 ─► E09 ─► E10 ─► E11
                │                    │       │       │      └─► E12 (needs E09 pay)
                │                    │       │       └─► E21
                ├─► E04              │       └─► E20 (needs E08, E10)
                └─► E13 ─► E14 (needs outbox E01 + E13 actions)
E05 ─► E17 ─► E19 ◄─ E18
E08 ─► E22 ; E10/E11/E12 ─► E23 ; E05/E06 ─► E24 ; E10 ─► E25
All ─► E26, E27, E28, E31
```

## Progress tracker

| Epic | Status | Notes |
|---|---|---|
| E01 | ✅ Done (2026-10-08) | See Implementation notes in the epic; follow-ups carried into E02, E03, E29, E30 |
| E02 | ✅ Done (2026-10-09); gap G2 ✅ Done (2026-10-14) | Incl. E02-TW1 (closure workflow, built with E32). Follow-ups in E04, E05, E06, E11, E24. Gap batch G2 (2026-10-14): in-product sample data from every main app ("Explore with demo data", E27 sandboxes), auto-tracked and cleared in one click (ADR 0036) |
| E03 | ✅ Done (2026-10-09; Phase 2 done 2026-10-12); gap G2 ✅ Done (2026-10-14) | Phase 2: passkeys (T08), custom roles and permission matrix (T11), SAML/OIDC per organisation (T12). See Implementation notes and Phase 2 notes Gap batch G2 (2026-10-14): Sign in with Apple, change-email flow (ADR 0036). |
| E04 | ✅ Done (2026-10-10) | Incl. E04-TW1 (trial and dunning workflows). API under `/subscription`; console for overrides with E30. See Implementation notes |
| E05 | ✅ Done (2026-10-09); T12 ✅ Done (2026-10-14); gap G1 ✅ Done (2026-10-14) | T12 map view done 2026-10-14: geocoded students and tutors (rounded, by area) with an accessible SVG map and list, fake/Google/Mapbox geocoders. Gap batch G1 (2026-10-14): merge tool for clients, contacts and students (per-app merge providers, ADR 0035), XLSX and selected-row exports, computed list fields/filters/sorting, lessons/invoices/payments on timelines, search over jobs and invoices, bulk send message/invite to portal, @mention notifications. See Implementation notes, Phase 2b notes and Gap backlog notes |
| E06 | ✅ Done (2026-10-09; Phase 2 done 2026-10-12) | Phase 2: pay tiers, tutor rates and CSV (T07), premiums and holiday calendars (T08), discounts, promo codes and price lists (T09), rooms and resources (T10). See Implementation notes and Phase 2 notes |
| E07 | ✅ Done (2026-10-09) | Lesson-dependent parts (replace preview, hours used, delivered totals) wired by E08-T10. See Implementation notes |
| E08 | ✅ Done (2026-10-09; Phase 2 done 2026-10-12) | Phase 2: rooms with exclusion constraint (T12), reschedule requests (T13), self-booking with holds and payment (T14), time-off approval and cover (T15), TW1 workflows on Temporal. See Implementation notes and Phase 2 notes |
| E09 | ✅ Done (2026-10-09); T09 ✅ Done (2026-10-14) | MVP scope. T09 done 2026-10-14: post-lesson feedback micro-surveys on `LessonFeedbackWorkflow` with consent rules, low-score alerts, E25/E19/E26 feeds. See Implementation notes, Phase 2b notes and ADR 0006/0031 |
| E10 | ✅ Done (2026-10-09); Phase 2 ✅ Done (2026-10-12) | Phase 1 per ADR 0007. Phase 2: packages with PackageExpiryWorkflow, recurring fixed fees with proration, late fees and collections blocks, split billing (ADR 0022) |
| E11 | ✅ Done (2026-10-09); Phase 2 ✅ Done (2026-10-12) | Phase 1 per ADR 0008. Phase 2: GoCardless, PayPal, bank statement import and Open Banking with a matching queue, split payments, ProviderMigrationWorkflow (ADR 0022) |
| E12 | ✅ Done (2026-10-10); Phase 3 ✅ Done (2026-10-14) | T01–T11 + TW1. Bank files, self-billing, holds, pay runs on Temporal. Phase 3 (T12): Wise Business payouts (per-org API token, recipients from bank details, signed webhooks plus the pay run's daily polling), commission pay as a share of collected revenue, US 1099-NEC totals with encrypted taxpayer ids, immutable filings and an IRIS-style CSV (ADR 0032). See Implementation notes |
| E13 | ✅ Done (2026-10-09); Phase 2 ✅ Done (2026-10-14); gap G4 ✅ Done (2026-10-14) | MVP scope. Phase 2: broadcasts to segments with consent rules, throttled `BroadcastWorkflow` and open/click statistics; a team inbox for email, text, WhatsApp and portal chat with assignment, snooze, SLA, notes, canned replies and safeguarding flags; WhatsApp (Twilio) with approved templates; custom sending domains; Mailchimp/Brevo sync on E22 (ADR 0027). See Implementation notes and Phase 2 notes. Gap batch G4 (2026-10-14): realtime bell over SSE, template versions per language and branch, students as recipients, digests, account emails on comms templates, Mailchimp/Brevo unsubscribes flowing back, new notification types (ADR 0038) |
| E14 | ✅ Done (2026-10-10); gap G4 ✅ Done (2026-10-14) | T01–T09 + TW1. See Implementation notes. Gap batch G4 (2026-10-14): feedback survey, mailing list, WhatsApp and saved-message actions; package triggers and the package-under-2-hours recipe (ADR 0038) |
| E15 | ✅ Done (2026-10-10); Phase 2 ✅ Done (2026-10-14); gap G2 ✅ Done (2026-10-14) | MVP scope. Phase 2 (T09): booking, reschedule and packages from E08/E10 Phase 2, plus makeup-credit booking and portal messaging with the business and tutors on the E13 inbox. See Implementation notes and Phase 2 notes Gap batch G2 (2026-10-14): household switcher, invite another guardian, guardian-managed under-13 logins, documents to e-sign (ADR 0036). |
| E16 | ✅ Done (2026-10-10); Phase 2 ✅ Done (2026-10-13); gap G4 ✅ Done (2026-10-14) | Responsive tutor shell in the portal app (expenses with E12, compliance with E18). Phase 2: installable PWA with a service worker, offline pack, idempotent outbox with background sync and conflict review, Web Push as an E13 channel (ADR 0023). Phase 3 ✅ Done (2026-10-14): Capacitor shells (generic app with an organisation picker, white-label apps from the E24 brand kit via `mobile_app_config` / `public/mobile-app`), a manual-only build workflow (ADR 0032). Gap batch G4 (2026-10-14): plan and move lessons with clash feedback, previous report, student lesson history, voice dictation, push for messages (ADR 0038) |
| E17 | ✅ Done (2026-10-10); T09 ✅ Done (2026-10-14); gap G5 ✅ Done (2026-10-21) | T01–T10 + TW1. T09 done 2026-10-14: proposals with PDF, signed acceptance link, conversion with tutor offer and deposit, `ProposalWorkflow`. See Implementation notes and Phase 2b notes. Gap batch G5 (2026-10-21): files on the public enquiry form (shared safe public uploads, ADR 0042) and waitlist suggestions when a tutor has room (ADR 0044) |
| E18 | ✅ Done (2026-10-10); Phase 3 ✅ Done (2026-10-14); gap G5 ✅ Done (2026-10-21) | T01–T10 + TW1. Phase 3 (T11): background checks through uCheck (DBS), the DBS Update Service (re-checked on a timer), Checkr (signed webhooks) and AU WWCC verification links, on `BackgroundCheckWorkflow`; results encrypted, reads audited, retention purge (ADR 0032). See Implementation notes Gap batch G2 (2026-10-14): the tutor agreement is e-signed (click-to-sign with audit trail and signed PDF). Gap batch G5 (2026-10-21): CVs and videos on applications (ADR 0042), compliance export and bulk document requests, probation reviews (`ProbationReviewWorkflow`), performance notes, offboarding checklist, interview booking with a video link (`InterviewWorkflow`), job-opening editor, tutor subject tests |
| E19 | ✅ Done (2026-10-10); T08 ✅ Done (2026-10-14); gap G5 ✅ Done (2026-10-21) | T01–T09 + TW1. T08 done 2026-10-14: shortlists shared with families through signed expiring links with minimal tutor cards; the choice starts an offer. See Implementation notes and Phase 2b notes. Gap batch G5 (2026-10-21): gender preference (opt-in hard filter), SEN tags and exam board in matching, with sensitive-field permissions (ADR 0044) |
| E20 | ✅ Done (2026-10-13) | T01–T10 + TW1: terms with breaks (skip class sessions; E10 termly plans follow term dates), courses and classes on E08 lesson series with roster-driven attendees, enrolment with class locks, eligibility and mid-term proration, per-term/monthly/per-session/instalment billing with sibling and multi-class discounts, transfers and withdrawals with credit notes, class waitlists on E17 offers, registers and makeups, term rollover and online enrolment with payment on Temporal, public catalogue widget and block, portal classes. See Implementation notes |
| E21 | ✅ Done (2026-10-14); gap G5 ✅ Done (2026-10-21) | T01–T08 + TW1: resource library (org and personal, files within plan storage, links, sharing to students/jobs/lessons/classes, view tracking), homework with portal hand-in, grade scales, resubmission and a reminder/overdue workflow, curricula (GCSE Maths, KS2 English, SAT Math built-ins, CSV import) with report topic tagging, mastery and a coverage heatmap, goals and milestones, assessments with score trends, progress reports with approval, portal sharing and PDF (E31 AI-draft seam), lending library with replacement charges and loan reminders, built-in auto-marked quizzes. See Implementation notes. Gap batch G5 (2026-10-21): monthly or termly progress reports drafted on a schedule (`ProgressReportRunWorkflow`); shared resources open from the classroom |
| E22 | ✅ Done (2026-10-10); gap G5 ✅ Done (2026-10-21) | T01–T09 + TW1: integration framework (OAuth+PKCE, encrypted tokens, health), Google/Microsoft/CalDAV two-way calendar sync with busy blocks in conflicts, Zoom/Teams/Meet/Lessonspace/built-in rooms, timed join links. Phase 3 ✅ Done (2026-10-14, T10): attendance from Zoom/Lessonspace join and leave webhooks pre-fills the register, recordings (references only, consent-restricted, audited playback, retention) fetched by `RecordingFetchWorkflow`, and an embedded classroom with safeguarding banner and consent prompt (ADR 0032). See Implementation notes. Gap batch G5 (2026-10-21): branch-level connections for the accounting ledgers (ADR 0043); classroom resources and the tutor app's classroom link fixed |
| E23 | ✅ Done (2026-10-10); T09 and Phase 3 ✅ Done (2026-10-14); gap G5 ✅ Done (2026-10-21) | T01–T08 + TW1: Xero and QuickBooks Online built on the E22 framework. Mappings are validated. Contacts, invoices, credit notes, payments, refunds, payouts with fees and tutor bills sync. Errors are readable, with retry and skip; lock dates are respected. Also: summary journals, backfill, a daily reconciliation check and digest, and GL exports for Sage 50, MYOB and IIF. T09 done 2026-10-14: payments recorded directly in Xero/QuickBooks are read back as E11 payments, idempotently, with reconciliation logging. Phase 3 (T10): Sage Business Cloud Accounting and FreeAgent on the same engine, and Xero Payroll timesheets for employed tutors on `XeroPayrollSyncWorkflow` (ADR 0032). See Implementation notes, Phase 2b and Phase 3 notes. Gap batch G5 (2026-10-21): payment read-back for Sage and FreeAgent, per-branch ledgers, reallocations and lost disputes after sync, summary journals in other currencies, bad-debt VAT relief, self-billing VAT in GL exports (ADR 0043) |
| E24 | ✅ Done (2026-10-10) | T01–T08 + custom-domain workflow on Temporal: brand kit with AA contrast handling across portals, emails and PDFs; custom domains (TXT/CNAME verification, Cloudflare/Caddy/fake TLS, routing, host-only cookies); Lit widgets (directory, enquiry, services, reviews, login, vacancies) with CORS/rate limits; WordPress plugin; website builder with themes, blocks, versions and SEO; moderated tutor profiles. Booking and class-catalogue widgets arrive with E08 Phase 2 and E20. See Implementation notes |
| E25 | ✅ Done (2026-10-14); gap G5 ✅ Done (2026-10-21) | T01–T06 + TW1: review requests after N lessons or trials with a signed review page, moderation, replies and rating aggregates (matching, directory); testimonials on the E24 widget and a Google prompt; client referral codes with `?ref=` attribution, fraud checks and E10 credit / E06 discount rewards on `ReferralRewardWorkflow`; affiliates with tracking links, a partner portal, commission rules (percent for N months, tiers, bounties, overrides), clawbacks, monthly statements and E12 bank files; tutor referral bonuses as E12 pay items. See Implementation notes and ADR 0026. Gap batch G5 (2026-10-21): referral, affiliate and review reports (in E26 reporting) |
| E26 | ✅ Done (2026-10-10); T08 and T09 ✅ Done (2026-10-14); gap G5 ✅ Done (2026-10-21) | T01–T09 + scheduled-report workflow. T08: custom report builder on a whitelisted, permission-scoped semantic layer with saved/shared reports and exports. Enterprise T09: nightly incremental warehouse export of the reporting facts and dimensions (gzipped CSV + documented schemas) to TutorTrack storage, S3, BigQuery or Snowflake on Temporal Schedules, gated by `warehouse_export` (ADR 0032). See Implementation notes, Phase 2b and Phase 3 notes. Gap batch G5 (2026-10-21): referral, affiliate and review reports; room utilisation; tutor utilisation net of time off; custom-field filters for students and tutors; scheduled custom reports |
| E27 | ✅ Done (2026-10-10) | T01–T09 + webhook delivery workflow (TW1). Zapier/Make ship as served manifests; sandboxes skip provider connections. See Implementation notes |
| E28 | ✅ Done (2026-10-10) | T01–T10 + TW1: import pipeline (mapping, dry run, chunked import, error report, 7-day rollback) through the owning apps' services, 14 importers incl. history and opening balances, cutover assistant with reconciliation, TutorCruncher/Teachworks API connectors, TutorBird presets, Google Sheets, full tenant export. See Implementation notes |
| E29 | ✅ Done (2026-10-14) | Part 1 (2026-10-09): T01–T04 (security baseline, KMS encryption, audit search, consent). Part 2: DSAR workflow and export compiler with redaction and secure links, erasure engine over a per-app privacy provider registry (financial records anonymised, legal holds), retention policies and nightly purge schedule, safeguarding cases for DSLs, messaging safeguards and lone-working check-ins, COPPA/AADC defaults, region-aware signup, DPA and sub-processors, compliance docs and `security.txt`; four privacy workflows (ADR 0028) |
| E30 | ✅ Done (2026-10-14) | Part 1 (2026-10-10): console, tenant actions, flags, ops/dead letters, support access, alarms, backups, runbooks. Part 2: help panel (repo markdown articles with search, What's new), accessible product tours, setup checklist ticked by domain events, built-in support chat with a console inbox and CSAT, consent-gated pseudonymous product analytics with a sink seam, nightly platform insights schedule (tenant health scores, churn-risk emails, subscription snapshots), NPS, SaaS metrics (MRR/ARR, movements, churn, NRR, ARPA, trial conversion, cohorts) (ADR 0030). See Implementation notes |
| E31 | ✅ Done (2026-10-14) | T01–T08 + FR-31-6: `ai` app on Claude (Opus 5.5 for drafting, command bar and copilot; Haiku 5.5 for classification and extraction) behind a provider abstraction with a deterministic fake for CI, per-feature opt-in, pseudonymisation, prompt-free request logs, metering against E04 AI credits with monthly caps, refusal fallbacks and an eval harness. Lesson report drafting (notes and voice notes) in the tutor portal, progress comments and parent rewrite/translation, enquiry extraction and triage, inbox replies, intent and summaries, a command bar whose changes run only when confirmed, a report-grounded copilot with cited sources, content and matching explanations. See ADR 0029 and Implementation notes |
| E32 | ✅ Done (2026-10-09) | Runtime, bridge, codec, timers, schedules, processes API, test harness; reference + closure workflows |
| E33 | 🚧 In progress (T01–T04 done 2026-10-25) | Workflow designer: Automations becomes Workflows; built-in, editable workflows replace the hard-wired timing of invoicing, payment chasing, lesson communications, sales follow-ups and expiry reminders. A workflow is a simple sequence (timed steps, plain "only if" questions, one-level Yes / No splits, Stop when) on the E14 Temporal interpreter (ADR 0047). T01–T09 |

## Test plan and end-to-end journeys

- **Manual test plan:** [`docs/test-plan/`](test-plan/README.md). One file per epic (1,818 cases, TP-E01-001 to TP-E32-067, each with role, steps, expected result, priority and automated coverage), 18 cross-epic business journeys, a WCAG 2.2 AA checklist, non-functional checks and a traceability matrix. The README covers environments, seeded accounts per role (one sign-in per role plus a second organisation, Northside Learning, for tenant isolation), fake providers and how to trigger them, Temporal and Mailpit, and how to record results. Phase 3 cases are marked "Verify after the Phase 3 merge".
- **Playwright journeys:** `frontend/e2e/` (14 specs, 55 tests, including axe accessibility scans) run against a seeded stack with the admin app and the portal served by `vite preview`; the CI e2e job builds and serves both (ADR 0033).
