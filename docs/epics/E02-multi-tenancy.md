# E02 — Multi-Tenancy, Organisations & Branches

| | |
|---|---|
| **Phase** | MVP |
| **Depends on** | E01 |
| **Parity** | TutorCruncher Agency→Branch model; TutorBird single business |

## 1. Summary
Implement the Organisation (tenant) and Branch hierarchy, tenant resolution (subdomain/custom domain/header), Postgres RLS, organisation-level settings, and the signup/onboarding wizard that creates a tenant.

## 2. Goals
- Strict data isolation between organisations.
- Sole traders never notice branches; agencies can run multiple branches with separate currency, timezone, branding, payment accounts and staff.
- Self-serve signup that produces a configured, usable tenant in under 5 minutes.

## 3. Functional requirements

### FR-02-1 Organisation
- Fields: name, legal name, slug (subdomain; unique, reserved words blocked), business type (`sole_trader | team | agency | centre | online`), country, default currency, default timezone, default locale, region (`uk|eu|us|au`), logo, primary colour, contact email/phone, address, company/VAT/tax numbers, fiscal year start, week start day, date/time format, status (`trial | active | past_due | suspended | cancelled`), `mode` (`solo | multi`), created_by.
- **AC:** the slug becomes `https://{slug}.tutortrack.app`; changing it keeps a 90-day redirect from the old slug.

### FR-02-2 Branch
- Every organisation has one **default branch** created at signup.
- Fields: name, code, address, timezone, currency, locale, tax settings, branding overrides, email sender identity, payment account links (E11), invoice prefix override, is_default, archived_at.
- Branch-scoped entities: Clients, Students, Tutors (many-to-many: a tutor may work for several branches), Jobs, Lessons, Invoices, Pay runs, Locations, Enquiries.
- Feature flag `multi_branch` (plan-gated in E04). When off, the branch UI is hidden and everything uses the default branch.
- **AC:** a branch-restricted admin sees only records whose `branch_id` is in their scope (lists, search, reports, exports, calendar).
- **AC:** each invoice uses its branch's currency; cross-currency totals in reports are converted using a stored daily FX rate (E26).

### FR-02-3 Tenant resolution
- Order: (1) custom domain (E24) → (2) subdomain → (3) `X-Organisation` header (API tokens, multi-org users) → (4) the user's last active org (for `app.tutortrack.app` root).
- Unknown host → 404 page; suspended org → "account suspended" page (staff can still reach billing settings).
- Middleware sets the contextvar and executes `SET LOCAL app.current_org = '<uuid>'` per transaction (via a `connection.execute_wrapper` or `ATOMIC_REQUESTS` + signal).

### FR-02-4 Row-Level Security
- Migration helper `enable_rls(table)` creates a policy `USING (organisation_id = current_setting('app.current_org', true)::uuid)`.
- The app DB role is **not** the table owner (so RLS applies); a separate migration role owns tables.
- Super-admin/platform tasks use a `bypass_rls` role on a separate DB alias, only reachable from `platform_admin` code.
- **AC:** a raw SQL `SELECT` from the app role without `app.current_org` set returns zero rows.

### FR-02-5 Organisation settings
Typed settings stored in an `OrganisationSettings` model (one row per org) plus `BranchSettings` overrides, grouped by area, each with defaults:
- General: business hours, week start, default lesson duration, terminology overrides (e.g. "Tutor"→"Teacher", "Lesson"→"Session", "Client"→"Family"), so the UI uses tenant terminology.
- Scheduling, billing, payroll, comms and portal settings are owned by their epics, but stored here via a settings registry (`settings_registry.register("billing.auto_invoice_day", type=int, default=1, scope="branch")`).
- API: `GET/PATCH /api/v1/settings/{area}` with schema-driven validation; the frontend renders settings forms from the schema.

