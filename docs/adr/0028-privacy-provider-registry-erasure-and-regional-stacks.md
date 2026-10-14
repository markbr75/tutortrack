# ADR 0028: Privacy provider registry for DSARs, erasure and retention; safeguarding on seams; regional stacks

- **Status:** Accepted
- **Date:** 2026-10-14
- **Epic:** E29 Part 2 (T05–T12, TW1). Builds on ADR 0002 (Temporal), ADR 0003 (database
  roles and RLS) and the E29 Part 1 consent and encryption work.

## Context
Part 2 must find, export, erase and expire *every* piece of a person's data in a codebase of
about 30 apps, and keep doing so as new apps arrive. The rules that had to hold:
- An app writes only its own tables (CLAUDE.md rule 2); the privacy app cannot reach into
  billing or learning models.
- Financial records are never deleted or edited after issue (rule 5), yet the epic's
  acceptance criterion asks for anonymised invoice lines.
- The audit table is append-only (core migration 0002) and the application role cannot delete
  from it.
- Safeguarding data must reach only Designated Safeguarding Leads (DSLs), be encrypted and be
  audited separately.
- Messaging safeguards must hook the comms pipeline while E13 is being extended in parallel.
- Data residency: one stack per region, no cross-region replication.

## Decision

### 1. A provider registry (`tutortrack/privacy/registry.py`)
Each app with personal data ships `<app>/privacy.py` registering a `Provider` (autodiscovered by
`privacy.apps.ready` with `autodiscover_modules("privacy")`):
- `expand(person)` adds related subjects and the names/emails/phones used to find and scrub
  free text (a client covers its contacts and students; a contact, student or tutor covers
  their login; a login covers the records it belongs to). Resolution repeats until nothing
  changes. `person.context` holds records whose legal holds apply but that are not erased
  (a student's household).
- `export(person) -> [Section]`, `files(person) -> [StoredFile]` for the DSAR export.
- `erase(person, ctx) -> ErasureOutcome` (anonymised / deleted / retained counts, released
  file ids, notes). Providers update their own rows with queryset `update()`.
- `revoke(person)` ends memberships, iCal feeds, API keys and app grants.
- `RetentionCategory(find=…)` (people to erase) or `RetentionCategory(purge=…)` (records to
  delete or clear) with a default period.

Providers ship for people, crm, identity, comms, billing, payments, payroll, scheduling,
delivery, learning, courses, leads, recruitment, growth, calendar_sync, migration, sites,
developer and privacy itself. A new app adds one module; nothing in privacy changes.

### 2. Erasure is planned once, then runs in idempotent steps
`ErasureRecord` stores the resolved subjects, a token label per erased record ("Erased Student
#12", a per-organisation sequence), the encrypted scrub terms (cleared when done) and per-step
results. Steps: legal-hold check → each provider → delete files (object removed, `StoredFile`
blanked so foreign keys stay valid) → revoke logins → audit summary + `data_subject.erased`.
`ErasureWorkflow` runs one activity per step; `erase_now` runs them inline (retention purges).

### 3. Financial records: anonymise the personal parts, keep the rest
Amounts, dates, numbers and references never change and rows are never deleted. On erasure:
student and tutor names on invoice lines become the token label and are scrubbed from
descriptions (the epic's acceptance criterion). The bill payer's name, contact, email and
address on an invoice (`billing_snapshot`) are a legal requirement, so they stay for
`privacy.financial_retention_years` (6 by default) from the erasure; invoices already older
than that are anonymised straight away, and the `erased_financial` retention category
anonymises the rest when the period ends. This is the one sanctioned edit of issued financial
records, made through the billing app's own provider.

### 4. Audit log retention uses the platform connection
The append-only trigger allows deletes only with `SET LOCAL tutortrack.audit_purge = 'on'`, and
the application role has no DELETE grant on `core_auditentry`. The `audit_logs` purge (7 years
minimum) therefore runs on the platform (BYPASSRLS) connection, limited by an explicit
`organisation_id` filter; `privacy/retention.py` is added to the platform-alias allowlist test.
Audit entries are otherwise kept through erasure (they are the legal record).

### 5. Workflows (E29-TW1, task queue `privacy`)
- `DataSubjectRequestWorkflow` `dsar:{org}:{request}`: reminders 7 days, 2 days and at the
  deadline are chosen by the workflow clock and sent once each (stale stages are skipped);
  waits for `identity_verified`; compiles; waits for `redaction_approved` or `erasure_approved`;
  delivers an expiring link (timer) or runs `ErasureWorkflow` as a child. Staff decisions are
  services that signal it; it also re-reads the request so a decision made before the signal
  arrives is not lost.
- `RetentionPurgeWorkflow`: a per-organisation Temporal Schedule (02:00 local) while
  `privacy.retention_purge` is `dry_run` or `on`, or started for a manual run.
- `LoneWorkingWorkflow` `lone-working:{org}:{visit}`: the overdue alert and escalation timers
  (not in the epic's table, but a timer process, so Temporal per rule 4a).

### 6. Safeguarding on seams
- Concerns, actions and flags are encrypted (`EncryptedField`), visible only with
  `safeguarding.dsl` (the owner by default; others through a custom role; admins and branch
  managers are denied it), every DSL read is `audit.record_read`, and a new
  `core.audit.RESTRICTED_OBJECT_TYPES` registry hides `privacy.safeguarding*` entries from the
  general audit search for non-DSLs. Alerts carry only the reference and category.
- **Messaging:** `comms/hooks.py` is a pre-send hook registry called from `comms.services._create`
  (one call; the parallel inbox/broadcast work calls `run_pre_send` for messages people write,
  passing `sender_user_id` and the thread `participants`). Privacy registers `check_outgoing`:
  no marketing to under-18s, no direct tutor-to-child messages, a parent on child threads,
  contact-detail blocking (configurable) and keyword flags for DSL review. Text that is already
  shared (lesson report comments) is screened from the `lesson_report.commented` event and
  flagged, never blocked.

### 7. Children's privacy
COPPA (automatic for US organisations, configurable): `people.services.invite_to_portal` calls
`privacy.children.require_login_allowed`, which needs a `parental-consent` consent record for
under-13s (unknown date of birth counts as under 13). AADC defaults: marketing consent cannot be
granted for under-18s and marketing-category messages to them are blocked.

### 8. Regional stacks
`REGIONS` (name and signup app URL per region) and `TT_REGION` (the region this stack serves;
empty = one stack serves all, used in development and tests) live in settings.
`tenancy.regions.require_served` refuses signup on the wrong stack with HTTP 409
`wrong-region` and the regional signup URL (built from settings, never from the request);
`GET /api/v1/signup/region?country=` lets the signup page send people there first.
`Organisation.region` already existed (E02) and is set from the country.

**Deployment (no infrastructure in this epic):** one Terraform workspace per region
(`uk` eu-west-2, `eu` eu-central-1, `us` us-east-1, `au` ap-southeast-2), each with its own RDS,
ElastiCache, S3 bucket, KMS key, ECS services, Temporal Cloud namespace and Sentry project, and
`TT_REGION` set. DNS: `app.tutortrack.app` (UK) and `{eu,us,au}.tutortrack.app`; tenant
subdomains resolve to their region's load balancer through per-region wildcard records
(`*.eu.tutortrack.app`, …) or, for custom domains, the region's Caddy fleet. No database,
bucket or queue is shared or replicated across regions; platform-level reporting reads each
region separately. Moving an organisation between regions is an export/import (E28), not
replication.

### 9. DPA and sub-processors
The DPA version and the sub-processor list are versioned in code (`privacy/compliance.py`);
acceptances are `DPAAcceptance` rows (owner-only `privacy.dpa.manage`); change notices are sent
once per version per organisation by a Celery fan-out (`manage.py notify_subprocessor_changes`).

## Consequences
- Every new app with personal data must add a `privacy.py` provider (and a retention category if
  it holds time-bound data); the registry test lists the expected providers.
- Erasure leaves an anonymised skeleton (rows, ids, amounts, token labels) so reports, ledgers
  and audit trails still add up.
- A global `User` login is not deleted by one organisation's erasure (it may belong to others);
  the membership ends and account deletion stays a platform feature (E30).
- Safeguarding cases are retained, not erased; DSAR exports exclude them (DSL decision under
  the safeguarding exemptions).
- Webhook delivery payloads and the outbox keep event data until their own clean-up; events
  from privacy carry ids only.
