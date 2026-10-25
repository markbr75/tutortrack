# E33 — Workflow Designer

- **Status:** Planned (2026-10-25)
- **Depends on:** E14 Automation (the engine it grows from), E32 Temporal, E10 Billing, E13
  Communications, E09 Delivery, E17 Leads, E18 Recruitment, E24 Growth
- **ADR:** [0047](../adr/0047-workflow-designer-on-the-automation-engine.md)

## 1. Summary

Organisations design their own workflows to decide when things happen: when invoices are
made, approved and sent, when payment reminders and late fees go out, when lesson reminders,
report chasers and feedback requests are sent, how enquiries are followed up and when expiry
reminders fire. TutorTrack ships these as **built-in workflows** that every organisation can
open, edit, test and reset, and staff can build **custom workflows** for anything else.

The existing Automations area (E14) becomes **Workflows**: one place, one designer, one
engine. The engine stays on Temporal (decided 2026-10-25): every workflow is versioned data
interpreted by the E14 run workflow, which this epic extends with new step types.

Owner decisions (2026-10-25):

- Engine: keep Temporal for everything.
- Built-in workflows in the first release: invoicing and payment chasing, lesson
  communications, sales and onboarding, expiry reminders.
- Automations merges into Workflows; existing automations and recipes move across.
- Access: every plan (Solo included) can edit and test the built-in workflows; new custom
  workflows follow today's plan limits (Team 10, Agency 50, Enterprise unlimited).

## 2. Functional requirements

### FR-33-1 One workflow model
A workflow is a **trigger**, optional **entry conditions** and a list of **steps**, stored
as JSON and checked against the registry when saved (ADR 0014). Saving a change writes a new
version; runs keep the version they started with.

Triggers:
- **Event:** a domain event (the E14 list plus the new ones in FR-33-4).
- **Schedule:** "every month on day N at HH:MM", "every week on DAY at HH:MM", "every
  term start", in each branch's time zone (one Temporal Schedule per workflow and branch).
