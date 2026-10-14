# E23 — Accounting integrations: manual tests

**Scope.** Connecting Xero or QuickBooks Online, account, tax and tracking mappings, one-way sync of contacts, invoices, credit notes, write-offs, payments, refunds, payouts with fees, tutor bills and bill payments, summary-journal mode, backfill, lock dates, the sync dashboard with retry/skip and digests, GL exports (generic CSV, Sage 50, MYOB, IIF), Phase 2b read-back of payments recorded in the ledger, and Phase 3 Sage Business Cloud, FreeAgent and Xero Payroll (T10). Spec: [E23](../epics/E23-accounting-integrations.md); decisions in [ADR 0018](../adr/0018-accounting-sync-on-the-integration-framework.md).

**Built differently from the spec (Implementation notes win):**
- One ledger per organisation; branches become tracking categories/classes (no per-branch ledgers).
- No `AccountingSyncJob` table: the queue is Temporal (`AccountingSyncWorkflow`).
- Reallocations of an already-synced payment and lost disputes are not sent. Write-offs carry no VAT adjustment. Summary journals skip non-base currencies. Expenses are lines on the tutor's bill.
- Read-back (T09) runs only in individual mode.

**Common preconditions.**
- Stack running and seeded (see [README](README.md)); admin http://brightminds.localhost:5173. Password: `SEED_ADMIN_PASSWORD` (default `tutortrack`). Use finance@tutortrack.localhost unless stated.
- The trial carries the Agency plan, so `accounting_integrations` is on.
- **Fake ledger:** with `XERO_*`/`QUICKBOOKS_*` empty, connecting goes through the fake OAuth (instant consent) to a simulated company. The page says "No Xero or QuickBooks keys are set up, so a simulated ledger stands in". Its chart: 090 Business Bank Account, 091 Stripe Clearing, 092 Cash and Cheques Clearing, 200 Tuition Sales, 210 Other Revenue, 310 Tutor Costs, 404 Bank and Payment Fees, 420 Tutor Expenses, 684 Bad Debts, 800 Accounts Payable, 820 VAT, 860 Rounding; tax codes OUTPUT2 (20%), ZERORATEDOUTPUT, EXEMPTOUTPUT, INPUT2, NONE; tracking "Branch" (Main, North).
- **Steering the fake ledger** from a Django shell (`cd backend && uv run python manage.py shell`):
  ```python
  from datetime import date
  from tutortrack.core.context import tenant_context
  from tutortrack.tenancy.models import Organisation
  from tutortrack.integrations.models import IntegrationConnection
  from tutortrack.accounting.providers.fake import FakeLedger
  from tutortrack.integrations.providers.fake import fail
  org = Organisation.objects.get(slug="brightminds")
  with tenant_context(org):
      conn = IntegrationConnection.objects.filter(provider="xero").latest("created_at")
  ledger = FakeLedger(conn.external_account_id)
  ledger.records("invoices")            # what reached the ledger
  ledger.archive("200")                 # archive an account
  ledger.set_lock_date(date(2026, 9, 30))
  ledger.record_payment("<ledger invoice id>", "20.00", "2026-10-14", reference="BACS")  # T09
  fail("xero", 3)                       # next 3 calls fail
  ```
- Fake Stripe for card payments; payouts via the payments fakes (see E11 tests in the README). Temporal worker running; sync workflows `acct-sync:<org>:...` and the daily schedule are visible at http://localhost:8233.

