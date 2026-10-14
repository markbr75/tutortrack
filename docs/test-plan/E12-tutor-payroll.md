# E12 — Tutor payroll: manual tests

**Scope.** Pay settings and tutor pay profiles (encrypted bank details), pay items from lessons, cancellations, paid events, ad hoc charge shares and expenses, holds (overdue report, client unpaid, compliance, manual), expenses and mileage, pay runs with review and dual approval, self-billing statements and remittance, bank files, Stripe Connect Express payouts (fake), payroll exports, and the tutor earnings pages. Phase 3 (E12-T12: Wise payouts, 1099 data, commission pay) is being built now. Spec: [E12](../epics/E12-tutor-payroll.md).

**Built differently from the spec (Implementation notes win):**
- Item statuses are `ready → in_pay_run → approved → paid`, plus `held` and `void` (no "pending").
- Pay methods: `stripe_connect`, `bank_file`, `manual`, `external_payroll` (Wise only after Phase 3). Tax IDs stay on the tutor record.
- Full bank details need `payroll.bank_details.view`, a re-authentication in the last 5 minutes (G3) and are audited.
- Payroll settings (`payroll.*`: pay period, cut-off, pay when client paid, hold on overdue reports, dual-approval threshold, bank file format, expense markup...) have **no admin screen**: use `PATCH /api/v1/settings/payroll`.
- Stripe payouts use a fake unless `PAYROLL_STRIPE_PAYOUTS` is on. Mileage uses straight line × 1.25 without a Google key.
- `PayRunWorkflow` and `ExpenseApprovalWorkflow` run on Temporal.

**Common preconditions.** Stack with Celery and Temporal workers; seed loaded. Nia Adeyemi (tutor@) has completed GCSE Maths lessons (£28/h pay). Screens: `/payroll` (Pay runs), `/payroll/runs/<id>`, `/payroll/expenses` (Expense claims), `/payroll/items` (Pay items), tutor record → Pay card; tutor portal `/portal/tutor/earnings`, `/portal/tutor/expenses`.

## Pay profiles and settings (FR-12-2, T01)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E12-001 | Tutor adds UK bank details | Tutor (tutor@) | — | 1. Portal → Earnings → **Pay details**.<br>2. **Name on the account** "Nia Adeyemi", **Sort code** 20-00-00, **Account number** 55779911.<br>3. **Save bank details**. | Saved; shows "Bank account ••••9911" (masked). | P1 | backend: `test_bank_details_are_normalised_and_masked` | |
| TP-E12-002 | Invalid bank details are rejected | Tutor | — | 1. Enter sort code 12-34 or a 6-digit account number.<br>2. (Via API) a bad IBAN, US routing or AU BSB. | Field errors; nothing saved. | P1 | backend: `test_bank_details_are_validated` | |
| TP-E12-003 | Staff see masked details; full view audited | Finance (finance@) | TP-E12-001 | 1. Tutor record → Pay card.<br>2. Request the full view (`?full=true`). | Masked by default. Full view works for Finance and is in the audit log; Coordinator gets 403. | P1 | backend: `test_pay_profile_api_masks_bank_details_and_audits_full_view` | |
| TP-E12-004 | Self-billing agreement | Tutor | — | 1. Pay details → read the self-billing text → **I agree to self-billing**. | "You've agreed to self-billing." Staff Pay card shows "Self-billing agreed" (version recorded). | P1 | backend: `tutortrack/payroll/tests/test_payroll.py` | |
| TP-E12-005 | VAT-registered tutor | Finance | Profile with VAT number | 1. Set VAT registered on Nia's profile. | Pay card shows "VAT <number>"; statements add VAT at `payroll.self_billing_vat` %. | P2 | No | |

