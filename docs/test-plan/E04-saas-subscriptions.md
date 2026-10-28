# E04 — SaaS subscriptions, plans and entitlements: manual tests

**Scope.** How TutorTrack bills its own customers: the plan catalogue (Solo, Team, Agency, Agency pay-as-you-go, Enterprise), entitlements and limits with upgrade prompts, the 30-day trial (`TrialLifecycleWorkflow`), Stripe Billing checkout/portal/webhooks (a fake gateway locally), seat and revenue-share metering, plan changes, cancellation and reactivation, dunning (`SubscriptionDunningWorkflow`) and read-only suspension, SMS/AI credits, and the **Billing & plan** page. Spec: [E04](../epics/E04-saas-subscriptions.md).

**Built differently from the spec:** the API lives under `/api/v1/subscription/...` (not `/billing/...`); add-ons other than SMS/AI credits are entitlement overrides granted by sales; trial notices go at the start, day 7, 7 days before the end and 2 days before the end; the trial workflow starts from `subscription.started`; organisations **without** a subscription are not limited at all; Enterprise is "contact sales". Prices: Solo £19; Team £39 + £6/tutor after 2; Agency £99 + £5/tutor after 10 + £25 per extra branch; Agency PAYG 1.5% of payments; annual = 10 × monthly.

**Common preconditions.** Empty `STRIPE_SECRET_KEY` = fake gateway: Checkout completes as soon as you return from it, cards "succeed", the customer portal link returns to the page. The fake keeps its state in the backend process memory, so restarting `runserver` forgets fake subscriptions (re-run checkout). Webhooks are simulated by posting JSON to `http://localhost:8010/webhooks/stripe/platform` with header `Stripe-Signature: fake-signature`; the body needs `id`, `type` and `data.object` with the organisation's fake `customer` and `subscription` IDs (read them from the `subscriptions_subscription` table or the platform console organisation page). A Celery worker processes stored events; the Temporal worker runs trial and dunning workflows (timers can't be fast-forwarded on the dev server: check the workflow's pending timer in the Temporal UI). For a clean trial, sign up a new organisation (E02) rather than using brightminds, whose subscription depends on whether the worker processed the seed's events.

## Plans and the Billing & plan page

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E04-001 | New organisation starts a 30-day Agency trial | New owner | Sign up "Trial Test Ltd" (E02) | 1. Open **Billing & plan** (`/settings/plan`). | Status **Free trial**, "30 days of your free trial left.", "Then you'll carry on with <plan from business type>"; Agency features unlocked. | P1 | backend: `tutortrack/subscriptions/tests/test_subscriptions.py` | |
| TP-E04-002 | Plan cards and prices | Owner | — | 1. Look at **Plans**; toggle **Monthly** / **Annual (2 months free)**.<br>2. Change org currency (USD org) and compare. | Solo, Team, Agency, Agency (pay as you go), Enterprise ("Contact us for a price"); per-tutor and per-branch add-ons shown; annual = 10 × monthly; prices shown in the org's currency (GBP, USD, EUR, AUD, CAD, NZD). | P1 | backend: `tutortrack/subscriptions/tests/test_subscriptions.py` | |
| TP-E04-003 | Usage meters | Owner | Trial org with 1–2 tutors | 1. Look at **Usage**. | Tutors, branches, active students and storage show "used of allowed"; "Billable tutors this period"; "Next invoice about …". | P2 | backend: `tutortrack/subscriptions/tests/test_subscriptions.py` | |
| TP-E04-004 | Organisation without a subscription | Owner | An org with no subscription row (e.g. brightminds if the worker never ran) | 1. Open Billing & plan. | "This organisation isn't on a TutorTrack plan."; no limits enforced. | P3 | backend: `tutortrack/subscriptions/tests/test_subscriptions.py` | |

