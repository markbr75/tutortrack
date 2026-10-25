# E33 — Workflow Designer

- **Status:** In progress (T01 to T03 done 2026-10-25)
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
- **Keep it simple enough for a tutoring business** (2026-10-25): a workflow is a
  *sequence* on one timeline, not a flowchart. Steps run top to bottom; a step can split
  into **Yes / No** paths on one plain question, one level deep, and the paths join again
  afterwards. A "Stop when" rule ends the sequence (for example, when the invoice is paid).
  No approval steps, loops or draft/publish screens in the first release.

## 2. Functional requirements

### FR-33-1 One workflow model: a sequence
A workflow is a **sequence**: a start, an optional **Stop when** rule and a list of steps,
stored as JSON and checked against the registry when saved (ADR 0014). Saving writes a new
version silently; runs already under way keep their version, new runs use the new one.

**Starts** (a plain sentence from a short list per area):
- **When something happens:** a domain event ("When an invoice is sent", "When a lesson is
  booked", "When an enquiry arrives"; the E14 list plus FR-33-4).
- **On a schedule:** "Every month on the [1st] at [06:00]", "Every week on [Monday] at
  [06:00]", in each branch's time zone (one Temporal Schedule per workflow and branch).
- **By hand:** from a record or the workflow page.

**Stop when** (optional): an event about the record ends the run ("the invoice is paid",
"the enquiry is won", "the lesson is cancelled"). Up to three.

**Steps.** Each step is a card with:
- **When:** straight away; after N minutes, hours or days; or N days before or after a date
  on the record (the due date, the lesson start, the expiry date), optionally at a time of
  day, the next business day, or outside quiet hours.
- **Only if** (optional): one plain check from the record type's list ("the invoice is
  still unpaid", "the family pays automatically", "this is the student's first lesson").
- **Do:** one or more actions (FR-33-4), done in order.

**Yes / No split.** A step can instead ask one plain question from the same list. Each
answer has its own steps (each with When and Do, but no further split: one level only).
After the split, the steps below it run for both paths. A sequence can have up to 20 steps
and 5 splits.

There are no loops, approval steps or free-form branching in the first release. Approvals
stay where they already are (the invoice run's review window and "approve run").### FR-33-2 Built-in workflows
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

### FR-33-3 The sequence editor
- **Workflows** replaces **Automations** in the menu (`/workflows`; `/automations`
  redirects). Tabs: **Built-in**, **Custom**, **Templates** (the recipe library) and
  **Runs**.
- **One timeline, top to bottom.** The start and **Stop when** sit at the top; each step is
  a card on a vertical line that reads as a sentence ("3 days before the due date, at
  09:00 · Send "Friendly reminder" by email"). A Yes / No split shows its two paths side by
  side from 768px and one under the other on phones, then the line joins again.
- **Editing in place.** Select a card to edit its When, Only if and Do in the card itself;
  **+ Add a step** sits between cards; **Move up**, **Move down** and **Delete** are on
  each card (so it all works by keyboard and on a phone). Every choice is a list or a
  number, never a formula.
- **Messages:** a Do that sends a message picks a message template and channels, and
  **Edit wording** opens it (Settings › Notifications) with a sample.
- **Problems in words:** a card that can't run says why ("Choose which message to send");
  **Save** is blocked until every card is complete.
- **Save and switch on.** Saving applies to new runs; a note says how many runs are
  already under way and that they finish on the old steps. A built-in can be **Reset to
  default**. Old versions are kept for the record but not shown as a screen.
- **Preview for a family** (or a lesson, an enquiry): choose a real record and see the
  timeline with real dates, which path each split would take and what each step would
  send. Nothing is sent or changed. For scheduled sequences, **Coming up** lists the next 5
  dates and how many records each would pick ("1 Nov, 06:00: 38 families").
- **Runs:** a list of runs with where each one is ("waiting until 12 Nov, 09:00"), its
  steps so far, **Cancel** and **Retry**; **Pause** on a workflow; the kill switch (E14)
  stays.### FR-33-4 New triggers, actions and record types
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
- Runs already under way always finish on the version they started with.
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
  default it came from), `edited` (bool), `stop_when` (event list) and `paused`.
- `AutomationVersion` unchanged (it already stores trigger, conditions and steps).
- `AutomationRun` gains `waiting_for` (the wake time or the stop-when events, shown on the
  timeline) and `next_wake_at`, both for display only. Temporal holds the real timers;
  nothing sweeps these columns (CLAUDE.md 4a).
- `AutomationRunStep` gains `path` labels for split arms and `outcome` ("skipped: only if
  not met", "skipped: invoice already paid", "stopped: invoice paid").
- Code: built-in definitions in `<app>/workflows_builtin.py`, registered with
  `@builtin_workflow(key, group)` and discovered like recipes.

The models keep their `automations` names in code; only the product says "Workflows".

## 4. API
- `/api/v1/workflows` (alias of `/automations`, which stays for one release): list, create,
  retrieve, update, `pause`, `resume`, `reset-to-default`, `preview` (dry run for a
  record), `upcoming`.
- `/api/v1/workflow-runs`: list and detail (timeline), `cancel`, `retry`.
- `/api/v1/workflow-schema`: starts, stop-when events, record types, plain questions (the
  "only if" and split list), date fields and actions. The editor is driven by it.
- Webhooks: `workflow.run_failed`.

## 5. Permissions
- `automation.view`: see workflows and runs (unchanged codename).
- `automation.manage`: edit, preview, save and pause custom workflows (owner, admin, branch
  manager).
- `automation.builtin.manage` (new): edit, save, pause and reset built-in workflows
  (owner, admin, branch manager, finance). As in ADR 0014 §6, saving also needs the
  permission of every action in the workflow, so finance can change the billing built-ins
  but not, say, the enquiry follow-up.
- Plans: built-in workflows are on every plan; custom workflows keep the E14 limits.

## 6. Delivery plan
Each ticket is one pull request, merged when CI is green.

- [x] **T01 — Engine: sequences.** "N days before or after a date, at a time" waits,
  business-day and quiet-hours timing, **Stop when** (the bridge signals the run; it ends
  before its next step), Yes / No splits that rejoin, and "only if" per step. Interpreter
  changes are versioned with `workflow.patched`, with replay histories (02-architecture
  §9). Hypothesis tests for date-relative waits across time zones and DST.
- [x] **T02 — Plain questions and the catalogue.** The per-record-type list of plain
  questions (each a named predicate with tests), the new starts, stop-when events, record
  types and actions in FR-33-4 (with permissions and idempotency keys), silent versions,
  pause and resume. `/workflow-schema`.
- [x] **T03 — Built-in workflow framework.** `@builtin_workflow`, install for new and
  existing organisations, reset to default, default upgrades, `edited` tracking, switching
  off safely, and built-ins on every plan.
- [ ] **T04 — Built-ins: invoicing and payment chasing.** Invoicing cycle, payment
  chasing, payment request reminders, statements. Each organisation's settings convert to
  its first version. Retire the replaced schedules, workflows and settings.
- [ ] **T05 — Built-ins: lesson communications.** Lesson reminders (retire the beat task),
  report chasing, feedback request, unconfirmed lesson chaser.
- [ ] **T06 — Built-ins: sales and onboarding, and expiry reminders.** Enquiry follow-up,
  trial follow-up, welcome a new family, review request, package expiry, compliance expiry.
- [ ] **T07 — Sequence editor.** The Workflows area, the timeline with in-place cards,
  splits, Stop when, + Add a step, Move up and down, problems in words, Save and switch on,
  Reset to default. Replaces the Automations pages. WCAG 2.2 AA; usability check with the
  built-ins (a first-time owner can change "when invoices go out" in under a minute).
- [ ] **T08 — Preview, coming up and runs.** Preview for a family, coming-up dates with
  counts, the runs list with where each run is, cancel and retry.
- [ ] **T09 — Migration and docs.** Automations → custom workflows (their branches map to
  splits; any that don't fit stay as they are and open read-only with "Contact support"),
  recipes → templates, `/automations` redirect, guides, help articles, What's new, roadmap
  and README.

Order: T01 → T02 → T03 → (T04, T05, T06) → T07 → T08 → T09. T07 can start after T02
against the API.

## Temporal workflows (E32)
- `AutomationRunWorkflow` (E14) interprets every workflow. Date-relative waits are timers;
  **Stop when** is a signal from the bridge that ends the run at its next wait. Histories
  stay small: every step is an activity or a timer.
- `AutomationScheduleWorkflow` (E14) runs schedule and relative-date triggers, one Temporal
  Schedule per workflow and branch.
- The replaced per-process workflows (FR-33-2 table) are removed after T05 to T07.

## Implementation notes

**T01 (2026-10-25).**
- Yes / No splits are the existing E14 `branch` steps (`if`, `then`, `else`). The steps after
  a branch already run for both paths, so splits rejoin with no engine change. The one-level
  limit is the editor's (T07); the engine keeps E14's nesting limit so existing
  automations still validate.
- "Only if" is `only_if` on action steps, checked by `execute_step` at the moment the step
  runs. A skipped step is recorded as `skipped` with `{"skipped": "only_if"}`; a card with
  several actions puts the same `only_if` on each. No workflow change was needed.
- Waits (`automations/timing.py`, pure and Hypothesis-tested): `until` with
  `offset_days`/`offset_hours` (negative for before), `days`/`hours` from now, `at`
  ("HH:MM"), `business_day` (closed weekdays from `general.business_hours` plus holidays and
  closures from `scheduling.services.holiday_dates`) and `quiet_hours` (`comms.quiet_hours_*`),
  in the record's branch time zone. Plain dates count from local midnight, not the
  server's time zone. `BusinessCalendar` gained `is_quiet`/`is_closed`.
- **Stop when** is `stop_when` on `Automation` and `AutomationVersion` (part of the
  definition, so it is versioned). `on_event` signals `stop` to runs under way for the
  record before it starts new runs, so a run never stops on its own trigger. The run wakes
  from a wait (`wait_condition` with the wait as timeout, behind `workflow.patched("stop-when")`;
  older histories keep `workflow.sleep`), finishes `stopped`, records `stop_reason`, and
  its unfinished wait is marked `skipped`.
- New histories: `AutomationRunWorkflow-only-if`, `-stopped`, `-timed`; the existing ones
  still replay.

**T02 (2026-10-25).**
- **Plain questions** (`automations/catalogue.py`) are predicates registered with a record
  type: `{"predicate": "invoice.unpaid"}` in `only_if` or a split's `if`. They read the
  record's whitelisted context, so a dry run answers them as a run would. Saving refuses a
  question about another kind of record. 29 questions across 13 record types; every one has
  a yes and a no test. Contexts gained `lesson.trial`, `lesson_report.overdue`/`escalated`
  and `enquiry.trial_booked`/`trial_outcome`.
- **Record types:** `branch` (so a schedule runs once per branch, for invoicing),
  `invoice_run` and `payment_request`. Package came with G4. The "statement (period)" record
  type isn't needed: statements are a monthly schedule on clients with **Send a statement**
  (last month).
- **Starts:** new events `invoice_run.drafted` and `invoice_run.issued` (billing),
  `trial_lesson.no_show` (leads, when a trial lesson is marked missed) and
  `client.first_lesson_completed` (scheduling, once per family); existing events now
  registered as starts: `payment_request.created`/`sent`/`paid`/`cancelled`,
  `lesson.unconfirmed`, `lesson_report.due`/`escalated`, `package.activated`, and
  `invoice.sent`/`partially_paid`/`voided`/`written_off` (mainly for **Stop when**).
  The relative-date starts in FR-33-4 (`invoice.due_soon`, `lesson.reminder_due`,
  `package.expiring`) are not new events: a sequence starts on the record's event and its
  first wait counts from the date (`DATE_STARTS` in the schema, for the editor). This is
  more exact than a daily date trigger and needs no sweeper. `statement.due` and "invoicing
  due" are named schedules (`SCHEDULE_STARTS`).
- **Actions** (each through the owning service, keyed by run and step, with a permission):
  Start an invoice run (branch; schedule's period, last or this week, last, this or next
  month, this term; arrears or advance; `create_run` is idempotent per period), Issue the
  invoice run (approves it, as staff would; the run's own workflow issues), Email the
  invoice (new `billing.services.email_invoice`), Send a statement, Collect payment now,
  Open a collections case, Send payment request reminder (moved into
  `billing.services.remind_payment_request`), Send lesson reminder, Mark report overdue and
  notify, Escalate to the tutor's manager, Assign to a person (enquiries), Ask for a review,
  Start another workflow (same record type; `prepare_run(depth=…)` so the loop limit
  applies). "Ask for lesson feedback" is G4's `send_feedback_survey`.
- **Skipped with a reason** (FR-33-5): an action whose record has moved on returns
  `{"skipped": "invoice already paid"}` and the step is logged as skipped with that result.
  The late fee now skips a paid invoice instead of noting "nothing owed".
- **Audit:** issue run, collect, late fee and collections write a `workflow.<action>` audit
  entry with the workflow, its version and the run.
- **Pause and resume:** `Automation.paused`. Paused: no new runs (manual ones included), and
  `execute_step` answers `paused` before the next action, so the run is held (status
  `paused`) on `wait_condition` until the `resume` signal, re-checking every 6 hours in
  case a signal was missed. Waits and Stop when go on as normal while paused. Only runs that
  meet a pause take the new path, so no `workflow.patched` was needed; new history
  `AutomationRunWorkflow-paused`. `POST /automations/{id}/pause` and `/resume`.
- **Silent versions:** already the case (E14); pausing, enabling and renaming don't make a
  version.
- `/workflow-schema` returns record types (date fields, stop-when events), starts (events,
  date starts, named schedules, frequencies), plain questions and actions (with `allowed`
  for the caller). `/automation-schema` stays for the current Automations pages. The
  `/workflows` aliases come with the editor (T07).

**T03 (2026-10-25).**
- **Registry:** `automations/builtin_workflows.py`. Apps declare built-ins in
  `<app>/workflows_builtin.py` with `@builtin_workflow(key, group, name=, description=,
  version=, first_version=, can_switch_off=, off_means=, enabled=)` on a function that
  returns the default definition; `AutomationsConfig.ready` discovers the modules. Groups:
  `invoicing`, `lessons`, `sales`, `expiry`. `first_version` builds an organisation's first
  version from its current settings (used from T04). No built-ins ship in T03; a test
  checks that every registered one validates.
- **Model:** `Automation.kind` (`custom` | `builtin`), `builtin_key` (unique per
  organisation), `builtin_version` and `edited`. `edited` is worked out on every save by
  comparing the definition with the current default, so changing it back clears it. A first
  version built from non-default settings counts as edited, so a later default never
  overwrites the organisation's settings; it is offered instead.
- **Install and upgrade:** `services.install_builtins()` (idempotent) installs missing
  built-ins switched on, and moves unedited ones whose `builtin_version` is behind to the new
  default (a new version, audited as `upgrade`). Edited ones are left alone and report
  `update_available`. It runs on `organisation.created` and, for existing organisations and
  new defaults, from the `sync_builtin_workflows` management command, which the Temporal
  worker task runs at start (ecs.tf, docker-compose) as with `ensure_platform_schedules`.
  This was chosen over a data migration because definitions are code and are checked
  against the registry.
- **Rules for built-ins:** they keep their name, description and record type (edits to
  those are ignored or refused); they can't be deleted (422); `can_switch_off=False` refuses
  switching off (pausing still works); **Reset to default** (`POST
  /automations/{id}/reset-to-default`, audited `reset`) writes the default as a new version,
  so runs under way keep theirs, and checks the caller's permission for every action in it.
  `GET /automations/{id}/default` returns the default to compare with.
- **Authority:** an unedited built-in is TutorTrack's own default, so its steps run with the
  platform's authority (`_authorised`); once edited, steps need the editor's permission at
  run time, as for custom automations (ADR 0014 §6).
- **Switched off safely (FR-33-5):** `off_means` says what happens instead; `GET
  /automations/notices` lists built-ins that are switched off or have a newer default, and
  Home shows them to staff with `automation.view`.
- **Permissions and plans:** new `automation.builtin.manage` (owner and admin through `*`,
  branch manager through `*:branch`, finance by grant; finance also gets
  `automation.view`). Writes to a built-in need it, writes to a custom one need
  `automation.manage`, creating always needs `automation.manage`. The plan's
  `automation_rules` limit, listed since E04 but not enforced, is now checked when creating
  a custom automation (recipes included); built-ins don't count and work on every plan.
- **API and UI:** the automation serializer gained `kind`, `builtin_key`,
  `builtin_version`, `edited`, `builtin` (group, latest version, `update_available`,
  `can_switch_off`, `off_means`) and `runs_under_way`; the list takes `?kind=`. The current
  Automations pages show **Built-in**, keep a built-in's name read-only, disable the switch
  for ones that can't be switched off, and offer **Reset to default**; the full editor is
  T07.