- **Relative date:** N minutes, hours or days before or after a date on a record (a lesson's
  start, an invoice's due date, a package's expiry, a check's expiry).
- **Manual:** started from a record or the workflow page.

Step types (existing ✓, new ★):
- ✓ **Action**: one of the registered actions (FR-33-4).
- ✓ **Wait for a duration**.
- ★ **Wait until**: a date on the record ± an offset, a time of day, the next business day
  (organisation business hours, `general.business_hours`), or outside quiet hours.
- ✓ **If / else** on conditions, evaluated against the record when reached.
- ★ **Wait for something**: an event about the record (for example "invoice paid",
  "report submitted") with a time limit; continues on the "happened" or "timed out" path.
- ★ **Approval**: asks people with a permission (or a named role) to approve, through a
  task and a notification; continues on "approved", "rejected" or "timed out".
- ★ **Repeat**: repeats its inner steps until a condition is true or N times (at most 12).
- ★ **Stop**: ends the run (optionally "and stop other runs of this workflow for this
  record").

### FR-33-2 Built-in workflows
Each built-in workflow is a definition shipped in code with a stable key, installed for
every organisation (and for new organisations at sign-up). In the designer it is marked
**Built-in**: it can be edited, switched off where that is safe, tested, and **Reset to
default**; it can't be deleted. When TutorTrack improves a default, organisations that never
edited it get the new version; edited ones are told and can compare and reset.

When this epic replaces a hard-wired process, each organisation's current settings become
the first version of its built-in workflow, so behaviour doesn't change on the day it ships.
The old settings stay readable for one release, then are removed.

| Group | Built-in workflow | Replaces today |
|---|---|---|
| Invoicing and payment chasing | Invoicing cycle (schedule → open run → review window or approval → issue → email) | `ScheduledInvoiceRunWorkflow`, `billing.invoice_schedule`, `invoice_day`, `review_days`, `auto_issue`, `auto_send` |
| | Payment chasing (reminders before and after due → late fee → collections) | `InvoiceDunningWorkflow`, `billing.reminder_offsets`, `reminders_enabled`, `collections_after_days`, the late-fee rule's timing |
| | Payment request reminders | `PaymentRequestWorkflow` (3 and 7 days) |
| | Monthly statements | statements Temporal Schedule, `billing.statement_schedule`, `statement_day` |
| Lesson communications | Lesson reminders | Celery `send_lesson_reminders` and the reminder offsets on the notification setting |
| | Lesson report chasing and escalation | `LessonReportSlaWorkflow`, `delivery.report_due_hours`, `report_reminder_hours`, `report_escalate_hours` |
| | Lesson feedback request | `LessonFeedbackWorkflow`, `delivery.feedback_delay_hours`, `feedback_expiry_days` |
| | Unconfirmed lesson chaser | `UnconfirmedLessonWorkflow`, `delivery.unconfirmed_after_hours` |
| Sales and onboarding | Enquiry follow-up | `EnquiryFollowUpWorkflow` |
| | Trial lesson follow-up | (new) |
| | Welcome a new family | (new; today a recipe) |
| | Review request | `ReviewRequestWorkflow`, `growth.review_after_lessons`, `review_after_trial` |
| Expiry reminders | Package expiry | `PackageExpiryWorkflow` reminder, `billing.package_expiry_reminder_days` |
| | Compliance expiry | `ComplianceRecordWorkflow` reminders, `compliance.reminder_days` |

Stay in code (protected, not designable): invoice runs' internal steps (collect, draft,
number, lock), pay runs and payouts, recurring fee charging, package expiry write-off,
GDPR deadlines, imports, calendar sync, booking holds, offers and cover cascades, background
checks, organisation closure, broadcasts and platform processes. They have legal or
financial rules that a workflow must not be able to skip. Designed workflows reach them only
through actions ("Start an invoice run", "Issue the run") and events ("Invoice run drafted").

### FR-33-3 The designer
- **Workflows** replaces **Automations** in the menu (`/workflows`; `/automations` redirects).
  Tabs: **Built-in**, **Custom**, **Templates** (the recipe library) and **Runs**.
- **Flow view:** the trigger, then the steps as a vertical flow; branches and waits show
  their paths side by side from 1024px and stacked on phones. Each step reads as a plain
  sentence ("Wait until 3 days before the due date, at 09:00"). Add a step with **+**
  between steps; move steps with Move up and Move down buttons as well as dragging, so it
  works by keyboard. Selecting a step opens its settings beside the flow (below on phones).
- **Validation as you go:** a step with a problem shows why in words; publishing is blocked
  until every step is valid.
- **Draft and publish:** edits are a draft until **Publish**; **Discard draft** goes back.
  **Versions** lists every published version with who and when, and can restore one.
- **Test:** choose a real record (or a sample) and run the workflow as a dry run. Every
  step says what it would do, and waits are skipped and labelled. Nothing is sent, charged
  or changed.
- **Coming up:** for schedule and relative-date workflows, the next 5 times it will run
  and, where possible, how many records each would pick ("1 Nov 06:00: 38 families").
- **Runs:** each run's timeline (steps done, waiting, next wake-up), with **Cancel run**,
  **Retry from this step** and, for a workflow, **Pause** and **Resume**. The organisation
  kill switch (E14) stays.
- **Message steps** choose a message template and channel; **Edit message** opens the
  template with its merge fields, and a preview shows a sample.

### FR-33-4 New triggers, actions and record types
- Events: `invoice_run.drafted`, `invoice_run.issued`, `invoice.due_soon` (relative date),
  `payment_request.created`, `lesson.reminder_due` (relative date), `lesson_report.due`,
  `lesson.unconfirmed`, `package.expiring` (relative date), `trial_lesson.no_show`,
  `client.first_lesson_completed`, `statement.due` (schedule).
- Record types: invoice run, payment request, package, statement (period).
- Actions:
  - Billing: **Start an invoice run** (period: last week, last month, this term, or the
    schedule's period; branch), **Issue the invoice run**, **Email the invoice**, **Send a
    statement**, **Collect payment now** (saved card or mandate), **Apply a late fee**
    (✓), **Request a payment** (✓), **Open a collections case**, **Send payment request
    reminder**.
  - Lessons: **Send lesson reminder** (respects each contact's reminder preference), **Mark
    report overdue and notify**, **Escalate to the tutor's manager**, **Ask for lesson
    feedback**.
  - Sales: **Move enquiry stage** (✓), **Assign to a person**, **Ask for a review**.
  - General: send a message (✓), create a task (✓), change a field (✓), tags (✓), call a
    webhook (✓), **Start another workflow** (depth limit applies).
- Each action declares the permission it needs (ADR 0014 §6). Money-moving actions
  (issue, collect, late fee, collections) also record the workflow and version on the audit
  entry.

### FR-33-5 Safety
Everything in ADR 0014 stays: registry-checked definitions, immutable versions,
idempotent steps keyed by run and step path, rate limits, loop detection, the kill switch.
Added:
- Money-moving steps can't run before the invariants allow it (no emailing a draft, no late
  fee on a paid invoice). The owning service still refuses, and the step records "skipped:
  invoice already paid".
- A built-in workflow that is switched off falls back to the manual way (for example,
  invoicing becomes manual) and Home says so.
- Publishing a change to a workflow with waiting runs asks whether those runs continue on
  their version (default) or move to the new one at their next step (only when the new
  version still has that step).
- Messages respect quiet hours and contact preferences unless the step is marked urgent
  (owner only).

### FR-33-6 Migration
- Every existing automation becomes a custom workflow with the same versions and runs.
  Recipes become **Templates**.
- For every organisation: install the built-in workflows from its current settings, cancel
  the old per-record Temporal workflows that the new ones replace (there are none in
  production yet), and remove the replaced Temporal Schedules and the lesson-reminder beat
  task.

## 3. Data model
Grows the E14 tables rather than adding new ones:
- `Automation` gains `kind` (`custom` | `builtin`), `builtin_key`, `builtin_version` (the
  default it came from), `edited` (bool), `draft` (JSON: trigger, conditions, steps), and
  `paused`.
- `AutomationVersion` unchanged (it already stores trigger, conditions and steps).
- `AutomationRun` gains `waiting_for` (event type, approval id or wake time, shown on the
  timeline) and `next_wake_at`, both for display only. Temporal holds the real timers;
  nothing sweeps these columns (CLAUDE.md 4a).
- `AutomationRunStep` gains `path` labels for branch arms and `outcome` ("timed out",
  "approved", "skipped: …").
- New `WorkflowApproval` (tenant): run, step key, permission or role, status, decided_by,
  decided_at, reason, and the task it created.
- Code: built-in definitions in `<app>/workflows_builtin.py`, registered with
  `@builtin_workflow(key, group)` and discovered like recipes.

The models keep their `automations` names in code; only the product says "Workflows".

## 4. API
- `/api/v1/workflows` (alias of `/automations`, which stays for one release): list, create,
  retrieve, update draft, `publish`, `discard-draft`, `pause`, `resume`, `reset-to-default`,
  `versions`, `test` (dry run), `upcoming`.
- `/api/v1/workflow-runs`: list and detail (timeline), `cancel`, `retry`.
- `/api/v1/workflow-approvals`: list mine, `approve`, `reject`.
- `/api/v1/workflow-schema`: triggers, record types, fields, actions, step types (the
  designer is driven by it).
- Webhooks: `workflow.run_failed`, `workflow.approval_requested`.

## 5. Permissions
- `automation.view`: see workflows and runs (unchanged codename).
- `automation.manage`: edit, test, publish and pause custom workflows (owner, admin, branch
  manager).
- `automation.builtin.manage` (new): edit, publish, pause and reset built-in workflows
  (owner, admin, branch manager, finance). As in ADR 0014 §6, saving also needs the
  permission of every action in the workflow, so finance can change the billing built-ins
  but not, say, the enquiry follow-up.
- Approvals use the permission named on the step.
- Plans: built-in workflows are on every plan; custom workflows keep the E14 limits.

## 6. Delivery plan
Each ticket is one pull request, merged when CI is green.

- [ ] **T01 — Engine: new step types.** `wait until`, `wait for something` (bridge signals
  the run when the awaited event arrives), approvals (`WorkflowApproval`, a task and a
  notification, then a signal on decision), `repeat`, `stop`. Interpreter changes are
  versioned with `workflow.patched`, with replay histories for each new step type
  (02-architecture §9). Hypothesis tests for "wait until" across time zones and DST.
- [ ] **T02 — Draft, publish, versions and pause.** Draft column, publish and discard,
  restore a version, pause and resume (Temporal Schedules paused too), and the
  move-waiting-runs option.
- [ ] **T03 — Catalogue.** The new triggers, record types and actions in FR-33-4, with
  permissions, idempotency keys and tests per action. `/workflow-schema`.
- [ ] **T04 — Built-in workflow framework.** `@builtin_workflow`, install for new and
  existing organisations, reset to default, default upgrades, `edited` tracking, switching
  off safely, and plan rules (built-ins on every plan).
- [ ] **T05 — Built-ins: invoicing and payment chasing.** Invoicing cycle, payment
  chasing, payment request reminders, statements. Each organisation's settings convert to
  its first version. Retire the replaced schedules, workflows and settings. Billing guide
  updates.
- [ ] **T06 — Built-ins: lesson communications.** Lesson reminders (retire the beat task),
  report chasing, feedback request, unconfirmed lesson chaser.
- [ ] **T07 — Built-ins: sales and onboarding, and expiry reminders.** Enquiry follow-up,
  trial follow-up, welcome a new family, review request, package expiry, compliance expiry.
- [ ] **T08 — Designer UI.** Workflows area (Built-in, Custom, Templates, Runs), flow view
  with branch lanes, step settings panel, plain-English summaries, keyboard moves,
  validation, draft and publish, versions. Replaces the Automations pages. WCAG 2.2 AA.
- [ ] **T09 — Test, coming up and runs.** Dry run against a real or sample record,
  upcoming runs with counts, run timeline with cancel and retry, approvals inbox.
- [ ] **T10 — Migration and docs.** Automations → custom workflows, recipes → templates,
  `/automations` redirect, guides (user, admin, API), help articles, What's new, roadmap
  and README.

Order: T01 → T02 → T03 → T04 → (T05, T06, T07) → T08 → T09 → T10. T08 can start after T02
against the API.

## Temporal workflows (E32)
- `AutomationRunWorkflow` (E14) interprets every workflow; the new step types are timers,
  `wait_condition` on signals from the bridge, and approval signals. Histories stay small:
  every step is an activity or a timer, and repeats continue-as-new after 50 iterations.
- `AutomationScheduleWorkflow` (E14) runs schedule and relative-date triggers, one Temporal
  Schedule per workflow and branch.
- The replaced per-process workflows (FR-33-2 table) are removed after T05 to T07.

## Implementation notes
(Fill in as built: deviations from this plan, and why.)