## Checkout, card and portal (fake Stripe)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E04-005 | Add a card during the trial | Owner | Trial org | 1. **Add payment method** → (fake) Checkout returns.<br>2. Reload Billing & plan. | "Thank you. Your plan is set up."; "Paying by <brand> ending <last4>"; trial days kept; trial reminders stop. | P1 | backend: `tutortrack/subscriptions/tests/test_workflows.py` | |
| TP-E04-006 | Choose a plan during the trial | Owner | Trial org with card | 1. **Choose Team** → confirm. | Plan set; no extra card step; still trialling until the end date. | P2 | backend: `tutortrack/subscriptions/tests/test_subscriptions.py` | |
| TP-E04-007 | Payment details and invoices | Owner | Paid org | 1. **Payment details and invoices** (portal).<br>2. Look at **Invoices**. | Fake portal returns to the page; invoices list with number, date, total, status and **Download**. | P3 | No | |
| TP-E04-008 | Webhook with a bad signature is ignored | Tester | curl | 1. POST to `/webhooks/stripe/platform` with `Stripe-Signature: wrong`. | 400; nothing stored. Unknown customers are ignored. | P2 | backend: `tutortrack/subscriptions/tests/test_subscriptions.py` | |

## Trial lifecycle (Temporal)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E04-009 | Trial welcome notice and workflow | New owner | New trial org; workers running | 1. Check Mailpit and in-app notices.<br>2. Temporal UI: search `trial:<org id>`. | Welcome notice to holders of `subscription.view`; workflow running with a timer for the day-7 checklist. | P1 | backend: `tutortrack/subscriptions/tests/test_workflows.py` | |
| TP-E04-010 | Trial-ending banner | Owner | Trial with ≤ 7 days left (platform **Extend trial** with negative days is not allowed; use a DB update of `trial_ends_at` on a throwaway org) | 1. Reload the app. | Banner "Your free trial ends in N days." with a **Billing & plan** link. | P2 | No | |
| TP-E04-011 | Trial ends without a card: read-only | Owner | Throwaway org; let the workflow reach expiry (or verify via backend test) | 1. After expiry, try to edit a client. | Status Read-only; "Your account is read-only until you choose a plan."; writes refused; billing pages still work. | P1 | backend: `tutortrack/subscriptions/tests/test_workflows.py` | |
| TP-E04-012 | Platform staff extend the trial | Platform staff | Trial org | 1. /platform → organisation → **Extend trial** 14 days with a reason. | "Trial extended."; trial end moves; the workflow receives `extended` (visible in its history). | P2 | backend: `tutortrack/subscriptions/tests/test_workflows.py` | |

## Entitlements and limits

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E04-013 | Second tutor on Solo needs Team | Owner | Org on Solo with one tutor | 1. Invite or create a second tutor.<br>2. Upgrade to Team from the dialog.<br>3. Retry without reloading. | Dialog "Upgrade to Team" ("Your plan allows 1 tutors…"); after upgrading the invite works. | P1 | backend: `tutortrack/subscriptions/tests/test_subscriptions.py` | |
| TP-E04-014 | Active student limit | Coordinator | Plan at its `max_active_students` | 1. Add an active student. | `upgrade_required` dialog; trial/active students counted, others not. | P2 | backend: `tutortrack/subscriptions/tests/test_subscriptions.py` | |
| TP-E04-015 | Branches need `multi_branch` and capacity | Owner | Team plan | 1. Try to add a branch. | Upgrade prompt naming Agency. | P2 | backend: `tutortrack/subscriptions/tests/test_subscriptions.py` | |
| TP-E04-016 | Storage quota | Owner | Low `storage_gb` override (e.g. 0) | 1. Upload a file. | Refused with an upgrade prompt. | P3 | backend: `tutortrack/subscriptions/tests/test_subscriptions.py` | |
| TP-E04-017 | Locked features show with an upgrade call to action | Coordinator | Solo plan | 1. Open a gated area (e.g. Payroll, Enquiries pipeline). (Workflows isn't gated: built-ins are on every plan; only **New workflow** beyond the plan's limit is refused, TP-E33-063.) | Shown as locked "Available on <plan> and above." with an upgrade link rather than hidden. | P2 | No | |
| TP-E04-018 | Platform entitlement override | Platform staff | Solo org | 1. /platform → organisation → **Entitlement overrides**: `max_tutors` = 5 until next month, **Grant**.<br>2. Invite tutors. | Up to 5 tutors allowed; after the expiry the plan limit applies again. | P2 | backend: `tutortrack/subscriptions/tests/test_subscriptions.py` | |
| TP-E04-019 | Feature flags can target plans | Platform staff | Flag with plan keys `agency` | 1. /platform/flags → set Plans `agency` for a flag.<br>2. Compare an Agency and a Team org. | On for the Agency org only. | P3 | backend: `tutortrack/subscriptions/tests/test_subscriptions.py` | |