## Pay items and holds (FR-12-1, T02, T03)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E12-006 | Completed lesson creates lesson pay | Finance | Complete a 60-min Arjun lesson (E09) | 1. `/payroll/items`. | Nia: £28.00 lesson pay, status Ready. | P1 | backend: `test_completed_lesson_creates_lesson_pay` | |
| TP-E12-007 | Changing a lesson replaces open pay, adjusts paid pay | Coordinator | One item Ready, one already Paid | 1. Change the duration of both lessons to 90 min. | Ready item replaced with £42.00. Paid item untouched; an adjustment item of +£14.00 is added. | P1 | backend: `test_changing_a_lesson_replaces_open_pay_and_adjusts_paid_pay` | |
| TP-E12-008 | Cancellation pay follows the pay share | Coordinator | Late cancellation paid 50% | 1. Cancel late as client. | £14.00 cancellation pay item. | P1 | backend: `test_cancellation_pay_follows_the_pay_share` | |
| TP-E12-009 | Paid calendar events use the hourly rate | Coordinator | Nia profile hourly rate £15; a 2 h paid training event | 1. Create the event; include it in a pay run. | £30.00 item. | P2 | backend: `test_paid_events_use_the_hourly_rate` | |
| TP-E12-010 | Ad hoc charge tutor share and manual items | Finance | — | 1. Add an ad hoc charge with a tutor share of £5.<br>2. Add manual bonus £20 and deduction −£10 via the API or UI. | Items created with the right type. | P2 | backend: `test_charge_shares_and_manual_items` | |
| TP-E12-011 | Overdue report holds pay | Finance | `payroll.hold_overdue_reports` on; report overdue (E09) | 1. `/payroll/items`. | Item **On hold**; tutor portal shows "Write the lesson report to release this." Submitting the report releases it. | P1 | backend: `test_overdue_report_holds_pay_until_written` | |
| TP-E12-012 | Pay when the client has paid | Finance | `payroll.pay_when_client_paid` on | 1. Complete a lesson; invoice it; leave unpaid.<br>2. Record payment. | Held ("Paid once the family pays the invoice.") until paid, then Ready. Refund claws back via an adjustment. | P1 | backend: `test_pay_when_client_paid` | |
| TP-E12-013 | Manual hold and release | Finance | Ready item | 1. Hold it with a reason.<br>2. **Release**. | On hold (tutor sees "Held by the office: ask them about it."), then Ready. | P2 | backend: `test_manual_hold_and_release` | |
| TP-E12-014 | Compliance hold (E18) | Finance | Nia's DBS check expired | 1. Check her items. | Held with reason compliance; released when the check is renewed. | P2 | No | |

## Expenses and mileage (FR-12-3, FR-12-4, T04, T05)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E12-015 | Tutor claims an expense with a receipt photo | Tutor | Category "Materials" | 1. Portal → Expenses → **New claim**.<br>2. **Category**, **Date**, **What was it for?** "Past papers", **Amount** £12.00, **Receipt photo** (camera or file), tick **Rebill to client**.<br>3. **Send claim**. | "Claim sent for approval." Status Waiting. | P1 | backend: `test_tutors_claim_expenses_and_see_their_own_earnings` | |
| TP-E12-016 | Approve a rebillable expense (epic AC) | Finance | Claim from TP-E12-015 linked to the Patel family | 1. `/payroll/expenses` → **Approve**. | £12.00 reimbursement pay item for Nia and a £12.00 Patel ad hoc charge (plus markup if set). | P1 | backend: `test_rebillable_expense_pays_the_tutor_and_charges_the_client` | |
| TP-E12-017 | Reject needs a comment; no self-approval | Finance | Claim; a staff member who claimed for themselves | 1. **Reject** without a comment.<br>2. Try to approve your own claim. | Both refused with clear messages. | P1 | backend: `test_expense_rules` | |
| TP-E12-018 | Category limits | Tutor | Category limit £50 | 1. Claim £75. | Refused or flagged with the limit. | P2 | backend: `test_expense_rules` | |
| TP-E12-019 | Mileage suggestion from my lessons | Tutor | Two in-person lessons on the same day at different addresses | 1. New claim → mileage category → **Suggest from my lessons**. | Distance ({{unit}}) filled from the legs (straight line × 1.25 without a key); amount = distance × rate. | P2 | backend: `test_mileage_suggestions_between_lessons` | |
| TP-E12-020 | Expense approval reminders | Finance | Claim waiting | 1. Temporal UI: `ExpenseApprovalWorkflow`. | Approver notified; reminders on day 3 and 7; deciding ends it. | P3 | backend: `test_expense_approval_reminds_until_decided`, `test_deciding_ends_the_reminders` | |

