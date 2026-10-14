# E11 — Payments: manual tests

**Scope.** Connecting payment providers (Stripe Connect, and in Phase 2 GoCardless and PayPal), saved methods and auto-pay consent, the hosted pay page, manual payments and allocation, auto-pay collection with retries and the collection lock, refunds, disputes, payouts, receipts, bank reconciliation (CSV/OFX/CAMT and Open Banking), split payments, and provider migration. Spec: [E11](../epics/E11-payments.md).

**Built differently from the spec (Implementation notes win):**
- Without keys, every provider is a **fake** (no network). Fake Stripe: webhooks are plain JSON with header `Stripe-Signature: fake-signature`; method refs containing `fail` are declined, `3ds` need authentication, `debit` stay pending. Fake GoCardless and PayPal redirect straight back to TutorTrack (no external page). Fake state lives in the backend process memory, so use one `runserver` process and don't restart it mid-test.
- The browser pay page loads real Stripe.js; with the fake key `pk_test_fake` the card form will not work. To pay by "card" in dev, post a fake `payment_intent.succeeded` webhook (see below). PayPal and GoCardless fakes work end to end in the browser.
- Methods per branch and card surcharges (where legal) were added by G3 (Settings → Payments). Evidence submission for disputes stays in Stripe. PayPal can't be saved for auto-pay. GoCardless needs a registered redirect URI in production. The Open Banking consent is given in GoCardless's portal.
- Collection, disputes, provider migration and bank feeds are Temporal workflows (`PaymentCollectionWorkflow` = the collection lock, `DisputeWorkflow`, `ProviderMigrationWorkflow`, `BankFeedSyncWorkflow`).

**Fake webhook recipes (dev).**
- Stripe account active: `curl -X POST http://localhost:8010/webhooks/stripe -H 'Stripe-Signature: fake-signature' -H 'Content-Type: application/json' -d '{"id":"evt_1","type":"account.updated","account":"<acct ref>","data":{"object":{"charges_enabled":true,"payouts_enabled":true,"requirements":{"currently_due":[]},"default_currency":"gbp"}}}'`. The account ref is shown in Settings → Payments (or `ProviderAccount.account_ref`).
- Card payment succeeded for an invoice: same endpoint, `"type":"payment_intent.succeeded"`, `data.object` = `{"id":"pi_manual1","amount":4500,"amount_received":4500,"currency":"gbp","metadata":{"invoice_id":"<uuid>","organisation_id":"<uuid>"},"payment_method":"pm_card_visa"}`. Use `payment_request_id` instead of `invoice_id` for a request. Use a new `id` per event.
- Failure: `payment_intent.payment_failed` with `last_payment_error`. Dispute: `charge.dispute.created` with `payment_intent` and `evidence_details.due_by`.
- GoCardless webhooks: `POST /webhooks/gocardless`, HMAC-SHA256 of the body with secret `fake-gocardless-secret` in header `Webhook-Signature`. PayPal: `POST /webhooks/paypal` with header `PAYPAL-TRANSMISSION-SIG: fake-signature`.

**Common preconditions.** Stack with Celery and Temporal workers; seed loaded. Patel family has an issued invoice (create one per E10). Screens: `/settings/payments` (Payments setup), client page → Billing → Payments and Payment methods, `/billing` → Payments and Bank tabs, invoice page **Collect now**, public `/pay/<token>` and `/pay/setup/<token>`.

## Provider onboarding (FR-11-1, T01, T02, T11, T12)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E11-001 | Connect Stripe (fake) | Owner (admin@) | No provider connected: "Online payments aren't set up." | 1. `/settings/payments` → **Connect Stripe**. | An account is created; status "Setup not finished" / "Stripe needs more information" with **Finish setup in Stripe** (fake link to connect.example.test). | P1 | backend: `test_connect_onboard_and_activate_by_webhook` | |
| TP-E11-002 | Account becomes active by webhook | Owner | TP-E11-001 | 1. Send the `account.updated` fake webhook.<br>2. **Check status**. | "Ready to take payments". | P1 | backend: `test_connect_onboard_and_activate_by_webhook` | |
| TP-E11-003 | Webhook signature and unknown account | Owner | — | 1. Post a webhook with a wrong signature.<br>2. Post one for an unknown account. | First returns 400 and is not stored as processed; second is stored and ignored. | P1 | backend: `test_webhooks_need_a_valid_signature_and_known_account` | |
| TP-E11-004 | Webhook replay is idempotent | Owner | A processed event | 1. Post the same event id again. | Nothing changes (unique per provider and event id). | P1 | backend: `test_pay_page_card_payment_is_recorded_once` | |
| TP-E11-005 | Disconnect blocked while auto-pay is in use | Owner | A client on auto-pay | 1. **Disconnect**. | Refused with a clear message. Without auto-pay clients it disconnects ("Disconnected"). | P2 | backend: `test_disconnect_is_blocked_while_clients_use_autopay` | |
| TP-E11-006 | Connect GoCardless (fake) | Owner | — | 1. Payments setup → More ways to get paid → **Connect GoCardless**. | Redirects straight back with code and state; "Connected." | P2 | backend: `test_partner_connect_and_complete` | |
| TP-E11-007 | Connect PayPal (fake) | Owner | — | 1. **Connect PayPal**. | Back with a fake merchant id; "Connected." | P2 | backend: `test_partner_connect_and_complete` | |
| TP-E11-008 | Tampered connect state is refused | Owner | — | 1. Change `state` in the return URL and load it. | Error; nothing connected. | P2 | backend: `test_partner_connect_and_complete` | |

