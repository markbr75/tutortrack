"""Permission codenames owned by lesson delivery (E09 §6).

Completing and cancelling lessons use ``scheduling.lesson.complete``/``cancel`` (E08); the
codenames here cover policies, attendance corrections and reports.
"""

PERMISSIONS = {
    "delivery.attendance.edit": "Correct attendance after a lesson is completed",
    "delivery.cancel.override_policy": "Override the cancellation policy outcome",
    "delivery.balance.override": "Complete lessons for clients without enough credit",
    "delivery.policy.manage": "Manage cancellation policies",
    "delivery.report.view": "See lesson reports",
    "delivery.report.write": "Write lesson reports",
    "delivery.report.approve": "Approve or return lesson reports",
    "delivery.report.edit_any": "Edit any report, even after the edit window",
    "delivery.report.share": "Share lesson reports with clients",
    "delivery.template.manage": "Manage lesson report templates",
    "delivery.makeup.view": "See makeup credits",
    "delivery.makeup.manage": "Issue, use and extend makeup credits",
}
