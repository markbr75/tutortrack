# TutorTrack — Product & Engineering Specification

TutorTrack is a multi-tenant SaaS platform that lets a tutoring business run end to end, whether it is a sole trader with ten students or an agency with hundreds of tutors across several branches. It combines the strongest parts of **TutorCruncher** (agency operations, double-sided finance, pipeline, recruitment, API) with those of **TutorBird** (simplicity for sole traders, calendar-based billing, student portal, website builder, LMS-lite). It also adds what both lack: a native mobile/PWA experience, an automation engine, classes and courses, deeper learning tools, and AI assistance.

> "TutorTrack" is the working name, taken from the repo folder. Find and replace it if the product is renamed.

## How to use these docs with Claude Code

1. Read `CLAUDE.md` at the repo root first. It holds the non-negotiable engineering conventions.
2. Read the foundation documents in order: vision, competitive analysis, architecture, domain model, roadmap.
3. Build the epics **in the order given in [04-roadmap.md](04-roadmap.md)**. Each epic file has:
   - functional requirements with IDs (`FR-<epic>-<n>`) and acceptance criteria
   - the data model it introduces
   - API endpoints, domain events and permissions
   - a **Delivery Plan**: an ordered list of build tickets sized for one Claude Code session each
4. Suggested prompt per ticket:
   > "Implement ticket E08-T03 from docs/epics/E08-scheduling-calendar.md. Follow CLAUDE.md and docs/02-architecture.md. Write tests first and make sure `make check` passes."
5. When an epic is finished, tick it off in `04-roadmap.md` and record any decisions in `docs/adr/`.

## Document index

| Doc | Purpose |
|---|---|
| [00-product-vision.md](00-product-vision.md) | Vision, target customers, personas, principles, differentiators |
| [01-competitive-analysis.md](01-competitive-analysis.md) | Deep dive on TutorCruncher, TutorBird, Teachworks and others; feature parity matrix |
| [02-architecture.md](02-architecture.md) | Tech stack, multi-tenancy, module layout, cross-cutting patterns |
| [03-domain-model.md](03-domain-model.md) | Glossary and core entity model shared by all epics |
| [04-roadmap.md](04-roadmap.md) | Phasing (MVP → Agency → Scale), epic dependency graph, build order |
| [adr/](adr/) | Architecture Decision Records |

## Epics

| # | Epic | Phase |
|---|---|---|
| E01 | [Platform Foundations & Engineering Standards](epics/E01-platform-foundations.md) | MVP |
| E02 | [Multi-Tenancy, Organisations & Branches](epics/E02-multi-tenancy.md) | MVP |
| E03 | [Identity, Authentication & Access Control](epics/E03-identity-access.md) | MVP |
| E04 | [SaaS Subscriptions, Plans & Entitlements](epics/E04-saas-subscriptions.md) | MVP |
| E05 | [People & CRM Core](epics/E05-people-crm.md) | MVP |
| E06 | [Service Catalogue, Pricing & Rates](epics/E06-catalogue-pricing.md) | MVP |
| E07 | [Jobs & Tutor Assignment](epics/E07-jobs.md) | MVP |
| E08 | [Scheduling, Calendar & Availability](epics/E08-scheduling-calendar.md) | MVP |
| E09 | [Lesson Delivery, Attendance & Lesson Reports](epics/E09-lesson-delivery.md) | MVP |
| E10 | [Client Billing: Ledger, Invoices, Credit & Packages](epics/E10-client-billing.md) | MVP |
| E11 | [Payments Processing](epics/E11-payments.md) | MVP |
| E12 | [Tutor Payroll, Expenses & Payouts](epics/E12-tutor-payroll.md) | Agency |
| E13 | [Communications & Notifications](epics/E13-communications.md) | MVP |
| E14 | [Automation & Workflow Engine](epics/E14-automation.md) | Agency |
| E15 | [Client & Student Portal](epics/E15-client-portal.md) | MVP |
| E16 | [Tutor Portal & Mobile Experience](epics/E16-tutor-portal-mobile.md) | MVP/Agency |
| E17 | [Leads, Enquiries & Sales Pipeline](epics/E17-leads-pipeline.md) | Agency |
| E18 | [Tutor Recruitment, Onboarding & Compliance](epics/E18-tutor-recruitment-compliance.md) | Agency |
| E19 | [Tutor Matching & Job Marketplace](epics/E19-matching-marketplace.md) | Agency |
| E20 | [Group Classes, Courses & Term Enrolment](epics/E20-classes-courses.md) | Scale |
| E21 | [Learning Tools: Progress, Homework, Resources](epics/E21-learning-tools.md) | Scale |
| E22 | [Calendar Sync & Online Lesson Integrations](epics/E22-calendar-video-integrations.md) | Agency |
| E23 | [Accounting Integrations](epics/E23-accounting-integrations.md) | Agency |
| E24 | [Public Website, Widgets & White-labelling](epics/E24-website-widgets-branding.md) | Agency |
| E25 | [Reviews, Referrals & Affiliates](epics/E25-reviews-referrals-affiliates.md) | Scale |
| E26 | [Reporting, Analytics & Dashboards](epics/E26-reporting-analytics.md) | Agency |
| E27 | [Public API, Webhooks & Integration Platform](epics/E27-public-api-webhooks.md) | Agency |
| E28 | [Data Import, Export & Competitor Migration](epics/E28-import-export-migration.md) | Agency |
| E29 | [Security, Privacy, Safeguarding & Compliance](epics/E29-security-privacy-compliance.md) | MVP→Scale |
| E30 | [Platform Administration, Support & Operations](epics/E30-platform-admin-ops.md) | MVP→Scale |
| E31 | [AI Assistant Features](epics/E31-ai-assistant.md) | Scale |
| E32 | [Workflow Orchestration (Temporal)](epics/E32-workflow-orchestration-temporal.md) | MVP (build after E03) |
