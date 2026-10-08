# E04 — SaaS Subscriptions, Plans & Entitlements

| | |
|---|---|
| **Phase** | MVP |
| **Depends on** | E01–E03 |

## 1. Summary
How **we** bill our tenants: plans, trials, per-seat/usage pricing, Stripe Billing integration, feature entitlements and limits, add-ons (SMS credits, AI credits, extra branches) and dunning for our own subscription. This is separate from tenant billing of *their* clients (E10/E11).

## 2. Functional requirements

### FR-04-1 Plan catalogue
- Plans stored in DB (managed in super-admin, E30): key, name, description, billing intervals (monthly/annual with discount), currency price list (GBP, USD, EUR, AUD, CAD, NZD), base price, metered components, included quantities, entitlements, visibility (public/legacy/custom), trial days.
- Initial plans: **Solo**, **Team**, **Agency**, **Enterprise** (see `00-product-vision.md §7`).
- Pricing components (configurable per plan):
  - `base_fee`
  - `active_tutor` (per active tutor per month: a tutor with ≥1 completed lesson in the billing period, or any active tutor; configurable)
  - `revenue_share` (% of client payments processed through TutorTrack, TutorCruncher PAYG-style; optional plan)
  - `branch` (per extra branch)
  - add-ons: SMS bundle, AI credits, custom domain, white-label mobile app, priority support.

### FR-04-2 Entitlements and limits
- Entitlement registry: boolean features (`multi_branch`, `payroll`, `pipeline`, `recruitment`, `matching`, `automation`, `courses`, `api_access`, `webhooks`, `custom_domain`, `white_label`, `sso_saml`, `accounting_integrations`, `advanced_reports`, `ai_assistant`) and numeric limits (`max_tutors`, `max_branches`, `max_active_students`, `storage_gb`, `sms_credits_monthly`, `automation_rules`).
- `entitlements.has(org, key)` and `entitlements.limit(org, key)`, cached and enforced in services and the API (403 with `upgrade_required` problem type including `required_plan`).
- Frontend `useEntitlement()` shows locked features with an upgrade CTA rather than hiding them entirely (for discoverability).
- Platform admin per-org overrides (grant feature, raise limit, until date).
- **AC:** inviting a 2nd tutor on Solo returns `upgrade_required`; after upgrading to Team the invite succeeds without a reload.

### FR-04-3 Trials
- 30-day trial (configurable) with full Agency features, then downgrade-to-chosen-plan or read-only lock if no payment method.
- Trial emails: day 1 welcome, day 7 checklist, day 23 reminder, day 28 last chance, expiry.
- Trial extension by platform admin.

### FR-04-4 Stripe Billing integration
- Each Organisation ↔ Stripe Customer (on **our** platform account).
- Checkout via Stripe Checkout or embedded Payment Element; customer portal for card changes and invoices.
- Subscription items map to pricing components; seat quantities synced nightly (and on change, debounced) from the active tutor count; revenue share reported as **usage records** (Stripe Billing Meters) daily from E11 payment totals.
- Webhooks: `customer.subscription.*`, `invoice.paid`, `invoice.payment_failed`, `customer.subscription.trial_will_end` → update `Subscription` state.
- Tax: Stripe Tax for VAT/GST/sales tax; collect VAT number (reverse charge in EU/UK).

### FR-04-5 Plan changes
- Upgrade immediately with proration; downgrade at period end, with validation (e.g. can't downgrade to Solo with 3 active tutors; UI lists what must change).
- Annual ↔ monthly switch.
- Cancel at period end with an exit survey; reactivation within the retention period.

### FR-04-6 Dunning for our subscription
- Failed payment → org status `past_due` → in-app banner to owners/finance, emails on days 0/3/7/14 → after 21 days `suspended` (read-only), and portals and automations paused. Payment restores immediately.

### FR-04-7 Usage dashboard (tenant-facing)
- Settings → Billing & Plan: current plan, next invoice estimate, seats used vs included, SMS/AI credits used, storage, invoices list (PDF), payment method, change plan.

### FR-04-8 Credits ledger (SMS, AI)
- `UsageCreditLedger` per org per credit type: monthly grants, purchases (one-off top-ups via Stripe), consumption entries (E13 SMS, E31 AI). Auto top-up option. Hard stop or overage per setting.

## 3. Data model
`Plan`, `PlanPrice(plan, currency, interval, component, unit_amount, stripe_price_id)`, `PlanEntitlement(plan, key, bool_value, int_value)`, `Subscription(org, plan, status, interval, currency, stripe_subscription_id, trial_ends_at, current_period_end, cancel_at)`, `EntitlementOverride(org, key, value, expires_at, reason)`, `UsageCreditLedger(org, credit_type, delta, reason, ref, balance_after)`, `BillingEvent` (raw Stripe webhook log).

## 4. API
`GET /api/v1/billing/plans`, `GET /api/v1/billing/subscription`, `POST /api/v1/billing/checkout-session`, `POST /api/v1/billing/portal-session`, `POST /api/v1/billing/change-plan` (with preview), `POST /api/v1/billing/cancel`, `GET /api/v1/billing/usage`, `GET /api/v1/entitlements`, `POST /webhooks/stripe/platform`.

## 5. Events
`subscription.started`, `subscription.changed`, `subscription.trial_ending`, `subscription.past_due`, `subscription.suspended`, `subscription.cancelled`, `credits.low`.

## 6. Permissions
`subscription.view` (Owner, Admin, Finance), `subscription.manage` (Owner).

## 7. Delivery plan
- [ ] **E04-T01** Plan, price and entitlement models, seed plans, entitlement service and API error type.
- [ ] **E04-T02** Enforce entitlements across existing endpoints (decorator plus limit checks for tutors and branches).
- [ ] **E04-T03** Trial lifecycle and emails (Celery beat).
- [ ] **E04-T04** Stripe customer, checkout, portal, subscription sync via webhooks.
- [ ] **E04-T05** Seat quantity sync and revenue-share metering.
- [ ] **E04-T06** Plan change preview, upgrade/downgrade validation, cancel/reactivate.
- [ ] **E04-T07** Dunning states, banners, read-only suspension mode.
- [ ] **E04-T08** SMS/AI credit ledger with top-ups.
- [ ] **E04-T09** Frontend Billing & Plan page and upgrade prompts.

## Temporal workflows (E32)

Implement these processes as Temporal workflows following the rules in [E32](E32-workflow-orchestration-temporal.md) (deterministic workflow code, side effects in tenant-scoped activities that call services, tenant-prefixed workflow IDs, signals for human decisions). Where the requirements above mention sweeper tasks, `next_*_at` / `resume_at` columns or retry schedules, the workflow replaces them.

- [ ] **E04-TW1** Trial and subscription dunning workflows (requires E32).

| Workflow | Started by | Steps, timers and signals | Replaces |
|---|---|---|---|
| `TrialLifecycleWorkflow` `trial:{org}` | `organisation.created` | Timers for day 1/7/23/28 emails → expiry: downgrade or read-only. Signals `converted` (paid), `extended(days)` (platform admin) | Trial email beat job |
| `SubscriptionDunningWorkflow` `sub-dunning:{org}:{invoice}` | Stripe `invoice.payment_failed` | Banner + emails on day 0/3/7/14 → day 21 suspend (read-only, pause portals and automations). Signal `paid` restores immediately | Dunning sweeper |
