# ADR 0036: Sample data side effects, Apple sign-in, portal households and click-to-sign

- **Status:** Accepted
- **Date:** 2026-10-14
- **Epics:** E02 (FR-02-6), E03 (FR-03-2, FR-03-9), E05 (FR-05-9), E15 (FR-15-1, FR-15-8),
  E18 (FR-18-5), E27 (FR-27-6); gap batch G2. Builds on ADR 0003 (database roles and RLS),
  ADR 0028 (privacy provider registry) and ADR 0035 (merge provider registry).

## Context
Gap batch G2 covers seven deferred items. Four needed design decisions:
1. "Explore with demo data" and E27 sandboxes had a mechanism (`tenancy/demo.py`) but no
   sample records. Real services write many side rows (ledger entries, charges, pay items,
   report facts, sequences, audit) and publish events that start Temporal processes, send
   messages, sync to accounting systems and call webhooks. Sample data must be coherent, but
   it must not reach the outside world, and clearing it must leave nothing behind and not
   touch real data. Invoice and credit-note numbers are gap-free (rule 5).
2. Apple sign-in differs from Google and Microsoft: a signed JWT client secret, and a
   `form_post` callback (a cross-site POST) when name and email are requested.
3. Under-13 students need logins without email (FR-15-1), within E29's COPPA rule (parental
   consent before a child gets a login).
4. FR-05-9/FR-15-8/FR-18-5 ask for e-signing "with audit"; E18 had shipped a recorded
   "I agree".

## Decision

### 1. Sample data: auto-tracked rows, contained side effects
- **Tracking.** While a provider runs, a `post_save` receiver records every new tenant row
  (`TenantModel`) in `DemoRecord`, not just the ones the provider returns. Rows created with
  `bulk_create` (lesson series, class sessions) are tracked explicitly by the provider.
- **Containment (`core.demo_mode`).** Each provider runs in a savepoint with demo mode on:
  `core.sequences.next_number` uses a separate `demo:<key>` counter with a `DEMO-` prefix,
  so clearing never leaves gaps in real numbering; `comms.notify` sends nothing; after-commit
  callbacks registered by the provider (workflow starts, emails, receipts, outbox kicks) are
  dropped. Domain events are still written to the outbox, run **inline** through the
  in-product projection subscribers only (`billing`, `payroll`, `reporting` handlers: charges
  from completed lessons, pay items, report facts) and then marked dispatched, so no other
  subscriber (automations, notifications, accounting, calendar sync, webhooks, Temporal
  bridges) ever sees them.
- **Clearing.** Tracked rows are deleted newest first with their cascades, in repeated
  passes (a row may only become deletable once a later one has gone). Querysets are used, so
  model-level "never delete" guards on financial rows don't apply to sample data. A sample
  row that real data now references (PROTECT) is kept and stays marked as demo data.
- A test asserts that after load and clear **every tenant table** has its earlier row count.

### 2. Apple on the existing OIDC code (no allauth)
`identity/sso.py` gains per-provider `scope`, `response_mode` and `pkce`. Apple uses
`openid name email`, `form_post` and no PKCE; its client secret is a 5-minute ES256 JWT
signed with the `.p8` key (`APPLE_TEAM_ID`, `APPLE_KEY_ID`, `APPLE_PRIVATE_KEY`,
`APPLE_CLIENT_ID`). The callback view accepts POST for `form_post` providers with no session
authentication (the request is a cross-site POST from Apple); the state cookie is
`SameSite=None` on https for those providers. The state, nonce, signature, issuer and
audience checks are unchanged. The name is read once from the posted `user` field.

### 3. Change email by signed link
A signed token bound to the user, the old and the new address (24 hours): changing the email
invalidates it, so it is single-use without a table. The link goes to the new address, a
notice to the old one (on request and on change); confirming revokes every other session.

### 4. Portal households and managed logins
- The household switcher stores the chosen client in the session; `household_for(user,
  selected)` narrows to it. Other callers (video, learning files) still see the whole
  household, which only widens access checks to records the person may see anyway.
- Guardian invitations reuse E03 invitations (target `people.contact`, role client) but are
  delivered through a comms notification type (`identity.services.invite(deliver=...)`).
- Managed logins are ordinary `User`s with an undeliverable placeholder address
  (`<username>.<org>@managed-students.invalid`) plus `portal.StudentLogin` (username unique
  per organisation). They sign in only with `POST /auth/student-login` on the
  organisation's host, which reuses the password lockout keyed on the placeholder address.
  PINs bypass the password strength rules (a 6-digit PIN can't meet them); repeated and
  sequential digits are refused, and the lockout limits guessing. The guardian's tick is
  recorded as the E29 `parental-consent` record when none exists, and
  `privacy.children.require_login_allowed` still gates the login.

### 5. Built-in click-to-sign
`crm.Signature` stores the evidence (signer login, typed name, email, role, time, IP, user
agent, statement, SHA-256 of the exact bytes or text signed) and a signed PDF copy rendered
by WeasyPrint: a signature page with the audit trail, the agreement text above it, and the
original file **embedded as a PDF attachment**. Documents carry `signature_required` and
`signed_at`; onboarding agreement items with `"sign": true` are signed rather than ticked.
No external provider (DocuSign/Dropbox Sign) and no new dependency.

## Consequences
- Sample data looks real inside the product (lessons, reports, invoices, payments, reports
  pages) but triggers no reminders, chasers, messages, integrations or workflows. Anything
  that relies on those for sample records must be demonstrated with real records.
- New apps get their side rows cleared automatically; only `bulk_create` needs care.
- Apple sign-in needs an https `APP_URL` (Apple doesn't allow http callbacks).
- Signed copies don't merge the original's pages into one document; the original is inside
  the PDF and its hash is printed on the signature page. A PDF library could replace the
  attachment later without changing the evidence model.
- Managed student logins can't use magic links, passkeys or password reset by email; the
  guardian resets the PIN.
