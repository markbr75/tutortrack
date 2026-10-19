# Product

<!-- impeccable:product-schema 1 -->

Source: `docs/00-product-vision.md` (confirmed by the owner as the product record, 2026-10-19).

## Platform

web

## Users

- **Owner** (Olivia): owns the tutoring business, often also tutors. Watches revenue, margin, cash flow and growth. Admin app: dashboards, settings, billing.
- **Admin / Coordinator** (Adam): agency operations staff and the power user. Handles enquiries, matching, scheduling, chasing payments and compliance all day. Admin app: inbox, pipeline, calendar.
- **Branch Manager** (Bea): runs one branch's tutors and clients. Admin app scoped to a branch.
- **Tutor** (Tom): self-employed or employed. Sees his schedule, logs lessons, writes reports, gets paid. Tutor portal, mostly on a phone.
- **Client / Parent** (Priya): pays the bills. Wants visibility, easy booking and rescheduling, painless payment. Client portal, mostly on a phone.
- **Student** (Sam): child or adult learner. Schedule, joining links, homework, resources. Student portal.
- **Affiliate / Referrer** (Raj): refers clients for commission. Affiliate portal.
- **Platform operator** (TutorTrack staff): support, billing, tenant health. Platform console.

Tenants range from a sole-trader tutor (1 tutor, 5–60 students) to agencies with 1,000+ tutors and several branches, learning centres and online tutoring companies. Initial markets: UK, US, Canada, Australia, New Zealand and Ireland, English first.

## Product Purpose

One platform to run a tutoring business, from first enquiry to tutor payout. It replaces the spreadsheets, calendar apps, invoicing tools, payment links, WhatsApp groups and payroll sums that tutoring businesses stitch together today. Success: it feels effortless to a solo tutor on day one (first invoice within 15 minutes of sign-up) and still has the depth an agency with 500 tutors and four branches needs.

## Positioning

Agency-grade depth (pipeline, matching, payroll, compliance, API) behind feature toggles, with guided setup and sensible defaults that a sole trader can use straight away. The main incumbent (TutorCruncher) is described by its own users as having a steep learning curve and dated UX; TutorBird does not scale to agencies. The calendar drives charges, pay, reports and reminders automatically.

## Operating Context

- **Admin app** (`frontend/apps/admin`, served at `<org>.tutortrack…`): used at a desk for long sessions by owners and coordinators; dense, task-heavy work across many modules (people, scheduling, billing, payroll, comms, reporting, compliance, settings).
- **Portal** (`frontend/apps/portal`, served at `/portal/`): one installable PWA with role shells for clients, students, tutors and affiliates; used mostly on phones, often briefly; offline schedule cache and push notifications.
- **Platform console** (`frontend/apps/admin/src/platform`): internal, for TutorTrack staff.
- Embeddable widgets and hosted tenant websites (`frontend/apps/widgets`, `sites` app) render in the tenant's brand.

## Capabilities and Constraints

- Feature set per epic in `docs/epics/E01–E32`; navigation items are gated by permission codenames, and modules a tenant has not switched on must stay hidden ("sole-trader simple, agency deep").
- Stack: React 18, TypeScript, Vite, TanStack Router/Query, Tailwind CSS v4, shared components in `frontend/packages/ui` (tokens in `packages/ui/src/styles.css`), i18n via `@tutortrack/i18n` (en-GB catalogue; every user-facing string translated; no hard-coded currency symbols or date formats).
- Light and dark colour schemes already exist (system preference plus `data-theme`).
- Terminology is tenant-configurable (Tutor, Student, Client, Lesson, Job can be renamed).
- Navigation route sections in the guides (`docs/guides/*.html`, `data-route`) are checked against the shells' nav definitions by `manage.py guides --check`.

## Brand Commitments

- Product name: **TutorTrack**. No logo, colour palette or typeface has been chosen yet: TutorTrack's own look is to be designed fresh (owner, 2026-10-19).
- **White-label by default:** clients, students, tutors and affiliates see the tenant's brand (colour and logo from `/api/v1/public/branding`, applied at runtime with `applyBrandTheme`), not TutorTrack's. The portal shows "Powered by TutorTrack" only as a small credit.
- The admin app takes the tenant's brand colour subtly (buttons and accents only, E24 FR-24-1).

## Evidence on Hand

- Demo/seed data (`make seed`): the "Bright Minds Tutoring" organisation with sample families, tutors, lessons and invoices, plus one sign-in per role.
- No customer testimonials, case studies, metrics or logos exist. Do not invent any.

## Product Principles

1. **Sole-trader simple, agency deep.** Progressive disclosure: advanced modules stay out of sight until they are switched on.
2. **Calendar is the source of truth.** Lessons drive charges, pay, reports and reminders.
3. **Money is sacred.** Immutable ledgers and full audit trails; financial records are corrected, never edited away.
4. **Mobile-first for tutors and parents.** Admins sit at desks; tutors and parents live on phones.
5. **White-label by default, safe by design.** Families see the tenant's brand; the platform deals with children, so safeguarding, privacy and least privilege are first-class.

## Accessibility & Inclusion

WCAG 2.2 AA across all UI (docs/02-architecture.md): keyboard-navigable calendar, managed focus, colour-contrast tokens; must hold in both colour schemes and with any tenant brand colour.
