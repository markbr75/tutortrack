# ADR 0002 — Temporal for durable business workflows

- **Status:** Accepted
- **Date:** 2026-10-08
- **Epic:** [E32](../epics/E32-workflow-orchestration-temporal.md)

## Context
Many TutorTrack processes run for days or weeks and combine timers, retries against external providers, and human decisions:
- invoice runs with a review window
- dunning and late fees
- pay runs with dual approval and payout reconciliation
- job-offer cascades with timeouts
- compliance expiry
- automations with "wait N days" steps
- imports with a rollback window
- GDPR requests with statutory deadlines

The original spec implemented these with Celery Beat sweepers polling "next step at" columns. That approach spreads each process across many tables and tasks, is hard to reason about and test, and gives staff no visibility of where a process is.

## Decision
Use **Temporal** (Python SDK `temporalio`) for durable, multi-step processes, following the rule in E32 §2. Keep **Celery** for short, stateless tasks and global crons.

- **Production:** Temporal Cloud. **Local:** the Temporal CLI dev server.
- Workflows are deterministic orchestration only. All side effects go through activities that call Django services in tenant context.
- The outbox (E01) remains the source of domain events. A bridge subscriber starts or signals workflows from events.
- Payloads are encrypted with a KMS-backed codec so PII never sits in Temporal in clear.

## Alternatives considered
- **Celery + database state machines (status quo):** no new infrastructure, but each process needs bespoke sweeper, timer and retry code, has poor visibility, and is hard to test across long time spans.
- **Celery Canvas / Dramatiq pipelines:** handle chaining but not long timers, signals or human waits.
- **AWS Step Functions:** durable and managed, but locks us into AWS, is awkward to run locally and test in Python, and is costly at our event volumes.
- **Replace Celery entirely with Temporal:** possible later. For now it adds latency and cost to high-volume fire-and-forget work such as message sends and webhook deliveries.

## Consequences
- A second runtime to operate: Temporal Cloud subscription, worker services, payload codec keys.
- Developers must learn workflow determinism rules, versioning (`patched`, build IDs) and replay testing. E32 provides helpers and a reference workflow.
- Process logic becomes explicit, testable with time-skipping, and visible to staff as a timeline.
- Several epic designs change: "next attempt at" and "resume at" columns and their sweeper tasks are replaced by workflows (see each epic's *Temporal workflows* section).