## Pay runs, statements, bank files, payouts (FR-12-5 to FR-12-7, T06–T09)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E12-021 | Create a pay run | Finance | Ready items this month for Nia | 1. `/payroll` → **New pay run**, From/To = this month. | Run created: Collecting → Ready for review; per-tutor totals and items. | P1 | backend: `test_pay_run_collects_items_and_flags_problems` | |
| TP-E12-022 | Review warnings | Finance | Sam Clarke has items but no bank details; an item on hold | 1. Open the run. | Warnings for missing bank details, held items, negative or small totals carried forward. | P1 | backend: `test_pay_run_collects_items_and_flags_problems` | |
| TP-E12-023 | Remove an item and add an adjustment | Finance | Run in review | 1. Remove one item.<br>2. Add an adjustment +£5. | Removed item returns to Ready; totals update. | P2 | backend: `test_pay_run_api` | |
| TP-E12-024 | Approve, statements and mark paid | Finance | Run in review; Nia paid by bank file | 1. **Approve**.<br>2. **Bank file**: Default → **Make bank file** → download.<br>3. **Mark all paid**. | Approved → Paying out → Paid. Self-billing invoice (per-tutor number, agreement wording) or remittance PDF for Nia. Download is audited. | P1 | backend: `test_statements_payouts_and_bank_file`, `test_pay_run_is_approved_paid_and_finished` | |
| TP-E12-025 | Dual approval above the threshold | Owner, Finance | `payroll.dual_approval_threshold` = £100; run total £200 | 1. Finance approves.<br>2. Same user tries again.<br>3. Owner approves. | "1 of 2 approvals"; the same person can't approve twice; second approval moves it on. | P1 | backend: `test_dual_approval_above_the_threshold` | |
| TP-E12-026 | Cancel a run returns its items | Finance | Run in review | 1. **Cancel run**. | Status Cancelled; items back to Ready; workflow ends. | P2 | backend: `test_cancelling_a_run_returns_its_items`, `test_cancelling_ends_the_pay_run_workflow` | |
| TP-E12-027 | Bank file formats | Finance | GBP and EUR tutors | 1. Make CSV, BACS Standard 18, SEPA pain.001 (EUR only), NACHA, ABA files. | Files match the golden formats; SEPA refuses GBP; missing details are reported. | P2 | backend: `test_bank_file_matches_golden`, `test_formats_reject_other_currencies_and_missing_details`, `test_nacha_is_blocked_to_ten_records_with_hash_and_totals` | |
| TP-E12-028 | Stripe Express onboarding and payouts (fake) | Tutor, Finance | Nia method stripe_connect | 1. Portal Pay details → **Set up payouts with Stripe**.<br>2. Approve a run. | Pay card shows "Waiting for the tutor to finish Stripe setup." until done; payouts Sending → Paid; a failed payout is "Carried forward" and the run is "Paid with failures". | P2 | backend: `test_stripe_payouts_and_failures` | |
| TP-E12-029 | Scheduled run at cut-off | Owner | `payroll.pay_period` monthly, cut-off day set | 1. Temporal UI → Schedules. | A schedule creates runs at the cut-off; changing the setting updates it. | P3 | backend: `tutortrack/payroll/tests/test_workflows.py` | |

## Exports and tutor earnings (FR-12-8, FR-12-9, T10, T11)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E12-030 | Payroll export for employed tutors | Finance | Sam method external_payroll | 1. Run detail → **Export for payroll:** Xero / QuickBooks / BrightPay / Gusto / CSV. | CSV with hours, pay, bonuses and reimbursements for external-payroll tutors only. | P2 | backend: `test_payroll_export_for_employees` | |
| TP-E12-031 | Tutor earnings page | Tutor | Items in several states; a paid run | 1. Portal → **Earnings**. | **Coming up**, **On hold** with what releases each, **Payouts and statements** with PDFs, **Paid this year**. "These amounts are confirmed when your pay run is processed." | P1 | backend: `test_tutors_claim_expenses_and_see_their_own_earnings` | |
| TP-E12-032 | Tutor sees only own earnings | Tutor | Sam has items | 1. Portal earnings; try Sam's statement URL. | Only Nia's; Sam's returns 404. | P1 | backend: `test_tutors_claim_expenses_and_see_their_own_earnings` | |

