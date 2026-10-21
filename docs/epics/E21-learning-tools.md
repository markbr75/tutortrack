# E21 — Learning Tools: Progress, Homework, Resources & Assessments

| | |
|---|---|
| **Phase** | Scale (Phase 3); homework and resources basics can ship in Phase 2 |
| **Depends on** | E05, E08, E09, E15, E16 |
| **Parity** | TutorBird LMS-lite (files, homework, news, lending library). **Beyond:** goals, curriculum mapping, assessments, progress reports — a reported gap in TutorBird |

## 1. Summary
Lightweight learning-management features that make tutoring outcomes visible: a resource library, homework assignment and submission, curriculum/topic tracking, goals, assessments/mock-exam scores, progress reports for parents, and a lending library.

## 2. Functional requirements

### FR-21-1 Resource library
- Org library + tutor personal libraries: files (PDF, images, audio, video), links (YouTube, Google Docs), folders, tags by subject/level/topic, visibility (staff, tutors, shared to specific students/classes).
- Share a resource to a student, job, lesson or class; students see it in the portal; track viewed/downloaded.
- Storage quotas per plan (E04).

### FR-21-2 Homework
- Assign from a lesson/report or standalone: title, instructions, attachments/resources, due date, student(s), expected time, submission type (file upload, text, link, none/mark done).
- Student/parent submits via portal; tutor reviews: mark complete, grade (scale per org: %, letter, 1–9, custom), feedback; resubmission.
- Reminders before due and when overdue (E13); homework completion stats.

### FR-21-3 Curriculum and topics
- Curriculum trees (Subject/Level → Units → Topics), seeded for major specs (e.g. GCSE Maths, KS2 English, SAT Math) and editable/importable (CSV).
- Lesson report "topics covered" picker (E09) links lessons to topics; topic mastery rating per student (not started / learning / secure / mastered).
- Coverage view per student: heatmap of topics covered and mastery.

### FR-21-4 Goals
- Student goals (target grade, exam date, custom SMART goals) with milestones and progress %; tutor updates; visible to parents; `goal.achieved` event.

### FR-21-5 Assessments
- Record assessment results: name, type (diagnostic, mock exam, quiz, school report), date, score/max, grade, notes, attachment.
- Simple built-in quizzes (Phase 3b): multiple choice/short answer, auto-marking, assigned like homework; also used for tutor subject tests (E18 FR-18-3).
- Charts of score trend over time.

### FR-21-6 Progress reports
- Periodic progress report (termly/monthly) generated from attendance, report highlights, topics, goals, assessments, homework completion; tutor adds summary comments (AI draft via E31); approval → shared to parents (portal + PDF).

### FR-21-7 Lending library
- Items (books, instruments, devices) with inventory, lend to student with due date, return tracking, overdue reminders, replacement charge (E10 ad hoc).

### FR-21-8 Whiteboard/online classroom resources
- Attach resources to online lessons and auto-share with the video integration (E22) where supported (e.g. Lessonspace space resources).

## 3. Data model
`Resource`, `ResourceFolder`, `ResourceShare`, `Homework`, `HomeworkAssignment(student)`, `HomeworkSubmission`, `GradeScale`, `Curriculum`, `CurriculumNode`, `LessonTopic`, `TopicMastery(student, node, level, updated_by)`, `Goal`, `GoalMilestone`, `Assessment`, `AssessmentResult`, `Quiz`, `QuizQuestion`, `QuizAttempt`, `ProgressReport`, `LibraryItem`, `Loan`.

## 4. Events
`resource.shared`, `homework.assigned/submitted/graded/overdue`, `goal.created/achieved`, `assessment.recorded`, `progress_report.shared`, `loan.overdue`.

## 5. Delivery plan
- [x] **E21-T01** Resource library with sharing and portal display.
- [x] **E21-T02** Homework assign/submit/review with reminders.
- [x] **E21-T03** Curriculum trees (seed + CSV import), topic tagging in lesson reports, mastery.
- [x] **E21-T04** Goals and milestones.
- [x] **E21-T05** Assessments and trend charts.
- [x] **E21-T06** Progress report generator and sharing.
- [x] **E21-T07** Lending library.
- [x] **E21-T08** (Phase 3b) Built-in quizzes.

