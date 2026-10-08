# E12 — Tutor Payroll, Expenses & Payouts

| | |
|---|---|
| **Phase** | Agency (Phase 2) |
| **Depends on** | E08, E09, E10, E11 |
| **Parity** | TutorCruncher payment orders, contractor payouts, pay reports, Xero/QBO export; TutorBird payroll calculation, expenses, mileage; Teachworks wage tiers, bonuses, reimbursements |

## 1. Summary
Calculates what each tutor has earned (lesson pay, premiums, travel, bonuses, expenses, deductions), lets finance review and approve it in **pay runs**, produces payslips or **self-billing statements** for self-employed tutors, and pays out automatically (Stripe Connect Express, bank payment files, Wise) or records manual payment. Employed tutors are exported to the tenant's payroll provider rather than processed through PAYE/W-2 by us.

## 2. Functional requirements

### FR-12-1 Pay items
- Created by event handlers:
  - `lesson.completed` → lesson pay per LessonTutor (rate snapshot × duration/units + premiums + group bonus) where payable.
  - `lesson.cancelled` with payable % → cancellation pay.
  - Paid calendar events (training/meetings).
  - Ad hoc charge tutor share (E10 FR-10-2).
  - Approved expenses and mileage.
  - Manual: bonus, referral bonus, adjustment, deduction (e.g. late-cancellation penalty, equipment), salary/fixed amount.
- Status: `pending → ready → approved → in_pay_run → paid`, plus `held` (with reason: overdue report (E09), compliance expired (E18), client unpaid (setting: "pay tutors only when client has paid", common in agencies), manual hold).
- Edits to locked lessons create adjustment items (never mutate paid items).

### FR-12-2 Pay settings
- Org/branch: pay period (weekly, fortnightly, semi-monthly, monthly, custom), pay day offset, cut-off, pay-when-client-paid toggle, hold-on-overdue-report toggle, include cancellations, travel pay rules, min payout amount, currency per tutor (defaults to branch).
- Per tutor: employment type, pay method (`stripe_connect | bank_file | wise | manual | external_payroll`), bank details (encrypted; validated: UK sort code/account, IBAN, US ACH routing, AU BSB), tax ID, VAT registered (for self-billing VAT), payee name.

### FR-12-3 Travel pay and mileage
- Travel time/mileage between consecutive in-person lessons or from home → lesson (setting): distance via routing API (Google Distance Matrix/OSRM), rate per mile/km, cap, minimum. Auto-calculated suggestions that tutors confirm in their claim.

### FR-12-4 Expenses
- Tutors (or staff) submit expenses: date, category, amount, tax, receipt photo (mobile camera via E16), linked lesson/job/client, rebillable to client flag (creates an E10 charge on approval).
- Approval workflow: submit → approve/reject (with comment) → pay item.
- Expense categories with account codes (E23) and limits.
- **AC:** an approved rebillable expense of £12 creates both a tutor reimbursement pay item of £12 and a client charge of £12 (or with markup per setting).

### FR-12-5 Pay runs
- Create a pay run for a period (auto-created at cut-off): includes all `ready`/`approved` items up to the cut-off for the selected branch(es)/tutors.
- Review screen: per tutor totals, item breakdown, held items with reasons, comparison to last period, warnings (negative net, missing bank details, compliance issues).
- Actions: add/remove items, add adjustments, hold/release, approve (requires `payroll.payrun.approve`; optional two-person approval for runs above a threshold).
- Approve → generate documents → payout processing → mark paid.

### FR-12-6 Documents
- **Self-billing statements/invoices** (UK HMRC self-billing compliant: supplier details, unique sequential number per tutor, VAT if registered, self-billing agreement acknowledgement captured at onboarding) for self-employed tutors.
- Payslip-style remittance advice for others.
- Delivered to the tutor portal and by email; PDF.

### FR-12-7 Payouts
- **Stripe Connect Express** (tutors onboard via Stripe-hosted KYC in the tutor portal): transfers from the tenant's platform balance to tutors' connected accounts; status tracking via webhooks. Requires the tenant to use Connect as a platform; a supported configuration in E11.
- **Bank payment files:** UK BACS Standard 18 / bank CSV formats (Barclays, HSBC, Lloyds, NatWest), SEPA pain.001 XML, US NACHA, AU ABA. Download, upload to bank, then mark paid.
- **Wise Business API** (Phase 3): batch transfers in multiple currencies.
- **Manual:** mark paid with reference.
- Partial failure handling: failed payouts return items to `approved` for the next run with notification.

