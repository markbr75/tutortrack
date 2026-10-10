# E14 — Automation & Workflow Engine

| | |
|---|---|
| **Phase** | Agency (Phase 2) |
| **Depends on** | E01 outbox, E05, E13 (+ actions from other epics) |
| **Differentiator** | Neither TutorCruncher nor TutorBird offers a general rules engine; this replaces Zapier for most in-platform needs |

## 1. Summary
A no-code "When → If → Then" automation builder that lets tenants react to domain events or schedules with conditions and actions: send messages, create tasks, change statuses, add tags, move pipeline stages, call webhooks, and wait/delay steps. Ships with a library of recipes.

## 2. Functional requirements

### FR-14-1 Triggers
- **Event triggers:** any event in the catalogue (`03-domain-model.md §5`) marked `automatable`, e.g. `enquiry.received`, `lesson.completed`, `student.status_changed`, `invoice.overdue`, `lesson_report.overdue`, `package.low`, `compliance.document_expiring`.
- **Schedule triggers:** cron-like (daily at 08:00 org tz, weekly, monthly) combined with a record query (e.g. "every Monday: students with no lesson in 21 days").
- **Date-field triggers:** relative to a date field (e.g. 7 days before `student.date_of_birth` anniversary; 30 days before `document.expires_at`; 3 days after `lesson.end`).
- **Manual trigger:** "Run automation" button/bulk action on selected records.

### FR-14-2 Conditions
- Field conditions on the subject and related objects (dot paths whitelisted per event, e.g. `lesson.service.subject`, `client.tags`, `student.custom.exam_year`), operators (equals, in, contains, gt/lt, is empty, changed from/to, within last N days), AND/OR groups.
- Built-in predicates: "is first lesson for student", "client has auto-pay", "balance below X".

### FR-14-3 Actions
- Send notification/email/SMS/WhatsApp (template or inline) to resolved recipients.
- Create task (assignee rules: account manager, round-robin among role, specific user).
- Update field / status / add or remove tag on the subject or related record.
- Move enquiry/application pipeline stage.
- Create payment request; apply late fee; create ad hoc charge (permission-gated action types).
- Send lesson feedback survey.
- Add to broadcast list / Mailchimp audience.
- Call outbound webhook (signed) / trigger Zapier.
- **Wait** (delay N hours/days, or until a date field) and **branch** (if/else) steps → multi-step workflows.
- Assign tutor offer (E19).

### FR-14-4 Builder UI
- Visual vertical flow builder; trigger picker with search; condition builder; action forms with variable insertion; test with a sample record (dry-run showing what would happen); enable/disable; versioned (edits create a new version; in-flight runs continue on their version).

### FR-14-5 Execution engine
- Event subscriber in the outbox dispatcher → matches enabled automations (indexed by trigger type) → evaluates conditions → creates `AutomationRun` → executes steps via Celery; waits are scheduled tasks (`AutomationRunStep.resume_at`) picked up by a beat sweeper.
- Guardrails: max runs per automation per record per day (default 1 unless configured), loop detection (automation-originated events carry `causation_chain`; depth > 3 is stopped), per-org rate limits, kill switch.
- Idempotent steps (keyed by run+step).
- Run log: status per step, errors, re-run failed step.

### FR-14-6 Recipe library
Pre-built, one-click-install automations, e.g.:
- New enquiry → auto-reply + task for coordinator within 1h.
- Trial lesson completed → wait 1 day → send feedback + offer packages email → if no booking in 5 days, task to call.
- Student no lesson in 30 days → mark dormant + re-engagement email.
- Report overdue 24h → SMS tutor; 48h → task for coordinator.
- Package < 2 hours remaining → email client with buy link.
- Invoice overdue 14 days → SMS + task; 30 days → pause bookings tag.
- DBS expiring in 60 days → email tutor + task.
- Birthday message to students (opt-in).
- New tutor approved → onboarding checklist tasks.

