# ADR 0006: Delivery decides lesson outcomes, scheduling records them

- **Status:** Accepted
- **Date:** 2026-10-09
- **Epic:** E09

## Context
Completing or cancelling a lesson now involves cancellation policies, attendance outcomes,
a prepaid-balance guard (E10), report SLAs and makeup credits. The lesson, its attendees
and its tutors belong to scheduling (E08). The rule is that apps never write each other's
models. E10 and E12 also need one event per completion or cancellation that says exactly
who is charged and paid, and by how much.

FR-09-8 asks for a process when a lesson's end passes while it is still planned. Starting
one workflow per lesson at scheduling time means months of sleeping workflows, which must
also follow every reschedule. A sweeper with `next_*_at` columns is forbidden (E32).

## Decision
1. **Scheduling owns state.** It stores attendance on `LessonAttendee` (outcome, minutes
   late, charge %) and `LessonTutor.pay_percent`, along with actual times and who
   cancelled. `scheduling.services.complete_lesson` / `cancel_lesson` / `record_attendance`
   take percentages as inputs. They publish `lesson.completed`, `lesson.cancelled` and
   `attendance.recorded`, with one row per attendee and per tutor (outcome, percentage,
   chargeable/payable).
2. **Delivery owns decisions.** `delivery.policies` resolves the most specific policy
   (client → job → service → branch → organisation) and maps who cancelled, the notice
   and the outcome to percentages. `delivery.services` calls the scheduling services with
   them and keeps a `CancellationRecord` with a snapshot of the policy. The lesson API's
   `complete`/`cancel`/`attendance` actions call delivery services.
3. **Billing plugs in through a guard.** Billing (E10) registers its balance check with
   `delivery.balance.set_guard`, as scheduling registered the jobs `LessonsProvider`.
4. **Unconfirmed lessons.** A tenant-sharded beat task runs every 15 minutes. It starts an
   `UnconfirmedLessonWorkflow` for lessons that ended in the last 6 hours and are still
   planned. Workflow ids make starts idempotent, and lessons that already have a
   `WorkflowLink` are skipped without calling Temporal. The wait, nudge and auto-complete
   all live in the workflow. Completion or cancellation signals it to finish early.
5. **Report SLA.** `lesson_report.requested` starts `LessonReportSlaWorkflow`, and
   `lesson_report.submitted` signals it. Both workflows run on the `default` task queue.

## Consequences
- E10/E12 charge and pay from the event rows (`charge_percent`/`pay_percent` × the lesson
  snapshot) and never re-evaluate policies.
- A policy change never alters past outcomes: records keep the rules they were decided by,
  and policies are versioned rather than edited.
- Each workflow test must let every workflow it starts finish. Otherwise its activities
  keep retrying against a flushed database and stall time-skipping for later tests.
