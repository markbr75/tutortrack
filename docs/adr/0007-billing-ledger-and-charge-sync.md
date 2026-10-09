# ADR 0007: Append-only ledger, credit as a derived pool, and charges that follow lessons

- **Status:** Accepted
- **Date:** 2026-10-09
- **Epic:** E10

## Context
E10 must support pay-as-you-go, invoicing in advance and prepaid credit. Packages and fixed
fees follow in Phase 2. Every financial record must be immutable once issued, and balances
must always be explainable. Lessons keep changing after they are charged: attendance is
corrected, lessons are re-priced or rescheduled, and lessons invoiced in advance are
cancelled or added. Payments (E11) must be able to allocate to invoices without billing
knowing about providers.

## Decision
1. **Ledger.** `ClientLedgerEntry` rows are append-only: the model refuses updates and
   deletes. Positive entries increase what the client owes (invoice, refund); negative
   entries reduce it (payment, credit note, top-up, write-off, invoice void). Posts lock
   the client row, so `balance_after` is a correct running total per currency.
2. **Credit is derived, not stored.** Available credit = Σ `balance_due` of open invoices −
   ledger balance, when positive. Applying credit to an invoice is an *allocation*
   (`CreditAllocation`, `invoice.amount_credited`) and posts no ledger entry. Payments
   from E11 post a `payment` entry and then `allocate_payment` to invoices; anything left
   over is credit automatically.
3. **Charges follow lessons.** One idempotent function, `sync_attendee_charge`, compares
   what an attendee *should* be billed (lesson status, the E09 charge %, makeup credit,
   advance mode) with what is already invoiced. It replaces any uninvoiced charges with a
   single charge for the difference. After invoicing, a difference becomes a
   `reconciliation` line on the next invoice. Every lesson event (`completed`,
   `cancelled`, `attendance.recorded`, `updated`, `locked_edited`) calls it, so redelivered
   events never double-charge.
4. **Invoices** are drafted from row-locked charges (`FOR UPDATE SKIP LOCKED`), so
   concurrent runs never invoice a charge twice. They are numbered gap-free at issue
   (`core.sequences`) and immutable once issued; corrections are credit notes. Lessons on
   an issued invoice are locked once delivered. Lessons invoiced in advance stay editable,
   and their changes reconcile.
5. **PDFs** are rendered on demand with WeasyPrint from the issued invoice's own lines and
   its billing snapshot (taken at issue), not stored files.

## Consequences
- Reconciliation for advance invoicing happens continuously, not in one end-of-period
  batch, and appears on the next invoice.
- Credit allocations to an invoice cannot be undone except by voiding it (the credit
  returns to the pool) or issuing a credit note.
- E11 needs only `ledger.post(payment)`, `allocate_payment`/`unallocate_payment` and
  `pay_payment_request`.
