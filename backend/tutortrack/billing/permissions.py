"""Permission codenames owned by client billing (E10 §7)."""

PERMISSIONS = {
    "billing.invoice.view": "See invoices, credit notes and client balances",
    "billing.invoice.create": "Create and edit draft invoices and run invoicing",
    "billing.invoice.issue": "Issue and send invoices",
    "billing.invoice.void": "Void invoices that have no payments",
    "billing.invoice.write_off": "Write off unpaid invoices",
    "billing.credit_note.issue": "Issue credit notes and apply client credit",
    "billing.charge.view": "See uninvoiced charges",
    "billing.charge.create": "Add one-off charges and discounts",
    "billing.charge.void": "Void uninvoiced charges",
    "billing.payment_request.view": "See payment requests",
    "billing.payment_request.manage": "Create, send and cancel payment requests",
    "billing.ledger.view": "See client ledgers and statements",
    "billing.ledger.adjust": "Post manual ledger adjustments",
    "billing.settings.manage": "Change billing settings",
}
