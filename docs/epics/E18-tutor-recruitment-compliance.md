# E18 — Tutor Recruitment, Onboarding & Compliance

| | |
|---|---|
| **Phase** | Agency (Phase 2) |
| **Depends on** | E05, E13, E17 (form builder) |
| **Parity** | TutorCruncher tutor applications and approvals; goes beyond both with full compliance/safeguarding tracking |

## 1. Summary
Attract and vet tutors: public application forms, a recruitment pipeline (screening, interview, references, checks), subject competency approval, onboarding checklists and agreements, and ongoing **compliance tracking** (DBS/background checks, right to work, ID, qualifications, safeguarding training, insurance) with expiry alerts and automatic restrictions.

## 2. Functional requirements

### FR-18-1 Application forms
- Built with the E17 form builder (`type=application`): personal details, subjects/levels with self-rated proficiency, qualifications and grades, experience, availability, location/travel radius, online/in-person, right-to-work status, CV upload, video intro (link or upload), references (2 referees), custom questions, consent and privacy notice.
- Public job pages per role/branch ("We're hiring Maths tutors in Leeds") listing open positions, with an apply button.

### FR-18-2 Recruitment pipeline
- Configurable stages (default: Applied → Screening → Interview → References & Checks → Decision → Onboarding), Kanban and list, owner assignment, scorecards (rating criteria per stage), notes, email templates (invite to interview, rejection, offer).
- Interview scheduling: send a booking link with interviewer availability (reuses E08 slot engine; video link via E22).
- Bulk reject with templated email; talent pool (keep for future).
- **AC:** approving an application creates a Tutor membership (status `onboarding`), TutorProfile populated from application data, an invitation email, and an onboarding checklist instance.

### FR-18-3 Subject competency
- Per subject/level approval states: `claimed → assessed → approved` with evidence (qualification, test score, interview). Only approved subjects are used for matching (E19) unless overridden.
- Optional online subject tests (Phase 3: integrate a quiz in E21 assessments).

### FR-18-4 References
- Automated reference requests to referees with a secure form; reminders; received references attached and scored; flag concerns.

### FR-18-5 Onboarding checklist
- Template checklists per employment type/branch: sign tutor agreement (e-sign), accept self-billing agreement (E12), safeguarding policy acknowledgement, upload documents, complete training modules (links/videos with completion tick), set availability, payout setup, profile photo/bio for approval.
- Progress tracking for tutor and staff; tutor becomes `active` when mandatory items are done (auto or manual).

### FR-18-6 Compliance requirements
- Requirement types (configurable per org/branch/role/delivery mode): e.g. **UK Enhanced DBS** (with Update Service number and check date), US background check, Canada Vulnerable Sector Check, AU Working With Children Check (state + number), right to work (share code), photo ID, proof of address, qualifications certificates, safeguarding training certificate, public liability insurance, first aid.
- Each requirement: document upload(s), reference number, issue date, expiry date (or renewal interval, e.g. DBS rechecked every 3 years by org policy), verification status (`missing → submitted → verified | rejected`), verified by/at, notes. Files stored with restricted visibility (E29).
- **Rules:** if a mandatory requirement is missing/expired → tutor `restricted`: cannot be assigned new jobs/lessons (hard block, overridable with permission + reason), optionally future lessons flagged, optionally pay held (E12).
- Expiry alerts: 60/30/7 days before to tutor and compliance staff; expired → restriction + event.
- **AC:** a tutor whose DBS expires today is automatically set to `restricted` by the nightly job, appears in the Compliance dashboard, and attempts to assign them to a new lesson fail with `tutor_not_compliant` unless overridden.

### FR-18-7 Background check integrations (Phase 3)
- Provider abstraction for online checks: UK (uCheck / Atlantic Data / DBS Update Service status check), US (Checkr), AU (state WWCC verification links). Initiate from the tutor record, track status via webhooks, attach results.

### FR-18-8 Compliance dashboard
- Matrix of tutors × requirements with status colours; filters; export; bulk request missing documents.

