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
- [x] **E17-T01** Form builder backend (schema, validation, field mapping to entities), public submit with Turnstile/honeypot and UTM capture.
- [x] **E17-T02** Pipelines, stages, enquiry model, assignment rules, stage history, SLA flags.
- [x] **E17-T03** Enquiry creation from form/API/inbound email/manual; duplicate linking; auto-ack.
- [x] **E17-T04** Kanban and list UI; enquiry detail with timeline.
- [x] **E17-T05** Trial lesson booking and outcome.
- [x] **E17-T06** Conversion wizard (client/job/series/billing/portal invite).
- [x] **E17-T07** Waitlist and offers.
- [x] **E17-T08** Registration forms with fee payment.
- [ ] **E17-T09** (Phase 2b) Proposals with online acceptance.
- [x] **E17-T10** Funnel reports (E26 widgets).

## Temporal workflows (E32)

Implement these processes as Temporal workflows following the rules in [E32](E32-workflow-orchestration-temporal.md) (deterministic workflow code, side effects in tenant-scoped activities that call services, tenant-prefixed workflow IDs, signals for human decisions). Where the requirements above mention sweeper tasks, `next_*_at` / `resume_at` columns or retry schedules, the workflow replaces them.

- [x] **E17-TW1** Lead follow-up, waitlist and proposal workflows (requires E32).

| Workflow | Started by | Steps, timers and signals | Replaces |
|---|---|---|---|
| `EnquiryFollowUpWorkflow` `enquiry:{org}:{id}` | `enquiry.received` | Auto-ack → SLA timers per stage (breach event + escalation) → trial follow-up sequence. Signals `stage_changed`, `won`, `lost` adjust or end it | SLA flag sweeper |
| `WaitlistOfferWorkflow` | Capacity appears for a waitlisted student | Offer to the first in queue → wait `accepted`/`declined` until expiry → cascade to the next student | Offer expiry job |
| `ProposalWorkflow` | Proposal sent | Reminders → wait `accepted` → conversion + optional upfront payment (`PaymentCollectionWorkflow`) | Manual chasing |

## Implementation notes (as built 2026-10-10)
- **App:** `leads`, with RLS on every table: `Form`, `FormSubmission`, `Pipeline`, `PipelineStage`, `Enquiry` (CRM target `leads.enquiry`, so notes, tasks and tags work on it), `EnquiryStageHistory`, `AssignmentRule` and `WaitlistEntry`.
- **Forms (T01):** the schema is steps of fields (text, email, phone, select, checkbox and consent, postcode, a repeatable `students` group, textarea...). Each field has an optional `maps_to` onto contact, client, student or enquiry fields, plus `show_if` conditions. Definitions are validated: keys are unique, and email or phone is required.
  - Public endpoints: `GET/POST /public/forms/{slug}` on the tenant host. They are protected by Turnstile and a honeypot (spam is stored, flagged and silently accepted) and throttled (`public_form`).
  - UTM, referrer, landing page and click ids are captured. Answers that aren't mapped are kept on the submission and summarised in the enquiry notes.
  - The admin app hosts the form at `/f/<slug>`. Embeddable widgets are E24.
  - Deviations: no file-upload field yet; consent wording is a form setting.
- **Pipelines (T02):** a default pipeline is created on first use: New (24h SLA), Contacted (72h), Trial booked, Trial done, Won, Lost.
  - Pipelines and stages are editable; each pipeline needs exactly one Won and one Lost stage, and a stage still holding enquiries can't be removed.
  - Enquiries carry owner, priority, subjects, value estimate, expected start, source and UTM. Stage history records time in the previous stage. First response is when the enquiry first leaves its starting stage.
  - Assignment rules round-robin owners by pipeline, branch and subject.
  - Lost reasons come from a setting. "Nurture" tags the client `nurture` for broadcasts.
- **Capture (T03):** sources are the form, `POST /public/enquiries` (TutorCruncher-style; Turnstile and honeypot), inbound email (`/webhooks/inbound-email?token=`, Postmark inbound for `enquiries+<subdomain>@…`) and manual phone entry.
  - Duplicate detection matches an existing contact by email (or normalised phone) and links to that client, adding students by first name.
  - AC: one transaction creates the prospect client, contact, `lead` students and the enquiry at "New". The acknowledgement (`enquiry_acknowledgement`) and the owner notice (`enquiry_assigned`) follow asynchronously through the workflow.
  - Deviation: API keys for `/public/enquiries` arrive with E24/E27 (`api_access`); until then it is captcha-protected like the forms.
- **UI (T04):** a Kanban board (drag and drop, plus an accessible "Move to" select on each card) with a pipeline switcher, SLA-breach badges and manual entry. Enquiry detail shows contact and students, stage history, next steps (trial, outcome, convert, lose) and the CRM activity (notes, tasks).
- **Trials (T05):** a trial lesson for the enquiry's students with a chosen service and tutor, free by default (charge override 0). Students become `trial`; the enquiry moves to "Trial booked", and recording the outcome moves it to "Trial done". `trial_lesson.booked/completed` are published.
- **Conversion (T06):** the client and students become active and jobs are created (`seeking_tutor`, or `active` when a tutor is chosen). The enquiry is won, with the job ids recorded. Optionally the contact is invited to the portal and a card setup link is created (E11).
  - Deviation: setting up a recurring series at conversion is done afterwards from the job (E08).
- **Waitlist (T07):** entries per student and subject (optionally tutor or service), with their position in the queue. "Offer place" sends a time-limited link (`/offers/<token>`; `waitlist_offer` message), which the family accepts or declines.
  - `WaitlistOfferWorkflow` expires unanswered offers and, with the setting on, offers the place to the next student. When a job ends or loses a tutor, staff are told if students are waiting for that subject.
  - Deviation: "capacity appears" suggestions beyond this alert come with E19 matching.
- **Registration forms (T08):** a `registration` form creates an active client and students directly, skipping the pipeline. A registration fee becomes a payment request whose pay link the form redirects to (E10/E11).
- **Reports (T10):** `/leads/reports/funnel` shows how many enquiries reached each stage and the rate, win rate, average first response, breakdown by source and owner, lost reasons and won value. It is shown on the Reports tab; E26 dashboard widgets come later.
- **Workflows (TW1):** `EnquiryFollowUpWorkflow` acknowledges, then watches each stage's SLA. A breach publishes `enquiry.sla_breached` with a staff alert, at most once per stage visit. After a trial lesson completes, it reminds the owner to record the outcome. It ends when the enquiry is won or lost.
  - `ProposalWorkflow` comes with T09 (Phase 2b).
- **Not built:** proposals (T09, Phase 2b); Facebook and Google Lead Ads (Phase 3); file uploads on public forms.
