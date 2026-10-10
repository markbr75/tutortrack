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
- [x] **E04-T01** Plan, price and entitlement models, seed plans, entitlement service and API error type.
- [x] **E04-T02** Enforce entitlements across existing endpoints (decorator plus limit checks for tutors and branches).
- [x] **E04-T03** Trial lifecycle and emails (Celery beat).
- [x] **E04-T04** Stripe customer, checkout, portal, subscription sync via webhooks.
- [x] **E04-T05** Seat quantity sync and revenue-share metering.
- [x] **E04-T06** Plan change preview, upgrade/downgrade validation, cancel/reactivate.
- [x] **E04-T07** Dunning states, banners, read-only suspension mode.
- [x] **E04-T08** SMS/AI credit ledger with top-ups.
- [x] **E04-T09** Frontend Billing & Plan page and upgrade prompts.

## Temporal workflows (E32)

Implement these processes as Temporal workflows following the rules in [E32](E32-workflow-orchestration-temporal.md) (deterministic workflow code, side effects in tenant-scoped activities that call services, tenant-prefixed workflow IDs, signals for human decisions). Where the requirements above mention sweeper tasks, `next_*_at` / `resume_at` columns or retry schedules, the workflow replaces them.

- [x] **E04-TW1** Trial and subscription dunning workflows (requires E32).

| Workflow | Started by | Steps, timers and signals | Replaces |
|---|---|---|---|
| `TrialLifecycleWorkflow` `trial:{org}` | `organisation.created` | Timers for day 1/7/23/28 emails → expiry: downgrade or read-only. Signals `converted` (paid), `extended(days)` (platform admin) | Trial email beat job |
| `SubscriptionDunningWorkflow` `sub-dunning:{org}:{invoice}` | Stripe `invoice.payment_failed` | Banner + emails on day 0/3/7/14 → day 21 suspend (read-only, pause portals and automations). Signal `paid` restores immediately | Dunning sweeper |

## Implementation notes (as built 2026-10-10)
- **App and catalogue (T01):** `subscriptions`. The platform tables are `Plan`, `PlanPrice`, `PlanEntitlement` and `CustomerRoute` (webhook routing). The tenant tables, all with RLS, are `Subscription`, `EntitlementOverride`, `CreditAccount`, `UsageCreditLedger`, `CreditPurchase`, `MeterReport` and `BillingEvent`. The catalogue is defined in `catalogue.py` and synced by a data migration and `manage.py sync_plans [--stripe]` (ADR 0009).
  - Plans: Solo £19, Team £39 + £6/tutor after 2, Agency £99 + £5/tutor after 10 + £25 per extra branch, Agency (pay as you go) 1.5% of payments processed, and Enterprise (custom, contact sales). Prices are indicative and listed in GBP, USD, EUR, AUD, CAD and NZD. Annual = 10 × monthly.
  - Deviation: add-ons other than SMS and AI credits (custom domain, white-label, priority support) are granted as entitlement overrides by sales for now, not bought in-app.
  - Deviation: the API lives under `/api/v1/subscription/...` rather than `/api/v1/billing/...`, which is the tenants' own invoicing. The webhook is `/webhooks/stripe/platform` as specified.
- **Entitlements (T01/T02):** `core.entitlements` (`has`, `limit`, `require`, `require_capacity`) raises 403 `upgrade-required` with `required_plan`. It is enforced in four places:
  - Tutors: `max_tutors` counts onboarding, active and restricted tutors, when they are created or reactivated, and on direct tutor invitations.
  - Students: `max_active_students` counts active and trial students.
  - Branches: the `multi_branch` entitlement and `max_branches`, alongside the existing rollout flag.
  - Uploads: `storage_gb`.
  
  Organisations without a subscription aren't limited. Feature flags can target plans (`PLAN_RESOLVER`). `GET /entitlements` feeds `useEntitlement()` and `<Locked>`. A mutation that fails with `upgrade-required` anywhere in the admin app opens an upgrade dialog. Platform overrides have services (`set_override`, `remove_override`, `extend_trial`) now; their console UI comes with E30. Payroll, pipeline, recruitment, matching and automation gates are added by those epics.