### FR-18-9 Tutor performance & offboarding
- Probation review reminders; performance notes; offboarding checklist (reassign jobs, revoke access, final pay run, retain records per retention policy).

## 3. Data model
`JobOpening`, `TutorApplication(form_submission, applicant details, stage, owner, scores, status, decision_reason)`, `ApplicationStage`, `Scorecard`, `ReferenceRequest`, `ChecklistTemplate`, `ChecklistInstance`, `ChecklistItem`, `ComplianceRequirementType(country, name, fields schema, renewal_months, applies_to rules, blocking: bool)`, `ComplianceRecord(tutor, requirement_type, status, number encrypted, issue_date, expiry_date, files, verified_by, verified_at)`, `BackgroundCheck(provider, status, ref, result)`.

## 4. API
`/api/v1/job-openings`, `/public/job-openings`, `/applications` (+ stage move, approve, reject), `/references`, `/checklists`, `/compliance/requirement-types`, `/compliance/records` (+ verify/reject), `/compliance/dashboard`, `/tutors/{id}/compliance`.

## 5. Events
`application.submitted/stage_changed/approved/rejected`, `reference.received`, `onboarding.completed`, `compliance.record_submitted/verified/rejected/expiring/expired`, `tutor.restricted/unrestricted`.

## 6. Permissions
`recruitment.application.*`, `recruitment.pipeline.manage`, `compliance.view`, `compliance.verify`, `compliance.manage_types`, `compliance.override_restriction`; compliance docs visible only to `compliance.view` holders and the tutor themself.

## 7. Delivery plan
- [x] **E18-T01** Job openings and public application form (form builder reuse).
- [x] **E18-T02** Recruitment pipeline, stages, scorecards, templated emails, bulk actions.
- [x] **E18-T03** Interview scheduling via slot engine.
- [x] **E18-T04** Reference requests with secure referee forms.
- [x] **E18-T05** Approval → tutor creation + onboarding checklist instance.
- [x] **E18-T06** Compliance requirement types (seed UK/US/AU/CA/IE/NZ), records, verification.
- [x] **E18-T07** Restriction rules, nightly expiry job, assignment guard in E07/E08, pay hold hook in E12.
- [x] **E18-T08** Compliance dashboard and alerts.
- [x] **E18-T09** Subject competency approvals.
- [x] **E18-T10** Frontend: recruitment board, application detail, tutor onboarding (tutor portal), compliance UI.
- [ ] **E18-T11** (Phase 3) Background check provider integrations.

## Temporal workflows (E32)

Implement these processes as Temporal workflows following the rules in [E32](E32-workflow-orchestration-temporal.md) (deterministic workflow code, side effects in tenant-scoped activities that call services, tenant-prefixed workflow IDs, signals for human decisions). Where the requirements above mention sweeper tasks, `next_*_at` / `resume_at` columns or retry schedules, the workflow replaces them.

- [x] **E18-TW1** Recruitment, onboarding and compliance workflows (requires E32).

| Workflow | Started by | Steps, timers and signals | Replaces |
|---|---|---|---|
| `TutorApplicationWorkflow` | `application.submitted` | Screening tasks → interview scheduling (wait for booking signal) → references (child `ReferenceRequestWorkflow` per referee with reminders and timeout) → decision signal → on approval start onboarding | Stage reminders |
| `TutorOnboardingWorkflow` `onboarding:{org}:{tutor}` | Application approved / tutor invited | Track checklist items via signals → reminders → activate tutor when mandatory items are done | Checklist polling |
| `ComplianceRecordWorkflow` `compliance:{org}:{record}` | `compliance.record_verified` with an expiry date | Timers at 60/30/7 days before expiry (reminders) → on expiry restrict tutor and hold pay. Signal `renewed` restarts with the new expiry (`continue_as_new`) | Nightly expiry job (FR-18-6) |

