"""Permission codenames owned by reporting (E26).

Each report family has its own codename so a role can get finance-only or operations-only
reports; the data scope of the grant (all / branch / own) limits the figures, e.g. a tutor
holding ``reporting.payroll.view:own`` only sees their own earnings.
"""

PERMISSIONS = {
    "reporting.dashboard.view": "See the dashboard",
    "reporting.finance.view": "Run finance reports (revenue, debtors, tax, margin)",
    "reporting.payroll.view": "Run payroll reports (earnings, pay runs, expenses)",
    "reporting.operations.view": "Run operations reports (lessons, attendance, utilisation)",
    "reporting.sales.view": "Run sales and growth reports (enquiries, retention, lifetime value)",
    "reporting.people.view": "Run people and compliance reports",
    "reporting.export": "Export reports (CSV, Excel, PDF)",
    "reporting.schedule.manage": "Schedule reports to be emailed",
    "reporting.manage": "Rebuild reporting data and refresh exchange rates",
}
