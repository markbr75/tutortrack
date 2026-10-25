# ADR 0047: The workflow designer grows the automation engine, on Temporal

- **Status:** Accepted
- **Date:** 2026-10-25
- **Epic:** [E33](../epics/E33-workflow-designer.md)
- **Builds on:** ADR 0002 (Temporal), ADR 0014 (automations interpreted on Temporal)

## Context
The owner wants to design workflows inside TutorTrack to decide when invoices go out and
when emails are sent, with ready-made workflows to start from. Today the timing of those
processes is hard-wired: about 15 Temporal workflows and one Celery beat task, tuned by
about 40 settings (many only reachable through the API). Separately, the E14 Automations
builder already lets staff build When → If → Then rules with waits and branches, interpreted
by a Temporal workflow.

The owner also asked whether Temporal is the right engine, or whether something inside the
system or the database would be better. We considered:

- **A Postgres-backed interpreter** (run state, timers and step log in our database,
  driven by Celery). It needs no external service and suits workflows that are data. But
  it brings back the "next_at column plus sweeper" pattern ADR 0002 removed, and we would
  have to own timer correctness.
- **DBOS** (durable execution in-process, state in Postgres). There is no separate
  service, but it is young, and it is unproven for workflows that wait for weeks across
  deploys and for per-tenant schedules.
- **Keep Temporal.** It is already integrated: 66 workflows, the bridge, the codec,
  replay tests and the run timelines. The cost is an external service (Temporal Cloud or
  self-hosted) and the determinism rules.

## Decision
1. **Keep Temporal for everything** (owner decision, 2026-10-25). The question can be
   revisited when the deploy is planned, mainly on cost. Because designed workflows are
   data interpreted by one workflow, a later engine change would touch the interpreter and
   the protected processes, not the designer or the definitions.
2. **One editor, one engine, kept simple.** Automations becomes Workflows. A workflow is
   a *sequence* on one timeline, because the people using it run tutoring businesses, not
   software teams (owner, 2026-10-25). It has:
   - steps with *When*, *Only if* and *Do*;
   - Yes / No splits on one plain question, one level deep, that join again afterwards;
   - an optional *Stop when* rule.
   There are no loops, approval steps or free-form flowcharts. The E14
   `AutomationRunWorkflow` stays the only interpreter. It gains waits relative to a date
   and time of day, splits that rejoin, and stop-when, which is a signal from the bridge.
   Interpreter changes use `workflow.patched` with replay histories.
3. **Built-in workflows are definitions shipped in code.** They are installed for every
   organisation, editable and resettable. They replace the hard-wired timing of invoicing,
   payment chasing, statements, lesson reminders, report chasing, feedback requests,
   enquiry follow-ups, review requests and expiry reminders (the table in E33 FR-33-2).
   Each organisation's current settings become its first version.
4. **Protected processes stay in code.** These are the processes with legal or financial
   rules:
   - invoice runs' internals;
   - pay runs and payouts;
   - recurring fees;
   - GDPR, imports and calendar sync;
   - booking holds and offer cascades;
   - checks and organisation closure.
   Workflows reach them only through registered actions and events, so a design can't skip
   a rule.
5. Built-in workflows are on every plan; custom workflows keep the E14 plan limits.

## Consequences
- The Celery lesson-reminder sweeper and about 12 bespoke Temporal workflows are retired
  in favour of definitions run by the interpreter. Their settings are removed one release
  after migration.
- `AutomationRun.next_wake_at` and `waiting_for` are display-only copies of Temporal
  state. Nothing sweeps them (CLAUDE.md 4a still holds).
- Adding a built-in workflow, trigger or action is a registry or definition change plus
  tests. The designer reads `/workflow-schema`.
- Every built-in workflow needs a test that its default reproduces the old behaviour.