## Implementation notes (as built 2026-10-14)
- **App:** `learning` (every table has RLS). See ADR 0025.
  - Models: `ResourceFolder`, `Resource`, `ResourceShare`, `ResourceActivity` (new: views and downloads per viewer), `GradeScale`, `Homework`, `HomeworkAssignment`, `HomeworkSubmission`, `Curriculum`, `CurriculumNode` (units and topics), `LessonTopic`, `TopicMastery`, `Goal`, `GoalMilestone`, `Assessment`, `AssessmentResult`, `ProgressReport`, `LibraryItem`, `Loan`, `Quiz`, `QuizQuestion` and `QuizAttempt`.
  - Records about one learner (assignments, mastery, goals, results, progress reports, loans, library items) are branch-scoped through the student's branch. Tutors work with the `own` scope: students on their jobs, the lessons they teach and the classes they teach (`learning.models.tutor_students`).
  - Permissions: `learning.resource.*`, `learning.homework.*`, `learning.curriculum.*`, `learning.mastery.edit`, `learning.goal.*`, `learning.assessment.*`, `learning.progress.*`, `learning.library.*`, `learning.quiz.*`, plus `portal.client.learning` and `portal.student.learning`. Coordinators get `learning.*`. Finance gets library view and charge. Tutors keep `learning.*:own`, but their role now denies curriculum editing, progress approval, the library and charging.
  - Settings (`learning.*`): portal on/off, homework reminder hours, homework from reports and its due days, late submissions, auto-achieving goals, progress approval and sharing on approval, loan period, loan reminder days, overdue notice interval and count.
- **Resources (T01):** an organisation library (owner empty) and tutors' personal libraries (a tutor's new resources are theirs and private by default). Visibility is staff only, staff and tutors, or the owner only.
  - Files use the existing direct-to-storage uploads, so the E04 `storage_gb` quota is enforced there. `GET /learning/storage` shows usage against the plan.
  - Links are typed (YouTube, Google Docs, other). Only http(s) addresses are accepted.
  - Resources can be tagged by subject, level, curriculum topics and free tags, and filed in folders.
  - Sharing targets a student, a job (its students), a lesson (its attendees) or a class (E20 attending enrolments). Tutors may only share with their own students. Families see shares in the portal and get a `resource_shared` message. Opening records a view or download.
  - File access for families and tutors uses `core.storage` access rules on resources, homework attachments and submissions.
- **Homework (T02):** set for picked students, a class roster, a job's students or a lesson's attendees. Each student gets a `HomeworkAssignment` and `homework.assigned`.
  - Submission types: text, file, link, mark as done, and quiz (T08). Late work is accepted and flagged unless `learning.late_submissions` is off.
  - Review: complete with a grade on the homework's scale and feedback (`homework.graded`), or return for resubmission with a new due date (`homework.returned`, a new reminder round). Staff can excuse or cancel.
  - Grade scales: percentage, letters, 9–1 and a custom list are created on first use. Percent grades also store `score_percent`.
  - Completion stats per student or overall (due, on time, late, overdue, rate).
  - "Assign from a lesson/report": the API takes a lesson or report. With `learning.homework_from_reports` (default on), a submitted E09 report's `homework` answer is set for the lesson's students once per report. It is a "mark as done" task, due N days later at 18:00 org time.
  - Reminders and overdue: `HomeworkReminderWorkflow` (TW1, below).
- **Curricula (T03):** built-in outlines for GCSE Maths, KS2 English and SAT Math (units and topics with codes) install as editable copies, once each.
  - CSV import (`unit,topic,code`) is additive: existing units match by name and topics by code or name, so re-imports add only what's new.
  - Units sit at the top and topics in a unit. A node used by lessons can't be deleted.
  - Topic tagging (E09): on `lesson_report.submitted`, the report's `topics` answers are matched to curriculum topics by id, code or name (the lesson's subject first). Free text that matches nothing is ignored. Tagging can also be done through `POST /learning/lesson-topics`.
  - The admin report form suggests topic names (datalist), and the tutor app adds a topic picker. Answers stay human-readable in the shared report.
  - Tagging moves each lesson student's mastery to at least *learning* and counts coverage. Tutors and staff set mastery (not started, learning, secure, mastered); `topic_mastery.changed` is published.
  - Coverage view (`/learning/students/{id}/coverage`, also in the portal): a heatmap of units and topics with level and lessons covered.
