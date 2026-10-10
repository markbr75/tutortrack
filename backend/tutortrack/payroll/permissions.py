"""Permission codenames owned by payroll (E12 §6)."""

PERMISSIONS = {
    "payroll.view": "See pay items, pay runs and payouts",
    "payroll.item.manage": "Add bonuses, adjustments and deductions; hold and release items",
    "payroll.expense.submit": "Submit expense and mileage claims",
    "payroll.expense.approve": "Approve or reject expense and mileage claims",
    "payroll.payrun.create": "Create pay runs and change their contents",
    "payroll.payrun.approve": "Approve pay runs",
    "payroll.payrun.pay": "Send payouts, download bank files and mark pay runs paid",
    "payroll.profile.manage": "Edit tutors' pay method and payout details",
    "payroll.bank_details.view": "See tutors' full bank details (otherwise masked)",
}
