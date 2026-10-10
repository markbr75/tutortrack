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
| E03 | ✅ Done (2026-10-09) | Phase 1 scope (T08/T11/T12 are Phase 2). See Implementation notes |
| E04 | ✅ Done (2026-10-10) | Incl. E04-TW1 (trial and dunning workflows). API under `/subscription`; console for overrides with E30. See Implementation notes |
| E05 | ✅ Done (2026-10-09) | Phase 1 scope (merge tool and map view are Phase 2). See Implementation notes |
| E06 | ✅ Done (2026-10-09) | MVP scope (T07–T10 pay tiers, premiums, discounts, rooms are Phase 2). See Implementation notes |
| E07 | ✅ Done (2026-10-09) | Lesson-dependent parts (replace preview, hours used, delivered totals) wired by E08-T10. See Implementation notes |
| E08 | ✅ Done (2026-10-09) | MVP scope (rooms, reschedule requests, self-booking, time-off approval + TW1 are Phase 2). See Implementation notes |
| E09 | ✅ Done (2026-10-09) | MVP scope (T09 feedback surveys are Phase 2). See Implementation notes and ADR 0006 |
| E10 | ✅ Done (2026-10-09) | Phase 1 scope (packages, fixed fees, late fees and split billing are Phase 2). See Implementation notes and ADR 0007 |
| E11 | ✅ Done (2026-10-09) | Stripe + manual (GoCardless, PayPal, bank feeds and split payments are Phase 2). See Implementation notes and ADR 0008 |
| E12 | ✅ Done (2026-10-10) | T01–T11 + TW1 (Wise/1099/commission are Phase 3). Bank files, self-billing, holds, pay runs on Temporal. See Implementation notes |
| E13 | ✅ Done (2026-10-09) | MVP scope (broadcasts, inbox, WhatsApp, custom domains are Phase 2). See Implementation notes |
| E14 | ✅ Done (2026-10-10) | T01–T09 + TW1. See Implementation notes |
| E15 | ✅ Done (2026-10-10) | MVP scope (booking, reschedule, packages and messaging are Phase 2). See Implementation notes |
| E16 | ✅ Done (2026-10-10) | Responsive tutor shell in the portal app (PWA/offline/push are Phase 2; expenses with E12, compliance with E18). See Implementation notes |
| E17 | ✅ Done (2026-10-10) | T01–T08, T10 + TW1 (proposals T09 are Phase 2b). See Implementation notes |
| E18 | ✅ Done (2026-10-10) | T01–T10 + TW1 (provider integrations T11 are Phase 3). See Implementation notes |
| E19 | ✅ Done (2026-10-10) | T01–T07, T09 + TW1 (client shortlist sharing T08 is Phase 2b). See Implementation notes |
| E20 | ☐ | |
| E21 | ☐ | |
| E22 | ⏭ Next | |
| E23 | ☐ | |
| E24 | ☐ | |
| E25 | ☐ | |
| E26 | ✅ Done (2026-10-10) | T01–T07 + scheduled-report workflow (T08 custom builder is Phase 2b, T09 warehouse export Enterprise). See Implementation notes |
| E27 | ☐ | |
| E28 | ☐ | |
| E29 | 🟡 Part 1 done (2026-10-09) | T01–T04 (security baseline, KMS encryption, audit search, consent). Part 2 (T05–T12, TW1) in Phase 3 |
| E30 | ◐ Part 1 done (2026-10-10) | Console, tenant actions, flags, ops/dead letters, support access, alarms, backups, runbooks. Part 2 (help, analytics, SaaS metrics) later. See Implementation notes |
| E31 | ☐ | |
| E32 | ✅ Done (2026-10-09) | Runtime, bridge, codec, timers, schedules, processes API, test harness; reference + closure workflows |
