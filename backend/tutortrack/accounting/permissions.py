"""Permission codenames for accounting integrations (E23). The Finance role has
``integrations.accounting.*``."""

PERMISSIONS = {
    "integrations.accounting.view": "See accounting sync status, errors and mappings",
    "integrations.accounting.manage": (
        "Connect Xero or QuickBooks, edit mappings, switch sync on, retry or skip records"
    ),
    "integrations.accounting.export": "Download general ledger exports",
}
