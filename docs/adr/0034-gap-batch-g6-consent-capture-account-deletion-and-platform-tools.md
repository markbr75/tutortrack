# ADR 0034: Gap batch G6 — consent capture, terms, account deletion, platform tools, add-ons and the blog

- **Status:** Accepted
- **Date:** 2026-10-14
- **Scope:** `docs/05-gap-backlog.md` batch G6 (E04, E24, E27–E30, E32). Builds on ADR 0003
  (database roles and RLS), ADR 0009 (subscriptions), ADR 0028 (privacy registry, erasure,
  retention), ADR 0030 (platform insights) and the E27 public API decisions.

## Context
Every ticket of E04, E24 and E27–E32 is ticked, but their notes deferred fourteen pieces of
spec: consent ticked outside the privacy screens was not recorded, the platform's own
terms were not accepted at signup, a person could not delete their login, platform staff
had no breach-notice tool, no workflow console and no plans screen, several post-E27 event
types and resources were missing from the public API, imports skipped TutorCruncher agents,
reviews, proformas and charges, add-ons were sold only by hand, and the website had no blog.
The constraints are the usual ones: tenant data under RLS, cross-tenant reads only in
`platform_admin` through the BYPASSRLS alias, services own writes and audit, events through
the outbox, Temporal for long processes, money in `Decimal`, and no new dependencies.

## Decision

### 1. One capture helper for consent (`privacy.capture.record_ticked`)
Public forms, class enrolment, the review page, the lesson-feedback page and imports call
one helper with the people a submission created and the consent keys that were ticked. Each
key is recorded for every person it applies to (`ConsentType.applies_to`: photo consent for
the children, given by the parent "on behalf of a child"). `ConsentRecord.source` (new)
says where the tick came from (`form:<slug>`, `enrolment:<class>`, `review:<request>`,
`lesson-feedback:<id>`, `import:<system>:<batch>`). Capture never blocks the submission:
unknown keys and consents the rules refuse (AADC) are skipped and logged. Imports skip a
record when the latest one already says the same, so re-running a file adds no evidence,
and rolling an import back deletes only its own (`method=import`) records. New default
types `review-publication` and `lesson-feedback` are created on first use.

### 2. Platform terms are global evidence, separate from tenant consent
`privacy.TermsAcceptance` (not a tenant table) records user, terms and privacy-notice
versions, time, IP, browser and the organisation created. The signup API requires
`accept_terms`; versions and URLs live in `privacy.compliance` and come back from
`/signup/config`. Tenant consent types stay per organisation.

### 3. Account deletion: erase per organisation, anonymise the login
A person deletes their whole login from their account page (password, or their email typed
when they have none). Safeguards: the last active owner of an open organisation and
platform staff are refused, with the reasons listed before anything changes. In each
organisation, inside its tenant context, the membership ends and then the E29 erasure runs
at once (`privacy.account_deletion = erase`, the default) or an erasure request is logged
for staff (`review`); a legal hold always turns the erasure into a request. The `User` row
is anonymised, not deleted, so organisations' foreign keys stay valid; sessions, MFA,
passkeys, linked SSO accounts, sign-in links and login history are deleted. An
`AccountDeletion` row keeps only an email hash. `user.account_deleted` is a platform event.

### 4. Retention for data no organisation owns alone
Dispatched outbox events are a normal per-organisation retention category
(`dispatched_events`, 90 days; pending and dead-lettered events are kept). Login history
(one table for all organisations) and organisation-less events have platform settings
(`LOGIN_HISTORY_RETENTION_DAYS` 400, `OUTBOX_RETENTION_DAYS` 90) and a short, batched Celery
beat task, like the existing webhook-log purge.

### 5. Impossible travel from CDN headers
The sign-in country comes from a configurable CDN header (`GEOIP_COUNTRY_HEADER`, default
`CF-IPCountry`) or an optional lookup class (`GEOIP_LOOKUP`); unknown/Tor codes are
ignored. A successful sign-in from another country within `IMPOSSIBLE_TRAVEL_HOURS` (2) of
the previous one emails the person and raises `security.alert` (kind `impossible_travel`)
in each organisation where they are staff, so owners are emailed by the existing handler.
Countries can't measure distance, so the rule is "another country, too soon"; the alert
blocks nothing, so VPN false positives are acceptable.

