# E09 — Lesson Delivery: Attendance, Cancellations & Lesson Reports

| | |
|---|---|
| **Phase** | MVP |
| **Depends on** | E08 |
| **Parity** | TutorCruncher lesson completion, reports, "prevent negative balance"; TutorBird attendance, lesson notes. **Improves on** both with report SLAs and structured templates |

## 1. Summary
What happens when a lesson takes place (or doesn't): marking completion and attendance, cancellation policies (who cancelled, when, and whether it's chargeable/payable), lesson reports with templates, sharing with clients, and SLA tracking. Completion is the trigger that drives billing (E10) and pay (E12).

## 2. Functional requirements

### FR-09-1 Completing a lesson
- Tutors (own lessons) and staff can mark a lesson complete after its start time (setting: allow early completion N minutes before end).
- Completion captures: actual start/end (default = scheduled; editing the duration re-resolves charge/pay if the setting "bill actual duration" is on), attendance per student, optional expenses (E12), lesson report (inline or later).
- Auto-complete option: lessons not marked within N hours are auto-completed as "present" (org setting; off by default for agencies), or flagged as **unconfirmed**.
- **Prevent negative balance** (TutorCruncher parity): if the client's available balance (prepaid billing) would go below zero (or below the credit limit), completion is blocked for tutors with the message "client needs to top up" and an admin notification; staff with permission can override.
- **AC:** completing a lesson emits `lesson.completed` with attendee outcomes; E10 creates charges for chargeable attendees and E12 creates pay items for payable tutors, all idempotently.

### FR-09-2 Attendance
- Outcomes per attendee: `present`, `late` (minutes), `absent_notified`, `no_show`, `cancelled_client`, `cancelled_tutor`, `cancelled_admin`.
- Each outcome maps via **policy** to chargeable (full/partial %/none) and payable (full/partial %/none).
- Group lesson register UI: tick list, bulk "all present".
- Attendance stats per student (rate %, streaks) for reports and portals.

### FR-09-3 Cancellation policies
- Org default policy plus overrides by branch, service, job, client:
  - Free cancellation window (e.g. ≥ 24h notice → no charge).
  - Late cancellation (< window) → charge X% to client, pay Y% to tutor.
  - No-show → charge X%, pay Y%.
  - Tutor cancellation → no charge; optional tutor penalty (deduction) or makeup credit.
  - Max free cancellations per term/month.
  - Makeup lesson credit option: instead of a refund, issue a makeup credit valid for N days (tracked per student; consumed when booking a makeup).
- Cancellation flow UI: who cancelled (client/student/tutor/admin), reason (configurable list), notice time computed automatically, policy outcome preview ("This is a late cancellation: client charged 100%, tutor paid 50%") with override (permissioned, audited), notify participants toggle, offer reschedule.
- Series cancellation: cancel all future occurrences (e.g. the student is stopping).
- **AC:** a client cancelling via the portal 10 hours before a lesson under a 24h policy is shown the fee before confirming, and the charge is created as a "Late cancellation fee" line referencing the lesson.

### FR-09-4 Lesson report templates
- Template builder: sections and fields (rich text, rating 1–5, select, multi-select, checklist, topics covered from a curriculum list (E21), homework set (E21), next steps, private-to-staff field, attachment).
- Templates assigned by service/subject/job; default "Simple" template = "What we covered" + "Homework" + "Notes for parent" + "Private notes".
- Per-field visibility: staff only / client / student.

### FR-09-5 Writing reports
- Tutors write reports from the lesson popover, the tutor portal/PWA (offline-capable, E16) or via a "reports due" list. Drafts autosave.
- AI draft assistance (E31): bullet notes → polished report.
- Submitting a report can auto-complete the lesson (setting).
- Edit window after submission (e.g. 48h) and then locked; staff can always edit (audited).

### FR-09-6 Report review and sharing
- Optional **approval** step (agencies): staff review before release to clients (queue with approve/edit/return-to-tutor).
- Sharing: automatic on submit/approve or manual; channels: client portal, email (rendered report), included with invoice email (TutorCruncher "report visibility" parity).
- Clients can reply or react to a report (thread → E13 messaging); replies go to tutor and/or staff as configured.

### FR-09-7 Report SLA tracking
- Setting: report due within N hours of lesson end (default 24h).
- States: `not_required | due | overdue | submitted | approved | shared`.
- Reminders to tutors at due time and when overdue (E13), escalation to staff after M hours.
- Optional rules: block **tutor pay** for lessons with overdue reports (pay item held, E12); block **invoice** generation for lessons without reports (setting).
- Tutor scorecard: % on-time reports (E26).
- **AC:** a lesson ending at 17:00 with a 24h SLA becomes overdue at 17:00 the next day, emits `lesson_report.overdue`, and appears in the tutor's and coordinator's "Overdue reports" lists.

