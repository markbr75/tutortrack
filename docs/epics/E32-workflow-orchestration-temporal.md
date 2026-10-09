# E32 — Workflow Orchestration (Temporal)

| | |
|---|---|
| **Phase** | MVP (build after E03, before the first epic that needs a workflow) |
| **Depends on** | E01 (outbox, audit, Celery), E02 (tenancy), E03 (actors) |
| **Unlocks** | Durable processes in E02, E04, E08–E14, E17–E20, E22, E23, E25, E28, E29 |
| **Decision** | [ADR 0002](../adr/0002-temporal-for-durable-workflows.md) |

## 1. Summary
Introduce **Temporal** as the engine for durable, long-running business processes: anything with multiple steps, timers measured in hours or days, retries against external providers, or human approvals. Examples are invoice runs with a review window, dunning schedules, pay runs with dual approval, job-offer cascades, compliance expiry, automations with "wait 3 days" steps, imports with a rollback window, and GDPR requests with statutory deadlines.

Celery (E01) stays for short, stateless background work: outbox dispatch, sending one message, virus scans, webhook deliveries, cache warming, and Beat fan-out crons.

## 2. When to use Temporal vs Celery (the rule every epic follows)

| Use **Temporal** when the process… | Use **Celery** when the task… |
|---|---|
| spans more than one step that must all eventually happen (a saga) | is a single unit of work |
| waits on a timer longer than a few minutes (due dates, grace periods, SLAs) | completes in seconds |
| waits for a human decision or external callback (approval, webhook, reply) | needs no coordination |
| must be visible as a process timeline to staff ("where is this pay run?") | is fire-and-forget |
| must be cancellable or changeable mid-flight (signal: "invoice paid, stop dunning") | is high volume and low value (thousands per minute) |

If in doubt: if you would otherwise store "next step at" timestamps in a table and poll for them with a sweeper task, use Temporal.

## 3. Functional requirements

### FR-32-1 Local and production runtime
- **Local:** add a Temporal dev server to `docker-compose.yml` (the official Temporal CLI image running `temporal server start-dev`, with the Web UI on `:8233` and gRPC on `:7233`; pin the image version) plus `make infra` support. Add `TEMPORAL_ADDRESS`, `TEMPORAL_NAMESPACE` and `TEMPORAL_TLS_*` to `.env.example`.
- **Production:** **Temporal Cloud** (recommended: no cluster to operate; regions available for UK/EU/US/AU data residency) with mTLS or API-key auth. A self-hosted option (Temporal server on ECS with its own RDS database) is documented in `infra/terraform/README.md` but not built.
- One **namespace per environment** (`tutortrack-staging`, `tutortrack-production`), not per tenant.

