# ADR 0032: Phase 3 provider integrations (Wise, background checks, video, ledgers, Xero Payroll), native shells and the warehouse export

- **Status:** Accepted
- **Date:** 2026-10-14
- **Epics:** E12-T12, E16-T11, E18-T11, E22-T10, E23-T10, E26-T09. Builds on ADR 0002
  (Temporal), ADR 0003 (database roles and RLS), ADR 0011 (payroll), ADR 0012 (compliance),
  ADR 0015 (integration framework), ADR 0016 (reporting), ADR 0018 (accounting) and ADR 0028
  (privacy provider registry).

## Context
The last deferred tickets all talk to outside services: Wise for payouts, uCheck, the DBS
Update Service and Checkr for background checks, Zoom, Lessonspace and Daily for attendance
and recordings, Sage and FreeAgent ledgers, Xero Payroll, and customer warehouses (S3,
BigQuery, Snowflake). They also add the most sensitive data in the product so far:
taxpayer ids, background check results and lesson recordings. The constraints:
- No real network calls in tests; every outbound call through `core.net.safe_urlopen`.
- Inbound webhooks arrive on the platform host before any tenant is known, and must be
  verified before they change anything.
- Long-running and timer-based processes run on Temporal, never `next_*_at` plus a sweeper.
- Credentials and tokens are encrypted; reads of sensitive data are audited; personal data
  is covered by the E29 privacy registry, retention and the sub-processor list.
- Money is `Decimal`, rounded half-up at line level; financial records are immutable.
- Another branch is building accounting read-back and the report builder at the same time.

## Decision

### 1. Every provider behind an interface with a fake
- Wise (`payroll/payouts/wise.py` + `wise_fake.py`), background checks
  (`recruitment/checks/`: `CheckClient` with uCheck, DBS Update Service, Checkr and a manual
  WWCC provider), recordings (`list_recordings`/`delete_recording` added to the meeting
  clients and their fake), Sage and FreeAgent (`AccountingClient`), Xero Payroll
  (`PayrollClient`) and warehouse destinations (`Destination`).
- Fakes are chosen the same way as before: credential providers (Wise, uCheck, Checkr) by
  `INTEGRATIONS_CREDENTIAL_PROVIDERS_LIVE`; OAuth providers (Sage, FreeAgent, Xero Payroll)
  by their platform keys; warehouse destinations by `WAREHOUSE_EXPORT_LIVE`. Development and
  tests use fakes; production uses the real clients.
- Real clients pass `user_url=True` to the provider HTTP helper, so every call goes through
  `core.net.safe_urlopen`. They are tested against request shapes.
- Tenant credentials (Wise token, uCheck/Checkr keys) are integration connections with the
  secret in an `EncryptedField`; warehouse credentials are an encrypted JSON field,
  write-only in the API.

### 2. Webhook routing and verification
- A small platform table `integrations.WebhookRoute(provider, external_id, organisation)`
  (ids only, no RLS, like `payments.AccountRoute`) routes Zoom meeting ids, Wise transfer
  ids and Checkr candidate ids to their organisation.
- Each webhook is verified with the provider's own scheme before it changes anything: Zoom
  `v0=` HMAC with the app's secret and a 5-minute timestamp window (plus the URL
  validation challenge); Wise RSA-SHA256 with Wise's public key; Checkr HMAC keyed with the
  organisation's API key (looked up after routing, before acting). Lessonspace takes a
  per-lesson webhook URL, so the URL carries an HMAC token naming the organisation and lesson
  (`integrations.routes.callback_token`), checked before any lookup.
- Webhooks only record facts and signal workflows; polling remains the fallback.

### 3. Temporal for every wait
- Wise settlement reuses `PayRunWorkflow`'s daily settle check: the `payouts_outstanding`
  activity now also polls Wise. The workflow code is unchanged, so recorded histories still
  replay; a Wise history was added.