## 3. Data model
`Automation(name, trigger_type, trigger_config, conditions JSONB, steps JSONB, version, enabled, created_by)`, `AutomationVersion`, `AutomationRun(automation_version, subject_type, subject_id, event_id, status, started_at, finished_at, causation_depth)`, `AutomationRunStep(run, step_index, status, resume_at, result, error)`, `AutomationRecipe` (platform-defined).

## 4. API
`/api/v1/automations` CRUD + `/test`, `/enable`, `/disable`, `/runs`; `/automation-recipes` + `/install`; `/automation-schema` (available triggers, fields, actions for the builder).

## 5. Permissions
`automation.view`, `automation.manage`; action types that touch finance require the creator to hold the corresponding finance permission (checked at save and at run).

## 6. Delivery plan
- [x] **E14-T01** Automation model, versioning, schema registry (triggers/fields/actions exposed by apps).
- [x] **E14-T02** Condition evaluator (safe, no eval) with tests.
- [x] **E14-T03** Event-triggered execution, run log, guardrails, loop detection.
- [x] **E14-T04** Core actions: notify, task, update field/tag/status, webhook.
- [x] **E14-T05** Wait and branch steps with resume sweeper.
- [x] **E14-T06** Schedule and date-field triggers.
- [x] **E14-T07** Finance and pipeline actions.
- [x] **E14-T08** Recipe library and install.
- [x] **E14-T09** Frontend flow builder with dry-run.

## Temporal workflows (E32)

Implement these processes as Temporal workflows following the rules in [E32](E32-workflow-orchestration-temporal.md) (deterministic workflow code, side effects in tenant-scoped activities that call services, tenant-prefixed workflow IDs, signals for human decisions). Where the requirements above mention sweeper tasks, `next_*_at` / `resume_at` columns or retry schedules, the workflow replaces them.

- [x] **E14-TW1** Run the automation engine on Temporal (requires E32).

| Workflow | Started by | Steps, timers and signals | Replaces |
|---|---|---|---|
| `AutomationRunWorkflow` `automation:{org}:{automation}:{subject}:{event}` | Matching event (via the outbox bridge), schedule trigger, date-field trigger or manual run | Interprets the automation version's steps: conditions → actions (activities) → **wait** steps become durable timers, **branch** steps are plain workflow logic. Guardrails (rate per record, causation depth) are checked before start. Run log = workflow history + `AutomationRunStep` rows written by activities | `AutomationRunStep.resume_at` + resume sweeper (FR-14-5) |
| Schedule and date-field triggers | **Temporal Schedules** per automation | Schedule fires → query matching records → start one `AutomationRunWorkflow` per record (workflow IDs dedupe) | Cron-like trigger evaluation |

## Implementation notes (as built 2026-10-10)
- **App:** `automations`, with RLS on every table: `Automation`, `AutomationVersion`, `AutomationRun` and `AutomationRunStep`. See ADR 0014.
  - Deviation: recipes are a code catalogue (`automations/recipes.py`, like the plan catalogue) rather than an `AutomationRecipe` table.
- **Registry (T01):** `automations.registry` holds three things:
  - *Subjects*: client, student, tutor, lesson, lesson report, enquiry, invoice, job, tutor application and compliance record. Each has a loader, a whitelisted context (the only fields conditions and message variables can see), recipients, an owner, settable fields and date fields.
  - *Event triggers*: 35 curated events across those subjects.
  - *Actions*.

  Built-ins live in `builtins.py`; other apps can register more the same way. `/api/v1/automation-schema` serves all of this to the builder.
