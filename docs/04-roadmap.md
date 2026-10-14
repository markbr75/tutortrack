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
| E02 | ✅ Done (2026-10-09) | Incl. E02-TW1 (closure workflow, built with E32). Follow-ups in E04, E05, E06, E11, E24 |
| E03 | ✅ Done (2026-10-09; Phase 2 done 2026-10-12) | Phase 2: passkeys (T08), custom roles and permission matrix (T11), SAML/OIDC per organisation (T12). See Implementation notes and Phase 2 notes |
| E04 | ✅ Done (2026-10-10) | Incl. E04-TW1 (trial and dunning workflows). API under `/subscription`; console for overrides with E30. See Implementation notes |
| E05 | ✅ Done (2026-10-09) | Phase 1 scope (merge tool and map view are Phase 2). See Implementation notes |
| E06 | ✅ Done (2026-10-09; Phase 2 done 2026-10-12) | Phase 2: pay tiers, tutor rates and CSV (T07), premiums and holiday calendars (T08), discounts, promo codes and price lists (T09), rooms and resources (T10). See Implementation notes and Phase 2 notes |
| E07 | ✅ Done (2026-10-09) | Lesson-dependent parts (replace preview, hours used, delivered totals) wired by E08-T10. See Implementation notes |
| E08 | ✅ Done (2026-10-09; Phase 2 done 2026-10-12) | Phase 2: rooms with exclusion constraint (T12), reschedule requests (T13), self-booking with holds and payment (T14), time-off approval and cover (T15), TW1 workflows on Temporal. See Implementation notes and Phase 2 notes |
| E09 | ✅ Done (2026-10-09) | MVP scope (T09 feedback surveys are Phase 2). See Implementation notes and ADR 0006 |
| E10 | ✅ Done (2026-10-09); Phase 2 ✅ Done (2026-10-12) | Phase 1 per ADR 0007. Phase 2: packages with PackageExpiryWorkflow, recurring fixed fees with proration, late fees and collections blocks, split billing (ADR 0022) |
| E11 | ✅ Done (2026-10-09); Phase 2 ✅ Done (2026-10-12) | Phase 1 per ADR 0008. Phase 2: GoCardless, PayPal, bank statement import and Open Banking with a matching queue, split payments, ProviderMigrationWorkflow (ADR 0022) |
| E12 | ✅ Done (2026-10-10) | T01–T11 + TW1 (Wise/1099/commission are Phase 3). Bank files, self-billing, holds, pay runs on Temporal. See Implementation notes |
| E13 | ✅ Done (2026-10-09); Phase 2 ✅ Done (2026-10-14) | MVP scope. Phase 2: broadcasts to segments with consent rules, throttled `BroadcastWorkflow` and open/click statistics; a team inbox for email, text, WhatsApp and portal chat with assignment, snooze, SLA, notes, canned replies and safeguarding flags; WhatsApp (Twilio) with approved templates; custom sending domains; Mailchimp/Brevo sync on E22 (ADR 0027). See Implementation notes and Phase 2 notes |
| E14 | ✅ Done (2026-10-10) | T01–T09 + TW1. See Implementation notes |
| E15 | ✅ Done (2026-10-10); Phase 2 ✅ Done (2026-10-14) | MVP scope. Phase 2 (T09): booking, reschedule and packages from E08/E10 Phase 2, plus makeup-credit booking and portal messaging with the business and tutors on the E13 inbox. See Implementation notes and Phase 2 notes |
| E16 | ✅ Done (2026-10-10); Phase 2 ✅ Done (2026-10-13) | Responsive tutor shell in the portal app (expenses with E12, compliance with E18). Phase 2: installable PWA with a service worker, offline pack, idempotent outbox with background sync and conflict review, Web Push as an E13 channel (ADR 0023). T11 native shells are Phase 3 |
| E17 | ✅ Done (2026-10-10) | T01–T08, T10 + TW1 (proposals T09 are Phase 2b). See Implementation notes |
| E18 | ✅ Done (2026-10-10) | T01–T10 + TW1 (provider integrations T11 are Phase 3). See Implementation notes |
| E19 | ✅ Done (2026-10-10) | T01–T07, T09 + TW1 (client shortlist sharing T08 is Phase 2b). See Implementation notes |
| E20 | ✅ Done (2026-10-13) | T01–T10 + TW1: terms with breaks (skip class sessions; E10 termly plans follow term dates), courses and classes on E08 lesson series with roster-driven attendees, enrolment with class locks, eligibility and mid-term proration, per-term/monthly/per-session/instalment billing with sibling and multi-class discounts, transfers and withdrawals with credit notes, class waitlists on E17 offers, registers and makeups, term rollover and online enrolment with payment on Temporal, public catalogue widget and block, portal classes. See Implementation notes |
| E21 | ✅ Done (2026-10-14) | T01–T08 + TW1: resource library (org and personal, files within plan storage, links, sharing to students/jobs/lessons/classes, view tracking), homework with portal hand-in, grade scales, resubmission and a reminder/overdue workflow, curricula (GCSE Maths, KS2 English, SAT Math built-ins, CSV import) with report topic tagging, mastery and a coverage heatmap, goals and milestones, assessments with score trends, progress reports with approval, portal sharing and PDF (E31 AI-draft seam), lending library with replacement charges and loan reminders, built-in auto-marked quizzes. See Implementation notes |
| E22 | ✅ Done (2026-10-10) | T01–T09 + TW1: integration framework (OAuth+PKCE, encrypted tokens, health), Google/Microsoft/CalDAV two-way calendar sync with busy blocks in conflicts, Zoom/Teams/Meet/Lessonspace/built-in rooms, timed join links (T10 is Phase 3). See Implementation notes |
| E23 | ✅ Done (2026-10-10) | T01–T08 + TW1: Xero and QuickBooks Online built on the E22 framework. Mappings are validated. Contacts, invoices, credit notes, payments, refunds, payouts with fees and tutor bills sync. Errors are readable, with retry and skip; lock dates are respected. Also: summary journals, backfill, a daily reconciliation check and digest, and GL exports for Sage 50, MYOB and IIF. T09 is Phase 2b; T10 is Phase 3. See Implementation notes |
| E24 | ✅ Done (2026-10-10) | T01–T08 + custom-domain workflow on Temporal: brand kit with AA contrast handling across portals, emails and PDFs; custom domains (TXT/CNAME verification, Cloudflare/Caddy/fake TLS, routing, host-only cookies); Lit widgets (directory, enquiry, services, reviews, login, vacancies) with CORS/rate limits; WordPress plugin; website builder with themes, blocks, versions and SEO; moderated tutor profiles. Booking and class-catalogue widgets arrive with E08 Phase 2 and E20. See Implementation notes |
| E25 | ✅ Done (2026-10-14) | T01–T06 + TW1: review requests after N lessons or trials with a signed review page, moderation, replies and rating aggregates (matching, directory); testimonials on the E24 widget and a Google prompt; client referral codes with `?ref=` attribution, fraud checks and E10 credit / E06 discount rewards on `ReferralRewardWorkflow`; affiliates with tracking links, a partner portal, commission rules (percent for N months, tiers, bounties, overrides), clawbacks, monthly statements and E12 bank files; tutor referral bonuses as E12 pay items. See Implementation notes and ADR 0026 |
| E26 | ✅ Done (2026-10-10) | T01–T07 + scheduled-report workflow (T08 custom builder is Phase 2b, T09 warehouse export Enterprise). See Implementation notes |
| E27 | ✅ Done (2026-10-10) | T01–T09 + webhook delivery workflow (TW1). Zapier/Make ship as served manifests; sandboxes skip provider connections. See Implementation notes |
| E28 | ✅ Done (2026-10-10) | T01–T10 + TW1: import pipeline (mapping, dry run, chunked import, error report, 7-day rollback) through the owning apps' services, 14 importers incl. history and opening balances, cutover assistant with reconciliation, TutorCruncher/Teachworks API connectors, TutorBird presets, Google Sheets, full tenant export. See Implementation notes |
| E29 | ✅ Done (2026-10-14) | Part 1 (2026-10-09): T01–T04 (security baseline, KMS encryption, audit search, consent). Part 2: DSAR workflow and export compiler with redaction and secure links, erasure engine over a per-app privacy provider registry (financial records anonymised, legal holds), retention policies and nightly purge schedule, safeguarding cases for DSLs, messaging safeguards and lone-working check-ins, COPPA/AADC defaults, region-aware signup, DPA and sub-processors, compliance docs and `security.txt`; four privacy workflows (ADR 0028) |
| E30 | ✅ Done (2026-10-14) | Part 1 (2026-10-10): console, tenant actions, flags, ops/dead letters, support access, alarms, backups, runbooks. Part 2: help panel (repo markdown articles with search, What's new), accessible product tours, setup checklist ticked by domain events, built-in support chat with a console inbox and CSAT, consent-gated pseudonymous product analytics with a sink seam, nightly platform insights schedule (tenant health scores, churn-risk emails, subscription snapshots), NPS, SaaS metrics (MRR/ARR, movements, churn, NRR, ARPA, trial conversion, cohorts) (ADR 0030). See Implementation notes |
| E31 | ⏭ Next | |
| E32 | ✅ Done (2026-10-09) | Runtime, bridge, codec, timers, schedules, processes API, test harness; reference + closure workflows |
