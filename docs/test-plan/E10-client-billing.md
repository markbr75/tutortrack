# E10 — Client billing (ledger, invoices, credit, packages): manual tests

**Scope.** The append-only client ledger and balances, charges from lessons and ad hoc charges, invoice runs (arrears and in advance) with a review window, invoice actions (issue, email, PDF, void, write-off, credit notes, apply credit), payment requests and prepaid credit, statements and ageing, dunning reminders, and the Phase 2 packages, recurring fees, late fees and collections, and split billing. Spec: [E10](../epics/E10-client-billing.md).

**Built differently from the spec (Implementation notes win):**
- Billing settings (`billing.*`: review days, auto-issue, auto-send, auto-apply credit, minimum amount, reminders, top-ups, prevent negative balance, package activation...) have **no admin screen**. Change them with `PATCH /api/v1/settings/billing` (Swagger at http://localhost:8010/api/v1/docs/ while signed in) or the Django shell.
- Statements are generated on demand (JSON or PDF) and, since G3, emailed monthly by the **Monthly statements** built-in workflow (E33; it was Billing → Options). Tutor pre-review of drafts and credit note PDFs were added by G3; the invoice template designer is not built.
- Packages: the `package_purchase` ledger type is unused (a sale is an ordinary invoice). Expiry posts no ledger entry.
- In advance mode reconciles continuously (credit or extra lines on the next invoice), not in one end-of-period batch.
- Collections block is exposed for scheduling/booking, but scheduling does not call it yet. Ad hoc charges are never split.
- Invoice runs, package expiry and recurring fees are Temporal workflows (`InvoiceRunWorkflow`, `PackageExpiryWorkflow`, `BillingPlanWorkflow`). Since E33, when invoices go out, payment chasing (reminders, late fee timing, collections), payment request reminders, monthly statements and the package expiry reminder are built-in workflows changed in **Workflows** (see [E33](E33-workflow-designer.md), TP-E33-038–043, 053). The billing settings they replaced (`invoice_schedule`, `invoice_day`, `reminders_enabled`, `reminder_offsets`, `collections_after_days`, `statement_schedule`, `statement_day`, `package_expiry_reminder_days`) are read-only.

**Common preconditions.**
- Stack with Celery and Temporal workers; seed loaded. Mailpit at http://localhost:8025.
- Patel family (Priya; Arjun and Maya). Arjun's GCSE Maths 1:1 lessons with Nia at £45/h. Catalogue: Registration fee £30, package "10 hours of tuition" £420 (180 days).
- Screens: `/billing` (tabs **Invoices**, **Not yet invoiced**, **Payment requests**, **Invoice runs**, **Ageing**, plus Packages, Recurring fees, Late fees, Split billing, Bank), `/invoices/<id>`, client page `/clients/<id>` → Billing section.
- To create charges quickly: complete one or more past Arjun lessons (E09), or **Add a charge** on the client.

## Ledger, balances and charges (FR-10-2, T01, T02)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E10-001 | Completed lesson creates one charge with tax | Finance (finance@) | One completed Arjun lesson | 1. Open `/billing` → **Not yet invoiced**. | One £45.00 charge for Arjun / GCSE Maths 1:1 dated the lesson date; tax per the service tax rate. | P1 | backend: `test_completion_creates_one_charge_with_tax` | |
| TP-E10-002 | Client balances summary | Finance | Patel with uninvoiced charges and an issued invoice | 1. Open the Patel client → Billing. | Tiles **Owed**, **Overdue**, **Credit**, **Not yet invoiced** show correct amounts in £ with two decimals. | P1 | backend: `test_ledger_balance_is_the_sum_of_entries` | |
| TP-E10-003 | Ledger is append-only with running balance | Finance | Several invoices and payments | 1. Client → Billing → **Ledger**. | Rows for Invoice, Payment, Credit note etc. with **Balance** running total. There is no edit or delete on any row. | P1 | backend: `test_ledger_posts_running_balance_and_is_immutable` | |
| TP-E10-004 | Add an ad hoc charge | Finance | — | 1. Patel → Billing → **Add a charge**: "Exam board fee", £25.00, Arjun.<br>2. Save. | "Charge added." It appears in Not yet invoiced. | P1 | backend: `test_ad_hoc_charges_and_discounts` | |
| TP-E10-005 | Discount as a negative charge | Finance | — | 1. **Add a charge** with −£10.00 ("Goodwill"). | Accepted (hint: "Use a negative amount for a discount."). The next invoice nets it off. | P2 | backend: `test_ad_hoc_charges_and_discounts` | |
| TP-E10-006 | Void an uninvoiced ad hoc charge | Finance | Charge from TP-E10-004 | 1. Void it from Not yet invoiced. | Charge status Void; not picked up by the next run. | P2 | backend: `test_ad_hoc_charges_and_discounts` | |
| TP-E10-007 | Attendance change updates the uninvoiced charge | Coordinator | Completed, uninvoiced lesson | 1. Change attendance to Absent (told us). | The charge drops to nothing (voided). | P1 | backend: `test_attendance_changes_update_uninvoiced_charges` | |
| TP-E10-008 | Editing an invoiced lesson adds an adjustment | Owner | Lesson on an issued invoice; unlock it (staff) and change duration | 1. Change the lesson so it is worth less. | A credit adjustment (credit note line or negative charge) for the difference; the issued invoice is unchanged. | P1 | backend: `test_editing_an_invoiced_lesson_adds_an_adjustment` | |
| TP-E10-009 | Makeup lessons are not charged | Coordinator | Makeup lesson booked with a credit (E09) | 1. Complete it. | No charge. | P2 | backend: `test_makeup_lessons_are_not_charged` | |

## Invoices and invoice runs (FR-10-3, FR-10-4, T03, T04)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E10-010 | Invoice now for one client | Finance | Patel has uninvoiced charges | 1. Patel → Billing → **Invoice now**. | A draft invoice with all uninvoiced Patel charges, lines sorted by student then date. | P1 | e2e: `e2e/billing.spec.ts` | |
| TP-E10-011 | Monthly arrears run for a family (epic AC) | Finance | Charges for Arjun and Maya last month; family grouping; Patel has £20 prior overpayment credit | 1. `/billing` → **Invoice runs** → **Run invoicing**.<br>2. From/To = last month, **Invoice**: Delivered lessons and charges.<br>3. **Preview**, then run.<br>4. **Issue now**. | Preview: "N charges for M clients would be invoiced." One Patel invoice, lines grouped by student, numbered INV-… with no gap, £20 credit applied. | P1 | backend: `test_monthly_arrears_run_for_a_family`, `test_run_reviews_then_issues` | |
| TP-E10-012 | Re-running the same period creates no duplicates | Finance | Run from TP-E10-011 | 1. Run invoicing again for the same period. | The same run is returned (idempotent); no new drafts; no charge on two invoices. | P1 | backend: `test_concurrent_runs_never_invoice_a_charge_twice` | |
| TP-E10-013 | Review window then auto-issue | Finance | `billing.auto_issue` on, `billing.review_days` = 0 or 1 | 1. Start a run; watch status Collecting → In review → Issuing → Completed.<br>2. Temporal UI: `invoice-run:<org>:...`. | Drafts are issued after the review timer. Workflow shows the steps. | P2 | backend: `test_run_reviews_then_issues` | |
| TP-E10-014 | Run waits for approval when auto-issue is off | Finance | `billing.auto_issue` off | 1. Start a run.<br>2. Later choose **Issue now**. | Run stays **In review** until approved, then issues. | P1 | backend: `test_run_waits_for_approval_when_auto_issue_is_off` | |
| TP-E10-015 | Edit a draft | Finance | Draft invoice | 1. Open the draft → **Add line** (£12 books).<br>2. **Remove** a lesson line.<br>3. Add a PO number and notes. | Totals recalculate. The removed charge returns to Not yet invoiced. | P1 | backend: `test_draft_editing_minimum_and_currency_splits` | |
| TP-E10-016 | Issue an invoice | Finance | Draft | 1. **Issue invoice**. | Gets the next INV- number, issue and due dates from payment terms, posts to the ledger, locks the lessons, status Issued. | P1 | backend: `test_issue_numbers_locks_posts_and_renders_pdf`; e2e: `e2e/billing.spec.ts` | |
| TP-E10-017 | Invoice PDF content | Finance | Issued invoice | 1. **Download PDF**. | Branded PDF with org and branch details, client billing details, PO, lines (date, student, service, tutor name if set, duration, rate, tax, amount), subtotal, tax summary, total, credit applied, amount due, due date, payment instructions and pay link. | P1 | backend: `test_issue_numbers_locks_posts_and_renders_pdf` | |
| TP-E10-018 | Email to client | Finance | Issued invoice | 1. **Email to client**. | Mailpit: email to Priya with the PDF attached and a `/pay/<token>` link. | P1 | No | |
| TP-E10-019 | Totals are sums of rounded lines | Finance | Three charges of £33.335 net each (e.g. via 44.45 min lessons or ad hoc with 20% tax) | 1. Invoice them. | Each line rounded half-up to the penny; subtotal and total equal the sum of rounded lines. | P1 | backend: `tutortrack/billing/tests/test_billing.py` | |
| TP-E10-020 | Zero, negative and minimum amounts carried forward | Finance | `billing.minimum_invoice_amount` = £20; client with only a £10 charge; another with net −£5 | 1. Run invoicing. | No invoice for either; charges stay uninvoiced for the next run. | P2 | backend: `test_draft_editing_minimum_and_currency_splits` | |
| TP-E10-021 | One invoice per currency | Finance | Patel ad hoc charge in EUR plus GBP lessons | 1. **Invoice now**. | Two drafts: one GBP, one EUR. | P2 | backend: `test_draft_editing_minimum_and_currency_splits` | |
| TP-E10-022 | Group per student instead of per family | Finance | Client setting group by student | 1. Run invoicing. | One invoice for Arjun, one for Maya. | P2 | No | |
| TP-E10-023 | Hold invoices for missing reports | Finance | `delivery.hold_invoice_without_report` on; a lesson without a report | 1. Run invoicing. | That charge is left out. | P2 | backend: `test_hold_invoices_for_missing_reports` | |
| TP-E10-024 | Scheduled invoice runs follow the Invoicing cycle | Owner | Invoicing cycle on, monthly on the 1st | 1. Workflows › Invoicing cycle › Coming up. | The next dates are listed; changing the start's day changes them after saving. | P3 | backend: `tutortrack/billing/tests/test_workflows_builtin.py` | |

## Credit notes, void, write-off, credit (FR-10-4, FR-10-5, T05)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E10-025 | Partial credit note kept as client credit | Finance | Issued, unpaid £90 invoice (two lessons) | 1. Invoice → **Credit note**.<br>2. Credit one line £45, **Reason** "Tutor ill".<br>3. **Use the credit to**: Keep as client credit.<br>4. **Issue credit note**. | CN-… number with no gaps; ledger credit −£45; Patel **Credit** goes up by £45; invoice still owes £90. | P1 | backend: `test_partial_credit_note_and_credit_left_with_client` | |
| TP-E10-026 | Credit note reduces the invoice | Finance | Issued invoice | 1. Credit note with Reduce what's owed on this invoice. | Amount due drops; Credit applied shown. | P1 | backend: `test_partial_credit_note_and_credit_left_with_client`; e2e: `e2e/billing.spec.ts` | |
| TP-E10-027 | Apply client credit to an invoice | Finance | Client credit £45, open invoice £90 | 1. Invoice → **Use client credit**. | Amount due £45; credit £0. Credit never exceeds what is owed. | P1 | backend: `test_credit_never_over_allocates` | |
| TP-E10-028 | Void an invoice with no payments | Finance | Issued invoice, no payments or credit notes | 1. **Void** → **Void invoice** with a reason. | Status Void; reversing ledger entry; charges return to Not yet invoiced; lessons unlocked. | P1 | backend: `test_void_reverses_and_returns_charges` | |
| TP-E10-029 | Void is refused after a payment | Finance | Invoice with a recorded payment | 1. Try **Void**. | Refused with a clear message; suggest a credit note. | P1 | backend: `test_void_reverses_and_returns_charges` | |
| TP-E10-030 | Write off bad debt | Finance | Overdue invoice | 1. **Write off** → reason → **Write off invoice**. | Status Written off; write-off ledger entry; dunning stops. | P2 | backend: `test_write_off` | |
| TP-E10-031 | Issued invoices cannot be edited | Finance | Issued invoice | 1. Look for line edit controls.<br>2. Try `PATCH /api/v1/invoices/<id>`. | No edit controls; API refuses. | P1 | backend: `test_issue_numbers_locks_posts_and_renders_pdf` | |
| TP-E10-032 | Delete a draft | Finance | Draft | 1. **Delete draft**. | Draft gone; charges back to uninvoiced; no number consumed. | P2 | No | |

## Payment requests and prepaid credit (FR-10-6, T06)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E10-033 | Request a payment for a client | Finance | — | 1. Okafor client → Billing → **Request payment** £400. | PR-… created, "Awaiting payment"; Mailpit has the request with a pay link. | P1 | backend: `test_payment_request_credit_is_drawn_down_by_lessons` | |
| TP-E10-034 | Paid request becomes credit, drawn down by lessons (epic AC) | Finance, Parent | Request from TP-E10-033 paid (record a bank transfer against it, or via fake Stripe webhook — see README) | 1. Check Okafor credit.<br>2. Complete two prepaid lessons.<br>3. Parent checks the portal billing page. | Credit +£400, then reduced by each lesson (receipt invoices when `billing.prepaid_invoice_each_lesson`). The portal shows the running balance. | P1 | backend: `test_payment_request_credit_is_drawn_down_by_lessons` | |
| TP-E10-035 | Bulk top-up requests | Finance | Several prepaid clients with low credit | 1. Payment requests tab → **Request top-ups**: **Clients with credit below** £50, **Top up to** £200. | "N payment requests created." Amounts top each client up to £200. | P2 | backend: `test_bulk_and_automatic_top_up_requests` | |
| TP-E10-036 | Automatic request at threshold | Owner | `billing.topup_threshold` set | 1. Complete lessons until credit drops below the threshold. | `client.balance_low` and one automatic request. | P2 | backend: `test_bulk_and_automatic_top_up_requests` | |
| TP-E10-037 | Request reminders | Finance | Open request | 1. Workflows › Runs: the **Payment request reminders** run for the request. | Reminders at day 3 and day 7; stops on payment or cancel. | P3 | backend: `tutortrack/billing/tests/test_workflows_builtin_runs.py` | |
| TP-E10-038 | Negative balance guard for prepaid jobs | Tutor | Prepaid job, credit £0, guard on | See E09 TP-E09-009. | Completion blocked for the tutor. | P1 | backend: `test_negative_balance_guard_blocks_prepaid_completion` | |

## In advance billing (FR-10-1, T07)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E10-039 | Invoice scheduled lessons in advance | Finance | Arjun job billing method `invoice_in_advance`; 4 planned lessons next month | 1. **Run invoicing**, **Invoice**: Scheduled lessons, in advance, next month. | One invoice for 4 × £45. Completing those lessons later creates no further charge. | P1 | backend: `test_advance_invoicing_and_reconciliation` | |
| TP-E10-040 | Free cancellation after advance invoicing reconciles | Coordinator | Invoice from TP-E10-039 | 1. Cancel one lesson free (with notice). | A −£45 reconciliation line appears on the next invoice (or credit). | P1 | backend: `test_advance_invoicing_and_reconciliation` | |
| TP-E10-041 | Extra lesson after advance invoicing | Coordinator | — | 1. Add an extra lesson in the invoiced period. | An extra charge appears for the next invoice. | P2 | backend: `test_advance_invoicing_and_reconciliation` | |

## Statements, ageing and reminders (FR-10-9, FR-10-10, T08, T09)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E10-042 | Client statement PDF | Finance | Patel with history | 1. Client → Billing → **Statement (PDF)** for the last 3 months. | Opening balance, invoices, payments, credits, closing balance and ageing; matches the ledger. | P2 | backend: `test_statement_and_ageing` | |
| TP-E10-043 | Ageing report | Finance | Invoices overdue by 10, 45, 100 days | 1. `/billing` → **Ageing**. | Buckets Not yet due, 1–30, 31–60, 61–90, Over 90 days with the right totals. | P2 | backend: `test_statement_and_ageing` | |
| TP-E10-044 | Reminder sent once per offset (epic AC) | Finance | Invoice 7 days overdue; **Payment chasing** has a step 7 days after “Due” | 1. **Workflows** → **Runs**: the Payment chasing run for the invoice.<br>2. Mailpit. | Exactly one +7 reminder at 09:00 local, even after a worker restart. `invoice.overdue` once. | P1 | backend: `test_reminders_publish_once_per_offset`, `test_payment_chasing_reminds_applies_the_late_fee_and_stops_when_paid` | |
| TP-E10-045 | Paying stops dunning | Finance | A Payment chasing run waiting | 1. Record full payment. | The run shows "Stopped: Invoice paid"; no later reminders. | P1 | backend: `test_payment_chasing_reminds_applies_the_late_fee_and_stops_when_paid` | |

## Packages (FR-10-7, T12, Phase 2)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E10-046 | Sell a package | Finance | — | 1. `/billing` → Packages → **Sell package**: Patel, Arjun, "10 hours of tuition". | "Sold. Invoice INV-…; the package can be used once it's paid." Status Awaiting payment. | P1 | backend: `test_selling_invoices_then_activates_on_payment` | |
| TP-E10-047 | Activate on payment | Finance | Package from TP-E10-046 | 1. Record a £420 payment on its invoice. | Package Active; expiry = today + 180 days. | P1 | backend: `test_selling_invoices_then_activates_on_payment` | |
| TP-E10-048 | Activation on issue setting | Owner | `billing.package_activation=issue` | 1. Sell a package. | Active as soon as the invoice is issued. | P3 | backend: `test_activation_on_issue_setting` | |
| TP-E10-049 | Lessons consume hours instead of charging | Coordinator | Active 10 h package; Arjun job billed by package | 1. Complete a 60-min lesson. | No charge; "9 of 10 hours left". Client portal and tutor show hours remaining. | P1 | backend: `test_lessons_consume_hours_instead_of_charging` | |
| TP-E10-050 | Overage charged for the part not covered | Coordinator | 0.5 h left | 1. Complete a 60-min lesson. | Package Used up; a £22.50 charge for the uncovered half. | P2 | backend: `test_overage_is_charged_for_the_part_not_covered` | |
| TP-E10-051 | Oldest-expiring package first, low and depleted | Finance | Two active packages | 1. Complete lessons. | The one expiring first is used first; `package.low` once at the threshold; then depleted (auto-renew templates sold again). | P2 | backend: `test_oldest_expiring_package_is_used_first_then_depletes_and_renews`, `test_low_balance_is_announced_once` | |
| TP-E10-052 | Attendance change gives units back | Coordinator | Lesson consumed 1 h | 1. Change attendance to Absent (told us). | Reversal movement; hours return. | P2 | backend: `test_changed_attendance_gives_units_back_and_takes_them_again` | |
| TP-E10-053 | Extend and cancel a package | Finance | Active package with 6 h left | 1. **Extend** with a **New expiry date**.<br>2. **Cancel package** with a reason. | Expiry moves. Cancelling issues a credit note for unused value (pro rata). | P2 | backend: `test_extend_moves_the_expiry`, `test_cancel_credits_unused_value_by_credit_note` | |
| TP-E10-054 | Package expiry reminder and write-off | Finance | Package near expiry; Temporal worker | 1. The **Package expiry reminder** built-in (14 days before, 09:00).<br>2. Temporal UI: `package:<org>:<purchase>:...`. | Reminder email `package_expiring` before, once per expiry date; at expiry unused units written off (status Expired). | P2 | backend: `test_packages_are_reminded_once_per_expiry_date`, `test_package_expires_and_leaves_the_reminder_to_the_workflow` | |
| TP-E10-055 | Voiding an unpaid sale cancels the package | Finance | Pending package | 1. Void its invoice. | Package Cancelled; charge voided. | P2 | backend: `test_voiding_an_unpaid_sale_cancels_the_package` | |

## Recurring fees (FR-10-8, T13)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E10-056 | Create a monthly fee with proration | Finance | — | 1. `/billing` → Recurring fees → **New recurring fee**: Okafor, £160, **Every** month, **Starts** the 15th, **Prorate part periods** on.<br>2. **Create**. | Plan Active "from <date>". Preview of the next 12 periods. First part period charged pro rata (days ÷ days in period, half-up). | P1 | backend: `test_periods_are_charged_once_prorated_and_invoiced`, `test_plan_api_creates_previews_and_pauses` | |
| TP-E10-057 | Pause, resume, end | Finance | Active plan | 1. **Pause**, then **Resume**, then **End**. | Periods starting while paused are not charged; ending stops billing. | P2 | backend: `test_pausing_skips_periods_and_ending_stops_billing` | |
| TP-E10-058 | Termly fee follows E20 terms | Finance | Branch with terms (seed "This term") | 1. Create a termly plan. | Periods match the terms; holidays between terms not billed. | P2 | backend: `tutortrack/billing/tests/test_phase2.py` | |
| TP-E10-059 | Lessons on recurring-fee jobs are not charged | Coordinator | Job billing method recurring fixed | 1. Complete a lesson. | No lesson charge. | P2 | backend: `test_lessons_on_recurring_fee_jobs_are_not_charged` | |
| TP-E10-060 | Attendance-dependent plan skips empty periods | Finance | Plan not attendance-independent; a month with no lessons | 1. Let the period pass. | No charge; `billing_plan.period_skipped`. | P3 | backend: `test_plans_that_follow_attendance_skip_periods_without_lessons` | |

## Late fees and collections (FR-10-10, T14)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E10-061 | Set a late fee rule | Finance | — | 1. `/billing` → **Late fees**: **Charge late fees** on, Fixed amount £10, **Days overdue** 14, **Charge** Once, **Bill it** On the next invoice.<br>2. **Save**. | "Saved." A new rule replaces any previous one. | P1 | backend: `test_a_new_rule_replaces_the_previous_one`, `test_late_fee_rules_api` | |
| TP-E10-062 | Fixed fee charged once | Finance | Invoice 14 days overdue | 1. Check charges after Payment chasing's late fee step. | One £10 late fee charge; not repeated. | P1 | backend: `test_fixed_late_fee_is_charged_once_per_application`, `test_the_late_fee_step_applies_the_rule_each_time` | |
| TP-E10-063 | Percentage fee recurs monthly up to the cap | Finance | 2% monthly, max 3 times | 1. Let an invoice stay unpaid. | Fees of 2% of owed each month, max 3. | P2 | backend: `test_percentage_fees_recur_monthly_up_to_the_cap` | |
| TP-E10-064 | Immediate fee invoice gets no fee on fee | Finance | Mode On its own invoice now | 1. Let it apply; let the fee invoice go overdue. | Fee invoice created; no late fee charged on it. | P2 | backend: `test_immediate_late_fees_get_their_own_invoice_without_fees_on_fees` | |
| TP-E10-065 | Waive a late fee | Finance | Uninvoiced and invoiced fees | 1. Waive each. | Uninvoiced fee voided; invoiced fee credited. | P2 | backend: `test_paid_invoices_get_no_fee_and_waiving_voids_or_credits` | |
| TP-E10-066 | Collections case and block | Finance | Payment chasing's collections step at 30 days after “Due”, block soft | 1. Let an invoice go 30 days overdue.<br>2. Late fees tab → **In collections**.<br>3. **Take out of collections**. | Case with a high-priority staff task; label "warn when scheduling". Closing ends it; paying closes it. | P2 | backend: `test_collections_open_a_task_and_block_until_paid` | |

## Split billing (FR-10-12, T15)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E10-067 | Split a job 50/50 | Finance | A second client "Raj Patel" | 1. `/billing` → Split billing → **Choose a job…** Arjun GCSE → **Split the job's billing** 50/50 → **Save split**. | "Total: 100%". Saved. | P1 | backend: `test_split_api` | |
| TP-E10-068 | Lesson charges split between payers | Coordinator | Split from TP-E10-067 | 1. Complete a £45 lesson. | Two charges £22.50 each, one per payer, each with its own tax treatment. | P1 | backend: `test_lesson_charges_are_split_between_payers` | |
| TP-E10-069 | Uneven split allocates pennies exactly | Finance | 33.33/33.33/33.34 split; £40 lesson | 1. Complete the lesson. | £13.33 / £13.33 / £13.34; parts add to £40.00. | P2 | backend: `test_lesson_charges_are_split_between_payers` | |
| TP-E10-070 | Validation | Finance | — | 1. Save a split totalling 90%, or with one payer, or a payer in another currency. | Refused with clear errors. | P2 | backend: `test_splits_must_add_up_and_name_two_payers`, `test_student_split_rejects_another_currency` | |
| TP-E10-071 | Stop splitting | Finance | Split job | 1. **Stop splitting**. | "Not split: the job's client pays." | P3 | No | |

## Permissions

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E10-072 | Finance has full billing | Finance | — | 1. Open `/billing`, an invoice, a client billing section. | All actions available. | P1 | e2e: `e2e/billing.spec.ts` | |
| TP-E10-073 | Coordinator can view but not change invoices | Coordinator | Issued invoice | 1. Open `/billing` and the invoice. | Lists and detail visible; no Issue, Void, Write off, Credit note or Add a charge actions; API returns 403. | P1 | e2e: `e2e/billing.spec.ts` | |
| TP-E10-074 | Tutor has no billing | Tutor | — | 1. Try `/billing` and `/api/v1/invoices`. | No nav item; 403. | P1 | No | |
| TP-E10-075 | Parent sees only own household invoices | Parent | Okafor has invoices too | 1. Portal → Billing.<br>2. Try an Okafor invoice id via the portal API. | Only Patel invoices; Okafor returns 404. | P1 | e2e: `e2e/portal-parent.spec.ts` | |
| TP-E10-076 | Branch manager limited to branch | Branch Manager | multi_branch, second branch invoices | 1. Open `/billing`. | Only MAIN branch invoices. | P2 | No | |

## Tenant isolation

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E10-077 | Northside never sees Bright Minds billing | Owner of Northside | Bright Minds invoices exist | 1. At northside.localhost open `/billing`.<br>2. GET a Bright Minds invoice id and `/pay/<Bright Minds token>` on the Northside host. | Empty lists; 404 for both. | P1 | backend: `tutortrack/billing/tests/test_billing.py` (TenantIsolationTestMixin) | |
| TP-E10-078 | Invoice numbering is per organisation | Both owners | — | 1. Issue an invoice in each org. | Each org has its own INV- sequence. | P2 | No | |

## i18n, time zones and currency

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E10-079 | Currency format follows locale | Finance | GBP org; switch user locale to en-US | 1. View an invoice and the PDF. | Amounts formatted by locale (£1,234.50); no hard-coded symbol for EUR/USD invoices. | P2 | No | |
| TP-E10-080 | Tax inclusive vs exclusive | Owner | Toggle `billing.prices_include_tax`; 20% VAT on a £45 service | 1. Invoice one lesson in each mode. | Exclusive: net £45, tax £9, gross £54. Inclusive: gross £45, net £37.50, tax £7.50. | P1 | backend: `test_completion_creates_one_charge_with_tax` | |
| TP-E10-081 | Tax-exempt client | Finance | Client flagged tax exempt | 1. Invoice a lesson. | No tax on lines. | P2 | No | |
| TP-E10-082 | Month boundaries in local time | Finance | Lesson at 23:30 on the last day of the month (Europe/London, BST) | 1. Run invoicing for that month. | The lesson is in that month (local date), not the next. | P2 | No | |

## Errors and edge cases

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E10-083 | Two runs at the same time | Finance ×2 | Two browsers | 1. Start runs for overlapping periods together. | No charge is invoiced twice (row locks). | P1 | backend: `test_concurrent_runs_never_invoice_a_charge_twice` | |
| TP-E10-084 | Credit note larger than the invoice | Finance | £45 invoice | 1. Try to credit £60. | Refused. | P2 | No | |
| TP-E10-085 | Gap-free numbering after a deleted draft | Finance | Delete a draft, issue another | 1. Compare numbers. | No gap (numbers assigned only at issue). | P2 | backend: `test_credit_notes_are_numbered_without_gaps` | |

## Gap batch G3 (as built 2026-10-14)

Built by gap batch G3 ([ADR 0037](../adr/0037-gap-batch-g3-scheduling-billing-payments-payroll.md)); see the epic's *Gap backlog* notes.

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E10-086 | Tutors check their lessons before issuing | Tutor (Nia) and Finance | Billing → Options → tutors check drafts on, 2 days; review days 0 | 1. Run invoicing.<br>2. Nia: portal → **Check invoices** → **These are right**. | Nia sees dates, students and minutes, never amounts; once every tutor has answered the run issues straight away. | P1 | backend: `test_issuing_waits_for_tutors_then_ends_early`; vitest (portal): `G3.test.tsx` | |
| TP-E10-087 | A flagged draft is held | Tutor and Finance | As above | 1. Nia: **Something's wrong** → comment → **Send**. | Staff get an alert; at the end of the window that draft stays a draft (run shows "1 invoice held"); others are issued. | P1 | backend: `test_flagged_drafts_are_held_when_the_window_ends`, `test_tutors_confirm_or_flag_through_the_api` | |
| TP-E10-088 | Credit note PDF | Finance | Issued invoice with a credit note | 1. Invoice page → credit notes → **PDF of CN-…**. | A PDF with the number, credited invoice, reason, lines and how the credit is used. | P2 | backend: `test_credit_note_pdf` | |
| TP-E10-089 | Monthly statements by email | Finance | **Monthly statements** built-in switched on, monthly on day 1; Patel had activity last month | 1. Wait for (or trigger) the schedule. | Priya gets last month's statement with a PDF, once. Billing → Options says statements are sent by the workflow. | P1 | backend: `test_statements_email_last_months_statement_with_the_pdf`, `test_statements_go_only_to_families_with_something_to_show` | |
| TP-E10-090 | Package liabilities fall as units are used | Finance | 10-hour package sold and paid | 1. Complete one hour.<br>2. Open the Package liabilities report. | Deferred revenue = sale net × 9/10. | P1 | backend: `test_package_revenue_is_recognised_as_units_are_used` | |