## Plan changes, cancel and reactivate

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E04-020 | Upgrade applies now with proration | Owner | Paid Team monthly | 1. **Choose Agency** → read the preview → **Confirm**. | "The change applies straight away."; "You'll pay £X now for the rest of this period."; plan updated. | P1 | backend: `tutortrack/subscriptions/tests/test_subscriptions.py` | |
| TP-E04-021 | Downgrade is validated then scheduled | Owner | Agency with 3 active tutors | 1. **Choose Solo**. | "Some things need to change first" lists the tutors to deactivate. After fixing, the change is scheduled: "Changes to Solo at the end of this billing period." | P1 | backend: `tutortrack/subscriptions/tests/test_subscriptions.py` | |
| TP-E04-022 | Monthly to annual and back | Owner | Paid monthly | 1. Switch to Annual (applies now).<br>2. Switch back to Monthly. | Annual applies immediately; annual → monthly is scheduled for the period end. | P2 | backend: `tutortrack/subscriptions/tests/test_subscriptions.py` | |
| TP-E04-023 | Enterprise needs sales | Owner | — | 1. Try to choose Enterprise. | "Contact us for a price"; no self-serve change. | P3 | backend: `tutortrack/subscriptions/tests/test_subscriptions.py` | |
| TP-E04-024 | Cancel with exit survey | Owner | Paid org | 1. **Cancel subscription** → reason "It's too expensive" + feedback → **Cancel at the end of the period**. | "Your subscription is set to end at the end of this…"; survey stored. | P1 | backend: `tutortrack/subscriptions/tests/test_subscriptions.py` | |
| TP-E04-025 | Reactivate before and after the end | Owner | Cancelled at period end | 1. **Keep my subscription** before the end.<br>2. On an ended subscription press **Subscribe again**. | 1: cancellation undone. 2: Checkout link (or the portal if a payment is unpaid). | P2 | backend: `tutortrack/subscriptions/tests/test_subscriptions.py` | |

## Dunning and suspension

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E04-026 | Failed renewal marks past due | Owner, Finance | Paid org; customer and subscription IDs | 1. POST `invoice.payment_failed` (fake signature, `data.object` = `{"id":"in_test1","customer":"<cus>","subscription":"<sub>"}`).<br>2. Reload as owner and as finance@. | Status **Payment overdue**; banner "Your TutorTrack payment failed…" for owners/finance; day-0 email; `sub-dunning:<org>:in_test1` workflow running. | P1 | backend: `tutortrack/subscriptions/tests/test_workflows.py` | |
| TP-E04-027 | Payment restores immediately | Owner | Past due | 1. POST `invoice.paid` for the same invoice. | Status Active; banner gone; dunning workflow ends (signal `paid`). | P1 | backend: `tutortrack/subscriptions/tests/test_workflows.py` | |
| TP-E04-028 | Day 21 suspends read-only and pauses portals | Owner, Parent | Verified by the replayed workflow test, or on a throwaway org left 21 days | 1. As owner try to edit; as a parent open the portal; check automations. | Read-only (owner/admin), portals show a maintenance message, background jobs paused; billing still writable. | P2 | backend: `tutortrack/subscriptions/tests/test_workflows.py` | |
| TP-E04-029 | Duplicate webhooks are processed once | Tester | — | 1. POST the same event `id` twice. | One `BillingEvent`; effects applied once. | P2 | backend: `tutortrack/subscriptions/tests/test_subscriptions.py` | |

## Seats and revenue share

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E04-030 | Seat quantity follows active tutors | Owner | Team plan with card | 1. Activate a 3rd tutor.<br>2. Wait 5 minutes (debounced task) and reload. | "Billable tutors this period" increases; next invoice estimate includes £6 for the extra tutor. | P2 | backend: `tutortrack/subscriptions/tests/test_subscriptions.py` | |
| TP-E04-031 | Revenue share is metered daily | Finance | Agency PAYG plan; yesterday's card payment through E11 fake Stripe | 1. Run the daily meter task (Celery beat, or call `subscriptions.tasks` from a shell). | A meter report for yesterday's card/debit payments in minor units; manual payments excluded; re-running doesn't double count. | P3 | backend: `tutortrack/subscriptions/tests/test_subscriptions.py` | |

