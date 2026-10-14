"""Permission codenames owned by communications (E13 §6)."""

PERMISSIONS = {
    "comms.settings.manage": "Choose which notifications are sent and how",
    "comms.template.manage": "Edit message templates",
    "comms.message.view_log": "See the messages sent to people",
    "comms.preferences.manage": "Change people's communication preferences",
    # Phase 2 (E13-T10..T12)
    "comms.broadcast.view": "See broadcasts and their delivery statistics",
    "comms.broadcast.send": "Write, schedule, pause and cancel broadcasts",
    "comms.inbox.view": "Read conversations in the inbox",
    "comms.inbox.reply": "Reply to conversations and add internal notes",
    "comms.inbox.assign": "Assign, snooze and close conversations; manage canned replies",
    "comms.channels.manage": "Sender domains, phone numbers, WhatsApp templates and marketing sync",
}