- **Goals (T04):** target grade, exam and SMART goals with milestones. Progress is the share of milestones done; without milestones the tutor sets it. When all milestones are done the goal is achieved (setting), or staff mark it achieved. Events: `goal.created`, `goal.achieved` (the family is told). Families see goals marked visible.
- **Assessments (T05):** assessments (diagnostic, mock exam, quiz, school report, other) with results: score/max (percentage half-up to 2 places, Hypothesis-tested), grade validated against the assessment's scale, notes, attachment and family visibility. `assessment.recorded` is published on the first record, not on corrections.
  - Score trend: `/learning/students/{id}/trend` (optionally by subject) and the portal results. Shown as an accessible SVG line chart (one 0–100% axis, focusable markers with tooltips, table view) in `packages/ui`.
- **Progress reports (T06):** generated per student and period, or in bulk for everyone with lessons in the period (tutors: their students).
  - The stored snapshot holds attendance (outcomes in the period, without tutor and admin cancellations), highlights from written lesson reports (client-visible text only), topics covered with mastery, goals, assessments in the period, and homework stats. Drafts can be regenerated.
  - Flow: draft → submitted → approved → shared. Submitting needs summary comments. Approval needs `learning.progress.approve`. Shared reports go to the portal and are emailed with a WeasyPrint PDF (`progress_report_shared`). With approval off, submitting approves and shares straight away.
  - AI draft (E31) seam: `learning.progress.register_drafter`. Until E31 registers one, `POST …/draft-summary` returns 403 `feature-disabled` and `ai_draft_available` is false.
  - Deviation: approval is a plain status change (no timers), and periodic generation is staff-triggered. There is no per-organisation Temporal Schedule yet.
- **Lending library (T07):** items with quantity, location and replacement cost (Money). Lending checks availability under a row lock and defaults to `learning.loan_days`. Loans can be returned, extended or marked lost.
  - Lost with `charge` (needs `learning.library.charge`) bills the family through `billing.services.charge_fee` (ad hoc kind, source key `library-loan:{id}`), so a retried request never bills twice. The endpoint also honours `Idempotency-Key`.
  - Reminders, overdue and notices: `LoanReminderWorkflow`.
- **Quizzes (T08, Phase 3b, built):** single-choice, multiple-choice (exact match) and short-answer questions. Short answers are compared ignoring case, accents, spacing and end punctuation.
  - A quiz is set as homework (`submission_type=quiz`). The portal shows questions without answers. Handing in auto-marks the quiz (`quiz.submitted`), completes the assignment with the percentage grade, and records a *quiz* assessment result, so it appears in the trend.
  - A quiz's questions can't change once it has been taken.
  - E18 tutor subject tests: `Quiz.purpose=tutor_test` and `services.take_quiz(student=None, user=…)` are the seam. The E18 UI is not built.
- **E21-TW1 (Temporal):**
  - `HomeworkReminderWorkflow` (`homework:{org}:{assignment}:{round}`): started by `homework.assigned` and `homework.returned`. It reminds before the due time (unless the homework was set inside the reminder window), then at the due time marks the assignment overdue (`homework.overdue`) and tells the family. A hand-in signals `changed` and ends it. Due-date changes, cancelling and excusing signal it from the services.
  - `LoanReminderWorkflow` (`loan:{org}:{loan}`): started by `loan.created`. It reminds before the due date, marks the loan overdue the day after (`loan.overdue`), then sends up to N notices every M days. Return and lost signal it; extending signals from the service.
  - Activities call idempotent services; overdue events use the activity dedupe key. Tests cover timers, signals, a retry and replay of recorded histories.
- **Messages (E13):** `homework_assigned`, `homework_reminder`, `homework_overdue`, `homework_graded` (family and student login), `homework_submitted` (tutor), `resource_shared`, `progress_report_shared` (PDF attached), `goal_achieved`, `loan_due` and `loan_overdue`. All are in the `reports` category.
- **UI:**
  - Admin `/learning` has tabs for homework (review queue, set homework), resources (storage, share), curricula (built-ins, tree, CSV import), assessments, progress reports (generate, edit, approve, share, PDF), library and quizzes (question builder).
  - `/learning/students/{id}` shows the coverage heatmap with mastery setting, the score trend, goals with milestones and homework completion.
  - Family portal `/portal/learning` has tabs for homework, resources, goals, results, progress reports and loans, plus a homework page for handing in (text, link, files, quiz, done). The `learning` feature is in `/portal/me`.
  - Tutor app: `/portal/tutor/homework` (review queue, set homework), `/portal/tutor/homework/{id}` (review) and `/portal/tutor/resources` (my library, share with my students).
