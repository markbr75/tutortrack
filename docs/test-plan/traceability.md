# Traceability

This file maps each epic to its manual test cases and automated coverage. Counts come from the case tables (`grep -c "^| TP-"`).

- **Backend-cited:** cases whose "Automated?" column names a pytest file or test.
- **E2E-cited:** cases that name a Playwright spec.
- **Specs:** the Playwright specs in `frontend/e2e/` that exercise the epic. Every list and detail endpoint also has a backend `TenantIsolationTestMixin` test (CLAUDE.md rule 1), and every Temporal workflow has replay histories in `backend/tests/workflow_histories/`.

## Epic matrix

| Epic | Test-plan file | Case IDs | Cases (P1) | Phase 2 / 2b / 3 tickets covered | Backend-cited | E2E-cited | Playwright specs |
|---|---|---|---|---|---|---|---|
| E01 Platform foundations | [E01-platform-foundations.md](E01-platform-foundations.md) | TP-E01-001–046 | 46 (16) | — | 41 | 4 | smoke, roles |
| E02 Multi-tenancy | [E02-multi-tenancy.md](E02-multi-tenancy.md) | TP-E02-001–054 | 54 (18) | branches (`multi_branch`), closure; gap G2 demo data: TP-E02-051–054 | 54 | 2 | roles |
| E03 Identity and access | [E03-identity-access.md](E03-identity-access.md) | TP-E03-001–068 | 68 (27) | T08 passkeys, T11 custom roles, T12 SAML/OIDC per organisation (Phase 2); gap G2 Apple sign-in, change email: TP-E03-065–068 | 67 | 6 | smoke, roles |
| E04 SaaS subscriptions | [E04-saas-subscriptions.md](E04-saas-subscriptions.md) | TP-E04-001–041 | 41 (15) | seats, revenue share, credit packs | 35 | 1 | roles |
| E05 People and CRM | [E05-people-crm.md](E05-people-crm.md) | TP-E05-001–080 | 80 (36) | T10 duplicate detection, T12 map view (Phase 2); gap G2 documents and e-signing: TP-E05-078–080 | 70 | 7 | people, roles |
| E06 Catalogue and pricing | [E06-catalogue-pricing.md](E06-catalogue-pricing.md) | TP-E06-001–051 | 51 (21) | T07 pay tiers, T08 premiums and holidays, T09 discounts, promo codes and price lists, T10 rooms (Phase 2) | 48 | 3 | catalogue |
| E07 Jobs | [E07-jobs.md](E07-jobs.md) | TP-E07-001–035 | 35 (15) | — | 25 | 2 | jobs-scheduling |
| E08 Scheduling and calendar | [E08-scheduling-calendar.md](E08-scheduling-calendar.md) | TP-E08-001–069 | 69 (32) | T12 rooms, T13 reschedule requests, T14 self-booking, T15 time-off approval (Phase 2) | 57 | 4 | jobs-scheduling, delivery, portal-tutor |
| E09 Lesson delivery | [E09-lesson-delivery.md](E09-lesson-delivery.md) | TP-E09-001–069 | 69 (29) | T09 lesson feedback surveys (Phase 2; built in the Phase 2b batch) | 56 | 8 | delivery, portal-tutor, roles |
| E10 Client billing | [E10-client-billing.md](E10-client-billing.md) | TP-E10-001–085 | 85 (43) | T12 packages, T13 recurring fees, T14 late fees/collections, T15 split billing (Phase 2) | 70 | 6 | billing, portal-parent |
| E11 Payments | [E11-payments.md](E11-payments.md) | TP-E11-001–054 | 54 (26) | T11 GoCardless, T12 PayPal, T13 bank statements and Open Banking, T14 split payments (Phase 2) | 44 | 4 | portal-parent, billing, roles |
| E12 Tutor payroll | [E12-tutor-payroll.md](E12-tutor-payroll.md) | TP-E12-001–043 | 43 (22) | Phase 2 epic; **T12 Wise/1099/commission (Phase 3): TP-E12-033–036** | 31 | 1 | roles |
| E13 Communications | [E13-communications.md](E13-communications.md) | TP-E13-001–055 | 55 (19) | T10 broadcasts, T11 conversations inbox, T12 WhatsApp, sender domains, Mailchimp/Brevo (Phase 2) | 50 | 4 | inbox, roles |
| E14 Automation | [E14-automation.md](E14-automation.md) | TP-E14-001–033 | 33 (17) | Phase 2 epic | 23 | 1 | roles |
| E15 Client portal | [E15-client-portal.md](E15-client-portal.md) | TP-E15-001–055 | 55 (25) | T09 booking, reschedule, packages, messaging (Phase 2); gap G2 household switcher, guardians, child logins, documents: TP-E15-050–055 | 32 | 6 | roles, portal-parent, portal-tutor |
| E16 Tutor portal and mobile | [E16-tutor-portal-mobile.md](E16-tutor-portal-mobile.md) | TP-E16-001–048 | 48 (19) | T08 PWA and offline, T09 web push, T10 job offers and board (Phase 2); **T11 Capacitor shells (Phase 3): TP-E16-039–042** | 17 | 2 | roles, portal-tutor |
| E17 Leads and pipeline | [E17-leads-pipeline.md](E17-leads-pipeline.md) | TP-E17-001–067 | 67 (28) | Phase 2 epic; T09 proposals (Phase 2b) | 47 | 5 | leads, roles |
| E18 Recruitment and compliance | [E18-tutor-recruitment-compliance.md](E18-tutor-recruitment-compliance.md) | TP-E18-001–056 | 56 (27) | Phase 2 epic; **T11 background-check providers (Phase 3): TP-E18-040–044**; gap G2 tutor agreement e-signing: TP-E18-055–056 | 35 | 1 | roles |
| E19 Matching and marketplace | [E19-matching-marketplace.md](E19-matching-marketplace.md) | TP-E19-001–048 | 48 (24) | Phase 2 epic; T08 shortlist sharing (Phase 2b) | 38 | 0 | — |
| E20 Classes and courses | [E20-classes-courses.md](E20-classes-courses.md) | TP-E20-001–064 | 64 (26) | Phase 3 epic (built) | 50 | 2 | courses |
| E21 Learning tools | [E21-learning-tools.md](E21-learning-tools.md) | TP-E21-001–054 | 54 (26) | Phase 3 epic; T08 quizzes (Phase 3b, built) | 47 | 0 | — |
| E22 Calendar sync and video | [E22-calendar-video-integrations.md](E22-calendar-video-integrations.md) | TP-E22-001–058 | 58 (21) | Phase 2 epic; **T10 video attendance and recordings (Phase 3): TP-E22-045–051** | 47 | 0 | — |
| E23 Accounting integrations | [E23-accounting-integrations.md](E23-accounting-integrations.md) | TP-E23-001–053 | 53 (18) | Phase 2 epic; T09 ledger payment read-back (Phase 2b); **T10 Sage/FreeAgent/Xero Payroll (Phase 3): TP-E23-041–046** | 42 | 0 | — |
| E24 Website, widgets, white-label | [E24-website-widgets-branding.md](E24-website-widgets-branding.md) | TP-E24-001–059 | 59 (25) | Phase 2 epic | 49 | 1 | roles |
| E25 Reviews, referrals, affiliates | [E25-reviews-referrals-affiliates.md](E25-reviews-referrals-affiliates.md) | TP-E25-001–078 | 78 (35) | Phase 3 epic (built) | 66 | 0 | — |
| E26 Reporting and analytics | [E26-reporting-analytics.md](E26-reporting-analytics.md) | TP-E26-001–065 | 65 (30) | Phase 2 epic; T08 custom report builder (Phase 2b); **T09 warehouse export (Enterprise): TP-E26-053–057** | 49 | 0 | — |
| E27 Public API and webhooks | [E27-public-api-webhooks.md](E27-public-api-webhooks.md) | TP-E27-001–060 | 60 (28) | Phase 2 epic | 49 | 1 | smoke |
| E28 Import, export, migration | [E28-import-export-migration.md](E28-import-export-migration.md) | TP-E28-001–057 | 57 (27) | Phase 2 epic | 47 | 0 | — |
| E29 Security, privacy, compliance | [E29-security-privacy-compliance.md](E29-security-privacy-compliance.md) | TP-E29-001–075 | 75 (43) | part 1 (Phase 1) and part 2 | 67 | 3 | leads, roles |
| E30 Platform admin and ops | [E30-platform-admin-ops.md](E30-platform-admin-ops.md) | TP-E30-001–062 | 62 (30) | part 1 (Phase 1) and part 2 | 53 | 5 | platform |
| E31 AI assistant | [E31-ai-assistant.md](E31-ai-assistant.md) | TP-E31-001–045 | 45 (25) | Phase 3 epic (built) | 40 | 1 | inbox |
| E32 Workflow orchestration (Temporal) | [E32-workflow-orchestration-temporal.md](E32-workflow-orchestration-temporal.md) | TP-E32-001–067 | 67 (27) | all workflows (TW1 tickets of each epic) | 57 | 0 | — |
| **Total** | 32 files | | **1,818 (799)** | | **1,455** | **80** | |