### FR-09-8 Unconfirmed lessons queue
- Staff dashboard list of past lessons still `planned` (not completed/cancelled) beyond N hours, with bulk complete/cancel and a nudge to the tutor.

### FR-09-9 Lesson feedback from clients/students (Phase 2)
- Optional post-lesson micro-survey (1–5 + comment) sent to client/student; feeds tutor rating (E25) and alerts staff on low scores.

## 3. Data model
`AttendanceRecord` (fields on LessonAttendee: outcome, late_minutes, recorded_by, recorded_at), `CancellationPolicy(scope generic, rules JSONB versioned)`, `CancellationRecord(lesson, cancelled_by_type, cancelled_by_user, reason, notice_minutes, policy_snapshot, charge_pct, pay_pct, overridden)`, `MakeupCredit(student, source_lesson, expires_at, consumed_by_lesson)`, `ReportTemplate`, `ReportTemplateField`, `LessonReport(lesson, tutor, template_version, answers JSONB, status, submitted_at, approved_by, shared_at, due_at)`, `LessonReportComment`, `LessonFeedback`.

## 4. API
`POST /api/v1/lessons/{id}/complete`, `POST /lessons/{id}/cancel` (with `?preview=true`), `PATCH /lessons/{id}/attendance`, `/report-templates` CRUD, `/lessons/{id}/report` (GET/PUT draft/POST submit/POST approve/POST share), `/reports?status=overdue&tutor=`, `/lessons/unconfirmed`, `/cancellation-policies`.

## 5. Events
`lesson.completed`, `lesson.cancelled` (with policy outcome), `attendance.recorded`, `lesson_report.due`, `lesson_report.submitted`, `lesson_report.overdue`, `lesson_report.approved`, `lesson_report.shared`, `lesson_feedback.received`, `makeup_credit.issued/consumed/expired`.

## 6. Permissions
`delivery.lesson.complete` (own/all), `delivery.attendance.edit`, `delivery.cancel.override_policy`, `delivery.report.{write,approve,edit_any,share}`, `delivery.policy.manage`.

## 7. Delivery plan
- [x] **E09-T01** Complete-lesson service: actual times, attendance, idempotent event emission; negative-balance guard (interface to E10 balance selector).
- [x] **E09-T02** Cancellation policy model, evaluation engine and preview; cancel service for single and series.
- [x] **E09-T03** Makeup credits.
- [x] **E09-T04** Report templates (builder backend), versioning.
- [x] **E09-T05** Lesson reports: draft/submit/approve/share, visibility rules, comments.
- [x] **E09-T06** SLA engine: due/overdue computation task, reminders, escalation, pay/invoice hold flags.
- [x] **E09-T07** Unconfirmed lessons queue and auto-complete task.
- [x] **E09-T08** Frontend: complete-lesson modal, register UI, cancel flow with policy preview, report editor, report review queue.
- [ ] **E09-T09** (Phase 2) Client feedback micro-surveys.

## Temporal workflows (E32)

Implement these processes as Temporal workflows following the rules in [E32](E32-workflow-orchestration-temporal.md) (deterministic workflow code, side effects in tenant-scoped activities that call services, tenant-prefixed workflow IDs, signals for human decisions). Where the requirements above mention sweeper tasks, `next_*_at` / `resume_at` columns or retry schedules, the workflow replaces them.

- [x] **E09-TW1** Lesson report SLA and unconfirmed-lesson workflows (requires E32).

| Workflow | Started by | Steps, timers and signals | Replaces |
|---|---|---|---|
| `LessonReportSlaWorkflow` `report-sla:{org}:{lesson}` | `lesson.completed` (report required) | Timer to **due** → reminder → overdue event + hold pay (E12) → escalate to coordinator after M hours. Signal `submitted` ends it; `approved`/`shared` update state | Due/overdue beat sweeper (FR-09-7) |
| `UnconfirmedLessonWorkflow` | Lesson end time passes while still `planned` | Nudge tutor after N hours → auto-complete or flag per setting. Signal `completed`/`cancelled` ends it | Unconfirmed sweeper (FR-09-8) |