### FR-02-6 Signup and onboarding wizard
1. Sign-up (name, email, password or Google/Microsoft SSO, business name, country) → email verification.
2. Wizard steps (skippable, progress saved):
   - Business type and size → sets `mode` and default feature flags
   - Locale, currency, timezone (pre-filled from country/browser)
   - Logo and colour
   - First service (subject, duration, price), with presets per country
   - Add tutors (invite) — agency/team only
   - Add first student/family (or import CSV → E28)
   - Connect payments (Stripe Connect onboarding → E11)
   - Choose invoicing style: *pay as you go after lessons*, *monthly in advance*, *prepaid packages*
3. A sample data option ("explore with demo data") that can be wiped with one click.
- **AC:** completing the wizard creates the org, default branch, owner membership, settings, one service and the trial subscription (E04), and emits `organisation.created`.

### FR-02-7 Multi-org users
- A user with memberships in several orgs gets an org switcher; sessions remember the last org. Each org is a separate security context; permissions never leak across orgs.

### FR-02-8 Organisation lifecycle
- Close account: owner-only, requires re-auth, offers a data export (E28), schedules deletion after a 30-day grace (E29 retention), and cancels the subscription.
- Suspension (by platform for non-payment or abuse): read-only mode banner; logins allowed for owner/admin; portals show a maintenance message.

## 4. Data model
`Organisation`, `Branch`, `OrganisationSettings (JSONB values + typed registry)`, `BranchSettings`, `OrganisationDomain (hostname, type: subdomain|custom, verified_at, ssl_status)` (custom domain logic in E24), `ReservedSlug`.

## 5. API
- `POST /api/v1/signup` (public, rate-limited, captcha-protected via Cloudflare Turnstile)
- `GET/PATCH /api/v1/organisation`
- `GET/POST /api/v1/branches`, `GET/PATCH/DELETE(archive) /api/v1/branches/{id}`
- `GET/PATCH /api/v1/settings/{area}` (+ `?branch=`)
- `GET /api/v1/me/organisations` (switcher)
- `POST /api/v1/onboarding/{step}`; `GET /api/v1/onboarding/state`

## 6. Events
`organisation.created`, `organisation.settings_updated`, `organisation.suspended`, `organisation.closed`, `branch.created`, `branch.updated`, `branch.archived`.

## 7. Permissions
`org.settings.view`, `org.settings.manage`, `org.branch.manage`, `org.close` (owner only).

## 8. Testing
- Cross-tenant isolation suite (API and raw SQL with RLS).
- Branch scoping tests on each branch-scoped list.
- Wizard E2E (Playwright): signup → first invoice-ready state.

## 9. Delivery plan
- [ ] **E02-T01** Organisation and Branch models, default branch creation, slug rules, reserved slugs.
- [ ] **E02-T02** Tenant resolution middleware (subdomain, header, last org), contextvar, `SET LOCAL app.current_org`.
- [ ] **E02-T03** RLS migration helper, DB roles, isolation test mixin (applied retro-actively to E01 models).
- [ ] **E02-T04** Branch scoping for `BranchScopedModel` and membership branch scopes (placeholder until E03 delivers memberships).
- [ ] **E02-T05** Settings registry, org and branch settings API with schema-driven validation, terminology overrides.
- [ ] **E02-T06** Signup API + email verification + Turnstile.
- [ ] **E02-T07** Onboarding wizard backend state machine + frontend wizard.
- [ ] **E02-T08** Org switcher, demo-data mode and wipe.
- [ ] **E02-T09** Org close/suspend flows.

## Temporal workflows (E32)

Implement these processes as Temporal workflows following the rules in [E32](E32-workflow-orchestration-temporal.md) (deterministic workflow code, side effects in tenant-scoped activities that call services, tenant-prefixed workflow IDs, signals for human decisions). Where the requirements above mention sweeper tasks, `next_*_at` / `resume_at` columns or retry schedules, the workflow replaces them.

- [ ] **E02-TW1** Organisation closure on Temporal (requires E32).

| Workflow | Started by | Steps, timers and signals | Replaces |
|---|---|---|---|
| `OrganisationClosureWorkflow` `org-closure:{org}` | Owner confirms close (FR-02-8) | Export data (activity) → email link → **30-day timer** → pause schedules → anonymise/delete per retention (E29). Signal `reactivate` cancels within the grace period | Scheduled deletion job |
