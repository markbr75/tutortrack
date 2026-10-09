"""Permission codenames owned by scheduling (E08 §6)."""

PERMISSIONS = {
    "scheduling.lesson.view": "See lessons and the calendar",
    "scheduling.lesson.create": "Schedule lessons and series",
    "scheduling.lesson.edit": "Edit and reschedule lessons and series",
    "scheduling.lesson.cancel": "Cancel lessons",
    "scheduling.lesson.complete": "Mark lessons completed or missed",
    "scheduling.lesson.delete": "Delete planned lessons that were never delivered",
    "scheduling.override_conflicts": "Schedule despite a tutor or room clash",
    "scheduling.edit_locked": "Edit invoiced or paid lessons (creates adjustments)",
    "scheduling.event.view": "See calendar events",
    "scheduling.event.manage": "Create calendar events and organisation-wide closures",
    "scheduling.availability.view": "See tutors' availability and time off",
    "scheduling.availability.edit": "Edit availability and time off",
    "scheduling.availability.manage_others": "Edit other tutors' availability",
    "scheduling.booking.settings": "Configure online booking (Phase 2)",
}