## Connection and mappings (FR-23-1, T02, T05)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E23-001 | Connect Xero and fetch the chart | Finance | finance@ | 1. **Settings → Accounting** (`/settings/accounting`), **Connect Xero**. | Returns connected: company name, base currency GBP, lock date (if any). Accounts, tax codes and tracking are fetched. "Connected. Choose your accounts below, then switch sync on." | P1 | backend: `tutortrack/accounting/tests/test_accounting.py::test_connecting_fetches_the_chart_and_needs_complete_mappings` | |
| TP-E23-002 | Connect QuickBooks Online | Finance | Disconnect Xero first | 1. **Connect QuickBooks Online**. | Connected; the company (realm) id is taken from the callback. | P1 | backend: `tutortrack/accounting/tests/test_clients.py::test_the_oauth_callback_forwards_the_quickbooks_company` | |
| TP-E23-003 | Sync can't start until mappings are complete | Finance | Connected, nothing mapped | 1. Click **Switch sync on**. | Refused; **Before sync can start:** lists missing mappings. | P1 | backend: `tutortrack/accounting/tests/test_accounting.py::test_connecting_fetches_the_chart_and_needs_complete_mappings` | |
| TP-E23-004 | Map accounts, taxes and tracking | Finance | Connected | 1. Map sales → 200, clearing (Stripe) → 091, bank → 090, fees → 404, tutor costs → 310, payables → 800, bad debt → 684, rounding → 860.<br>2. Map tax rates (20% → OUTPUT2, zero → ZERORATEDOUTPUT); tax for VAT on self-billing → INPUT2.<br>3. Map branch MAIN → Main.<br>4. **Save mappings**. | "All required accounts and tax codes are mapped." | P1 | backend: `tutortrack/accounting/tests/test_accounting.py::test_connecting_fetches_the_chart_and_needs_complete_mappings` | |
| TP-E23-005 | Specific accounts per service, product or method | Finance | Mappings | 1. Under **Different accounts by service, product or payment method**, map "Sales: Piano lesson" → 210. | Piano invoices post to 210; others to 200. | P2 | No | |
| TP-E23-006 | Unknown or archived accounts | Finance | Shell: `ledger.archive("210")` then **Refresh accounts** | 1. Try to map to an unknown code via the API.<br>2. Look at the 210 mapping. | Unknown refused; archived account flagged in problems. | P2 | backend: `tutortrack/accounting/tests/test_accounting.py::test_mapping_an_unknown_account_is_refused_and_archived_accounts_are_flagged` | |
| TP-E23-007 | Sync options | Finance | Connected | 1. Set **Sales** = Each invoice, **Sync from** today, **Send tutor bills and payouts** on, **Attach our invoice PDF** on, lock behaviour **Post on the first open date, with a note**.<br>2. **Switch sync on**. | "Sync is on for records from <date>." A daily schedule (03:30 UK time) is created in Temporal. | P1 | backend: `tutortrack/accounting/tests/test_workflows.py::test_the_daily_run_is_a_schedule_that_follows_the_sync_switch` | |
| TP-E23-008 | Disconnecting switches sync off | Finance | Sync on | 1. **Disconnect**. | Sync off; schedule removed; mappings kept for reconnect. | P2 | backend: `tutortrack/accounting/tests/test_accounting.py::test_disconnecting_switches_sync_off` | |

