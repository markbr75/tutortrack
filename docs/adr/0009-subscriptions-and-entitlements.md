# ADR 0009: Plan entitlements behind a core hook, a code-defined catalogue and Stripe Billing

- **Status:** Accepted
- **Date:** 2026-10-10
- **Epic:** E04

## Context
Every app (people, tenancy, storage, and later payroll, recruitment, automation...) must
refuse work its plan doesn't include, without depending on the subscriptions app. Plans
are "stored in the database and managed by platform admin", but the same plans must exist
in every environment and in tests. Our own billing runs on Stripe Billing on the platform
account, separate from tenants' Stripe Connect accounts (E11). Billing state has to drive the
organisation's status (trial, past due, read-only), which already gates requests in
`OrganisationStatusMiddleware`.

## Decision
1. **`core.entitlements`** exposes `has`, `limit`, `require` and `require_capacity`
   and raises `UpgradeRequired` (403 `upgrade-required` with `feature` or `limit`, plus
   `allowed`, `used` and `required_plan`). It delegates to a resolver that the
   subscriptions app registers at start-up. Until then, and for organisations with no
   subscription (internal, created before E04), nothing is limited.
2. **Resolution:** an unexpired `EntitlementOverride` (platform admin) beats the plan.
   While trialing, the trial plan (`SUBSCRIPTIONS["TRIAL_PLAN"]`, Agency) applies instead
   of the chosen plan. Snapshots are cached per organisation; any change to the
   subscription or its overrides bumps a version key, so an upgrade applies on the next
   request. `core.flags` uses the same resolver to target feature flags at plans
   (`FeatureFlag.plan_keys`).
3. **Catalogue in code, synced to the database.** `subscriptions/catalogue.py` defines the
   plans, prices (six currencies; annual = 10 × monthly) and entitlements. A data
   migration and `manage.py sync_plans` write it, idempotently. `sync_plans --stripe`
   creates the Stripe products, prices (by lookup key) and the revenue-share meter. The
   platform console (E30) can edit the rows; the catalogue remains the source for new
   environments.
4. **A billing gateway interface** with `StripeGateway` (Checkout, the customer portal,
   Stripe Tax, subscription schedules for period-end downgrades, Billing Meters) and an
   in-memory `FakeGateway` used whenever `STRIPE_SECRET_KEY` is empty. Webhooks go to
   `POST /webhooks/stripe/platform`. They are routed by customer through the platform
   `CustomerRoute` table, stored per tenant as `BillingEvent` (unique by event id) and
   processed by a retrying task. The Checkout return calls `checkout-session/complete`,
   so the plan shows without waiting for the webhook; both paths are idempotent.
5. **The subscription drives the organisation's status:** trialing → trial, active →
   active, past due → past due, and suspended or cancelled → suspended (read-only for
   owners and admins, closed to portals). This goes through tenancy's lifecycle services
   (`set_billing_status`, `suspend_organisation`, `reactivate_organisation`). The API lives
   under `/api/v1/subscription` (rather than `/billing`, which is the tenants' own invoicing),
   so it stays writable while suspended.
6. **Processes on Temporal:** `TrialLifecycleWorkflow` (emails and expiry; signals
   `converted`, `extended`) and `SubscriptionDunningWorkflow` (notices on days 0/3/7/14,
   then read-only on day 21; signal `paid`). Trial expiry compares the deadline against the
   workflow's clock, not wall-clock time.

## Consequences
- New features add a key to `FEATURES` or `LIMITS` and call `core.entitlements` where
  they are enforced; the frontend's upgrade dialog works for every endpoint.
- Tests that need plans after a transactional test (which flushes platform tables) get
  them back through `get_plan`'s self-healing sync or the app's `plans` fixture.
- A card added during the trial keeps the remaining trial days (Checkout `trial_end`).
