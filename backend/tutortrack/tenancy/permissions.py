"""Permission codenames owned by tenancy (E02 §7)."""

SETTINGS_VIEW = "org.settings.view"
SETTINGS_MANAGE = "org.settings.manage"
BRANCH_MANAGE = "org.branch.manage"
CLOSE = "org.close"  # owner only

PERMISSIONS = {
    SETTINGS_VIEW: "View organisation profile and settings",
    SETTINGS_MANAGE: "Change organisation profile and settings",
    BRANCH_MANAGE: "Create, edit and archive branches",
    CLOSE: "Close the organisation account (owner only)",
}