- `BackgroundCheckWorkflow` (initiate → webhook signal or provider polling interval →
  invitation expiry → DBS Update Service re-checks on a timer), `RecordingFetchWorkflow`
  (15 minutes, 1, 6 and 24 hours after the lesson, stopped early by the Zoom webhook),
  `XeroPayrollSyncWorkflow` (retried idempotent sync per pay run) and
  `WarehouseExportWorkflow` (one retried activity per dataset) all have happy-path, failure
  and replay tests with recorded histories. Warehouse exports run on per-destination Temporal
  Schedules, synced from domain events like scheduled reports.

### 4. Sensitive data
- Taxpayer ids: encrypted on the pay profile with only the type and last four digits in
  clear; the full number needs `payroll.tax.view` and each read is audited. Filed 1099 rows
  keep only the last four digits and are immutable (corrections supersede).
- Background checks: invitation links, results, certificate numbers and report links are
  encrypted; reading them needs `compliance.checks.results` and is audited; events carry
  ids and outcomes only; a retention category purges details after 183 days; erasure keeps
  the fact of the check as evidence.
- Recordings: references only, never copies; encrypted links; playback is access-checked and
  audited; recordings of lessons without every student's `lesson-recording` consent are
  restricted until released; the existing `recordings` retention category deletes them at the
  provider, and join/leave logs have their own category.
- New personal data is in privacy providers; new processors are optional sub-processors
  (`SUBPROCESSORS_VERSION` 2026-10-14.2).

### 5. Money
- Commission pay is `percent × collected net revenue`, where collected = charge net × paid
  share of its invoice, rounded half-up once. Locked pay items never change: differences
  (including refunds) become adjustments. Hypothesis tests cover the maths.
- 1099 box 1 is computed on a cash basis from paid payouts; reimbursements are excluded.
- Wise amounts are sent as decimal strings.

### 6. Native shells without native toolchains in CI
- `frontend/apps/mobile` is a Capacitor project outside the pnpm workspace. It loads the
  hosted portal (white-label: the organisation's portal; generic: a bundled organisation
  picker) so authentication, tenancy by host and the service worker behave as in the PWA.
- White-label configuration comes from the E24 brand kit (`mobile_app_config`,
  `GET /public/mobile-app`), gated by `white_label`.
- The build is a manual-only GitHub Actions workflow; signing secrets are documented, not
  configured. Normal CI never installs Capacitor, Android or Xcode tooling.

### 7. Warehouse export format
- Gzipped CSV with a JSON manifest of documented schemas, incremental on `updated_at` with a
  weekly full refresh, instead of Parquet: Parquet needs pyarrow (about 40 MB) in the
  backend image. BigQuery and Snowflake receive the same rows directly.
- Gated by a new Enterprise plan feature `warehouse_export`.

### 8. Additive changes next to a parallel branch
- Accounting and reporting additions live in new modules (`accounting/payroll_sync.py`,
  `payroll_processes.py`, `api/payroll_views.py`, `providers/sage.py`, `freeagent.py`,
  `xero_payroll.py`; `reporting/warehouse/` with its own models module and URL include).
  i18n keys are in new namespaces (`payrollPhase3`, `backgroundChecks`, `videoLessons`,
  `classroom`, `accountingPhase3`, `warehouse`).

## Consequences
- Real provider behaviour is only proven against request shapes until credentials exist;
  uCheck endpoint shapes and Lessonspace webhook payloads need confirming with the providers.
- Existing Zoom connections must reconnect to grant recording scopes.
- Migrations: `integrations/0002`, `payroll/0002`, `recruitment/0002`, `calendar_sync/0002`,
  `accounting/0002`, `reporting/0002`, `subscriptions/0004`. A parallel branch that also adds
  `accounting/0002` or `reporting/0002` needs a merge migration.
- Native push for the shells, Parquet output, Teams/Meet attendance and IRS e-filing remain
  follow-ups.