## What syncs (FR-23-2, T03, T04)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E23-009 | Issued invoice syncs after its contact | Finance | Sync on; Patel family | 1. Issue an invoice for Priya Patel (2 × GCSE Maths 1:1 60 min = £90.00 + VAT if registered).<br>2. Open the invoice. | Badge "In Xero". Ledger: contact Priya Patel, then an invoice with the same number, tax-exclusive lines on 200 with OUTPUT2, tracking Main; PDF attached. | P1 | backend: `tutortrack/accounting/tests/test_workflows.py::test_an_issued_invoice_syncs_after_its_contact_and_the_payment_after_both` | |
| TP-E23-010 | Part-payment by card, refund and payout keep balances in step | Finance, Parent | TP-E23-009 | 1. Parent pays £50.00 by card (fake Stripe, with a fee).<br>2. Finance refunds £20.00.<br>3. Simulate the Stripe payout (fake).<br>4. Compare balances after each step. | Ledger: one invoice, one payment (reference with the invoice number), one refund, fee entries on payout (one net bank transfer 091 → 090 plus fees as spend money on 404). The ledger's amount due equals TutorTrack's at each step. (AC FR-23-3) | P1 | backend: `tutortrack/accounting/tests/test_accounting.py::test_invoice_payment_refund_and_payout_keep_the_ledger_balance_in_step` | |
| TP-E23-011 | QuickBooks equivalents | Finance | QuickBooks connected | 1. Repeat TP-E23-010. | Invoice, ReceivePayment, RefundReceipt; payout as one deposit with a negative fee line. | P2 | backend: `tutortrack/accounting/tests/test_accounting.py::test_invoice_payment_refund_and_payout_keep_the_ledger_balance_in_step`, `tutortrack/accounting/tests/test_clients.py::test_quickbooks_payout_is_a_deposit_with_a_negative_fee_line` | |
| TP-E23-012 | Syncing again is a no-op; changes update | Finance | Synced invoice and contact | 1. Retry the synced invoice.<br>2. Change Priya's billing address. | 1: no new ledger call. 2: contact updated. | P2 | backend: `tutortrack/accounting/tests/test_accounting.py::test_syncing_again_is_a_no_op_and_changes_update` | |
| TP-E23-013 | Client credit applied to a later invoice | Finance | Overpayment on account | 1. Issue a new invoice that uses the credit. | The overpayment is allocated in the ledger. | P2 | backend: `tutortrack/accounting/tests/test_accounting.py::test_client_credit_applied_to_a_later_invoice` | |
| TP-E23-014 | Credit note and write-off | Finance | Issued invoices | 1. Issue a credit note on one.<br>2. Write another off. | Credit note allocated to the invoice; write-off as a credit note to 684 Bad Debts. | P1 | backend: `tutortrack/accounting/tests/test_accounting.py::test_credit_note_and_write_off` | |
| TP-E23-015 | Voided invoice | Finance | Synced invoice | 1. Void it. | Voided in the ledger. | P2 | backend: `tutortrack/accounting/tests/test_accounting.py::test_voided_invoice_is_voided_in_the_ledger` | |
| TP-E23-016 | Tutor bills and bill payments | Finance | Self-employed Nia with an approved pay run (E12) | 1. Approve the pay run.<br>2. Mark the payout paid. | Supplier Nia; one bill (number = self-billing number), lines grouped by pay item kind on 310, expenses on 420, INPUT2 for self-billing VAT; then a bill payment. | P1 | backend: `tutortrack/accounting/tests/test_accounting.py::test_tutor_bills_and_bill_payments` | |
| TP-E23-017 | Employees aren't billed | Finance | Tutor with employment type employee | 1. Approve a pay run. | No bill for the employee. | P2 | backend: `tutortrack/accounting/tests/test_accounting.py::test_employees_are_not_billed` | |
| TP-E23-018 | Drafts and older records are skipped | Finance | Start date today; a draft invoice; an invoice issued yesterday | 1. Check the dashboard. | Draft never sent; yesterday's invoice **Skipped** (unless backfilled). | P2 | backend: `tutortrack/accounting/tests/test_accounting.py::test_drafts_and_records_before_the_start_date_are_skipped` | |

