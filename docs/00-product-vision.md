# 00 — Product Vision

## 1. Vision statement

**One platform to run a tutoring business, from first enquiry to tutor payout.** TutorTrack replaces the spreadsheets, calendar apps, invoicing tools, payment links, WhatsApp groups and payroll calculations that tutoring businesses currently stitch together. It should feel effortless to a solo tutor on day one and still have the depth an agency with 500 tutors and four branches needs.

## 2. Target customers (tenants)

| Segment | Size | Primary jobs-to-be-done | Must-haves |
|---|---|---|---|
| **Sole trader tutor** | 1 tutor, 5–60 students | Schedule lessons, bill parents automatically, get paid, look professional | 10-minute setup, calendar-based billing, Stripe/PayPal, student portal, simple website or booking page, mobile-friendly |
| **Small team / micro-agency** | 2–15 tutors | Above, plus allocate students to tutors, pay tutors, see who's doing what | Multi-tutor calendar, permissions, payroll calculation, lesson reports |
| **Tutoring agency** | 15–1,000+ tutors, mostly self-employed | Win clients, match tutors, take a margin, handle compliance and safeguarding, scale ops staff | Pipeline, tutor recruitment and compliance, matching, charge-rate vs pay-rate margin, automated payouts, API, white-label |
| **Learning centre / academy** | 1–10 locations, rooms, group classes | Run term-based classes, enrolments, rooms, waitlists | Courses/terms, room scheduling, enrolment, recurring monthly fees, attendance registers |
| **Online tutoring company** | Any size, remote | Above, online-first | Video integrations, timezone handling, multi-currency, global payments |

Initial geography: **UK, US, Canada, Australia, New Zealand and Ireland** (English-first). The system must be multi-currency, multi-timezone and i18n-ready from day one.

## 3. Personas

| Persona | Description | Key surfaces |
|---|---|---|
| **Owner** (Olivia) | Owns the business. Cares about revenue, margin, cash flow and growth. Often also tutors. | Admin app, dashboards, settings, billing |
| **Admin / Coordinator** (Adam) | Agency ops staff. Handles enquiries, matching, scheduling, chasing payments and compliance. | Admin app (power user), inbox, pipeline, calendar |
| **Branch Manager** (Bea) | Manages one branch's tutors and clients | Admin app scoped to a branch |
| **Tutor** (Tom) | Self-employed or employed. Wants to see his schedule, log lessons, write reports and get paid on time. | Tutor portal / mobile PWA |
| **Client / Parent** (Priya) | Pays the bills. Wants visibility, easy booking and rescheduling, and painless payment. | Client portal, emails/SMS, payment pages |
| **Student** (Sam) | Child or adult learner. Needs schedule, joining links, homework and resources. | Student portal |
| **Affiliate / Referrer** (Raj) | Schools, partners or individuals who refer clients for commission | Affiliate portal |
| **Platform Operator** (us) | Runs the SaaS: support, billing, tenant health | Super-admin console |

## 4. Product principles

1. **Sole-trader simple, agency deep.** Progressive disclosure: advanced features (branches, pay tiers, pipeline, compliance) stay hidden until they are switched on. A sole trader should never see "payroll" if they don't need it.
2. **Calendar is the source of truth.** Lessons drive charges, tutor pay, reports and reminders. Finance follows the calendar automatically (TutorBird's best idea) and can be overridden with full audit (TutorCruncher's rigour).
3. **Money is sacred.** Immutable ledgers, no deletion of financial records, credit notes instead of edits, reconciliation and full audit trails.
4. **Everything is automatable.** Every meaningful action emits a domain event that can drive notifications, automations, webhooks and integrations.
5. **API-first.** Our own frontends use the same versioned API that we expose publicly.
6. **Mobile-first for tutors and parents.** Admins may sit at desks; tutors and parents live on phones.
7. **White-label by default.** Clients and tutors see the tenant's brand, not ours.
8. **Safe by design.** The platform deals with children, so safeguarding, privacy, least-privilege and GDPR/COPPA are first-class concerns.

## 5. Differentiators vs incumbents

| Gap in market | TutorTrack answer |
|---|---|
| TutorBird doesn't scale to agencies: no pipeline, weak payroll, no API | Full agency tooling behind feature toggles (E12, E17–E19, E27) |
| TutorCruncher has a steep learning curve and dated UX, and is costly for solo tutors | Guided onboarding, setup wizard, sensible defaults, free/low-cost solo tier (E04, E30) |
| No native mobile app (TutorBird) and a limited one (TutorCruncher) | Installable PWA with push notifications, offline lesson logging (E16) |
| Limited automation (fixed email triggers) | Visual "When/If/Then" automation engine (E14) |
| Weak group classes and term enrolment | Courses, terms, enrolment, waitlists, rooms (E20) |
| Little academic depth (TutorBird has no progress tracking) | Goals, progress, homework, assessments, resources (E21) |
| Late lesson reports not tracked (a TutorCruncher reviewer complaint) | SLA tracking for reports, nudges, and blocking billing until a report is submitted (E09) |
| Payment provider switching problems | Provider-agnostic payment abstraction with per-client mandate management (E11) |
| No AI assistance | AI lesson-report drafting, parent summaries, smart matching, scheduling assistant (E31) |
| Painful migration | One-click importers from TutorCruncher API, TutorBird CSV and Teachworks (E28) |

## 6. Success metrics (product)

- Time-to-first-invoice for a new sole trader under **15 minutes**.
- At least **95%** of invoices generated automatically, not manually.
- At least **80%** of lessons marked complete by tutors within 24h.
- Days-sales-outstanding (DSO) for tenants using auto-pay under **5 days**.
- Tenant monthly logo churn under **2%**.
- p95 page/API response under **300ms** for core reads.

## 7. Commercial model (indicative, see E04)

| Plan | Target | Indicative pricing model |
|---|---|---|
| **Solo** | 1 tutor | Low flat monthly fee, all core features |
| **Team** | 2–15 tutors | Base fee plus per-active-tutor fee |
| **Agency** | 15+ tutors | Base fee plus % of processed revenue *or* per-active-tutor, plus advanced modules |
| **Enterprise** | Large or multi-branch | Custom, SSO, data residency, SLA |

Optional add-ons: SMS bundles, AI credits, extra branches, custom domain, white-label mobile app.