### FR-32-2 Python SDK integration (`tutortrack.workflows` app)
- Dependency: `temporalio` (Python SDK).
- `core.workflows.client.get_client()` returns a cached Temporal client configured from settings, with OpenTelemetry tracing and Sentry interceptors.
- **Worker process:** `manage.py temporal_worker --task-queue <queue>` registers the workflows and activities declared by installed apps (autodiscovered from each app's `workflows.py` and `activities.py`). Task queues mirror the Celery ones: `default`, `billing`, `payroll`, `comms`, `integrations`, `imports`, `privacy`.
- Docker Compose service `temporal-worker`; ECS service in Terraform.

### FR-32-3 Tenancy, identity and determinism rules
- Every workflow input is a frozen dataclass whose first field is `organisation_id`. Workflow IDs are deterministic and tenant-prefixed, e.g. `invoice-run:{org}:{branch}:{period}`, `invoice-dunning:{org}:{invoice_id}`, `pay-run:{org}:{pay_run_id}`. Duplicate starts are therefore rejected (`WorkflowIdReusePolicy.REJECT_DUPLICATE` or `ALLOW_DUPLICATE_FAILED_ONLY`), which gives start-idempotency for free.
- Search attributes on every workflow: `OrganisationId`, `BranchId`, `SubjectType`, `SubjectId`, `TutorTrackProcess`, so staff can list a tenant's or a record's processes.
- **Workflow code is deterministic:** no ORM, no network, no `datetime.now()` (use `workflow.now()`), no randomness. All side effects go through **activities**.
- **Activities** call Django **services** (never write to models directly), inside `tenant_context(organisation_id)` and a request context identifying the actor as the workflow (`actor = {"type": "workflow", "id": workflow_id}`). This happens via an activity base decorator `@tenant_activity`.
- Activities must be idempotent: they receive an idempotency key (`workflow_id + activity_id`) and pass it to provider calls and to `core.events.publish`.
- The Postgres RLS variable (E02) is set inside activities exactly as in `TenantTask`.

### FR-32-4 Bridge from domain events to workflows
- An outbox subscriber (`workflows.handlers.temporal_bridge`) maps domain events to **start** or **signal** operations, configured declaratively per app:
  ```python
  bridge.on("invoice.issued", start=InvoiceDunningWorkflow, id="invoice-dunning:{org}:{subject_id}")
  bridge.on("payment.succeeded", signal=InvoiceDunningWorkflow.paid, id="invoice-dunning:{org}:{data.invoice_id}")
  ```
- Signals to workflows that have already finished are ignored (logged at debug level). Starts are idempotent via workflow IDs.
- Services may also start or signal workflows directly through `core.workflows.start()` / `signal()`. These calls are deferred with `transaction.on_commit` so a workflow never sees uncommitted state.

### FR-32-5 Human-in-the-loop
- Approvals, reviews and replies are **signals** sent by API endpoints, for example `POST /api/v1/pay-runs/{id}/approve` → service → `signal(PayRunWorkflow.approve, approver_id)`. Workflows validate signals (permission already checked in the API) and record them in audit.
- **Queries** expose live state (current step, next timer, waiting for whom) to the API, so the admin UI shows a process timeline on the record page (invoice, pay run, application, DSAR).
- **Updates** (validated synchronous signals) are used where the caller needs an immediate result, such as "extend this offer by 24h".

### FR-32-6 Timers, business calendars and timezones
- Durations come from tenant settings, read through an activity at workflow start and snapshotted in workflow state, so a settings change doesn't alter in-flight processes unless the workflow is explicitly signalled.
- A helper `wait_until_local(dt_local, tz)` converts tenant-local deadlines (e.g. "09:00 on the due date in Europe/London") to durable timers. It respects quiet hours (E13) and holiday calendars (E06) when a reminder would fall outside business hours.

### FR-32-7 Schedules
- Recurring per-tenant processes that need durable state use **Temporal Schedules** (one per organisation and process, created and updated by settings services). Examples: invoice runs on the 1st, pay-run cut-offs, monthly statements. Simple global crons (outbox sweep, cleanup) stay on Celery Beat.
- When an organisation is suspended or closed (E02/E04), its schedules are paused or deleted by a service hook.

### FR-32-8 Versioning and deployment
- Workflow changes use `workflow.patched()` for in-flight compatibility. Breaking changes use **Worker Versioning** (build IDs) so old executions finish on old code.
- CI replays recorded histories (`Replayer`) for each workflow type against the new code, failing on non-determinism. Histories are stored in `backend/tests/workflow_histories/`.
- Deploy order: new workers are deployed alongside the old ones, then the old ones drain.

### FR-32-9 Security and privacy
- **Payload encryption:** a custom `PayloadCodec` encrypts all workflow and activity payloads with AES-GCM keys from KMS before they leave our process, so Temporal (Cloud) never stores PII in clear. A codec server endpoint (`/temporal-codec`, staff-only) lets the Temporal UI decrypt for authorised operators.
- Payloads carry IDs and small values, never documents or large blobs. Activities load data from Postgres by ID.
- Temporal Cloud region chosen per data-residency stack (E29).

### FR-32-10 Observability and operations
- OpenTelemetry interceptor linking HTTP request → outbox → workflow → activity traces; Sentry for activity failures.
- Platform console (E30): list failed or stuck workflows per tenant, terminate, reset or retry, with an audited reason. Deep links to the Temporal UI.
- Alerts: workflow task failures, activity retry storms, schedule backlog, worker poll latency.

### FR-32-11 Testing harness
- `pytest` fixture `temporal_env` using `WorkflowEnvironment.start_time_skipping()` so tests can run 30 days of timers in milliseconds.
- Activity tests run against the real Django test database. Workflow tests mock activities with the SDK's activity registration.
- Each workflow ships with: a happy-path test, a signal/cancellation test, a timer test, a failure/retry test, and a replay test.

### FR-32-12 Reference workflow
- Implement `DemoReminderWorkflow` (wait N days in tenant time → activity publishes `demo.reminder_due` → finish; cancellable by signal) as the documented example used by later epics. Remove it once a real workflow exists.

## 4. Catalogue of workflows by epic
Each epic below has a **Temporal workflows** section with details. Summary:

| Epic | Workflows |
|---|---|
| E02 | `OrganisationClosureWorkflow` (30-day grace, export, deletion) |
| E04 | `TrialLifecycleWorkflow`, `SubscriptionDunningWorkflow` |
| E08 | `BookingHoldWorkflow`, `RescheduleRequestWorkflow`, `TimeOffApprovalWorkflow` |
| E09 | `LessonReportSlaWorkflow`, `UnconfirmedLessonWorkflow` |
| E10 | `InvoiceRunWorkflow` (scheduled), `InvoiceDunningWorkflow`, `PaymentRequestWorkflow`, `PackageExpiryWorkflow` |
| E11 | `PaymentCollectionWorkflow`, `DisputeWorkflow`, `ProviderMigrationWorkflow` |
| E12 | `PayRunWorkflow` (scheduled), `ExpenseApprovalWorkflow` |
| E13 | `BroadcastWorkflow` |
| E14 | `AutomationRunWorkflow` (the automation engine executes on Temporal) |
| E17 | `EnquiryFollowUpWorkflow`, `WaitlistOfferWorkflow`, `ProposalWorkflow` |
| E18 | `TutorApplicationWorkflow`, `ReferenceRequestWorkflow`, `TutorOnboardingWorkflow`, `ComplianceRecordWorkflow` |
| E19 | `JobOfferCascadeWorkflow`, `CoverRequestWorkflow` |
| E20 | `TermRolloverWorkflow`, `EnrolmentPaymentWorkflow` |
| E22 | `CalendarConnectionWorkflow`, `OnlineMeetingProvisioningWorkflow` |
| E23 | `AccountingSyncWorkflow`, `AccountingBackfillWorkflow` |
| E25 | `ReferralRewardWorkflow`, `ReviewRequestWorkflow` |
| E28 | `ImportWorkflow`, `MigrationProjectWorkflow`, `TenantExportWorkflow` |
| E29 | `DataSubjectRequestWorkflow`, `ErasureWorkflow`, `RetentionPurgeWorkflow` (scheduled) |

## 5. Data model
No new business tables. Optional `WorkflowLink(organisation, subject_type, subject_id, workflow_id, process, status, started_at, closed_at)`, updated by activities and completion callbacks, so the API can list a record's processes without querying Temporal for every page view.

## 6. API
- `GET /api/v1/processes?subject_type=&subject_id=` lists linked workflows with status and current step (via Query).
- `POST /api/v1/processes/{workflow_id}/cancel` (permissioned; process-specific rules).
- Process-specific signal endpoints live in their epics (e.g. `/pay-runs/{id}/approve`).

## 7. Non-functional
- Workflow start latency p95 < 200ms after commit; timer accuracy ±1 minute.
- Worker autoscaling on task-queue backlog.
- No workflow history over 10k events: long-lived processes use `continue_as_new`.

## 8. Delivery plan
- [x] **E32-T01** Temporal dev server in docker-compose and `make infra`; settings and env vars; `temporalio` dependency.
- [x] **E32-T02** Client factory, worker management command, autodiscovery of `workflows.py`/`activities.py`, Compose `temporal-worker` service.
- [x] **E32-T03** Tenancy and actor plumbing: `@tenant_activity`, input dataclass conventions, workflow ID helpers, search attributes, RLS variable.
- [x] **E32-T04** Payload encryption codec (KMS-backed; local key in dev) and staff-only codec server endpoint.
- [x] **E32-T05** Outbox → workflow bridge (start/signal mapping, finished-workflow handling, on-commit start/signal helpers).
- [x] **E32-T06** Tenant-local timer helpers (quiet hours, holidays) and settings snapshotting.
- [x] **E32-T07** Temporal Schedules management service (create/update/pause/delete per organisation).
- [x] **E32-T08** Testing harness: time-skipping fixture, activity mocks, replay tests in CI.
- [x] **E32-T09** `WorkflowLink` + processes API + record "Process timeline" UI component.
- [x] **E32-T10** OpenTelemetry/Sentry interceptors; platform-console views (list, retry, terminate with audit).
- [x] **E32-T11** Terraform: worker ECS service, Temporal Cloud namespace/certificates via secrets, alarms.
- [x] **E32-T12** Reference `DemoReminderWorkflow` with full test set; document the pattern in `docs/02-architecture.md`.

## 9. Implementation notes (as built, 2026-10-09)

Where the build differs from, or adds to, the requirements above. Later epics should treat
these as the source of truth; the coding pattern is in `docs/02-architecture.md` §9.

| Area | As built | Why |
|---|---|---|
| Layout | Runtime in `tutortrack/core/workflows/` (client, registry, `@tenant_activity`, ids, ops, bridge, codec, timers, schedules, links, worker, testing). App `tutortrack.workflows` holds the processes API, the codec endpoint, the worker command and the reference workflow. `WorkflowLink`/`ScheduleLink` live in core models (RLS) | Core infrastructure next to the outbox; the spec named both `core.workflows` and a workflows app |
| SDK / server | `temporalio` 1.34; dev server image `temporalio/temporal:1.9.1` (`start-dev`, namespace `tutortrack-local`, search attributes registered on start) in `make infra`; worker service in Compose and ECS | |
| Sync ↔ async | `core.workflows.runtime` runs one asyncio loop in a daemon thread; sync Django code calls `runtime.run(coro)`. One client per process | Services, outbox handlers, views and tests are synchronous |
| Activities | `@tenant_activity` registers on **every** task queue by default (activities run on the calling workflow's queue); `idempotency_key()` = `workflow_id/activity_id`; `publish(..., dedupe_key=)` derives the event id so retries publish once. Actor in events is `{"type": "workflow", "id": workflow_id}`; audit `request_id` carries the workflow/activity id | |
| Sandbox | Workflows run sandboxed with Django, `tutortrack`, `zoneinfo`, `sentry_sdk` passed through (imported once, outside the sandbox) | Re-importing Django per workflow is slow and breaks |
| Starts / signals | `start`/`signal` defer to `on_commit`; `start_now`/`signal_now` immediate. Reuse policy `ALLOW_DUPLICATE_FAILED_ONLY` (duplicates return `None`); signals to finished/unknown workflows return `False` | |
| Encryption (FR-32-9) | AES-256-GCM codec, keys `TEMPORAL_PAYLOAD_KEYS` (`id:base64`, newest first, rotation via key id in metadata); dev default key, required in prod. Codec server `POST /temporal-codec/{encode,decode}` for platform staff (session) with CORS for `TEMPORAL_CODEC_CORS_ORIGINS`; decodes are logged. KMS-managed keys come with E29 | |
| Timers (FR-32-6) | `wait_until_local(local_dt, BusinessCalendar, until=)`; `BusinessCalendar` (timezone, quiet hours, closed weekdays, holiday dates) is built from a `snapshot_settings` activity at start. E13 (quiet hours) and E06 (holidays) supply the settings | |
| Schedules (FR-32-7) | `schedules.ensure_schedule(process, workflow, input, cron, timezone)` + `ScheduleLink`; suspension pauses and reactivation resumes an org's schedules (outbox handlers); closure deletes them | |
| Processes API | `GET /processes` (filter by subject/process/status), `GET /processes/{workflow_id}` (refreshes status, adds the workflow's `state` query as `live`), `POST …/cancel` (only processes registered with a `cancel_permission`), `POST …/terminate` and `…/restart` (platform staff, audited with a reason; restart reuses the stored input). Process timeline UI: `apps/admin/src/components/ProcessTimeline.tsx` | |
| Observability (FR-32-10) | Sentry interceptor (activities and workflows, tagged with tenant/workflow); OpenTelemetry `TracingInterceptor` when `OTEL_EXPORTER_OTLP_ENDPOINT` is set. Platform console pages, alarms and dashboards are **E30** (API endpoints exist) | E30 owns the console |
| Testing (FR-32-11) | Fixtures `temporal_env` (time-skipping, session server, per-test workers; `env.result(id)` unlocks time skipping) and `temporal_local_env` (real dev server; Schedules are not implemented by the time-skipping server). Replay tests load `backend/tests/workflow_histories/*.json`; record with `RECORD_WORKFLOW_HISTORIES=1`. Test settings point Temporal at an unreachable address so only fixture-backed tests talk to it | |
| Infra (FR-32-1/T11) | Temporal Cloud in hosted environments (address/namespace variables; `TEMPORAL_API_KEY`, `TEMPORAL_PAYLOAD_KEYS` secrets); `temporal-worker` ECS service in the deploy action. **Not validated with `terraform validate` in this session** (no Terraform binary locally; CI has no Terraform job yet). Alarms → E30 | |
| First real workflow | **E02-TW1 `OrganisationClosureWorkflow`** (`tenancy/closure.py`): pause schedules + `organisation.export_requested` → owner notice → grace period from `privacy.closure_grace_days` (30) with `reactivate` signal (Django admin "Reopen") → delete schedules + `organisation.deletion_due` (E29 purges data) | |
| Reference workflow | `DemoReminderWorkflow` kept (the epic says remove once real workflows exist; one does now, but it remains the documented, fully tested template) | |

### Verified
- Backend: 395 tests (stable across repeated parallel runs), including workflow tests for the demo and closure workflows (happy path, signal, timer, retry with once-only publish, encrypted payloads, replay of recorded histories), Schedules against a real dev server, processes API and codec endpoint.
- Live on the local stack: `temporal_worker` polling all queues against the docker dev server; demo workflow started from Django, found by `OrganisationId`/`TutorTrackProcess` search attributes, queried, cancelled by signal; `WorkflowLink` updated.

### Carried forward
- **E29:** KMS-managed `TEMPORAL_PAYLOAD_KEYS`; consume `organisation.deletion_due` (retention purge); `privacy.*` settings area.
- **E28:** consume `organisation.export_requested`.
- **E30:** platform console (list failed/stuck processes across tenants via the platform DB alias, terminate/restart UI, deep links to the Temporal UI), alarms.
- **E13/E06:** quiet hours and holiday calendars feeding `BusinessCalendar`.
- Worker Versioning (build IDs) is configured per deployment when the first breaking workflow change ships; replay tests guard until then.