## Cross-cutting files

| File | IDs | Count | Automated |
|---|---|---|---|
| [journeys.md](journeys.md) | J01–J18 | 18 journeys | In part: all specs (see each journey's "Automated" line) |
| [accessibility.md](accessibility.md) | TP-A11Y-001–035 (admin), 040–050 (portal), 060–067 (public), 070–072 (console) | 57 | `e2e/accessibility.spec.ts` scans 11 screens |
| [non-functional.md](non-functional.md) | TP-NF-001–008, 010–025, 030–033, 040–044, 050–052, 060–064, 070–073 | 45 | Partly backend; `e2e/smoke.spec.ts` (`/healthz`), `e2e/roles.spec.ts` (IDOR, sign-in) |

## Playwright specs

14 specs, 55 tests, all passing locally against a freshly seeded stack (Chromium, one worker) on 2026-10-14, and again on the same database (re-runnable).

| Spec | Tests | Covers | Epics |
|---|---|---|---|
| `e2e/smoke.spec.ts` | 3 | API health; the sign-in page; the owner signs in and reaches the app | E01, E03 |
| `e2e/roles.spec.ts` | 12 | Navigation per staff role (owner, admin, branch manager, coordinator, finance); wrong password; sign in and out with the form; parent and tutor sent to the portal; API refusals per role; tenant isolation (search, by id, the other organisation's host, the people list) | E02, E03 |
| `e2e/people.spec.ts` | 3 | Add a family with two students in one step and find it; add a note; change a student's status; empty form stays put | E05 |
| `e2e/catalogue.spec.ts` | 3 | Create a one-to-one service with charge and pay rates; price check (90 min of £45/h = £67.50 charged, £42.00 paid); coordinator is read-only | E06 |
| `e2e/jobs-scheduling.spec.ts` | 2 | "Set up lessons" weekly job from a student; the series on the calendar (agenda, tutor filter, next week, 17:00 London); a seeking-tutor job becomes active when a tutor is assigned | E07, E08 |
| `e2e/delivery.spec.ts` | 3 | Complete yesterday's lesson from the calendar with a register (late 10 minutes); bulk-complete from Unconfirmed lessons; a tutor can't open another tutor's lesson | E08, E09 |
| `e2e/billing.spec.ts` | 3 | Ad hoc charge → Invoice now → issue → record a bank transfer → Paid; credit note reduces the amount due; coordinator can view but not issue (UI and API 403) | E10, E11 |
| `e2e/portal-parent.spec.ts` | 3 | Parent sees only her children's lessons; pays an issued invoice with the fake PayPal provider from the portal (invoice becomes Paid); portal billing shows only her household | E15, E11 |
| `e2e/portal-tutor.spec.ts` | 2 | Tutor completes a lesson and submits the report in the portal; staff approve and share it; the parent reads it (private notes hidden); the tutor's schedule lists only her lessons | E16, E09, E15 |
| `e2e/leads.spec.ts` | 3 | Public enquiry form (cookie banner first) → enquiry on the board → convert to a client with a GCSE Maths job; a missing required field blocks the form; finance can't see the pipeline | E17, E24, E29 |
| `e2e/inbox.spec.ts` | 2 | Parent writes from the portal; coordinator finds it in the inbox, gets an AI-suggested reply (fake provider, grounded in Arjun's next lesson), adds a canned reply and sends; the parent sees it; internal notes stay hidden from the family | E13, E15, E31 |
| `e2e/courses.spec.ts` | 2 | Enrol a Year 6 student in a new class with a fee quote and places count; a full class offers the waitlist | E20 |
| `e2e/platform.spec.ts` | 3 | Platform staff see both organisations and open one; tenant health, SaaS metrics and the support inbox; an organisation admin is refused | E30 |
| `e2e/accessibility.spec.ts` | 11 | axe (WCAG 2.0/2.1/2.2 A and AA tags) on `/login`, `/`, `/clients`, `/calendar`, `/billing`, `/catalogue`, `/leads`, `/inbox`, `/portal/`, `/portal/tutor` and a public enquiry form: no violations | cross-cutting |

## Not testable without real credentials or infrastructure

These need accounts, keys or infrastructure that the local fakes can't stand in for. In the epic files, record these cases as **Blocked** with the reason, or run them in a staging environment that has the credentials.

- **App stores:** signing and store submission of the Capacitor shells (E16-T11), plus real native push.
- **Payments:** real Stripe, GoCardless and PayPal sandboxes; Stripe Connect onboarding; live payouts, including Stripe Express and Wise (E12-T12); card payments in the browser (Stripe.js needs real keys).
- **Messaging:**
  - real Twilio numbers, WhatsApp Business templates and inbound routing;
  - Postmark sending domains (DKIM/SPF) and real inbound email.
- **Calendars and video:**
  - Google, Microsoft, Zoom, Daily, Whereby and Lessonspace OAuth apps or keys;
  - real calendars, iCloud CalDAV and push-notification channels;
  - video attendance and recordings from real meetings (E22-T10).
- **Accounting:** Xero, QuickBooks Online, Sage Business Cloud, FreeAgent and Xero Payroll sandboxes (E23, E23-T10).
- **Other providers:**
  - background-check provider accounts (UK online DBS, DBS Update Service, Checkr, AU WWCC) (E18-T11);
  - Mailchimp and Brevo accounts;
  - Google or Mapbox geocoding keys.
- **AI and speech:**
  - speech-to-text provider: none ships, so `AI_TRANSCRIBER` has no live option;
  - live Claude API behaviour and evals (`ai_evals --live` needs `ANTHROPIC_API_KEY`).
- **Domains and push:**
  - Cloudflare for SaaS custom-domain certificates, and real DNS (CNAME and TXT verification);
  - VAPID web push to real devices (iOS home-screen apps, Android).
- **Infrastructure:**
  - AWS deployment (Terraform, ECS, RDS, KMS for field keys, S3, AWS Backup) and the restore drills against it;
  - regional stacks and data residency;
  - Temporal Cloud with mTLS or API keys.
- **Enterprise:**
  - warehouse export targets such as Snowflake, BigQuery or S3 (E26-T09);
  - SSO with real SAML or OIDC identity providers (Okta, Entra ID, Google Workspace).
- **Captcha:** Cloudflare Turnstile with real site and secret keys.