- **Trials (T03, TW1):** `organisation.created` starts a 30-day trial with Agency features; the plan it moves to defaults from the business type. `TrialLifecycleWorkflow` sends four notices:
  - welcome at the start (FR "day 1");
  - checklist on day 7;
  - a reminder 7 days before the end;
  - a last chance 2 days before the end.
  
  These go as in-app and email notices (`subscription_notice`) to holders of `subscription.view`. At the end:
  - With a card, the account carries on with the chosen plan.
  - Without one, it is suspended read-only until they subscribe.
  
  Signals: `converted` and `extended(days)`. A card added during the trial keeps the remaining trial days. Deviation: the workflow is started by `subscription.started` rather than directly by `organisation.created`.
- **Stripe (T04):** Checkout (Stripe Tax and VAT ID collection), the customer portal, and webhooks for `checkout.session.completed`, `customer.subscription.*`, `invoice.paid` and `invoice.payment_failed`, stored then processed by a task. The Checkout return calls `checkout-session/complete`. Without Stripe keys, a fake gateway runs every flow.
- **Seats and revenue share (T05):** a nightly task, and a debounced task (5 minutes) after tutor, branch or lesson changes, sync two quantities:
  - per-tutor quantities: billable tutors are those with a completed lesson in the period, or every active tutor depending on the plan's `seat_mode`, beyond the included number;
  - extra-branch quantities.
  
  A daily task reports yesterday's card and debit payments (not manual ones) in minor units to the Billing Meter `tutortrack_revenue`, idempotent by identifier.
- **Plan changes (T06):** `change-plan?preview=true` returns the direction, when it takes effect, blockers and the proration due now. Upgrades (and monthly → annual) apply immediately with proration. Downgrades, sideways moves and annual → monthly are scheduled for the period end with a Stripe subscription schedule; `pending_plan` shows them. Blockers cover tutors, branches, active students and storage. Cancelling records an exit survey and cancels at the period end. Reactivating undoes it; after the subscription ends it returns a Checkout link (or the portal when a payment is unpaid).
- **Dunning (T07, TW1):** `invoice.payment_failed` → past due (organisation `past_due`, banner) → `SubscriptionDunningWorkflow` sends notices on days 0, 3, 7 and 14, then makes the account read-only on day 21. Read-only pauses portals and background jobs (`is_operational`). `invoice.paid` restores straight away and signals `paid`.
- **Credits (T08):** `CreditAccount` per type with a monthly allowance (`sms_credits_monthly`) that resets each period, plus purchased credits that carry over. Every movement is in `UsageCreditLedger`. The SMS meter is registered with comms: 1 credit per segment at home (GB, IE, US, CA), 2 elsewhere. Options:
  - hard stop or overage, which is charged at the next reset;
  - `credits.low` with a notice when the balance drops below a threshold;
  - automatic top-ups;
  - packs of 500 or 2,000 SMS credits, and 1,000 or 5,000 AI credits, charged to the saved card (or bought through Checkout without one).
  
  AI consumption is wired in E31.
- **Frontend (T09):** Settings → Billing & plan (`/settings/plan`) shows:
  - status, the trial countdown and the card on file;
  - Checkout and portal buttons;
  - usage meters, seats and the next-invoice estimate;
  - plan cards with a monthly/annual toggle and change preview;
  - credits with top-ups and settings;
  - invoices, and cancel with the exit survey.
  
  A banner covers trials ending within 7 days, past due and read-only. Admins and Finance can view; only the Owner manages (`subscription.manage`).
- **Follow-ups:** the platform console for plans, overrides and trial extension (E30); in-app add-on purchases; usage-based overage invoicing through Stripe instead of one-off charges; AI credit consumption (E31).
