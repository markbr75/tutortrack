# E10 — Client Billing: Ledger, Invoices, Credit & Packages

| | |
|---|---|
| **Phase** | MVP (packages, late fees, split billing in Phase 2) |
| **Depends on** | E05–E09 |
| **Parity** | TutorCruncher auto-invoicing, proformas/credit requests, client balances, ad hoc charges, negative balance prevention; TutorBird calendar-based billing, recurring invoices, tutor pre-review summary, late fees, family invoicing; Teachworks packages/credit |

## 1. Summary
Turns delivered (or scheduled) lessons into money owed. An **append-only client ledger** underpins every billing model: pay-as-you-go invoicing after lessons, invoicing in advance (monthly/termly from the schedule), prepaid credit via payment requests, packages, and fixed recurring fees. It also covers invoices, credit notes, statements, late fees and dunning reminders.

## 2. Key concepts and rules
- **Charge:** a billable line awaiting invoicing (from a lesson attendee, ad hoc charge, fee, package sale or late fee). Has amount, tax, client, student, job, source, date and status (`uninvoiced | invoiced | void`).
- **Invoice:** groups charges; numbered sequentially per org (or per branch prefix); **immutable once issued**. Corrections are made via **credit notes** (full or partial) and new invoices.
- **Ledger:** `ClientLedgerEntry` rows with types `invoice` (+debit), `payment` (−), `credit_note` (−), `refund` (+), `payment_request_payment` (credit), `adjustment` (±), `write_off` (−), `package_purchase`. The balance = Σ entries. **Never update or delete entries.**
- **Balances shown:** *Invoice balance* (owed on issued invoices), *Available credit* (unallocated payments/credit), *Uninvoiced charges* (accrued), *Projected balance* (credit − uninvoiced − future scheduled for prepaid clients). (TutorCruncher's invoice vs available balance concept.)

## 3. Functional requirements

### FR-10-1 Billing modes (per client, overridable per job)
1. **Pay-as-you-go in arrears:** charges are created on lesson completion; invoices are generated on a schedule (after each lesson, weekly, fortnightly, monthly on day N, or manually) grouping uninvoiced charges.
2. **Invoice in advance (calendar-based, TutorBird parity):** on the schedule (e.g. 25th of the month for next month), invoice all *scheduled* lessons in the next period. At period end, **reconcile**: cancellations under the free policy generate credits (credit note or carry-forward credit line on the next invoice); additions generate extra charges.
3. **Prepaid credit (TutorCruncher parity):** clients top up via **Payment Requests**; lesson completion draws down credit by issuing a (zero-due) invoice or receipt allocated from credit. Auto top-up when the balance falls below a threshold (charge a saved card or send a request).
4. **Packages:** purchase a package (invoice + payment) → lessons consume package units instead of creating charges; overage lessons beyond the package fall back to mode 1.
5. **Recurring fixed fee:** monthly/termly fixed tuition (e.g. £160/month for weekly lessons regardless of count), with optional proration on start/stop and an attendance-independent setting. Used heavily by centres (E20).

### FR-10-2 Charge creation
- Subscribes to `lesson.completed`, `lesson.cancelled` (fee outcomes), `attendance.recorded` (changes), `lesson.updated` (unlocked).
- Idempotent per (lesson_attendee, charge_kind). Updates to an unlocked lesson update/void its uninvoiced charge. Changes to an **invoiced** lesson create an adjustment: a credit note line for the difference or an additional charge.
- Ad hoc charges (TutorCruncher parity): staff (or tutors if permitted, e.g. for materials) add one-off charges from the product catalogue or free-form, to a client/student/job, with date, category, tax and optional tutor share (→ E12 pay item).
- Negative ad hoc charges = discounts/goodwill credits.

### FR-10-3 Invoice generation
- **Invoice run** (scheduled per branch/client cycle or manual "Generate invoices" for a period with filters):
  1. Collect eligible charges (excluding those held for missing reports if the setting is on).
  2. Group per client (or per student/job per client setting; family = one invoice for all siblings).
  3. Create **draft** invoices.
  4. **Review window:** drafts are visible to admins (and optionally tutors, as a summary of their lessons for checking, TutorBird parity) for N days before auto-issue, or require manual approval (setting).
  5. Issue: assign number, render PDF, post ledger entry, send via email/portal, and trigger auto-pay (E11) if enabled.
- Invoice content: tenant branding, branch details, client billing details, PO number, lines (date, student, service, tutor name (setting), duration, rate, discount, tax, amount), subtotal, tax breakdown, total, credit applied, amount due, due date, payment instructions and pay-now link, notes/footer, optional attached lesson reports (E09).
- Minimum invoice amount and "don't invoice zero totals" settings.
- Multi-currency: an invoice is in one currency; charges in other currencies form separate invoices.
- **AC:** running monthly arrears invoicing for March with 3 siblings in one family and family grouping on produces 1 invoice with lines grouped by student, numbered sequentially without gaps, and credit from prior overpayment auto-applied.
- **AC:** re-running the invoice run for the same period produces no duplicates.

### FR-10-4 Invoice lifecycle and actions
- States: `draft → issued → partially_paid → paid`, `void` (only if no payments; posts a reversing entry), `written_off` (bad debt with reason).
- Actions: edit draft, add line, remove line (returns the charge to uninvoiced), issue, send/resend, download PDF, record payment (E11), apply credit, credit note (full/partial with line selection and reason), void, write off, duplicate.
- Due date from client payment terms; overdue is derived.

### FR-10-5 Credit notes
- Numbered sequence `CN-…`; reference the original invoice; lines; reason; posts a negative ledger entry; resulting credit is applied to the invoice balance or left as client credit (choice), or refunded (E11).

### FR-10-6 Payment requests (proforma / credit requests)
- Create manually, in bulk (e.g. all prepaid clients with balance < £X), or automatically (balance threshold / scheduled monthly top-up based on the next month's scheduled lessons).
- Not a tax invoice; numbered `PR-…`; pay link; reminders; on payment → `payment_request_payment` ledger credit (and optionally an issued "receipt" invoice when VAT treatment requires).
- **AC:** a payment request of £400 paid by card increases available credit by £400; subsequent completed lessons reduce it, and the client sees the running balance in the portal.

### FR-10-7 Packages (purchase and consumption)
- Sell a package template (E06) to a client/student: creates invoice/charge for the package price; on payment (or on issue, setting) the package becomes `active`.
- Consumption: on lesson completion, eligible attendee charges are replaced by a consumption entry (hours or lessons) from the oldest-expiring eligible package (FIFO). Partial consumption supported.
- Expiry: unused units expire (with optional reminder at N days before and a revenue recognition entry), or extend (admin).
- Balance visible to client, tutor (hours remaining only) and admin. Low-balance notification and auto-renew.
- Sibling sharing if the template allows it.

### FR-10-8 Recurring fixed fees
- Billing plan on a job/enrolment: amount, interval (monthly/termly/weekly), anchor date, proration rules, start/end, attendance-independent flag; generates charges on schedule; pause/resume.

### FR-10-9 Statements
- Client statement for a date range: opening balance, invoices, payments, credits, closing balance, ageing. PDF/email. Scheduled monthly statements (setting).

### FR-10-10 Reminders, late fees and dunning
- Reminder schedule (setting): before due (−3 days), on due, +3, +7, +14, +30, each with template (E13) and channel (email/SMS).
- Late fees (TutorBird parity): fixed or % after N days overdue, once or recurring monthly, capped; added as a charge on the next invoice or as an immediate invoice (setting); waivable.
- Collections actions: pause lessons for overdue clients (soft block: warning on scheduling; hard block for portal booking), escalate task to staff, mark "in collections".
- **AC:** an invoice 7 days overdue sends the +7 reminder exactly once even if the beat job runs multiple times.

### FR-10-11 Tax handling
- Line-level tax from service/product tax rate; inclusive/exclusive calculation per org; tax summary on invoices; tax-exempt clients; reverse charge note for B2B where applicable.
- Rounding per line, half-up; invoice totals are sums of rounded lines.

### FR-10-12 Split billing (Phase 2)
- A job or student can be billed to multiple clients by percentage (e.g. separated parents 50/50, or school 70% / parent 30%). Each charge is split with `Money.allocate` into separate client charges.

### FR-10-13 Billing settings
- Per org/branch: numbering format, invoice template (choose layout, colours, logo, footer), default terms, schedules, review window, auto-issue, auto-send, attach reports, minimum amount, rounding display, late fee rules, reminder schedule, negative balance prevention and credit limit default, show tutor names on invoices, group by.

### FR-10-14 Client billing UI
- Client → Billing tab: balances summary, ledger (filterable), invoices, payment requests, credit notes, packages, payment methods (E11), billing settings.
- Global Billing area: uninvoiced charges, invoice runs, drafts awaiting review, overdue invoices (ageing buckets), payment requests, packages report.

## 4. Data model
`Charge(client, student, job, lesson_attendee, source_type, source_id, kind, description, date, quantity, unit, unit_price, discount, tax_rate, net, tax, gross, currency, status, invoice_line)`, `Invoice(number, client, branch, currency, status, issue_date, due_date, period_start, period_end, subtotal, tax_total, total, amount_paid, amount_credited, balance_due, po_number, pdf_file, sent_at, invoice_run)`, `InvoiceLine`, `InvoiceRun(period, filters, status, stats)`, `CreditNote`, `CreditNoteLine`, `PaymentRequest`, `ClientLedgerEntry(client, type, amount (signed), currency, ref_type, ref_id, occurred_at, balance_after)`, `PackagePurchase(template_snapshot, client, student(s), units_total, units_used, expires_at, status)`, `PackageConsumption`, `BillingPlan` (recurring), `LateFeeRule`, `ReminderSchedule`, `ReminderLog`, `Statement`.

## 5. API
`/api/v1/charges`, `/ad-hoc-charges`, `/invoices` (+ `/{id}/{issue,send,void,write-off,credit-note,pdf,apply-credit}`), `/invoice-runs` (+ preview), `/credit-notes`, `/payment-requests` (+ bulk), `/clients/{id}/ledger`, `/clients/{id}/balance`, `/clients/{id}/statement?from&to`, `/packages` (purchases), `/billing-plans`, `/billing/settings`.

## 6. Events
`charge.created/voided`, `invoice.drafted`, `invoice.issued`, `invoice.sent`, `invoice.paid`, `invoice.partially_paid`, `invoice.overdue`, `invoice.voided`, `invoice.written_off`, `credit_note.issued`, `payment_request.created/sent/paid`, `client.balance_low`, `package.purchased/activated/low/depleted/expiring/expired`, `late_fee.applied`.

## 7. Permissions
`billing.invoice.{view,create,issue,void,write_off}`, `billing.credit_note.issue`, `billing.charge.create` (tutor: optional, limited categories), `billing.payment_request.*`, `billing.package.sell`, `billing.settings.manage`, `billing.ledger.adjust`.

## 8. Testing
- Property tests: ledger balance = Σ entries; invoice totals = Σ rounded lines; credit allocation never over-allocates.
- Scenario tests for each billing mode over a month incl. cancellations, edits after invoicing, DST, multi-currency and package overage.
- Concurrency test: two simultaneous invoice runs → no duplicate charges invoiced (row locks).

## 9. Delivery plan
- [x] **E10-T01** Ledger entry model, posting service with invariants, balance selectors (invoice/available/uninvoiced/projected).
- [x] **E10-T02** Charge model and lesson-event handlers (create/update/void), ad hoc charges.
- [x] **E10-T03** Invoice model, numbering, draft builder (grouping rules), issue service, PDF rendering (WeasyPrint templates).
- [x] **E10-T04** Invoice runs (scheduled and manual), review window, auto-issue, idempotency, concurrency locks.
- [x] **E10-T05** Invoice actions: void, credit notes, write-off, apply credit.
- [x] **E10-T06** Payment requests (manual, bulk, threshold auto).
- [x] **E10-T07** Invoice-in-advance mode with end-of-period reconciliation.
- [x] **E10-T08** Statements and ageing.
- [x] **E10-T09** Reminder schedules (E13 templates).
- [x] **E10-T10** Billing settings and invoice template customisation.
- [x] **E10-T11** Frontend: client billing tab, invoices list/detail/editor, invoice run wizard, payment requests.
- [x] **E10-T12** (Phase 2) Packages purchase/consumption/expiry.
- [x] **E10-T13** (Phase 2) Recurring fixed-fee billing plans with proration.
- [x] **E10-T14** (Phase 2) Late fees and collections blocks.
- [x] **E10-T15** (Phase 2) Split billing.

## Temporal workflows (E32)

Implement these processes as Temporal workflows following the rules in [E32](E32-workflow-orchestration-temporal.md) (deterministic workflow code, side effects in tenant-scoped activities that call services, tenant-prefixed workflow IDs, signals for human decisions). Where the requirements above mention sweeper tasks, `next_*_at` / `resume_at` columns or retry schedules, the workflow replaces them.

- [x] **E10-TW1** Billing workflows (invoice runs, dunning, payment requests, packages) (requires E32).

| Workflow | Started by | Steps, timers and signals | Replaces |
|---|---|---|---|
| `InvoiceRunWorkflow` `invoice-run:{org}:{branch}:{period}` (**Temporal Schedule** per branch cycle) | Schedule, or manual "Generate invoices" | Collect charges → build drafts → **review window timer** (or wait for `approve` signal) → issue in batches → send → start `PaymentCollectionWorkflow` for auto-pay clients. Query shows progress. Workflow ID makes re-runs idempotent | Invoice-run beat task + review-window polling |
| `InvoiceDunningWorkflow` `invoice-dunning:{org}:{invoice}` | `invoice.issued` | Reminder timers per schedule (−3, 0, +3, +7, +14, +30) → late fee activity → collections task/booking block. Signals `paid`, `credited`, `voided`, `paused` stop or pause it | Reminder log + daily dunning job (FR-10-10) |
| `PaymentRequestWorkflow` | Payment request sent | Reminders until paid or cancelled; auto top-up retry for threshold requests | Reminder job |
| `PackageExpiryWorkflow` `package:{org}:{purchase}` | `package.activated` | Timer to N days before expiry → reminder → expiry → expire units + revenue entry. Signals `depleted`, `extended(until)` | Expiry sweeper |

## Implementation notes (as built 2026-10-09)
- **App:** `billing` with `ClientLedgerEntry` (append-only), `Charge`, `Invoice` (+ `InvoiceLine`), `InvoiceRun`, `CreditNote` (+ lines), `CreditAllocation` and `PaymentRequest`. All have RLS; invoices, charges, credit notes, runs and requests are branch-scoped. See ADR 0007 for the ledger, credit and charge-sync design.
- **Balances (T01):** `ledger.balances(client)` returns the ledger balance, invoice balance (open invoices), available credit (invoice balance − ledger, when positive), uninvoiced, overdue and projected (credit − uninvoiced − planned lessons). There are property tests for Σ entries and for credit never over-allocating.
- **Charges (T02):** `sync_attendee_charge` keeps one uninvoiced charge per attendee equal to what is owed minus what is invoiced. It handles lesson, late-cancellation (description "Late cancellation fee – <lesson>", E09 AC), advance and reconciliation charges. Tax per line comes from the lesson's pricing snapshot, inclusive or exclusive per `billing.prices_include_tax`; tax-exempt clients pay no tax. Makeup lessons aren't charged. Ad hoc charges and discounts go through `POST /charges` (negative unit price allowed, any currency) and can be voided while uninvoiced.
- **Invoices (T03):** grouping per client (siblings together) or per student/job (client setting), one invoice per currency. Lines are sorted by student then date. Totals are sums of rounded lines. Negative or zero totals and amounts under `billing.minimum_invoice_amount` are carried forward. Issuing assigns a gap-free `INV-` number, takes the billing snapshot, sets the due date from payment terms, posts to the ledger, locks delivered lessons, applies credit (`billing.auto_apply_credit`) and emails the PDF (`billing.auto_send`; a Celery task with an attachment and pay link until E13 templates). PDFs are rendered on demand with WeasyPrint (`/invoices/{id}/pdf`).
- **Runs (T04, TW1):** `POST /invoice-runs` is idempotent per branch, period and mode, and starts `InvoiceRunWorkflow`: collect → drafts → review window (`billing.review_days`, or wait for `approve` when `billing.auto_issue` is off) → issue. `preview` counts what would be invoiced. Drafting row-locks charges with SKIP LOCKED (concurrency test). Weekly/monthly schedules are per-branch Temporal Schedules (`ScheduledInvoiceRunWorkflow`, kept in sync with `billing.invoice_schedule`/`invoice_day`). The tutor pre-review summary was not built.
- **Actions (T05):** void (no payments and no credit notes; reversing entry; charges return to uninvoiced; lessons unlock), write-off, credit notes (`CN-`, full or per line, applied to the invoice or kept as client credit), apply credit, draft editing (add or remove lines, PO, notes, delete). `allocate_payment`/`unallocate_payment` are the hooks for E11.
- **Payment requests (T06):** `PR-` numbered, single, bulk (projected balance below X → fixed amount or top up to Y) and automatic (`billing.topup_threshold` → `client.balance_low` + a request). Paying one (E11) posts `payment_request_payment` and applies credit to open invoices. Prepaid jobs get a receipt invoice per lesson paid from credit (`billing.prepaid_invoice_each_lesson`). The negative-balance guard for E09 is `PrepaidBalanceGuard` (prepaid jobs; client override or `billing.prevent_negative_balance`; credit limit included). `PaymentRequestWorkflow` reminds after 3 and 7 days until paid or cancelled.
- **Advance mode (T07):** a new job billing method `invoice_in_advance`. An advance run charges planned lessons in the period. Later cancellations or edits reconcile continuously as credit or extra lines on the next invoice, instead of one end-of-period batch. Completing an advance-billed lesson doesn't charge again.
- **Statements (T08):** `/clients/{id}/statement?from&to` (JSON or `?pdf=true`) gives the opening balance, movements, closing balance and ageing. `/billing/ageing` is the overdue report. Scheduled statement emails are left to E13.
- **Reminders (T09, TW1):** `InvoiceDunningWorkflow` sends one `invoice.reminder` per `billing.reminder_offsets` day at 09:00 local, plus `invoice.overdue` once. Paid, voided or written-off invoices signal `closed`. E13 sends the messages.
- **Settings (T10):** numbering prefixes, schedule, review days, auto-issue/send/credit, minimum amount, zero totals, tutor names, payment instructions, footer, reminders, negative balance and top-ups, all in the `billing` settings area. Template layouts and colours are left for E24 branding.
- **Frontend (T11):** Billing area (invoices by state, uninvoiced charges, payment requests with bulk top-ups, invoice runs with preview and approve, ageing); invoice page (issue, email, PDF, credit note per line, apply credit, void, write-off, draft lines); client billing section (balances, invoices, ledger, payment requests, add charge or discount, invoice now, statement PDF).
- **Fix:** `core.workflows.timers.wait_until_local` waited forever when its deadline had already passed and an early-exit condition was given; it now returns at once.
- **Deferred:** packages (T12), recurring fees (T13), late fees and collections blocks (T14), split billing (T15), PackageExpiryWorkflow (Phase 2). Credit note PDFs, the invoice template designer and tutor draft review are follow-ups.


## Phase 2 implementation notes (as built 2026-10-12)
- **Where:** still the `billing` app, in service modules per feature: `packages.py` (T12), `plans.py` (T13), `dunning.py` (T14 late fees and collections) and `splits.py` (T15). New models (all with RLS, migration `0002`): `PackagePurchase`, `PackageConsumption` (append-only), `BillingPlan`, `LateFeeRule`, `CollectionsCase` and `BillingSplit`. New charge kinds: `package`, `plan`, `late_fee`. See ADR 0022.
- **Packages (T12):** `POST /packages` sells a catalogue template: a `package` charge (template tax rate), invoiced at once by default (`billing.package_invoice_immediately`; otherwise the next invoice run picks it up). The package is `pending` until its invoice is paid, or issued with `billing.package_activation=issue`; the `invoice.paid`/`invoice.issued` subscriber activates it, and then `expires_at` comes from `validity_days`/`valid_until`. Voiding an unpaid sale invoice cancels the package and voids its charge.
  - Consumption runs inside charge sync: lessons on `package` jobs and lessons clients booked (`created_via=client_booking`) take units from eligible active packages (same client and currency, the student's own or an any-student/shareable package, matching services, the job's template if set, not expired at the lesson), oldest expiry first. Hours = scheduled duration × the attendee's charge percentage; lessons = 1 × percentage; credit = the price. A lesson only partly covered is charged for the rest (overage). Attendance changes post `reversal` movements and re-take units, so re-syncing is idempotent. Units are valued at price ÷ units (rounded per movement).
  - `package.low` once at `billing.package_low_units`; `package.depleted` (auto-renewing templates are sold again by a subscriber); cancel (`POST /packages/{id}/cancel`) credits unused value by a **credit note** on the sale invoice line as the refund policy allows (`unused_pro_rata`, or `full` before first use; `refund` overrides); extend moves the expiry.
  - **PackageExpiryWorkflow** (`package:{org}:{purchase}:{run}`, started on activation when there is an expiry): reminder `billing.package_expiry_reminder_days` before (`package.expiring` → E13 email `package_expiring`), then expiry writes the unused units off as an `expiry` movement whose value is the revenue released (`package.expired`). Signals `depleted` and `extended(until)`; the expiry activity compares the stored expiry with the deadline the workflow waited for (not the wall clock), so a missed signal just re-waits. The run suffix lets a depleted package that gets units back start a new workflow (completed ids can't be reused).
  - **Deviation:** the `package_purchase` ledger type stays unused: the sale is an ordinary invoice, so ledger, payments and accounting sync are unchanged. Expiry posts no ledger entry (the client already paid); E23 doesn't sync expiry value (revenue was recognised on the invoice; deferred-revenue journals are a follow-up).
- **Recurring fees (T13):** `BillingPlan` (client, optional job/student, amount, tax rate, weekly/monthly/termly from an anchor date, start/end, `prorate`, `attendance_independent`). Periods start on the anchor's weekday or day of month (clamped to short months); **termly = every four months** until E20 brings term dates. Part periods are charged days-in-segment ÷ days-in-period, rounded half-up; Hypothesis tests check that segments tile the plan exactly, fractions are in (0, 1], monthly boundaries keep the anchor day, and a plan ending the day before another starts charges the full fee ± 1p across the shared period. Lessons on `recurring_fixed` jobs are no longer charged (the fee covers them). Not attendance-independent = skip periods with no lessons (`billing_plan.period_skipped`).
  - **BillingPlanWorkflow** (`billing-plan:{org}:{plan}`) charges each period at 06:00 local on its first day (`plan:{plan}:{start}`, idempotent), invoicing it at once (`billing.plan_invoice_immediately`); `changed` (pause, resume, edit, end) re-plans; periods that start while paused aren't charged; continue-as-new every 24 periods. No `next_*_at` columns. `GET /billing-plans/{id}/periods` previews the next 12 periods.
- **Late fees and collections (T14):** one active `LateFeeRule` per organisation (and optionally per branch; a new active rule replaces the old one): fixed or % of what is owed, after N days, once or monthly up to N times, optional cap and minimum balance, added to the next invoice or invoiced at once. `InvoiceDunningWorkflow` gained the steps behind `workflow.patched("late-fees-collections")`, so in-flight runs and the recorded history replay unchanged: reminders, fees and the collections step share one timeline. Fees are idempotent per invoice and application (`late_fee:{invoice}:{n}`) and never charged on fee-only invoices. Waiving (`POST /charges/{id}/waive`) voids an uninvoiced fee or credits an invoiced one.
  - Collections: `billing.collections_after_days` (0 = off) opens a `CollectionsCase` with a high-priority staff task on the invoice and a block (`billing.collections_block`: none/soft/hard); the case closes when the invoice is paid, voided or written off, or by staff. **Deviation:** scheduling and booking belong to the other Phase 2 work, so the block is exposed as `billing.selectors.booking_block(client_id)` (`none`/`soft`/`hard`) for the scheduling warning and the E08 self-booking engine to call; nothing in scheduling calls it yet.
- **Split billing (T15):** `POST /billing/splits` sets a job's (or a student's) paying clients and percentages (≥ 2 payers, sum 100, same currency). Lesson charges and plan charges are split with `Money.allocate` (parts always add up; e.g. £40 at 33.33/33.33/33.34 → £13.33/£13.33/£13.34), each payer's own tax exemption applies, and changed lessons reconcile per payer. A job split wins over a student split; without one, the attendee's client (or `bill_to`) pays as before. **Deviation:** one-off (ad hoc) charges aren't split: staff choose the client.
- **Accounting (E23):** package sales, plan fees and late fees are ordinary invoices and credit notes, so they sync through the existing `invoice.*`/`credit_note.issued` events with their own revenue mapping keys (product/service category). Package consumption and expiry don't sync (see above).
- **Portal (E15):** package balances and buying packages sold online; see E15's notes.
- **Frontend:** Billing gains Packages (sell, extend, cancel), Recurring fees (create, pause/resume/end), Late fees (rule form, clients in collections) and Split billing (per job) tabs; client billing gains a Packages tab.
