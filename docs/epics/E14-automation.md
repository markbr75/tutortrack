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
- [ ] **E14-T01** Automation model, versioning, schema registry (triggers/fields/actions exposed by apps).
- [ ] **E14-T02** Condition evaluator (safe, no eval) with tests.
- [ ] **E14-T03** Event-triggered execution, run log, guardrails, loop detection.
- [ ] **E14-T04** Core actions: notify, task, update field/tag/status, webhook.
- [ ] **E14-T05** Wait and branch steps with resume sweeper.
- [ ] **E14-T06** Schedule and date-field triggers.
- [ ] **E14-T07** Finance and pipeline actions.
- [ ] **E14-T08** Recipe library and install.
- [ ] **E14-T09** Frontend flow builder with dry-run.

## Temporal workflows (E32)

Implement these processes as Temporal workflows following the rules in [E32](E32-workflow-orchestration-temporal.md) (deterministic workflow code, side effects in tenant-scoped activities that call services, tenant-prefixed workflow IDs, signals for human decisions). Where the requirements above mention sweeper tasks, `next_*_at` / `resume_at` columns or retry schedules, the workflow replaces them.

- [ ] **E14-TW1** Run the automation engine on Temporal (requires E32).

| Workflow | Started by | Steps, timers and signals | Replaces |
|---|---|---|---|
| `AutomationRunWorkflow` `automation:{org}:{automation}:{subject}:{event}` | Matching event (via the outbox bridge), schedule trigger, date-field trigger or manual run | Interprets the automation version's steps: conditions → actions (activities) → **wait** steps become durable timers, **branch** steps are plain workflow logic. Guardrails (rate per record, causation depth) are checked before start. Run log = workflow history + `AutomationRunStep` rows written by activities | `AutomationRunStep.resume_at` + resume sweeper (FR-14-5) |
| Schedule and date-field triggers | **Temporal Schedules** per automation | Schedule fires → query matching records → start one `AutomationRunWorkflow` per record (workflow IDs dedupe) | Cron-like trigger evaluation |