- **Versioning (T01):** editing the trigger, conditions or steps saves a new `AutomationVersion`; renaming doesn't. Runs keep the version they started with.
- **Conditions (T02):** `conditions.evaluate` interprets a JSON tree (`all`/`any`/`not`/`field`/`predicate`) without `eval`.
  - Operators: equals, in, contains, comparisons (numbers or dates), empty, `changed`/`changed_from`/`changed_to` (from the event's changes), and within the last, more than ago, or within the next N days.
  - Predicates: first lesson for a student; client pays automatically.
  - "Balance below X" is the field `client.balance_due`.
  - Paths are checked against the subject's fields when an automation is saved.
- **Execution (T03):** an outbox subscriber on the registered trigger events matches enabled automations by event type (indexed `trigger_key`), evaluates the conditions and creates a run. Guardrails:
  - the org kill switch `automations.enabled`;
  - per record, at most `max_runs_per_record` runs in 24 hours (default 1; manual runs are exempt);
  - per organisation, at most `automations.max_runs_per_hour` runs;
  - once per event or schedule slot (a unique run key);
  - loop detection: events written by a run carry its workflow as actor, so a run's causation depth is its parent's plus one; deeper than 3 is recorded as skipped.

  The run log is the `AutomationRunStep` rows. A failed run can be retried from its failed step, and completed steps aren't repeated.
- **Actions (T04/T07):**
  - send a message (inline subject and body rendered per recipient with the record's variables; email, SMS, in-app; to the family, tutor, owner or a user);
  - create a task (owner, a user, or round-robin among a role, picking whoever has the fewest open tasks);
  - change a whitelisted field;
  - add or remove a tag (created if new);
  - move an enquiry or application stage;
  - call a webhook, signed `X-TutorTrack-Signature: t=..,v1=hmac-sha256` with the automation's secret and sent through the SSRF guard;
  - add a one-off charge, apply a late fee (percent of the balance with a minimum, rounded half-up) or request a payment;
  - offer a job to the top matches (E19).

  Finance and offer actions need the author to hold the permission, both when saving and when running.
  - Deviations: no feedback surveys (E21), broadcast or Mailchimp lists (E27), or WhatsApp. Messages are inline rather than picking an E13 template.
- **Wait and branch (T05):** waits are hours, days, or until a date field on the record plus an offset. Branches re-check their condition when the run reaches them. Both are interpreted by the workflow (below), so there's no `resume_at` sweeper.
- **Schedules and dates (T06):**
  - Schedule triggers run daily, weekly or monthly at a local time. Each records' conditions act as the query (e.g. active students whose last lesson was more than 30 days ago).
  - Date triggers fire N days before or after a date field, optionally every year (birthdays).
  - Each enabled timed automation has a Temporal Schedule (`automation-schedule`), kept in step by `automation.saved` and `automation.deleted`. It picks today's records (up to 2,000) and starts one run each, deduplicated per day.
  - Manual: "Run" on chosen records (`/automations/{id}/run`).
- **Recipes (T08):** new enquiry reply and task; trial follow-up with waits and a branch; dormant students; overdue report nudge then escalate; prepaid balance low; overdue invoice (remind, task, and tag "Bookings paused" 16 days later); check expiring in 60 days; birthdays (opt-in tag); tutor approved onboarding tasks. Installing one creates a disabled automation to review.
  - Deviation: the spec's "package < 2 hours" recipe is "prepaid balance low", because packages are a Phase-2 E10 remainder.
- **Frontend (T09):** `/automations` has the list (on/off), recipes and the run log (with retry). `/automations/$id` is the builder:
  - trigger picker with search, plus schedule and date options;
  - all/any condition rows;
  - a vertical step list (action forms from the schema with "insert a variable", waits, and nested if/else);
  - save as a new version, a dry run against a record ID, and the automation's runs.
  - Deviation: steps are a structured vertical form rather than a drag-and-drop canvas.
- **Workflows (TW1):**
  - `AutomationRunWorkflow` `automation:{org}:{automation}:{subject}:{key}`: actions are idempotent activities, retried up to five times and then failing the run; waits are durable timers; branches are workflow logic. Retries use `...-retryN`.
  - `AutomationScheduleWorkflow` is started by each automation's Temporal Schedule.
  - Replay histories are in `backend/tests/workflow_histories/`.
- **Events:** `automation.saved`, `automation.deleted` and `automation.run_failed`. Automations never react to `automation.*` events.
