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
- [ ] **E18-T01** Job openings and public application form (form builder reuse).
- [ ] **E18-T02** Recruitment pipeline, stages, scorecards, templated emails, bulk actions.
- [ ] **E18-T03** Interview scheduling via slot engine.
- [ ] **E18-T04** Reference requests with secure referee forms.
- [ ] **E18-T05** Approval → tutor creation + onboarding checklist instance.
- [ ] **E18-T06** Compliance requirement types (seed UK/US/AU/CA/IE/NZ), records, verification.
- [ ] **E18-T07** Restriction rules, nightly expiry job, assignment guard in E07/E08, pay hold hook in E12.
- [ ] **E18-T08** Compliance dashboard and alerts.
- [ ] **E18-T09** Subject competency approvals.
- [ ] **E18-T10** Frontend: recruitment board, application detail, tutor onboarding (tutor portal), compliance UI.
- [ ] **E18-T11** (Phase 3) Background check provider integrations.