## Engine, errors and lock dates (FR-23-3, T01, T07)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E23-019 | Archived account is a readable error until re-mapped | Finance | Shell: `ledger.archive("200")` | 1. Issue an invoice.<br>2. Open **Sync status → Needs attention**.<br>3. Re-map sales to 210 and click **Retry**. | Error: "Account code 200 is archived in Xero. Choose another account in the mappings, then retry." After retry: synced. The invoice badge says "Xero sync error" with the reason until fixed. | P1 | backend: `tutortrack/accounting/tests/test_accounting.py::test_archived_account_is_a_readable_error_until_remapped`, `tutortrack/accounting/tests/test_workflows.py::test_an_error_waits_for_retry_after_remapping` | |
| TP-E23-020 | Missing mapping waits; dependents say so | Finance | Remove a tax mapping | 1. Issue an invoice and take a payment. | Invoice error `tax_mapping_missing`; the payment shows it is waiting for the invoice. | P2 | backend: `tutortrack/accounting/tests/test_accounting.py::test_missing_mapping_waits_and_dependents_say_so` | |
| TP-E23-021 | Skip from the dashboard | Finance | An error | 1. Click **Skip**.<br>2. Later click **Retry**. | Skipped until retried; the waiting workflow ends on skip. | P2 | backend: `tutortrack/accounting/tests/test_accounting.py::test_skip_from_the_dashboard`, `tutortrack/accounting/tests/test_workflows.py::test_skip_ends_a_waiting_sync` | |
| TP-E23-022 | Retry all | Finance | Several errors | 1. Click **Retry all**. | Every error retried. | P3 | backend: `tutortrack/accounting/tests/test_accounting.py::test_retry_failed_retries_every_error` | |
| TP-E23-023 | Transient failures retry with backoff | Finance | Shell: `fail("xero", 3)` | 1. Issue an invoice; watch the workflow. | Retried automatically; ends synced. | P2 | backend: `tutortrack/accounting/tests/test_workflows.py::test_transient_failures_are_retried_with_backoff` | |
| TP-E23-024 | Revoked access needs reconnecting | Finance | Revoke the fake grant (`fail("xero", 1, auth=True)`) | 1. Issue an invoice. | Error `reconnect`; the page asks to reconnect. | P2 | backend: `tutortrack/accounting/tests/test_accounting.py::test_transient_failures_raise_for_retry_and_revoked_access_needs_reconnecting` | |
| TP-E23-025 | Lock date: post to first open date | Finance | Shell: `ledger.set_lock_date(...)` after an invoice date; **Refresh accounts** | 1. Sync an invoice dated in the locked period. | Posted on the first open date with the note "Originally dated …". | P1 | backend: `tutortrack/accounting/tests/test_accounting.py::test_lock_dates` | |
| TP-E23-026 | Lock date: hold | Finance | Lock behaviour = hold | 1. Sync the same. | Held as a `period_locked` error until unlocked and retried. | P2 | backend: `tutortrack/accounting/tests/test_accounting.py::test_lock_dates`, `::test_period_locked_in_the_ledger_is_explained` | |
| TP-E23-027 | Rate-limit budget | Finance | Many invoices (invoice run of 100) | 1. Issue them together. | All sync within our budget (Xero 55/min); no provider 429 errors shown as failures. | P3 | backend: `tutortrack/accounting/tests/test_accounting.py::test_our_rate_limit_budget` | |
| TP-E23-028 | Error digest | Finance | Errors open; `accounting.error_digest` on | 1. Let the daily run happen (or trigger the schedule in the Temporal UI). | Finance gets one `accounting_sync_errors` email listing errors. | P3 | backend: `tutortrack/accounting/tests/test_accounting.py::test_reconciliation_flags_payments_recorded_in_the_ledger_and_digests_errors` | |
| TP-E23-029 | Sync badges in lists | Finance | Mixed statuses | 1. Open **Billing** invoice list and payments list. | Badges: In Xero / Syncing to Xero / Xero sync error / Not sent to Xero. | P2 | backend: `tutortrack/accounting/tests/test_accounting.py::test_records_filter_by_object_for_sync_badges` | |

## Summary journals and backfill (T06)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E23-030 | Daily summary journal | Finance | **Sales** = A daily summary journal; yesterday's invoices, payments, refunds and fees | 1. Trigger the daily schedule in the Temporal UI. | One balanced manual journal in GBP grouped by account, tax code and tracking, with a VAT liability line (820) and a rounding line if needed. Payouts and bills still sync individually. | P1 | backend: `tutortrack/accounting/tests/test_accounting.py::test_summary_mode_posts_a_balanced_daily_journal`, `tutortrack/accounting/tests/test_workflows.py::test_daily_run_posts_the_summary_journal` | |
| TP-E23-031 | Backfill history | Finance | Sync off; invoices from last month | 1. Enter **Also send history from** = first of last month, **Switch sync on**.<br>2. Watch progress; click **Stop** midway once. | "Sending history: N sent, M with errors so far" → "History sent" (or "stopped after N records"). Batches paced; resumable. | P2 | backend: `tutortrack/accounting/tests/test_accounting.py::test_backfill_batches_are_resumable`, `tutortrack/accounting/tests/test_workflows.py::test_backfill_pages_through_history_in_paced_batches` | |
| TP-E23-032 | Reconciliation check | Finance | Shell: change an invoice balance in the fake ledger | 1. Run the daily job. | The difference is logged on the record (log and meta). | P3 | backend: `tutortrack/accounting/tests/test_accounting.py::test_reconciliation_flags_payments_recorded_in_the_ledger_and_digests_errors` | |

