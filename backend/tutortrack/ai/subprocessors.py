"""Sub-processors the AI assistant adds (E31 §2), for the E29 sub-processor list page
(FR-29-8). Only used when an organisation turns an AI feature on."""

from __future__ import annotations

from django.utils.translation import gettext_lazy as _

SUBPROCESSORS = [
    {
        "name": "Anthropic, PBC",
        "service": _("Claude API (AI drafts, suggestions, command bar and copilot)"),
        "location": _("United States"),
        "data": _(
            "Pseudonymised text needed for the AI feature in use (names, email addresses "
            "and phone numbers replaced by placeholders where known). Never safeguarding "
            "notes, encrypted fields, bank details or credentials."
        ),
        "retention": _(
            "Not used for model training; API inputs and outputs are retained only as set "
            "out in Anthropic's commercial terms and data processing addendum."
        ),
        "features": "ai_assistant",
        "url": "https://www.anthropic.com/legal/commercial-terms",
    }
]