- **Not built:** FR-21-8 (sending resources to E22 video rooms such as Lessonspace). Lesson shares publish `resource.shared` with `target=lesson` for E22 to pick up when providers support it.

## Gap backlog (as built 2026-10-21)
Gap batch G5a.

- **Tutor subject tests (E18 FR-18-3).** The quiz builder sets the purpose (homework and practice, or tutor subject test), a catalogue subject and the pass mark, and the quiz list shows the purpose. Tutor subject tests are taken in the tutor app (`/portal/tutor/tests`) through `take_quiz(student=None, user=…)`; see the E18 notes. New selectors `tutor_tests()` and `tutor_test_attempts()`.

Gap batch G5c ([ADR 0044](../adr/0044-students-needs-and-capacity-suggestions.md)).

- **Progress reports on a schedule (FR-21-6).** The setting `learning.progress_schedule` (`none` by default, `monthly`, `termly`) keeps a per-organisation **Temporal Schedule** in step (handler on `organisation.settings_updated`; `learning.progress_schedule.sync_schedule`). It starts `ProgressReportRunWorkflow` (process `progress-reports`, queue `default`): monthly at 06:00 on the 1st (organisation time) for last month; termly at 06:00 every day, drafting for E20 terms that ended in the last 7 days, limited to students in the term's branch. This removes the "periodic generation is staff-triggered" deviation.
  - Activities: plan (the periods due and the students with lessons in them who have no report for the period), draft in batches of 25, then announce. Only missing reports are drafted; existing reports (drafts included) are never refreshed by the schedule, so the termly look-back and reruns are idempotent and never overwrite a tutor's comments.
  - Each draft's author is the student's main tutor in the period (most lessons; cancelled lessons don't count), so the tutor's own scope covers it.
  - When a run drafts something for a period: each author gets `progress_reports_drafted` (email and in-app, with the count), staff with `learning.progress.approve` get `staff_progress_reports_drafted`, and `progress_report.batch_drafted` (counts only; the subject is the organisation) is published once per period (dedupe key on the period). Approval and sharing are unchanged.
  - Admin **Learning → Progress reports** has a "Draft reports automatically" section for staff who approve reports and can see settings.
  - Tests cover planning (monthly, termly, look-back, off), drafting and authorship, the announce dedupe, the workflow and the schedule sync; the history `ProgressReportRunWorkflow-drafted.json` is replayed.
  - Deviation: termly runs need E20 terms; without terms, choose monthly or keep generating by hand.
- **Resources in the video room (FR-21-8), checked against E22-T10.** The E22 classroom listed the lesson's shares by title only, linking to the library. G5c makes them usable in the room:
  - `GET /lessons/{id}/classroom` resources now carry `kind`, `media_type`, the share message and when it was shared (newest first; archived resources left out).
  - `POST /lessons/{id}/classroom/resources/{resource_id}/open` opens a resource shared with the lesson, its job or (for a family) their students, for anyone in the classroom: a short-lived inline link for files, the link itself otherwise. The view is recorded (E21 resource activity). A tutor can so open a staff-library resource that staff shared with the lesson.
  - The tutor shares one of their resources into the room from the classroom page (the existing `POST /learning/resources/{id}/share` with `lessons`). The classroom polls every 15 seconds while the room is open, so the resource appears for everyone within seconds. The family's `resource_shared` notice links to the classroom when the share is for an online lesson that hasn't ended.
  - Fix: the tutor app sent every path outside `/tutor` back to Today, so the tutor's "Open the classroom" link (E22-T10) never reached the classroom. The tutor shell now lets `/classroom/<lesson>` through.
  - Deviation: nothing is uploaded into the provider's own room. Lessonspace's launch API has no documented resource field, Zoom, Teams and Meet have no in-meeting file API we can use, and provider code lives in `integrations` (outside this batch). The classroom page, which embeds the built-in and Lessonspace rooms, shows the resources beside the room instead.
