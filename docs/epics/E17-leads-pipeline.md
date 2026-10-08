# E17 — Leads, Enquiries & Sales Pipeline

| | |
|---|---|
| **Phase** | Agency (Phase 2) |
| **Depends on** | E05, E13 (E14 for automations) |
| **Parity** | TutorCruncher enquiry form, configurable pipeline, automated onboarding; TutorBird Lead/Trial/Waiting statuses, waitlist, registration forms |

## 1. Summary
Capture enquiries from websites, widgets, phone, email and marketplaces; work them through a configurable pipeline (Kanban) to won/lost; book trial lessons; and convert them into Client + Students + Job in one step. Includes registration forms, a waitlist and source/marketing attribution.

## 2. Functional requirements

### FR-17-1 Enquiry capture
- **Forms** (builder): fields from Client/Contact/Student + custom fields, subjects/levels picker, availability picker, postcode (for matching), budget, how-did-you-hear, consent checkboxes, file upload; multi-step; conditional fields; spam protection (Turnstile + honeypot); thank-you message/redirect.
- Channels: hosted form page (tenant domain), embeddable widget (E24), API (`POST /api/v1/public/enquiries`, TutorCruncher parity), inbound email to `enquiries@` address (parsed into an enquiry), manual entry (phone call), import, Zapier/Make, Facebook/Google Lead Ads (via webhooks, Phase 3).
- UTM/source capture (utm_*, referrer, landing page, gclid/fbclid) stored for attribution.
- Duplicate detection against existing contacts (link to the existing client instead of creating a new one).
- **AC:** a public form submission creates an Enquiry (stage "New"), a prospect Client + Contact + Student(s) flagged `lead`, sends the auto-acknowledgement (E13) and notifies the assigned coordinator, within 1 transaction + async notifications.

### FR-17-2 Pipeline
- Multiple pipelines (e.g. "Private tuition", "Schools/B2B"); stages configurable (name, order, probability %, SLA hours, colour); fixed outcome stages Won/Lost.
- Kanban board with drag between stages, cards showing name, subjects, value estimate, age, next task, owner; list view with filters; stage SLA breach highlighting.
- Enquiry fields: pipeline, stage, owner (round-robin assignment rules by branch/subject), estimated value (lessons/week × rate × weeks), expected start, priority, lost reason (configurable list), source, tags, custom fields.
- Activity: notes, calls logged, emails/SMS (E13 threads), tasks, stage history with time-in-stage.

### FR-17-3 Proposals / quotes (Phase 2b)
- Generate a branded proposal from templates: suggested tutor profiles (E19), schedule, pricing/packages; client accepts online → triggers conversion and optional upfront payment (E11).

### FR-17-4 Trial lessons
- Book a trial lesson from the enquiry (special price/free), with selected tutor; outcome capture after the trial (continue? feedback) → automation hooks.

### FR-17-5 Conversion
- "Convert to client": confirm client/contacts/students, create Job(s) (`seeking_tutor` or with tutor assigned), optional series, billing setup, portal invitation, payment method setup link. Enquiry → Won, linked to created records.
- Lost: reason required; nurture option (add to broadcast segment).

### FR-17-6 Waitlist
- Students with status `waiting` per subject/level/branch/tutor/class (E20); position, date added, notes; when capacity appears (tutor availability or class space) staff get a suggestion and can send an offer (time-limited accept link).

### FR-17-7 Registration forms (centres)
- Full registration form (TutorBird "replace paper registration"): household + students + medical + consents + terms acceptance + registration fee payment (E11) → creates active client directly (bypassing pipeline, setting).

### FR-17-8 Reporting
- Funnel conversion by stage, source, owner, branch; time to first response; win rate; lost reasons; revenue from won enquiries (E26 widgets).

## 3. Data model
`Form(type: enquiry|registration|application(E18)|custom, schema JSONB, settings, published)`, `FormSubmission(raw data, ip, utm, created_records)`, `Pipeline`, `PipelineStage`, `Enquiry(client, contact, students, pipeline, stage, owner, value_estimate, source, utm JSONB, status, lost_reason, won_at, lost_at, converted_job_ids)`, `EnquiryStageHistory`, `AssignmentRule`, `WaitlistEntry`, `Proposal`.

## 4. API
`/api/v1/forms` (+ publish), `/public/forms/{slug}` (GET schema, POST submit), `/public/enquiries` (API key or public with captcha), `/enquiries` CRUD + `/move`, `/convert`, `/lose`; `/pipelines`; `/waitlist` (+ `/offer`); `/proposals`.

## 5. Events
`enquiry.received`, `enquiry.assigned`, `enquiry.stage_changed`, `enquiry.won`, `enquiry.lost`, `enquiry.sla_breached`, `trial_lesson.booked/completed`, `waitlist.place_offered/accepted/expired`, `form.submitted`.

## 6. Permissions
`leads.enquiry.{view,create,edit,convert}`, `leads.pipeline.manage`, `leads.form.manage`, `leads.waitlist.manage`.

## 7. Delivery plan
- [ ] **E17-T01** Form builder backend (schema, validation, field mapping to entities), public submit with Turnstile/honeypot and UTM capture.
- [ ] **E17-T02** Pipelines, stages, enquiry model, assignment rules, stage history, SLA flags.
- [ ] **E17-T03** Enquiry creation from form/API/inbound email/manual; duplicate linking; auto-ack.
- [ ] **E17-T04** Kanban and list UI; enquiry detail with timeline.
- [ ] **E17-T05** Trial lesson booking and outcome.
- [ ] **E17-T06** Conversion wizard (client/job/series/billing/portal invite).
- [ ] **E17-T07** Waitlist and offers.
- [ ] **E17-T08** Registration forms with fee payment.
- [ ] **E17-T09** (Phase 2b) Proposals with online acceptance.
- [ ] **E17-T10** Funnel reports (E26 widgets).

## Temporal workflows (E32)

Implement these processes as Temporal workflows following the rules in [E32](E32-workflow-orchestration-temporal.md) (deterministic workflow code, side effects in tenant-scoped activities that call services, tenant-prefixed workflow IDs, signals for human decisions). Where the requirements above mention sweeper tasks, `next_*_at` / `resume_at` columns or retry schedules, the workflow replaces them.

- [ ] **E17-TW1** Lead follow-up, waitlist and proposal workflows (requires E32).

| Workflow | Started by | Steps, timers and signals | Replaces |
|---|---|---|---|
| `EnquiryFollowUpWorkflow` `enquiry:{org}:{id}` | `enquiry.received` | Auto-ack → SLA timers per stage (breach event + escalation) → trial follow-up sequence. Signals `stage_changed`, `won`, `lost` adjust or end it | SLA flag sweeper |
| `WaitlistOfferWorkflow` | Capacity appears for a waitlisted student | Offer to the first in queue → wait `accepted`/`declined` until expiry → cascade to the next student | Offer expiry job |
| `ProposalWorkflow` | Proposal sent | Reminders → wait `accepted` → conversion + optional upfront payment (`PaymentCollectionWorkflow`) | Manual chasing |