## Saved methods and auto-pay (FR-11-2, FR-11-3, T03, T06)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E11-009 | Staff create a setup link | Finance (finance@) | Stripe or GoCardless connected | 1. Patel → Billing → Payment methods → **Create a setup link**. | "Send this link to the client:" with `/pay/setup/<token>`. Staff never type card numbers. | P1 | backend: `test_setup_link_saves_a_card_and_records_autopay_consent` | |
| TP-E11-010 | Client saves a GoCardless mandate with auto-pay consent | Parent (no sign-in) | GoCardless connected; setup link | 1. Open the link; choose **Bank (Direct Debit)** → **Continue to GoCardless**.<br>2. Tick the auto-pay consent. | Back on the page: "Saved: card or account ending ####." and "Invoices will be paid automatically." Consent records wording version, IP, user agent. | P1 | backend: `test_setup_link_saves_a_gocardless_mandate` | |
| TP-E11-011 | Setup link is single use and expires | Parent | Used link | 1. Open the link again. | "This link has expired or has already been used." | P2 | backend: `test_setup_link_saves_a_card_and_records_autopay_consent` | |
| TP-E11-012 | Auto-pay needs consent | Finance | Method saved without consent | 1. **Turn auto-pay back on**. | Refused until a consent is on record. **Turn off auto-pay** works any time. | P1 | backend: `test_autopay_needs_the_clients_consent` | |
| TP-E11-013 | Default method and removal | Finance | Two methods | 1. **Make default** on the second.<br>2. **Remove** the first. | Default badge moves; removed method gone. | P2 | No | |
| TP-E11-014 | Auto-pay on issue (card) | Finance | Patel auto-pay on with a fake card | 1. Issue an invoice.<br>2. Temporal UI: `collect:<org>:<invoice>`. | Payment Received; invoice Paid; receipt email. | P1 | backend: `test_card_collected_on_issue` | |
| TP-E11-015 | Declined card retries then tells staff | Finance | Fake method ref containing `fail` | 1. Issue an invoice. | Attempts at issue, +3 and +5 days (`payments.card_retry_days`); client gets a pay-now link after each failure; staff notified on the final one. | P1 | backend: `test_declined_card_retries_then_tells_staff` | |
| TP-E11-016 | Direct debit pending until confirmed | Finance | GoCardless mandate default | 1. Issue an invoice.<br>2. Send a GoCardless `payments.confirmed` webhook. | Payment Pending, then Received; invoice paid only after confirmation. | P1 | backend: `test_direct_debit_is_pending_until_confirmed`, `test_direct_debit_waits_for_confirmation`, `test_gocardless_debit_is_pending_until_the_webhook_confirms` | |
| TP-E11-017 | Collection lock (epic AC) | Finance | Collection in progress (pending debit) | 1. Invoice → **Collect now**. | 409 `collection_in_progress`; message in the UI; no second attempt. | P1 | backend: `test_collect_is_refused_while_a_collection_runs` | |
| TP-E11-018 | Failed debit and cancelled mandate | Finance | GoCardless | 1. Send `payments.failed`, then `mandates.cancelled`. | Payment Failed; retry once; method removed after cancellation. | P2 | backend: `test_failed_debit_and_cancelled_mandate` | |
| TP-E11-019 | 3-D Secure required | Finance | Fake method ref with `3ds` | 1. Issue an invoice with auto-pay. | Counts as a failed attempt; client gets a link to complete. | P2 | backend: `test_collection_attempt_success_and_failure` | |
| TP-E11-020 | Move a client to another provider | Finance | Patel on Stripe card; GoCardless connected | 1. Payment methods → **Move to GoCardless**.<br>2. Complete the emailed setup link.<br>3. Temporal UI: `ProviderMigrationWorkflow`. | New mandate becomes default once added; old card cancelled after no collection is running. Cancelling the migration while waiting stops it. | P2 | backend: `test_provider_migration_steps`, `test_migration_switches_then_cancels_the_old_method` | |

