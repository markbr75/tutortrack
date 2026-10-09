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
- [x] **E02-T01** Organisation and Branch models, default branch creation, slug rules, reserved slugs.
- [x] **E02-T02** Tenant resolution middleware (subdomain, header, last org), contextvar, `SET LOCAL app.current_org`.
- [x] **E02-T03** RLS migration helper, DB roles, isolation test mixin (applied retro-actively to E01 models).
- [x] **E02-T04** Branch scoping for `BranchScopedModel` and membership branch scopes (placeholder until E03 delivers memberships).
- [x] **E02-T05** Settings registry, org and branch settings API with schema-driven validation, terminology overrides.
- [x] **E02-T06** Signup API + email verification + Turnstile.
- [x] **E02-T07** Onboarding wizard backend state machine + frontend wizard.
- [x] **E02-T08** Org switcher, demo-data mode and wipe.
- [x] **E02-T09** Org close/suspend flows.

## Temporal workflows (E32)

Implement these processes as Temporal workflows following the rules in [E32](E32-workflow-orchestration-temporal.md) (deterministic workflow code, side effects in tenant-scoped activities that call services, tenant-prefixed workflow IDs, signals for human decisions). Where the requirements above mention sweeper tasks, `next_*_at` / `resume_at` columns or retry schedules, the workflow replaces them.

- [ ] **E02-TW1** Organisation closure on Temporal (requires E32).

| Workflow | Started by | Steps, timers and signals | Replaces |
|---|---|---|---|
| `OrganisationClosureWorkflow` `org-closure:{org}` | Owner confirms close (FR-02-8) | Export data (activity) → email link → **30-day timer** → pause schedules → anonymise/delete per retention (E29). Signal `reactivate` cancels within the grace period | Scheduled deletion job |

## 10. Implementation notes (as built, 2026-10-09)

Where the build differs from, or adds to, the requirements above. Later epics should treat
these as the source of truth. Design rationale for RLS is in [ADR 0003](../adr/0003-postgres-rls-and-database-roles.md).

