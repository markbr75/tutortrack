"""Permission codenames owned by the AI assistant (E31). Every AI feature also checks the
permission of the data it reads or the action it proposes (grounded, permission-scoped
retrieval), so ``ai.use`` alone never widens what a user can see or do."""

PERMISSIONS = {
    "ai.use": "Use AI drafts, suggestions and the command bar",
    "ai.copilot": "Ask the business copilot questions about reports",
    "ai.settings.manage": "Turn AI features on or off and set their tone",
    "ai.usage.view": "See AI usage, credits and the request log",
}