## Pay page (FR-11-4, T05)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E11-021 | Pay page shows the invoice summary | Parent (no sign-in) | Issued invoice; pay link from Mailpit | 1. Open `/pay/<token>`. | "Invoice INV-…", due date, **Amount due**, **Download the invoice (PDF)**, **Pay with** options for connected providers. | P1 | e2e: `e2e/portal-parent.spec.ts` | |
| TP-E11-022 | Pay with PayPal (fake) end to end | Parent | PayPal connected | 1. Pay page → PayPal → pay. | Redirect returns; "Thank you – your payment has been received." Invoice Paid; PayPal fee recorded; capture recorded once even on reload. | P1 | backend: `test_paypal_checkout_is_captured_once_with_its_fee`; e2e: `e2e/portal-parent.spec.ts` | |
| TP-E11-023 | One-off bank payment with GoCardless | Parent | GoCardless connected | 1. Pay page → **Bank (Direct Debit)** → **Continue to GoCardless**. | "Your payment is being processed. We'll email you when it's confirmed." Payment pending until the `payments.confirmed` webhook. | P2 | backend: `test_pay_page_bank_payment_with_gocardless` | |
| TP-E11-024 | Card payment recorded once (fake webhook) | Finance | Issued invoice | 1. Post the fake `payment_intent.succeeded` for the invoice twice. | One payment; invoice Paid; fee and net from the fake balance transaction (1.5% + 20p). | P1 | backend: `test_pay_page_card_payment_is_recorded_once` | |
| TP-E11-025 | Partial payments follow the setting | Parent | `payments.allow_partial` on, then off | 1. Pay page: change the amount. | On: a smaller amount is accepted, invoice Partly paid. Off: the amount is fixed. | P2 | No | |
| TP-E11-026 | Nothing due and invalid links | Parent | Paid invoice; random token | 1. Open the paid invoice link.<br>2. Open `/pay/nonsense`. | "Nothing is owed. Thank you!" / "This payment link isn't valid." | P2 | No | |
| TP-E11-027 | Pay a payment request | Parent | Open PR | 1. Open its pay link and pay (PayPal fake). | Payment request Paid; client credit up by the amount. | P1 | backend: `test_paying_a_payment_request_adds_credit` | |

## Manual payments, allocation, split payments (FR-11-5, FR-11-6, T04, T14)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E11-028 | Record a bank transfer, oldest first | Finance | Patel invoices of £45 (older) and £90 | 1. Client → Billing → Payments → **Record payment**: £100, **How they paid** Bank transfer, reference "PATEL OCT".<br>2. Save. | "Payment recorded." £45 invoice Paid, £55 on the £90 invoice (Partly paid), nothing left as credit. | P1 | backend: `test_manual_payment_pays_oldest_first_and_keeps_the_rest_as_credit`; e2e: `e2e/billing.spec.ts` | |
| TP-E11-029 | Overpayment becomes credit | Finance | £45 open | 1. Record £60 cash. | Invoice Paid; £15 client credit. | P1 | backend: `test_manual_payment_pays_oldest_first_and_keeps_the_rest_as_credit` | |
| TP-E11-030 | Choose which invoices a payment pays | Finance | Two open invoices | 1. Record payment → **Choose which invoices it pays** → pick the newer one. | Only that invoice is paid. | P2 | backend: `test_explicit_allocation_and_reallocation` | |
| TP-E11-031 | Reallocate a payment (audited) | Finance | Allocated payment | 1. Change its allocation. | Allocation replaced; audit log entry. | P2 | backend: `test_explicit_allocation_and_reallocation` | |
| TP-E11-032 | Validation of manual payments | Finance | — | 1. Record £0, a negative amount, or a future date far ahead. | Clear field errors (RFC 7807). | P2 | backend: `test_record_rejects_bad_requests` | |
| TP-E11-033 | Split one receipt across clients | Finance | School pays for Patel and Okafor | 1. Record a split payment (via Bank tab **Split between clients** or `POST /payments/split`): £100 → Patel £45, Okafor £55. | One payment per client, each allocated oldest first; parts must add up to the receipt. | P2 | backend: `test_one_receipt_split_across_clients`, `test_split_parts_must_add_up` | |