| Area | As built | Why |
|---|---|---|
| RLS session variable (FR-02-3/4) | `core.db.RLSSessionWrapper` (a `connection.execute_wrappers` entry) sets `app.current_org` and `app.current_user` with session-level `set_config` before any query whose context differs from the cached value; the cache is dropped on rollback/savepoint rollback. No `SET LOCAL` / `ATOMIC_REQUESTS` | Works in autocommit, transactions, Celery and tests with no caller discipline; one extra statement per tenant change |
| DB roles (FR-02-4) | Aliases `default` (app role `tutortrack_app`, NOBYPASSRLS, not owner), `owner` (migrations; `manage.py migrate` is overridden to use it) and `platform` (BYPASSRLS). `manage.py ensure_db_roles` creates/updates roles; grants re-run after every `migrate`. The app role has SELECT/INSERT only on `core_auditentry` | Spec; least privilege |
| Tests | The whole suite runs as the app role (conftest switches `default` after creating the test DB as owner), so every test exercises RLS. A meta-test fails if any `TenantModel` table lacks the `tenant_isolation` policy; another fails if `PLATFORM_DB_ALIAS` is used outside `platform_admin`/core | Defence in depth is only real if it is tested |
| Policies | `enable_rls(table, user_column=None, allow_null_org_writes=False)`. `identity_membership` uses `user_column` so users see their own memberships across orgs (switcher); `core_auditentry` accepts NULL-org inserts (platform events) | |
| Routing tables | `Organisation`, `OrganisationDomain`, `ReservedSlug` are not `TenantModel`s and have no RLS | Read before a tenant is known |
| Membership (E03 scope) | Minimal `identity.Membership` (single built-in `role` key, `branch_scope`, `MembershipBranch`) and `User.email_verified_at` built here; interim `identity.backends.MembershipRoleBackend` maps owner/admin/branch manager/finance to `org.*` permissions | Needed for owner at signup, header resolution, branch scoping and the switcher. **E03 extends these models and replaces the backend; do not recreate them** |
| `HasOrganisation` | Now requires an active membership (or a superuser) in the resolved organisation | FR-02-7: permissions never leak across orgs |
| Tenant resolution | `tenancy.middleware.TenantMiddleware` replaces the E01 core resolver. Former slugs redirect with **308** (keeps method/body). `X-Organisation` accepts id or slug, members only, and is ignored on tenant subdomains; unknown → 404 problem. Header resolution for API tokens lands with E27 | |
| Suspension/closure | `OrganisationStatusMiddleware`: closed → 410 `organisation-closed`; suspended → owners/admins read-only (423 `organisation-read-only`) except `SUSPENDED_ORG_WRITE_ALLOWLIST` (E04 adds its billing paths), everyone else 403 `organisation-suspended`. Platform staff and auth paths exempt | |
| Org close (FR-02-8) | Records the decision (status `cancelled`, `closed_at`) and publishes `organisation.closed`. Export, 30-day grace, reactivation and deletion are **E02-TW1** (Temporal, with E32); subscription cancel is E04's handler | Per E32: no deletion column + sweeper |
| Settings (FR-02-5) | Registry in `tenancy.settings_registry`; apps register in `<app>/org_settings.py` (autodiscovered). Types: int/str/bool/choice/object (object = validator + JSON-schema fragment). Only explicitly set values are stored | No data migrations for new settings |
| Settings registered by E02 | `general.business_hours` (branch), `general.default_lesson_duration` (branch), `general.terminology` (tutor/student/client/lesson/job), `billing.invoicing_style` (set by the wizard; **E10 takes ownership**) | |
| Signup (FR-02-6) | Existing email → 422 with an explicit "sign in instead" (rate limit + Turnstile limit enumeration). Signed-in users can create further orgs without credentials. Turnstile fails closed and is mandatory in prod. Password strength = Django validators (zxcvbn/HIBP in E03) | UX for a self-serve SaaS |
| Session handoff | After signup the user continues at `continue_url` on their subdomain; a 2-minute, single-use, org-bound signed token is exchanged at `POST /auth/handoff` for a session. Prod also sets `SESSION_COOKIE_DOMAIN` (`.tutortrack.app`) | Cookies can't be shared across hosts in dev or on custom domains (E24) |
| Verification email | Celery task with a plain-text template; link to `APP_URL/verify-email` | E13 moves it onto comms templates |
| Onboarding (FR-02-6) | Steps business, locale, branding, service, tutors (teams/agencies only), students, payments, invoicing. Tenancy applies what it owns (profile, branding, `multi_branch` override for agencies/centres, invoicing style); every step publishes `onboarding.step_completed` with its answers. **E06 creates the first service, E03 sends tutor invites, E05 creates the first student/family, E11 starts Stripe onboarding, E04 starts the trial** from these/`organisation.created` events | Owning epics don't exist yet |
| Demo data | Mechanism only: apps add providers in `<app>/demo.py` and track created records (`DemoRecord`); `POST/DELETE /demo-data`. E02 contributes no sample records; E05+ add them | Sample content belongs to the domain epics |
| Branch scoping (FR-02-2) | `core.models.BranchScopedModel` (branch defaults to the default branch; manager filters by `current_branch_ids()`; out-of-scope writes raise `CrossBranchWrite` 403). Branch-scoped domain models arrive with E05+ | |
| New events | `organisation.updated`, `organisation.reactivated`, `onboarding.step_completed`, `onboarding.completed` (added to the catalogue) | |
| Frontend | Admin app: `/signup`, `/verify-email`, `/onboarding` (public routes; onboarding performs the handoff), `/settings` (profile, general + terminology, branches when `multi_branch`, demo-data wipe, close account), org switcher and suspended banner in the shell. `ui` gained `TextField`, `SelectField`, `Alert` | |

### Verified
- Backend: 273 tests (suite runs under RLS as the app role), 94% coverage; ruff, mypy, migrations check, `check --deploy`, OpenAPI schema with zero warnings.
- Frontend: lint, typecheck, 19 unit tests, production builds for all packages.
- Live smoke on the local stack: signup → handoff on the new subdomain → onboarding step → settings → switcher; unknown subdomain 404; replayed handoff rejected.

### Carried forward
- **E03:** extend `Membership` (roles, invitations), replace `MembershipRoleBackend`, real login screen (the shell still uses the Django-admin sign-in), zxcvbn/HIBP, handle `onboarding.step_completed` (tutors) to send invites.
- **E04:** start trial on `organisation.created`; plan-gate `multi_branch`; add billing paths to `SUSPENDED_ORG_WRITE_ALLOWLIST`; call `lifecycle.suspend_organisation`/`reactivate_organisation` on dunning.
- **E05/E06/E11:** consume onboarding answers (first student, first service, Stripe); add demo providers.
- **E24:** custom-domain verification/TLS on `OrganisationDomain`; dynamic CSRF origins.
- **E32:** `OrganisationClosureWorkflow` (E02-TW1).
- **Infra:** confirm RDS lets the master user create a BYPASSRLS role (see `infra/terraform/README.md`).
- Not built: Playwright wizard E2E (§8) — the e2e job needs the signup flow plus E03 login; add with E03-T13.