## Phase 3 (E12-T12) — verify after the Phase 3 merge

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E12-033 | Wise payouts (verify after the Phase 3 merge) | Finance | Wise connected (fake); tutors in GBP and EUR with method Wise | 1. Approve a pay run. | One Wise batch with transfers in each currency; status tracked; failures carried forward. | P2 | No (Phase 3) | |
| TP-E12-034 | 1099-NEC data export (verify after the Phase 3 merge) | Finance | US org (USD) with self-employed tutors over the threshold | 1. Export 1099 data for the tax year. | Per-tutor totals with tax IDs (from the tutor record), US tenants only. | P2 | No (Phase 3) | |
| TP-E12-035 | Tutor annual earnings summary (verify after the Phase 3 merge) | Tutor | Paid runs in the year | 1. Portal → Earnings → annual summary. | Year totals suitable for a tax return; 1099 data for US tutors. | P3 | No (Phase 3) | |
| TP-E12-036 | Commission-based pay (verify after the Phase 3 merge) | Finance | Pay when client paid on; Nia pay rule 60% of collected revenue | 1. Complete a £45 lesson; invoice; record payment of £45. | Pay item £27.00 created after the payment is allocated; partial payment pays pro rata; refund claws back. | P2 | No (Phase 3) | |

## Permissions

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E12-037 | Finance runs payroll | Finance | — | 1. Open `/payroll`, create and approve a run. | Allowed. | P1 | No | |
| TP-E12-038 | Coordinator has no payroll | Coordinator | — | 1. Look at the nav; open `/payroll`. | No Payroll nav item; no access; tutor financial fields hidden on the tutor record. | P1 | e2e: `e2e/roles.spec.ts` | |
| TP-E12-039 | Tutor has own scope only | Tutor | — | 1. Try `/api/v1/pay-runs`. | 403. Own earnings and expenses only. | P1 | No | |

## Tenant isolation

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E12-040 | Other org's pay runs return 404 | Owner of Northside | Bright Minds run id | 1. GET `/api/v1/pay-runs/<id>` on northside.localhost; open `/payroll`. | 404; empty list. | P1 | backend: `tutortrack/payroll/tests/test_payroll.py::test_detail_of_other_organisation_is_404` | |

## Currency, time and edge cases

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E12-041 | Pay rounding | Finance | 45-min lesson at £28/h | 1. Complete it. | £21.00 exactly; 50-min lesson gives £23.33 (half-up). | P2 | No | |
| TP-E12-042 | Period boundary in local time | Finance | Lesson at 23:30 local on the last day of the period | 1. Create the run for that period. | The lesson's pay is in that period. | P2 | No | |
| TP-E12-043 | Minimum payout carried forward | Finance | `payroll.minimum_payout` £10; tutor owed £4 | 1. Approve a run. | The £4 is carried forward with a warning. | P3 | No | |

## Gap batch G3 (as built 2026-10-14)

Built by gap batch G3 ([ADR 0037](../adr/0037-gap-batch-g3-scheduling-billing-payments-payroll.md)); see the epic's *Gap backlog* notes.

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E12-044 | Re-authenticate before full bank details | Finance | Tutor with bank details | 1. Tutor → pay card → **Show full bank details**.<br>2. Enter your password → **Confirm**. | Asked to confirm first; then the full details show (audited). After 5 minutes it asks again. | P1 | backend: `test_pay_profile_api_masks_bank_details_and_audits_full_view`, `test_reauth_window_expires`; vitest: `G3.test.tsx` | |
| TP-E12-045 | Authenticator code or passkey | Finance with TOTP | — | 1. Confirm with a code. | Accepted; a wrong code is refused and counts as a failed sign-in. | P2 | backend: `identity/tests/test_g3_reauth.py` | |
| TP-E12-046 | Edit an item in a pay run | Finance | Run under review | 1. Run → Items → **Edit** a lesson item → amount and reason → Save. | A linked correction for the difference appears in the run; totals update; the original item is unchanged. Approved runs can't be edited. | P1 | backend: `test_editing_an_amount_adds_a_linked_correction`, `test_edit_item_api_and_locked_runs` | |
| TP-E12-047 | Annual earnings summary | Tutor (Nia) | Paid pay runs this tax year | 1. Portal → Earnings → **Earnings summary** → choose a year → **Download PDF**. | Earnings and repaid expenses for the UK tax year (6 Apr – 5 Apr), by type and month; the PDF matches. | P1 | backend: `test_annual_summary_counts_what_was_paid_in_the_year`, `test_tutors_get_their_summary_and_pdf` | |