### 6. Platform tools run in each tenant's context and audit there
- **Notify customers:** `CustomerNotice` (platform table) with templates (breach — the
  72-hour tenant notice — security, service, legal), preview, a required reason and a
  once-only send that fans out one Celery task per organisation. Each task notifies owners
  and admins through a hidden, transactional comms type and writes the organisation's
  audit log with the staff member as actor.
- **Workflow console:** failed, timed-out, terminated and stuck (`running` with an error or
  no progress for 14 days) `WorkflowLink`s across tenants via the platform alias, with
  Temporal UI deep links (`TEMPORAL_UI_URL`). Terminate, reset (Temporal reset to the last
  completed workflow task) and retry (start again with the stored ids-only input) run in
  the process's organisation and are audited with the reason.
- **Revenue share:** the nightly snapshot adds `revenue_share_mrr` = share × metered
  payments of the last 30 days (rounded half-up, Hypothesis-tested) into MRR.
  Reconciliation recomputes processed payments per day for a month and compares them with
  the meter reports; unreported days can be reported from the console. Negative
  differences (refunds after reporting) are shown, not sent, because meter events can't be
  negative.
- Tenant list: MRR filter and sort from the latest snapshot; tenant detail: integration
  connections (status, last sync, failed accounting syncs; no secrets) and active add-ons.
- Support replies notify the person who opened the conversation by in-app, email and Web
  Push (hidden, transactional `support_reply`), with a link that opens the chat.

### 7. Public API and webhooks
New aggregates are offered as webhook types, with each type's payload fields in the event
type listing and samples. `NEVER_AGGREGATES` lists what must never be offered (safeguarding,
privacy casework, security, the platform relationship, AI internals), and `IDS_ONLY`
events (background checks, inbox messages, threads, recordings) carry only allowed fields
and no record representation, so background-check results, safeguarding flags, message
contents and recording links never leave. Reviews (`reviews` scope) and form submissions
(`enquiries` scope, read-only, without IP or browser) are public resources.

### 8. Add-ons are Stripe subscription items
Custom domain, white-label apps and priority support (a new feature, included in
Enterprise) have prices per currency (`AddonPrice`, annual = 10 × monthly). Buying adds a
prorated item to the Stripe subscription and an active `SubscriptionAddon` (RLS) that
grants the feature in the entitlement snapshot (overrides still apply on top). `items_for`
keeps active add-ons on plan changes; an add-on removed in Stripe's portal ends when the
subscription update arrives. Buying needs a paid subscription (trials go to checkout).

### 9. Blog posts are their own records, not site pages
`BlogPost` (RLS) has a plain-text body (paragraphs, escaped), a summary, cover image,
author, SEO fields and draft/published with an optional future date. The site serves
`/blog` (paginated), `/blog/<slug>` (`og:type=article`, `BlogPosting` JSON-LD) and
`/blog/rss.xml`; published posts join the sitemap and their cover images become public
assets. A `blog_list` block shows the latest posts on any page; `blog` is a reserved page
address. Posts don't need versions: publishing is a status, and the page cache revision is
bumped as for pages.

### 10. Imports reach E25 and E10 through their services
New importers: affiliates (with a percentage rule and the clients they introduced),
reviews (source `import`, published ones approved, nothing sent), ad hoc charges (dated on
or after the cutover; earlier ones are in the invoice history) and payment requests (unpaid
proformas). A migration project gains a "growth" step after balances. Teachworks wage tiers
become E06 pay tiers: tutors are put on their tier from the cutover date and each tier's
wage is set as the tier rate on every imported service. Rollback removes what nobody has
used since (voids charges, cancels requests, keeps affiliates with commission).

## Consequences
- Signup clients must send `accept_terms: true` (the admin signup page has the checkbox).
- Consent evidence now exists for public submissions; the privacy centre and DSAR exports
  show it without changes. Forms choose what a consent field records (`consent_key`).
- Deleting an account can erase a tutor's or parent's records in an organisation without
  staff review unless the organisation chooses `review`; financial records are kept
  anonymised as for any E29 erasure.
- Webhook consumers see new event types only when they subscribe to them; `IDS_ONLY` is the
  place to add any future sensitive aggregate.
- Revenue-share MRR fluctuates with payments, so MRR movements include it.
- New settings: `GEOIP_COUNTRY_HEADER`, `GEOIP_LOOKUP`, `IMPOSSIBLE_TRAVEL_HOURS`,
  `LOGIN_HISTORY_RETENTION_DAYS`, `OUTBOX_RETENTION_DAYS`, `TEMPORAL_UI_URL`.
