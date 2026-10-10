# ADR 0014: Automations are versioned JSON interpreted by a Temporal workflow

- **Status:** Accepted
- **Date:** 2026-10-10
- **Epic:** E14

## Context
Tenants build "When → If → Then" automations with waits and branches that can last days.
They must be safe: no code execution, no access to data beyond what the builder exposes,
no runaway loops. Edits must not break runs already in flight, and failed steps must be
retryable without repeating side effects.

## Decision
1. **Definitions are data, checked against a registry.** Triggers, conditions and steps
   are JSON. `automations.registry` declares, per subject:
   - the whitelisted context (fields);
   - recipients and the owner;
   - settable fields and date fields.

   It also declares the actions, with their config fields and any permission they need.
   Saving validates every field path, action and permission. Conditions are interpreted by
   a small evaluator; there is no `eval` and no template logic beyond the sandboxed comms
   renderer.
2. **Versions are immutable.** Changing the trigger, conditions or steps writes an
   `AutomationVersion`; runs reference the version they started with.
3. **One workflow per run interprets the version.**
   - `AutomationRunWorkflow` walks the steps. Actions are activities that call the owning
     apps' services. Waits are durable timers. Branch conditions are re-evaluated against
     the record when the run reaches them.
   - Each action writes an `AutomationRunStep` row keyed by run and step path in the same
     transaction as its effects, so a retried activity or a retried run returns the stored
     result instead of acting twice. Messages also dedupe on that key.
   - This replaces the spec's `resume_at` column and sweeper.
4. **Guardrails run before a run exists:**
   - kill switch, per-record daily limit and per-organisation hourly limit;
   - one run per event or schedule slot (a unique run key);
   - the conditions.

   **Loop detection** uses the actor that activities already stamp on events (the
   workflow id). A run's causation depth is its parent run's plus one, and a depth over 3
   is recorded as skipped instead of starting.
5. **Timed triggers are Temporal Schedules per automation.** Each schedule fans out to one
   run per due record. The automation's events keep the schedule in step with its
   definition and enabled state.
6. **Finance actions are attributed to the automation's author.** The author must hold the
   permission when saving, and still hold it when each run executes the step.

## Consequences
- Subject contexts are built per record. Schedule fan-out is capped at 2,000 records per
  run, and heavier queries will need indexed pre-filters per subject.
- Adding a trigger, field or action is a registry entry plus tests; the builder picks it up
  from `/api/v1/automation-schema`.
- Workflow histories stay small: the plan is loaded once by an activity, and every step is
  an activity or a timer.
