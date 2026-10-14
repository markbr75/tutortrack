# ADR 0025: Learning tools in one app on existing seams; homework and loan timers on Temporal; progress reports as stored snapshots

- **Status:** Accepted
- **Date:** 2026-10-14
- **Epic:** E21. Builds on ADR 0002 (Temporal), ADR 0007 (charges), ADR 0024 (classes).

## Context
E21 adds resources, homework, curricula and mastery, goals, assessments, progress reports, a lending library and quizzes. Each of these touches work that other epics already own:
- lesson reports (E09);
- billing (E10);
- messages (E13);
- the portals (E15, E16);
- classes (E20);
- plan storage (E04);
- AI drafting (E31, not built yet).

The rules that had to hold:
- Apps write other apps' data only through their services.
- Timers live in Temporal, never in `next_*_at` columns with a sweeper.
- Tutors see only their own students.
- What a family receives must not change after approval.

## Decision
1. **One `learning` app.**
   - Records about one learner are branch-scoped through the student's branch.
   - Tutors' `own` scope is one shared query (`tutor_students`): students on their jobs, the lessons they teach and the classes they teach. Every model's `own_scope_q` builds on it.
   - Organisation-wide models (curricula, quizzes, resources) treat a branch grant as organisation-wide.
2. **Other apps are used only through their seams.** No other app writes learning data, and learning writes no other app's data.
   - **Files (E04):** core direct-to-storage uploads, so the plan's storage quota is enforced in one place. Learning registers `core.storage` access rules for resources, homework attachments and submissions.
   - **Lesson reports (E09):** learning only reads them. It reads them in a `lesson_report.submitted` handler:
     - `topics` answers are matched to curriculum topics by id, code or name;
     - the `homework` answer becomes homework, once per report.

     The report form is unchanged. The UI only suggests topic names, so shared reports stay readable.
   - **Replacement charges (E10):** `billing.services.charge_fee` with an ad hoc kind and the source key `library-loan:{id}`. This makes them idempotent without extra state.
   - **Messages (E13):** learning registers its own notification types.
   - **Classes (E20):** homework and shares targeting a class read its attending enrolments.
3. **Timers are two workflows, and they re-read state on a single `changed` signal.**
   - `HomeworkReminderWorkflow` (one per assignment round) and `LoanReminderWorkflow` (one per loan) sleep until the next moment that matters: the reminder, the due time, the next notice.
   - When a signal arrives, they ask an activity for the current state before they do anything.
   - So a hand-in, a new due date, a cancellation, a return or an extension needs no workflow-specific code, only a signal.
   - A returned (resubmit) assignment starts a new round with a new workflow id. Completed workflow ids are never reused.
   - Activities call idempotent services: reminders are sent once, and overdue events use the activity dedupe key. The activities trust the workflow's timer, not the wall clock, so time-skipping tests and replays are deterministic.
4. **A progress report stores a snapshot.**
   - Generation copies attendance, client-visible report highlights, topics and mastery, goals, assessments and homework stats into the report.
   - Drafts can be regenerated. Once a report is approved and shared, the portal page and the PDF render the stored snapshot, so later edits elsewhere don't change what the family received.
   - Approval is a plain status change: there is no waiting step, so no workflow is needed.
   - E31 plugs in through `progress.register_drafter`. Until then the endpoint returns `feature-disabled`.
5. **Quizzes reuse homework and assessments.**
   - A quiz is a homework submission type. Marking is a pure function (Hypothesis-tested).
   - A homework quiz also records a *quiz* assessment result, so it appears in the score trend with no separate chart.
   - E18 subject tests can use the same models (`purpose=tutor_test`, an attempt without a student).

## Consequences
- **Good:**
  - No other app's data model changed. The shared-file changes are role grants, the portal `learning` feature flag, router and navigation entries, and a topic suggestion list in the report forms.
  - Reminders and overdue handling can be cancelled and are visible as process timelines.
  - Billing for lost items is safe to retry.
- **Trade-offs:**
  - Topic tagging from free text depends on names or codes matching.
  - Periodic report generation is staff-triggered. A per-organisation Temporal Schedule can be added later without changing the model.
  - Sending resources to video rooms (FR-21-8) waits for E22 provider support; lesson shares already publish `resource.shared`.