## SMS and AI credits

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E04-032 | Credit balances | Owner | — | 1. Look at **SMS and AI credits**. | Balance, used this period and monthly allowance per type. | P2 | backend: `tutortrack/subscriptions/tests/test_subscriptions.py` | |
| TP-E04-033 | Buy a credit pack | Owner | Card on file | 1. **Buy 500** SMS credits. | Charged to the saved card (fake succeeds); balance +500; ledger entry. Without a card it goes through Checkout. | P2 | backend: `tutortrack/subscriptions/tests/test_subscriptions.py` | |
| TP-E04-034 | Hard stop vs overage | Owner | SMS balance 0 | 1. With overage off, send an SMS (E13).<br>2. Turn on **Keep sending when credits run out** and send again. | 1: refused, "credits" message. 2: sent; overage charged at the next reset. | P2 | backend: `tutortrack/subscriptions/tests/test_subscriptions.py` | |
| TP-E04-035 | Low-credit notice and auto top-up | Owner | Balance just above the threshold | 1. Turn on **Top up automatically when running low**; consume credits below the threshold. | `credits.low` notice; an automatic top-up is bought once. | P3 | backend: `tutortrack/subscriptions/tests/test_subscriptions.py` | |
| TP-E04-036 | AI usage consumes AI credits | Coordinator | AI features on (seed) | 1. Use "Draft with AI" (E31) a few times. | AI credit balance decreases; ledger entries name the feature. | P3 | No | |

## Permissions

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E04-037 | Who sees Billing & plan | Owner, Admin, Finance, Coordinator, Branch Manager, Tutor | — | 1. Sign in as each and look for **Billing & plan**. | Owner, Admin, Finance see it; Coordinator, Branch Manager (`subscription.view` denied) and Tutor don't (page/API 403). | P1 | e2e: `e2e/roles.spec.ts` | |
| TP-E04-038 | Only the Owner manages | Admin, Finance | — | 1. As office@ and finance@ try to change plan, cancel or buy credits (UI and `POST /api/v1/subscription/change-plan`). | Buttons absent; API 403 (`subscription.manage` is owner-only). | P1 | backend: `tutortrack/identity/tests/test_rbac.py` | |

## Tenant isolation

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E04-039 | Subscription data is per organisation | Owner | Two orgs | 1. Compare `/api/v1/subscription` on brightminds and northside. | Each shows only its own plan, usage, invoices and credits. | P1 | backend: `tutortrack/subscriptions/tests/test_subscriptions.py` | |
| TP-E04-040 | A webhook for one customer only touches its organisation | Tester | Two paid orgs | 1. Send `invoice.payment_failed` for org A's customer. | Only org A goes past due. | P1 | backend: `tutortrack/subscriptions/tests/test_subscriptions.py` | |

## i18n and currency

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E04-041 | Prices and dates are localised | Owner | GB and US orgs | 1. Compare plan cards and renewal dates. | £ / $ by currency; dates in each locale's format; pluralised "1 day" / "N days". | P2 | No | |

## Gap batch G6 (as built 2026-10-14)

Built by gap batch G6 ([ADR 0034](../adr/0034-gap-batch-g6-consent-capture-account-deletion-and-platform-tools.md)); see the epic's *Gap backlog* notes. Signup now requires `accept_terms: true` (the terms checkbox).

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E04-042 | Buy an add-on in-app | Owner | Paid subscription with a card; Billing & plan | 1. **Add-ons** → Priority support → **Add**.<br>2. Confirm the prorated price. | A Stripe subscription item is added and the add-on is active; the `priority_support` feature is on (entitlements). | P1 | backend: `test_buying_an_add_on_adds_a_stripe_item_and_grants_the_feature`; vitest: `G6.test.tsx` buys an add-on | |
| TP-E04-043 | Add-ons survive a plan change and end on cancel | Owner | Add-on active | 1. Change plan.<br>2. Remove the add-on in Stripe's portal (or cancel it). | The add-on stays across the plan change; removed in Stripe → it ends when the update arrives. | P2 | backend: `test_add_ons_stay_when_the_plan_changes_and_stop_on_cancel`, `test_an_add_on_removed_in_stripes_portal_ends` | |
| TP-E04-044 | Trial without a card goes to checkout | Owner | Trial, no card | 1. Try to buy an add-on. | Answer `checkout_required`; the page sends you to checkout. | P2 | backend: `test_a_trial_without_a_card_is_sent_to_checkout` | |
| TP-E04-045 | Only the owner buys add-ons | Admin | — | 1. Try `POST /api/v1/subscription/addons/custom_domain`. | 403. | P2 | backend: `test_only_the_owner_buys` | |