## Implementation notes (as built 2026-10-09)
- **App:** `delivery` holds `CancellationPolicy` (versioned: an update creates a new version and deactivates the old one), `CancellationRecord`, `MakeupCredit`, `ReportTemplate` + `ReportTemplateVersion` (fields as JSON on immutable versions, replacing the separate `ReportTemplateField` table), `LessonReport` and `LessonReportComment`. All have RLS. Attendance lives on scheduling's `LessonAttendee` (outcome, late minutes, charge %, recorded by/at). `LessonTutor.pay_percent`, `Lesson.actual_start/actual_end/cancelled_by/auto_completed/unconfirmed_at` were added in scheduling 0002. See ADR 0006 for the split.
- **Completion (T01):** `POST /lessons/{id}/complete` takes `attendance` (students left out were present), optional actual times and `override_balance`. Policies map each outcome to a charge %. Tutors are paid in full if anyone attended; otherwise they get the best outcome's pay %. Completion opens at the start, or N minutes before the end (`delivery.completion_opens`). `delivery.bill_actual_duration` re-prices from actual times. The prepaid-balance guard is a hook (`delivery.balance.set_guard`) that E10 fills. A blocked completion returns 422 `code=insufficient_balance` and publishes `lesson.completion_blocked`. Overriding needs `delivery.balance.override`. Completing publishes `lesson.completed` with per-attendee and per-tutor rows. Corrections go through `PATCH /lessons/{id}/attendance` (unlocked lessons only; `attendance.recorded`). The permission to complete stays `scheduling.lesson.complete` (the spec's `delivery.lesson.complete` was not added).
- **Cancellation (T02):** `POST /lessons/{id}/cancel` takes `cancelled_by` (client/student/tutor/admin), reason, notify, `scope` (`following` also ends the series; later lessons are cancelled free) and an optional `override` of the percentages (`delivery.cancel.override_policy`; audited as `override_policy`). `?preview=true` returns the outcome and message ("This is a late cancellation: client charged 100%, tutor paid 50%.") without changing anything. Notice is computed from the cancellation time. "Max free cancellations per month" counts the client's free cancellations in the lesson's local calendar month. A client policy applies when every attendee belongs to that client. Cancellations carry over "charge %" for the E10 late-fee line. The "term" limit waits for terms (E20).
- **Makeup credits (T03):** issued on free or tutor cancellations when the policy says so, and valid for N days. Consuming one marks the makeup lesson for that student (E10 doesn't charge it, via `selectors.makeup_students`). Credits can be extended or voided. Expiry is derived from `expires_at`, so there is no sweeper and no `makeup_credit.expired` event yet; E13 reminders can add a workflow if needed.
- **Templates (T04):** a builder backend with types rich text, text, rating, select, multi-select, checklist, topics, homework, next steps and attachment. Visibility is staff, client or student per field. Topics and homework are free lists until E21 curricula. Attachments are stored as references (names/URLs) until uploads are wired. Resolution order is job → service → subject → default "Simple" (seeded on `organisation.created` and created lazily).
- **Reports (T05):** one report per lesson and tutor. `POST /lessons/{id}/reports` opens it (writable before completion). Then `/lesson-reports/{id}` GET/PUT (draft autosave), `submit`, `approve`, `return`, `share` and `comments`. Reports are addressed by their own id rather than `/lessons/{id}/report`. Submitting completes a started planned lesson (`delivery.report_submit_completes`). Reports auto-share unless approval is required. Tutors can edit for `delivery.report_edit_window_hours` after submitting; staff with `delivery.report.edit_any` always can (audited). Answers are filtered per audience (`templates.visible_answers`) for the portals (E15).
- **SLA (T06, TW1):** `LessonReportSlaWorkflow` sends a reminder N hours before due (`lesson_report.due`). At the due time it marks the report overdue (`lesson_report.overdue`, `pay_held` when `delivery.hold_pay_overdue_reports`). M hours later it escalates (`lesson_report.escalated` plus a CRM task on the report). Submission signals it to stop, and each step re-checks the report. `?sla=overdue` lists overdue reports for tutors (own) and staff. `selectors.lessons_with_open_reports` serves E10's `delivery.hold_invoice_without_report`.
- **Unconfirmed (T07, TW1):** `/unconfirmed-lessons` lists them, and `POST` nudges tutors (`lesson.unconfirmed`, flags the lesson). Bulk complete/cancel uses `/lessons/bulk`, which now applies delivery policies. A 15-minute beat task starts `UnconfirmedLessonWorkflow` for lessons that just ended (ADR 0006). After `delivery.unconfirmed_after_hours` it auto-completes (setting) or flags and nudges. A prepaid client with too little credit is flagged rather than auto-completed.
- **Stats:** `/students/{id}/attendance` returns the rate, streak and counts by outcome. Cancellations by the tutor or by us don't count.
- **Frontend (T08):** the calendar quick view gains a register (outcome per student, minutes late, "mark all present", actual times, balance override) and a cancel flow with a live policy preview, override and series option. It also has "Write report". New pages: report editor with field types, autosave, submit/approve/return/share and comments; reports list (due/overdue/to approve/shared); unconfirmed lessons with bulk actions; lesson policies (organisation cancellation policy and report template builder). Overrides for a branch, service, job or client are API-only for now.
- **Deferred:** T09 feedback micro-surveys (Phase 2); AI drafting (E31); offline writing (E16); report emails and reminders are events for E13.
