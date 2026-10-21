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
- [x] **E18-T11** (Phase 3) Background check provider integrations.

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

## Phase 3 implementation notes (as built 2026-10-14)
See ADR 0032.

- **Providers (FR-18-7, `recruitment/checks/`):** a `CheckClient` interface (`initiate`, `fetch`, `cancel`) with:
  - `ucheck` (UK DBS basic/standard/enhanced, with or without the children's barred list): an application and an applicant link; polled every 6 hours;
  - `dbs_update` (DBS Update Service status check of an existing certificate, no account needed): the government API's answer (`BLANK/NON_BLANK_NO_NEW_INFO` = clear, `NEW_INFO` = needs review, `NO_MATCH_FOUND` = unable) is read from the XML with a regular expression (no XML entity expansion); re-checked every `compliance.dbs_update_recheck_days` (90);
  - `checkr` (US): candidate + invitation (hosted consent and details); report `clear/consider`; webhooks `/webhooks/background-checks/checkr` verified with the account's API key (HMAC-SHA256, `X-Checkr-Signature`) after routing by candidate id;
  - `wwcc` (AU Working With Children Checks): no API, so the check carries the state's verification page and staff record the outcome.
  uCheck and Checkr connect with an API key (integration framework, encrypted); all HTTP goes through `core.net.safe_urlopen`; without live credential providers every provider is `FakeChecks`. The real clients are tested against request shapes only (uCheck endpoint shapes to be confirmed against its partner documentation).
- **Model:** `BackgroundCheck` (RLS): provider, package, status (`requested → invited/in_progress → completed | cancelled | expired | failed`), result (`clear | consider | unable`), external and candidate ids, consent time, requester, reviewer. The invitation link, result details, certificate number and report link are `EncryptedField`s.
- **Flow (`BackgroundCheckWorkflow`, `bg-check:{org}:{check}`):** initiate → wait for `updated` (webhooks, staff "Check now" or an outcome) or the provider's polling interval → fetch → until complete, `cancel`led, or the invitation passes `compliance.check_invite_days` (30) and is expired at the provider. DBS Update Service checks then keep re-checking on a timer (up to 20 rounds per run). Histories `BackgroundCheckWorkflow-completed/expired.json` are replayed.
- **Results onto compliance records:** a completed check submits the mapped requirement (`dbs_enhanced`, `background_check`, `wwcc`) with the certificate number and issue date (expiry from the renewal interval). A clear result is verified by the provider when `compliance.checks_auto_verify` is on (default; `verified_by` empty, which starts the usual `ComplianceRecordWorkflow` for expiry). "Needs review" waits for a `compliance.verify` holder (`POST /background-checks/{id}/outcome`, not the tutor themself). New information from the Update Service rejects the record (restricting the tutor when the requirement blocks) and tells staff.
- **Sensitive data:** results and numbers are only readable through `GET /background-checks/{id}/details` (new `compliance.checks.results`, audited with `audit.record_read`); events carry ids and the outcome only. Starting and cancelling needs the new `compliance.checks.request` and a recorded tutor consent. A privacy provider exports checks without results; erasure clears results and numbers but keeps the fact of the check as evidence; the new retention category `background_check_details` (183 days, in line with DBS guidance) purges results, certificate numbers and links. uCheck and Checkr are listed as optional sub-processors (UK and US stacks).
- **UI:** the tutor record has an "Online background checks" card (start with provider, check type, certificate number or state, consent tick; check now, cancel, show result, mark clear or not completed). The tutor portal's Checks page lists the tutor's checks with the link to complete each.
- **Deviations:** Atlantic Data is not a separate provider (uCheck is Atlantic Data's DBS product); Canadian vulnerable sector checks and NZ police vetting stay manual uploads.

## Gap backlog (as built 2026-10-14)
Gap batch G2 (`docs/05-gap-backlog.md`, [ADR 0036](../adr/0036-identity-portal-households-demo-data-and-e-signing.md)).
- **Tutor agreements are e-signed (FR-18-5).** Checklist items with `"sign": true` (the default `agreement` item; older templates sign their `agreement` item) are signed, not ticked: `POST /api/v1/me/onboarding/{key}/sign {full_name, agree}` records a `crm.Signature` (kind agreement, the item text hashed and printed on the signed PDF) and completes the item with the signature id; `…/done` refuses such items. Staff can still mark an item done for a paper signature. Acknowledgements (safeguarding policy) stay a tick. Tutors also see and sign documents staff attach to their record (`GET /api/v1/tutor/documents`, `…/download`, `…/sign`), on the tutor portal's onboarding page. Event `agreement.signed`. This replaces the "recorded I agree" deviation above.

## Gap backlog (as built 2026-10-21)
Gap batch G5a (`docs/05-gap-backlog.md`, [ADR 0042](../adr/0042-anonymous-uploads-on-public-forms.md)).

- **CV and video uploads on the application form (FR-18-1).** Application forms take `file` fields (`file_kind` `cv`, `video` or `document`); `applicant.cv` and `applicant.video` map a single upload onto the application (`TutorApplication.cv`, new `video`), other file fields go to the new `attachments`. Uploads use the shared anonymous upload mechanism (`core.storage.public`, upload context `opening:<slug>`, only while the opening is published and open): CV PDF or Word up to 10 MB, video MP4/MOV/WebM up to 100 MB. The application detail returns `cv_file`, `video_file` and `attachments`. DSAR export includes the files; erasure deletes them. This replaces the "CV and video are links" deviation (a video link field stays available).
- **Job-opening editor (FR-18-1, E31 deviation).** Admin `/recruitment/openings` (nav: the Recruitment area's Openings tab, so no new sidebar item) lists openings with open applications and edits title, web address (made from the title when empty, unique), description (with "Draft with AI", which closes the E31 "no editor" deviation), subjects, location, branch, application form, published and closing date. Without a form the opening uses the standard application form (`POST /job-openings/default-form`, created once from `catalogue.APPLICATION_FORM`: details, subjects, qualifications, experience, right to work, CV, video, referees, privacy notice). Saving goes through `services.save_opening` (audited). The form builder now offers file fields and, for application forms, the `applicant.*` mappings and the referees field (`leads.forms.clean_schema(schema, form_type)`).
- **Compliance export and bulk requests (FR-18-8).** The dashboard filters by tutor status, requirement, cell status and "only tutors with gaps" (`GET /compliance/dashboard?tutor_status=&requirement=&cell_status=&gaps=`). `GET /compliance/dashboard/export` returns the same view as CSV (status and expiry per requirement, formula injection neutralised, audited as an export). `POST /compliance/request-missing {tutors?, requirements?}` (`compliance.verify`) messages each tutor (E13 `compliance_documents_requested`, email and in-app, with a link to Checks) listing their missing, rejected or expired documents and publishes `compliance.documents_requested`; the same request for the same tutor and documents is sent at most once a day.
- **Interview booking through the slot engine with a video link (FR-18-2).** `POST /applications/{id}/interviews` takes `mode=availability` with a date window (up to four weeks) and length: the applicant's link offers every free start (30-minute steps) of the interviewer in that window. Free time comes from the E08 slot engine (`scheduling.availability.fit_slots`, factored out of `free_slots`): an interviewer who is also a tutor uses their weekly availability, lessons, time off and connected calendars; other staff use the new `recruitment.interview_hours` setting (weekdays 09:00-17:00 by default) minus organisation closures; their other booked interviews are always busy. Booking re-checks the slot under a per-interviewer advisory lock (`slot_taken`). `mode=times` (staff offer times) still works. When an interview is booked, `InterviewWorkflow` (`interview:{org}:{interview}`) creates the meeting on the organisation's default video provider (the interviewer's own connection, the organisation's, or the built-in room; `calendar_sync.meetings.create_standalone_meeting`, retried up to five times; a link typed in by hand is kept), emails the applicant (`interview_confirmed`), alerts recruiters (`staff_interview_booked`) and reminds the applicant 24 hours before (`interview_reminder`). `recruitment.interview_video` turns the automatic link off. Event `application.interview_meeting_created`. Histories `InterviewWorkflow-reminded.json` replayed. This replaces the T03 deviation (times proposed by hand, video links later).
- **Probation reviews, performance notes and offboarding (FR-18-9).** New RLS tables `ProbationReview`, `PerformanceNote`, `OffboardingChecklist`.
  - A tutor who finishes onboarding gets a probation review `recruitment.probation_days` (90; 0 = none) later; staff can schedule one by hand (one open review per tutor). `ProbationReviewWorkflow` (`probation:{org}:{review}`) alerts staff (`staff_probation_review`, holders of `recruitment.performance.manage`) `recruitment.probation_reminder_days` (7) before, on the day (09:00 local), then weekly up to eight times until the outcome is recorded (`POST /probation-reviews/{id}/complete`: passed, extended to a later date (a new review), not passed or cancelled), which signals `closed`. Histories `ProbationReviewWorkflow-reviewed/unreviewed.json` replayed. Events `probation.scheduled/completed`.
  - Performance notes (praise, concern, note) are staff-only (`/performance-notes`, `recruitment.performance.view/manage`); `performance.note_added` is never offered to webhooks.
  - `POST /tutors/{id}/offboarding {reason, leaving_on}` (`recruitment.offboarding.manage`) starts the checklist (`catalogue.OFFBOARDING`), makes the tutor inactive and cancels an open probation review. Jobs, future lessons, access and final pay tick themselves from the tutor's data (no active or offered job links, no planned future lessons, no active login, no unpaid pay items); equipment and records are ticked by staff. `…/revoke-access` removes the tutor's membership (E03 `remove_member`); `…/complete` (only when every step is done) archives the tutor, whose records then follow the retention policy. Events `offboarding.started/completed`.
  - Admin: a Performance card (probation, notes, subject-test results) and an Offboarding card on the tutor record.
  - Deviation: offboarding has no reminders or timers (staff work through it), so it is a checklist, not a workflow; performance notes are not shown to the tutor.
- **Online subject tests (FR-18-3; E21 seam).** Quizzes with purpose "Tutor subject test" (Learning > Quizzes now sets purpose, subject and pass mark) are offered to tutors who teach the quiz's subject (and level, when set) in the tutor app at `/portal/tutor/tests` (`GET /me/subject-tests`, `GET/POST /me/subject-tests/{id}`; questions without answers). Marking uses E21 `take_quiz(student=None, user=…)`. Passing moves the matching claimed subjects to `assessed` with the score as evidence (approval stays with staff); a failed test can be retaken after `recruitment.subject_test_retake_days` (7); a passed one isn't retaken. Staff see results on the tutor record (`GET /tutors/{id}/subject-tests`, `people.tutor.approve_subjects`). Deviation: the quiz's time limit is shown but not enforced; applicants (who have no login) don't take tests; tutors do once approved into onboarding.
- **New settings:** `recruitment.probation_days`, `recruitment.probation_reminder_days`, `recruitment.interview_hours`, `recruitment.interview_video`, `recruitment.subject_test_retake_days`. **New permissions:** `recruitment.performance.view`, `recruitment.performance.manage`, `recruitment.offboarding.manage` (admins and owners through `*`). **New messages:** `compliance_documents_requested`, `interview_confirmed`, `interview_reminder`, `staff_interview_booked`, `staff_probation_review`.
