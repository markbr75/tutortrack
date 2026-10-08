# 01 — Competitive Analysis

Research compiled October 2026 from vendor sites, help centres, developer docs and review sites (Capterra, GetApp, Teach 'n Go, Toolradar). Competitor-authored reviews are treated with caution.

## 1. TutorCruncher (UK; agency-focused)

**Positioning:** Back-office for tutoring *agencies*. Handles both sides of the money: client invoicing and tutor payouts, with the agency's margin in between. Strong in the UK, US and Australia.

**Core concepts (their terminology → ours):**
| TutorCruncher | Meaning | TutorTrack term |
|---|---|---|
| Branch | Tenant isolation unit; an Agency has 1..n Branches, each with its own data, branding, currency and payment processors | Organisation + Branch (E02) |
| Client | Bill payer (parent or company) | Client account + Contacts (E05) |
| Recipient | Student receiving the service | Student (E05) |
| Contractor | Tutor | Tutor (E05) |
| Agent | Affiliate/referrer earning commission | Affiliate (E25) |
| Service / Job | An arrangement for a client's recipients with tutors at a charge rate and pay rate | Job (E07) |
| Appointment / Lesson | A scheduled session in a Job | Lesson (E08) |
| Lesson report | Tutor's post-lesson report, optionally emailed to the client | Lesson report (E09) |
| Ad hoc charge | One-off charge or payment (books, travel, fees) with categories | Ad hoc charge (E10) |
| Credit request / Proforma invoice | Request for prepayment that tops up the client's balance | Payment request (E10) |
| Client balance | Running balance of lessons, credit, ad hoc charges and refunds; option to prevent negative balances | Client ledger (E10) |
| Payment order | Batch of tutor payouts | Pay run (E12) |
| Labels, Pipeline stages | CRM tagging, sales pipeline | Tags, Pipeline (E05, E17) |
| Socket | Embeddable public tutor directory and enquiry form | Public widgets (E24) |
| Chronos | Webhook delivery service, HMAC-SHA256 signed | Webhooks (E27) |

**Feature inventory:**
- *CRM:* unlimited profiles for clients, tutors and students; custom fields; labels; configurable sales pipeline; notes; tasks; automated client onboarding; action history (audit).
- *Scheduling:* single calendar; 1:1 and group lessons; recurring series; cancellations; tutor availability; reminders; whiteboard/video integrations.
- *Finance:* auto-invoicing from lessons; proformas/credit requests (manual and bulk, reminders); client balances, including invoice vs available balance and unallocated credit; prevent negative balances (block tutors from completing lessons); custom charge/pay rates per job and per lesson (only admins see both); ad hoc charges; split payments; multi-currency; tutor payroll and payouts; exports to Xero/QuickBooks with reconciliation.
- *Payments:* Stripe (Standard + Connect; GBP/USD/EUR/AUD/CAD/NZD/SEK), GoCardless direct debit (UK/EU/AU/NZ), bank transfer.
- *Comms:* branded email templates ("email definitions" that can be toggled), SMS, broadcasts, automated reminders.
- *Reporting:* customisable dashboard; financial reports; contractor pay reports; client statements; lesson reports; custom exports; BigQuery export.
- *Branding:* white-label, custom domain, logo and colours.
- *Integrations:* Xero, QuickBooks Online, Stripe, GoCardless, Mailchimp, Intercom, Zapier, Zoom, Daily.co, Lessonspace, Microsoft Teams, Google Calendar, iCal feeds, Google/Apple SSO, Meta for Business.
- *API:* REST with OpenAPI schema, Swagger/ReDoc; token auth per Integration; resources for appointments, services, clients, contractors, recipients, agents, invoices, proformas, payment orders, ad hoc charges, balance updates, reviews, tasks, notes, labels, enquiries. Webhooks for create/update/delete, HMAC signed.
- *Security:* 2FA (TOTP), SSO, GDPR export/erasure, EU/UK data residency on request, encryption, card data held only at Stripe.
- *Commercial:* PAYG (% of revenue), Startup and Enterprise plans; 2-week trial; support in London and Chicago.

**Weaknesses reported:** steep learning curve; dated UI; no tracking of late lesson reports; billing confusion when moving clients between GoCardless and Stripe; pipeline can't drive broadcasts; costly for solo tutors.

## 2. TutorBird (Canada; sole-trader and small-team focused)

**Positioning:** Affordable all-in-one for independent tutors and small centres (sister product of My Music Staff). From $14.95/month plus $4.95 per extra tutor, 30-day trial.

**Feature inventory:**
- *Students and families:* student profiles (contacts, notes, attachments, lesson history, billing); family grouping with combined invoicing; statuses Active/Trial/Waiting/Lead; waitlist; spreadsheet import; replaces paper registration.
- *Calendar:* private, group and non-tutoring events; daily/weekly/monthly recurrence; colour coding by category and location; filters by student, tutor, category and location; attendance tracking; tutor availability and conflict prevention; **two-way sync** with Google, Apple and Outlook; email and SMS reminders with custom timing and content.
- *Billing:* **calendar-based billing** (charges calculated from scheduled lessons and attendance); default price per lesson, per month or per hour; manual or recurring invoices emailed automatically; tutor gets a summary to review a few days before invoices go out; overdue reminders and **late-fee automation**; Stripe and PayPal; **Auto-Pay** using stored payment methods; cash and cheque recorded manually; revenue tracking.
- *Business:* expenses; mileage tracking; reports.
- *LMS-lite:* share files, homework and news; lesson notes; homework submission; lending library (track items lent to students).
- *Multi-tutor:* staff and tutors with custom roles and permissions; tutor-specific schedules; payroll calculation.
- *Portal:* parents and students view schedule, pay, read lesson notes, submit homework, and (if allowed) book or cancel.
- *Website builder:* drag-and-drop, mobile templates, branding, registration and contact forms, free subdomain or custom domain; embeddable login widget for Wix, Squarespace and WordPress.
- *Integrations:* Zapier, Stripe, PayPal.
- *i18n:* English, French, Spanish, Dutch, German, Polish.

**Weaknesses reported:** no native mobile app or push notifications; no virtual classroom; no grading, gradebooks or formal progress reports; Stripe unavailable in some regions; per-tutor pricing; calendar sync not frequent enough; invoicing and sync can be confusing; not suited to large academies; no public API.

## 3. Teachworks (Canada; mid-market centres and agencies)

- Strong multi-teacher, multi-location scheduling.
- **Wage tiers:** pay different hourly rates for the same service based on experience or credentials; tiers assigned per teacher. Editing a tier doesn't retroactively change lessons.
- Non-hourly compensation: bonuses, referrals, salaries, reimbursements.
- Cost premiums (per-lesson surcharges), lesson packages, prepaid credit.
- Pricing: base fee plus per-student-lesson fee; unlimited users.
- Public API.

## 4. Other notable players (for inspiration)

| Product | Notable ideas worth adopting |
|---|---|
| **Teach 'n Go** | Course/class-centric model, enrolment forms, waitlists, multi-language |
| **Oases Online** | Learning-centre CRM, program/assessment tracking |
| **Fons / Acuity / Calendly** | Frictionless self-booking with payment at booking |
| **Lessonspace / Bramble / Pencil Spaces** | Embedded online classroom with whiteboard and recordings; AI lesson notes |
| **Jackrabbit Class** | Class enrolment, recurring tuition, registration fees, family billing |
| **Wise / Stripe Connect / Payouts** | Automated multi-currency tutor payouts |

## 5. Feature parity matrix

Legend: ● full, ◐ partial, ○ none. "TT" is TutorTrack's target.

| Capability | TutorCruncher | TutorBird | Teachworks | TT target | Epic |
|---|---|---|---|---|---|
| Multi-branch tenancy | ● | ○ | ◐ | ● | E02 |
| Roles and custom permissions | ● | ● | ● | ● | E03 |
| SSO and 2FA | ● | ○ | ◐ | ● | E03 |
| Custom fields, tags | ● | ◐ | ◐ | ● | E05 |
| Families and multiple guardians | ◐ | ● | ● | ● | E05 |
| Wage tiers / pay rate rules | ◐ | ◐ | ● | ● | E06 |
| Packages and prepaid bundles | ◐ | ◐ | ● | ● | E06/E10 |
| Job model with charge/pay margin | ● | ○ | ◐ | ● | E07 |
| Recurring and group lessons | ● | ● | ● | ● | E08 |
| Rooms and resources | ◐ | ◐ | ● | ● | E08 |
| Client self-booking and rescheduling | ◐ | ● | ◐ | ● | E08/E15 |
| Cancellation policies (late-cancel fees) | ◐ | ◐ | ● | ● | E09 |
| Lesson reports and SLA tracking | ◐ | ◐ | ◐ | ● | E09 |
| Calendar-based auto billing | ● | ● | ● | ● | E10 |
| Prepayment / credit / balances | ● | ◐ | ● | ● | E10 |
| Late fees, dunning | ◐ | ● | ◐ | ● | E10/E11 |
| Card, direct debit, PayPal, auto-pay | ● | ● | ● | ● | E11 |
| Tutor payroll and automated payouts | ● | ◐ | ● | ● | E12 |
| Expenses and mileage | ◐ | ● | ● | ● | E12 |
| Email, SMS, broadcasts | ● | ● | ● | ● | E13 |
| WhatsApp, in-app chat, push | ○ | ○ | ○ | ● | E13 |
| Automation builder | ◐ | ○ | ○ | ● | E14 |
| Client/student portal | ● | ● | ● | ● | E15 |
| Native/PWA mobile app | ◐ | ○ | ◐ | ● | E16 |
| Sales pipeline and enquiries | ● | ◐ | ◐ | ● | E17 |
| Tutor recruitment and compliance (DBS etc.) | ● | ○ | ○ | ● | E18 |
| Tutor matching and job board | ● | ○ | ○ | ● | E19 |
| Courses, terms, enrolment | ◐ | ◐ | ◐ | ● | E20 |
| Homework, resources, progress | ○ | ◐ | ◐ | ● | E21 |
| Two-way calendar sync | ◐ | ● | ● | ● | E22 |
| Video (Zoom/Teams/Meet/Lessonspace) | ● | ○ | ◐ | ● | E22 |
| Xero / QuickBooks | ● | ○ | ● | ● | E23 |
| Website builder / widgets | ◐ | ● | ◐ | ● | E24 |
| White-label and custom domain | ● | ◐ | ◐ | ● | E24 |
| Reviews, referrals, affiliates | ● | ○ | ○ | ● | E25 |
| Dashboards and reports | ● | ◐ | ● | ● | E26 |
| Public API and webhooks | ● | ○ | ● | ● | E27 |
| Zapier/Make | ● | ● | ● | ● | E27 |
| Import/migration tools | ◐ | ◐ | ◐ | ● | E28 |
| GDPR tools, audit trail | ● | ◐ | ◐ | ● | E29 |
| AI assistance | ○ | ○ | ○ | ● | E31 |

## 6. Sources

- TutorCruncher: tutorcruncher.com/features, tutorcruncher.com/llms-full.txt, help.tutorcruncher.com (Credit Requests, Client Balances, Lessons, Lesson Reports, Accounting)
- TutorBird: tutorbird.com/features; Teach 'n Go TutorBird review; GetApp/Capterra listings
- Teachworks: blog.teachworks.com (wages), Teachworks Intercom help (wage tiers), Toolradar comparisons