## Refunds, disputes, payouts, receipts (FR-11-7 to FR-11-11, T07–T09)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E11-034 | Refund takes credit first then reopens invoices | Finance | Payment of £60 (£45 invoice + £15 credit) | 1. Payment → **Refund** £30, reason.<br>2. Tick **Also credit the invoices it paid** on another run. | £15 credit refunded first, then £15 un-allocated from the invoice which reopens. With the tick, a credit note keeps it closed. Ledger refund entry. | P1 | backend: `test_refund_takes_credit_first_then_reopens_invoices_with_a_credit_note` | |
| TP-E11-035 | Full refund | Finance | Card payment | 1. **Refund**, leave the amount blank. | "Leave blank to refund everything." Status Refunded. | P2 | No | |
| TP-E11-036 | Lost dispute reverses the payment | Finance | Card payment; post `charge.dispute.created` then a lost outcome | 1. Watch the payment and invoice.<br>2. Temporal UI: `DisputeWorkflow`. | Payment Disputed; staff alerted; evidence reminders 3 and 1 day before the deadline; on loss a "Chargeback" refund entry and the invoice reopens. | P2 | backend: `test_lost_dispute_reverses_the_payment_and_reopens_the_invoice` | |
| TP-E11-037 | Payouts listed with fees | Finance | Fake `payout.paid` webhook / GoCardless `payouts.paid` | 1. `/billing` → Payments → payouts. | Payout row with gross, fees, net; GoCardless fees written onto payments. | P3 | backend: `test_payouts_and_receipts`, `test_payouts_record_gocardless_fees_on_the_payments` | |
| TP-E11-038 | Receipt PDF and email | Finance, Parent | `payments.send_receipts` on | 1. Record a payment.<br>2. Payment → **Receipt**. | Mailpit has a receipt PDF; the receipt downloads; visible in the portal. | P2 | backend: `test_payouts_and_receipts` | |

## Bank reconciliation (FR-11-5, T13)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E11-039 | Import a CSV statement with suggested matches | Finance | Open invoice INV-0005 £45; CSV with a line "INV-0005 PATEL" £45.00 | 1. `/billing` → Bank → **Import a bank statement** → file → **Import**. | "N new lines imported (0 already imported)". The line shows **Suggested match**, "100% sure". | P1 | backend: `test_csv_import_suggests_invoice_matches_and_is_idempotent` | |
| TP-E11-040 | Re-import adds nothing | Finance | Same file | 1. Import again. | "0 new lines imported (N already imported)". | P1 | backend: `test_csv_import_suggests_invoice_matches_and_is_idempotent` | |
| TP-E11-041 | Confirm, ignore, reopen | Finance | Suggested lines | 1. **Confirm** one; **Ignore** another; **Put back in the queue**. | Confirm records a bank-transfer payment and the invoice is paid; ignored line hidden from the queue; reopened returns. | P1 | backend: `test_bank_line_split_between_clients_and_ignore` | |
| TP-E11-042 | Split a bank line between clients | Finance | £100 line | 1. **Split between clients** → Client 1 Patel £45, Client 2 Okafor £55 → **Record split payment**. | Two payments recorded. | P2 | backend: `test_bank_line_split_between_clients_and_ignore` | |
| TP-E11-043 | OFX, CAMT.053 and US dates | Finance | Sample files; CSV with month-first dates | 1. Import each; tick **Dates are month first (US)** for the US file. | Parsed correctly. A file with a DTD or entities is refused. | P2 | backend: `test_ofx_and_camt_parsing` | |
| TP-E11-044 | Open Banking feed (fake bank) | Finance | Connect the Open Banking integration (E22 marketplace) | 1. **Sync bank feed**.<br>2. Temporal UI: `BankFeedSyncWorkflow` schedule. | Lines imported and matched; a daily schedule exists; disconnecting deletes it. | P3 | backend: `test_open_banking_feed_imports_and_matches`, `test_bank_feed_sync_workflow` | |