## Implementation notes (as built 2026-10-10)
- **App:** `recruitment`, with RLS on every table: `JobOpening`, `ApplicationStage`, `TutorApplication` (CRM target), `Scorecard`, `Interview`, `ReferenceRequest`, `ChecklistTemplate`, `ChecklistInstance`, `RequirementType`, `ComplianceRecord` (number encrypted) and `TutorComplianceState`. See ADR 0012.
- **Openings and applications (T01):** application forms reuse the E17 form builder (`type=application`, `applicant.*` mappings, a `referees` field). Public pages are `/vacancies` and `/vacancies/<slug>` (`/public/job-openings`); they use Turnstile, a honeypot and throttling. Referees named on the form get reference requests straight away.
  - Deviations: CV and video are links rather than uploads (anonymous uploads come with E24 widgets). The paths are `/vacancies` because `/jobs` is the tuition-jobs screen.
- **Pipeline (T02):** stages are Applied, Screening, Interview, References & checks, Decision, Hired, Rejected. Stages carry scorecard criteria and reminder days. Recruiters move applications between stages, score them (1-5 plus a recommendation), and reject them (single or bulk, with a templated email, optionally into the talent pool).
  - Deviations: the board shows open stages without drag and drop; email templates are editable through E13 templates (`application_rejected`, `interview_invite`, `reference_*`).
- **Interviews (T03):** staff propose times; the applicant picks one at `/interviews/<token>`.
  - Deviation: the E08 slot engine covers tutors' availability, not staff, so times are proposed by hand. Video links come with E22.
- **References (T04):** secure referee forms at `/references/<token>`: questions, a 1-5 rating and a concern flag. `ReferenceRequestWorkflow` reminds after 3 and 7 days and marks the request "no reply" after `recruitment.reference_days`.
- **Approval (T05):** AC: approving creates the tutor (status `onboarding`, subjects from the application) with an invitation, plus an onboarding checklist instance.
  - Checklist items: agreements and training are ticked by the tutor. Self-billing, payout details, availability, profile and documents complete themselves from the tutor's data.
  - `TutorOnboardingWorkflow` re-checks the checklist on item, compliance and availability events and every 3 days (with a reminder). It activates the tutor when every mandatory item is done (`recruitment.auto_activate`).
  - Deviation: e-signature is a recorded "I agree" with a timestamp.
- **Compliance (T06–T08):** requirement types are seeded from the organisation's country plus common types (photo ID, safeguarding training, qualifications, insurance), and staff can edit them. A requirement can apply only to some employment types or only to in-person work.
  - Records hold a number, issue and expiry dates (filled in from the renewal interval) and files. They are submitted by the tutor or staff and verified or rejected by `compliance.verify` holders (not the tutor themself).
  - The restriction rule is in ADR 0012. AC: a DBS expiring today is expired and the tutor restricted by the nightly sweep; the dashboard shows it; and lesson or job assignment fails with `tutor_not_compliant` unless overridden with permission and a reason.
  - Pay is held while restricted (`compliance.hold_pay`).
  - `ComplianceRecordWorkflow` sends reminders 60, 30 and 7 days before expiry, to the tutor and to staff, and expires the record on the date.
  - The dashboard (`/compliance`) shows tutors × requirements, and the tutor record shows a card with verify and reject. Tutors upload documents in the portal (`/portal/tutor/compliance`).
  - Deviations: no export or bulk "request missing documents" yet.
- **Subject competency (T09):** `TutorSubject.competency` moves `claimed → assessed → approved` (or rejected) with evidence; `approved` mirrors it for matching (E19). A data migration carried existing approvals over.
- **Frontend (T10):** admin recruitment board, application detail (stage, interview, references, approve or reject), compliance dashboard and tutor compliance card. Tutor portal: Getting started (checklist) and Checks (uploads). Public: vacancies, interview choice and reference pages.
- **Workflows (TW1):** application reminders when an application sits in a stage too long, plus the reference, onboarding and compliance-record workflows above.
- **Not built:** T11 (Phase 3 background-check providers); FR-18-9 probation reviews and offboarding checklists; public CV uploads.