## GL exports (FR-23-5, T08)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E23-033 | Generic GL journal CSV | Finance | **Account codes for exports** filled; invoices and payments this month | 1. **General ledger export**: From/To this month, format **Generic GL journal (CSV)**, **Download export**. | CSV with date, account, debit, credit, tax code, tax, currency, reference; debits equal credits. The export is audited (`gl_export`). | P1 | backend: `tutortrack/accounting/tests/test_accounting.py::test_generic_gl_export_balances` | |
| TP-E23-034 | Sage 50, MYOB and IIF formats | Finance | As above | 1. Download each format. | Sage 50 JD/JC rows, MYOB general journal, QuickBooks Desktop IIF; each opens in a text editor with the right headers. | P2 | backend: `tutortrack/accounting/tests/test_accounting.py::test_package_exports` | |
| TP-E23-035 | Exports need permission and mappings | Coordinator | coordinator@ | 1. Try the export endpoint. | 403. Finance without export codes gets a clear "map export codes" error. | P2 | backend: `tutortrack/accounting/tests/test_accounting.py::test_exports_need_the_permission_and_mappings` | |

## Read-back of ledger payments (FR-23-4, T09, Phase 2b)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E23-036 | Import a payment recorded in the ledger | Finance | Individual mode; synced unpaid invoice; **Import payments recorded directly in Xero** on; shell: `ledger.record_payment(<id>, "20.00", "2026-10-14", reference="BACS")` | 1. Click **Check now**. | "Checked N invoices: 1 payments imported, 0 …". A manual payment of £20.00 dated 14 October 2026 is allocated to the invoice; the list shows **Recorded in TutorTrack**; the invoice sync log has an `imported` entry. | P1 | backend: `tutortrack/accounting/tests/test_read_back.py::test_payment_recorded_in_the_ledger_is_imported_once` | |
| TP-E23-037 | Imported once; never pushed back | Finance | TP-E23-036 | 1. **Check now** again; check the dashboard. | Nothing new imported; the imported payment is already "synced" and not sent to Xero. | P1 | backend: `tutortrack/accounting/tests/test_read_back.py::test_payment_recorded_in_the_ledger_is_imported_once` | |
| TP-E23-038 | Our own payments aren't imported | Finance | Card payment synced from TutorTrack | 1. **Check now**. | Not imported. | P2 | backend: `tutortrack/accounting/tests/test_read_back.py::test_payments_tutortrack_sent_are_not_imported` | |
| TP-E23-039 | Payments that don't fit are skipped with a reason | Finance | Ledger payment larger than owed; or invoice no longer open | 1. **Check now**. | **Not recorded** with the reason. | P2 | backend: `tutortrack/accounting/tests/test_read_back.py::test_payments_that_do_not_fit_are_skipped_with_a_reason` | |
| TP-E23-040 | Off by default; not in summary mode | Finance | Toggle off; or summary mode | 1. Look for **Check now**. | Off: no import on the daily run. Summary mode: explanatory message, no read-back. | P2 | backend: `tutortrack/accounting/tests/test_read_back.py::test_read_back_is_off_unless_switched_on` | |

## Sage Business Cloud, FreeAgent and Xero Payroll (T10 — Phase 3)