### FR-12-8 Employed tutors / external payroll
- Export approved hours/amounts per employee for the payroll provider (CSV formats for Xero Payroll, QuickBooks Payroll, BrightPay, Gusto, ADP generic) and sync via API where available (Xero Payroll UK in E23 Phase 3).

### FR-12-9 Tutor earnings view
- Tutor portal: upcoming pay (pending/ready), held items with reasons and actions (e.g. "submit report to release £30"), pay history, statements, expense claims, year-to-date totals, annual earnings summary (for tax returns), 1099-NEC data export for US tenants (Phase 3).

### FR-12-10 Commission-based pay (agencies)
- Pay rate as % of collected client revenue per lesson (alternative to fixed rate), computed after payment allocation (requires pay-when-client-paid).

## 3. Data model
`PaySettings`, `TutorPayProfile(tutor, method, bank_details encrypted, tax_id encrypted, vat_registered, vat_number, self_billing_agreed_at, stripe_connect_account)`, `PayItem(tutor, type, source_type, source_id, description, date, quantity, rate, amount, currency, status, hold_reason, pay_run)`, `Expense`, `ExpenseCategory`, `MileageClaim`, `PayRun(number, branch, period_start, period_end, status, totals, approved_by, approved_at)`, `PayRunTutorSummary`, `PayoutBatch`, `Payout(tutor, pay_run, amount, method, provider_ref, status, failure_reason)`, `SelfBillingStatement(number per tutor)`, `BankFileExport`.

## 4. API
`/api/v1/pay-items` (+ manual create, hold/release), `/expenses` (+ approve/reject), `/mileage-claims`, `/pay-runs` (+ preview, approve, generate-files, mark-paid), `/payouts`, `/tutors/{id}/pay-profile`, `/me/earnings`, `/payroll/exports/{format}`.

## 5. Events
`pay_item.created/held/released`, `expense.submitted/approved/rejected`, `pay_run.created/approved/paid/partially_failed`, `payout.paid/failed`, `self_billing_statement.issued`.

## 6. Permissions
`payroll.view`, `payroll.item.manage`, `payroll.expense.approve`, `payroll.payrun.{create,approve,pay}`, `payroll.bank_details.view` (masked by default; full view needs re-auth), tutor `own` scope for earnings and expenses.

## 7. Testing
- Pay calculation table tests (rates, premiums, partial cancellations, group bonuses, travel).
- Pay-when-client-paid scenarios incl. partial payments and refunds (clawback adjustment).
- Bank file format golden-file tests.

## 8. Delivery plan
- [ ] **E12-T01** Pay settings and tutor pay profile (encrypted bank details with validation).
- [ ] **E12-T02** Pay item model and event handlers (lessons, cancellations, events, ad hoc shares).
- [ ] **E12-T03** Hold rules (report overdue, compliance, client unpaid) and release automation.
- [ ] **E12-T04** Expenses and categories with approval; rebillable expenses → E10 charges.
- [ ] **E12-T05** Mileage/travel calculation (routing provider abstraction).
- [ ] **E12-T06** Pay runs: auto-create, review, approve (incl. dual approval).
- [ ] **E12-T07** Self-billing statements and remittance PDFs.
- [ ] **E12-T08** Bank file exports (BACS, SEPA, NACHA, ABA, CSV) with golden tests.
- [ ] **E12-T09** Stripe Connect Express tutor onboarding and transfers.
- [ ] **E12-T10** External payroll exports.
- [ ] **E12-T11** Frontend: pay runs UI, expenses approval, tutor earnings pages.
- [ ] **E12-T12** (Phase 3) Wise payouts, 1099 data, commission-based pay.

## Temporal workflows (E32)

Implement these processes as Temporal workflows following the rules in [E32](E32-workflow-orchestration-temporal.md) (deterministic workflow code, side effects in tenant-scoped activities that call services, tenant-prefixed workflow IDs, signals for human decisions). Where the requirements above mention sweeper tasks, `next_*_at` / `resume_at` columns or retry schedules, the workflow replaces them.

- [ ] **E12-TW1** Pay run and expense workflows (requires E32).

| Workflow | Started by | Steps, timers and signals | Replaces |
|---|---|---|---|
| `PayRunWorkflow` `pay-run:{org}:{pay_run}` (**Temporal Schedule** at cut-off) | Schedule or manual create | Assemble items → wait for `approve` signal(s) (dual approval above threshold; reminders) → generate statements → payouts (Stripe Connect transfers / bank file) → wait for payout webhook signals → mark paid; failed payouts return items to the next run. Query exposes status for the pay-run screen | Pay run state machine + polling |
| `ExpenseApprovalWorkflow` | `expense.submitted` | Notify approver → reminders → `approve`/`reject` signal → pay item and optional rebill charge | Approval queue reminders |
