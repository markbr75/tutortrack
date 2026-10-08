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
- [ ] **E09-T01** Complete-lesson service: actual times, attendance, idempotent event emission; negative-balance guard (interface to E10 balance selector).
- [ ] **E09-T02** Cancellation policy model, evaluation engine and preview; cancel service for single and series.
- [ ] **E09-T03** Makeup credits.
- [ ] **E09-T04** Report templates (builder backend), versioning.
- [ ] **E09-T05** Lesson reports: draft/submit/approve/share, visibility rules, comments.
- [ ] **E09-T06** SLA engine: due/overdue computation task, reminders, escalation, pay/invoice hold flags.
- [ ] **E09-T07** Unconfirmed lessons queue and auto-complete task.
- [ ] **E09-T08** Frontend: complete-lesson modal, register UI, cancel flow with policy preview, report editor, report review queue.
- [ ] **E09-T09** (Phase 2) Client feedback micro-surveys.