With `SAGE_*` / `FREEAGENT_*` empty, Sage and FreeAgent connect through the fake OAuth to the same simulated ledger as Xero (same chart and tax codes; the banner still says "No Xero or QuickBooks keys are set up, so a simulated ledger stands in for the real one."). Steer it with the shell snippet above, using `provider="sage"` or `provider="freeagent"`. Xero Payroll uses an in-memory fake that has **no employees** in development, so matching and sending timesheets can only be checked end to end in automated tests.

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E23-041 | Connect Sage Business Cloud (fake) | Finance | Sage keys empty; no ledger connected (disconnect Xero first: one ledger per organisation) | 1. **Settings → Accounting** → **Connect Sage Business Cloud Accounting**.<br>2. **Switch sync on** before mapping, then map as in TP-E23-004 and switch it on. | 1: connected to a simulated company; chart, tax codes and tracking fetched; mappings are kept per provider (`sage`). 2: refused with **Before sync can start:** listing missing mappings; then sync on. | P2 | backend: `tutortrack/accounting/tests/test_phase3.py::test_new_ledgers_connect_and_need_complete_mappings` | |
| TP-E23-042 | Sage: invoice, payment, refund and payout in step | Finance, Parent | TP-E23-041 with sync on | 1. Repeat TP-E23-009 and TP-E23-010 with Sage.<br>2. Shell: `ledger.records("invoices")` on the Sage connection. | Sync badges and dashboard as for Xero; the invoice, part payment with fee, refund and payout reach the ledger and balances match at each step. (Against the real API: sales invoice, contact payment allocated per invoice, payout as a bank transfer plus an "other payment" for fees; checked by request-shape tests.) | P2 | backend: `tutortrack/accounting/tests/test_phase3.py::test_new_ledgers_keep_the_invoice_balance_in_step`, `::test_sage_invoice_and_payment_requests` | |
| TP-E23-043 | Connect FreeAgent (fake) | Finance | FreeAgent keys empty; no other ledger connected | 1. **Settings → Accounting** → **Connect FreeAgent**.<br>2. **Switch sync on** before mapping, then map and switch it on. | 1: connected to a simulated company. 2: refused until mappings are complete, then sync on. | P2 | backend: `tutortrack/accounting/tests/test_phase3.py::test_new_ledgers_connect_and_need_complete_mappings` | |
| TP-E23-044 | FreeAgent: invoice, credit note, payment | Finance | TP-E23-043 with sync on | 1. Issue an invoice, issue a credit note on another, take a payment and refund part of it.<br>2. Open **Sync status**. | Each record synced (badges "In FreeAgent"); credit note allocated to its invoice; balances in step. (Against the real API: invoices marked as sent, bank transaction explanations for payments, refunds and payouts; checked by request-shape tests.) Payment read-back (T09) can't be switched on for Sage or FreeAgent. | P2 | backend: `tutortrack/accounting/tests/test_phase3.py::test_new_ledgers_keep_the_invoice_balance_in_step`, `::test_freeagent_invoice_is_created_then_marked_as_sent` | |
| TP-E23-045 | Xero Payroll for employed tutors | Finance | A tutor with employment type employee and approved hours; a self-employed tutor; ledger sync on with tutor bills | 1. **Settings → Accounting** → **Xero Payroll for employed tutors** (`/settings/accounting/payroll`) → **Connect Xero Payroll** (fake consent).<br>2. Pick **Earnings rate for tutors' hours**; **Match tutors by email**.<br>3. Approve the pay run.<br>4. **Send again** on the result. | 1: "Xero Payroll is connected." (a separate connection with payroll scopes only). 2: rates "Ordinary Hours (default)" / "Overtime Hours"; with the fake's empty employee list the employed tutor stays under "Tutors not linked to a Xero employee". 3: **Timesheets sent** shows the run as **Sent with problems** (`no_employee` for the unlinked tutor); bonuses and reimbursements are listed for the payroll administrator, not sent. The self-employed tutor still gets a bill in the ledger; the employee never does (TP-E23-017). 4: sent again without duplicating timesheets. A linked employee getting one draft timesheet with a line per day is covered by automated tests. | P2 | backend: `tutortrack/accounting/tests/test_phase3.py::test_xero_payroll_sends_employed_tutors_hours_as_timesheets`, `::test_xero_payroll_api_links_rates_and_retry`, `::test_xero_payroll_client_requests`; `tutortrack/accounting/tests/test_phase3_workflows.py::test_approving_a_pay_run_sends_the_timesheets` | |
| TP-E23-046 | Provider errors are explained | Finance | Sage or FreeAgent connected with sync on | 1. Shell: `ledger.archive("200")` on that connection, then issue an invoice.<br>2. Shell: `fail("sage", 3)` (or `"freeagent"`), then issue another.<br>3. Re-map sales and **Retry**; **Skip** another error. | 1: finance-language error on **Sync status → Needs attention** naming the archived account (as TP-E23-019, with the provider's name). 2: retried automatically and synced. 3: retry and skip work as for Xero. | P3 | backend: `tutortrack/accounting/tests/test_phase3.py::test_new_ledgers_keep_the_invoice_balance_in_step` (fakes); error handling shared with Xero: `tutortrack/accounting/tests/test_accounting.py` | |

## Permissions

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E23-047 | Only Finance and Admins connect ledgers | Coordinator, Finance | coordinator@, finance@ | 1. Coordinator opens **Settings → Accounting** and tries **Connect Xero**.<br>2. Finance does the same. | Coordinator: no Accounting menu item; API 403. Finance: allowed (`integrations.accounting.manage`). | P1 | backend: `tutortrack/accounting/tests/test_accounting.py::test_only_finance_and_admins_connect_ledgers` | |
| TP-E23-048 | Tutors and families never see accounting | Tutor, Parent | tutor@, parent@ | 1. Open `/settings/accounting`. | Refused. | P2 | No | |

## Tenant isolation

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E23-049 | Connections and records per organisation | Owner (Northside) | owner@northside.localhost | 1. Open accounting in Northside; request brightminds record ids. | Nothing from brightminds; 404. Brightminds invoices never reach Northside's ledger. | P1 | backend: `tutortrack/accounting/tests/test_accounting.py::TestConnectionIsolation`, `::TestRecordIsolation`, `tutortrack/accounting/tests/test_read_back.py::TestPaymentImportIsolation` | |

## i18n, time zones and currency

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E23-050 | Dates and amounts | Finance | Synced records | 1. Check posted dates around midnight UK time and amounts. | Ledger dates are the organisation's local date (an invoice issued at 00:30 BST is dated that day, not the previous UTC day); amounts to the penny, no float artefacts. | P1 | backend: `tutortrack/accounting/tests/test_clients.py::test_xero_dates_and_lock_date` | |
| TP-E23-051 | Non-base currency in summary mode | Finance | An EUR invoice | 1. Run the daily journal. | Skipped (documented deviation) and visible as skipped. | P3 | No | |

## Errors and edge cases

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E23-052 | Credit note waits for the refund | Finance | A refund that issues a credit note | 1. Refund; watch both records. | The credit note syncs after the refund reopens the invoice. | P3 | No | |
| TP-E23-053 | Switching sync off mid-backfill | Finance | Backfill running | 1. **Switch sync off**. | Backfill stops; nothing half-posted. | P3 | No | |

## Gap batch G3 (as built 2026-10-14)

Built by gap batch G3 ([ADR 0037](../adr/0037-gap-batch-g3-scheduling-billing-payments-payroll.md)); see the epic's *Gap backlog* notes.

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E23-054 | Package sales as deferred revenue | Finance | Accounting → Package sales on; deferred revenue account mapped | 1. Sell and pay a package.<br>2. Complete a lesson that uses it.<br>3. Export the GL journal. | The sale credits deferred revenue; the lesson day moves its share to package revenue (balanced). | P1 | backend: `accounting/tests/test_g3_deferred.py` | |
| TP-E23-055 | Daily package journal in individual mode | Finance | Individual mode | 1. Next day's housekeeping. | A `package_revenue` journal syncs for the day. | P2 | backend: `test_individual_mode_daily_package_journal` | |