## Permissions

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E11-045 | Coordinator cannot record payments | Coordinator | — | 1. Open a client's Billing → Payments.<br>2. Try `POST /api/v1/payments`. | No **Record payment** button; 403. | P1 | backend: `test_coordinators_cannot_record_payments` | |
| TP-E11-046 | Only owner/finance manage providers | Admin (office@), Finance, Coordinator | — | 1. Open `/settings/payments` as each. | Owner, Admin and Finance can manage; Coordinator has no nav item and gets no access. | P1 | e2e: `e2e/roles.spec.ts` | |
| TP-E11-047 | Tutor and parent can't see others' payments | Tutor, Parent | — | 1. Tutor tries `/api/v1/payments`; parent opens portal billing. | Tutor 403; parent sees only Patel payments. | P1 | No | |

## Tenant isolation

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E11-048 | Payments of another org return 404 | Owner of Northside | Bright Minds payment id | 1. GET `/api/v1/payments/<id>` on northside.localhost. | 404. | P1 | backend: `test_detail_of_other_organisation_is_404` | |
| TP-E11-049 | Invoices are not payable across tenants | Parent | Bright Minds pay token | 1. Open `http://northside.localhost:5173/pay/<token>`. | "This payment link isn't valid." | P1 | backend: `test_invoices_are_not_payable_across_tenants` | |
| TP-E11-050 | Webhooks route only to the owning org | Owner | Fake webhook for a Bright Minds account | 1. Post it; check Northside. | Only Bright Minds data changes (AccountRoute). | P2 | backend: `test_webhooks_need_a_valid_signature_and_known_account` | |

## Currency and edge cases

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E11-051 | Payment in the invoice currency only | Finance | EUR invoice | 1. Record a payment in GBP against it. | Refused, or allocated only to invoices in the payment's currency. | P2 | No | |
| TP-E11-052 | Amounts never use floats | Finance | Pay £33.33 three times on £99.99 | 1. Record three payments. | Invoice exactly Paid; balance £0.00. | P2 | No | |
| TP-E11-053 | PCI scope: no card fields in our DOM | Security reviewer | Real Stripe test key (optional) | 1. Open the pay page; inspect the DOM. | Card fields are inside Stripe iframes only; the CSP allows js.stripe.com and 3-D Secure frames. | P2 | No | |
| TP-E11-054 | Booking payment hook | Owner | — | 1. Use the self-booking flow that needs payment (E08). | A payment request pay URL is returned; when paid it becomes credit used by the lesson. | P3 | backend: `test_booking_payment_hook_returns_a_pay_link` | |

## Gap batch G3 (as built 2026-10-14)

Built by gap batch G3 ([ADR 0037](../adr/0037-gap-batch-g3-scheduling-billing-payments-payroll.md)); see the epic's *Gap backlog* notes.

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E11-055 | Payment methods per branch | Owner | Settings → Payments → Ways each branch takes payment | 1. Untick Card for the branch → save.<br>2. Open an invoice's pay page. | Card isn't offered; staff can't record a disabled manual method. | P1 | backend: `test_pay_page_offers_only_enabled_providers`, `test_manual_payment_methods_follow_the_branch` | |
| TP-E11-056 | Card surcharge where legal | Owner, Family | Organisation country US; surcharge 2% | 1. Pay a £40 invoice by card on the pay page. | Charged £40.80; the invoice stays £40 and paid; a separate £0.80 "Card surcharge" invoice is issued and paid. | P1 | backend: `test_card_surcharge_is_charged_and_invoiced_separately` | |
| TP-E11-057 | Surcharge refused in the UK/EEA or above the cap | Owner | Country GB (then US with 3.5%) | 1. Set a surcharge. | Refused with the reason. | P1 | backend: `test_surcharge_setting_is_refused_where_banned_or_too_high` | |
| TP-E11-058 | Expiring-card notice | Family | Saved card expiring this month | 1. Run the monthly card check. | One email with a link to add a new card; running again sends nothing. | P2 | backend: `test_expiring_cards_are_told_once` | |
| TP-E11-059 | Auto-pay before the due date | Finance | Auto-pay timing "A number of days before it is due", 3 | 1. Issue an invoice due in 14 days to an auto-pay client. | Collection waits until 3 days before due; **Collect now** collects at once. | P1 | backend: `test_autopay_waits_until_days_before_due`, `test_collect_now_skips_the_wait` | |
| TP-E11-060 | Bulk payment entry | Finance | Two clients with open invoices | 1. Billing → **Record payments** → fill two rows → **Record 2 payments**. | Both recorded, oldest invoices paid; a bad row refuses the whole batch with the row marked. | P1 | backend: `test_bulk_entry_records_every_row_or_none`; vitest: `G3.test.tsx` records several payments | |
