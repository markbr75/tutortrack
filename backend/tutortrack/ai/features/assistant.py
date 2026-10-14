"""FR-31-5 Command bar and FR-31-7 business copilot: tool-calling over whitelisted,
permission-checked tools (``tools``). The command bar returns proposals (confirmed
separately) and tutor-search filters; the copilot returns an answer citing the reports and
filters it used, with links to open them. Neither ever runs free SQL."""

from __future__ import annotations

from typing import Any

from django.utils.translation import gettext as _

from tutortrack.core.exceptions import BusinessRuleViolation, PermissionDenied
from tutortrack.core.permissions import has_perm

from .. import engine, prompts, services
from ..redaction import Redactor
from ..tools import CommandToolBox, CopilotToolBox, prime_names, today_line
from . import quoted

MAX_QUESTION = 2000
MAX_HISTORY = 6


def _text(value: str, field: str) -> str:
    value = (value or "").strip()
    if not value:
        raise BusinessRuleViolation(
            _("Type a request first."), extra={"errors": {field: [_("Required.")]}}
        )
    return value[:MAX_QUESTION]


def command(user: Any, text: str) -> dict[str, Any]:
    text = _text(text, "text")
    redactor = Redactor()
    prime_names(user, text, redactor)
    toolbox = CommandToolBox(user, redactor)
    content = f"{today_line()}\n\nInstruction:\n{quoted(text)}"
    result = engine.run(
        prompts.COMMAND, user=user, content=content, redactor=redactor, toolbox=toolbox
    )
    services.attach_request(toolbox.proposals, result.log)
    return {
        "request": str(result.log.pk),
        "message": result.text,
        "proposals": toolbox.proposals,
        "searches": toolbox.searches,
    }


def ask(user: Any, question: str, history: list[dict[str, str]] | None = None) -> dict[str, Any]:
    """``history``: earlier questions and answers of this chat (text only, last few)."""
    if not has_perm(user, "ai.copilot"):
        raise PermissionDenied()
    question = _text(question, "question")
    redactor = Redactor()
    prime_names(user, question, redactor)
    toolbox = CopilotToolBox(user, redactor)
    earlier = []
    for turn in (history or [])[-MAX_HISTORY:]:
        earlier.append(f"Q: {str(turn.get('question', ''))[:MAX_QUESTION]}")
        earlier.append(f"A: {str(turn.get('answer', ''))[:4000]}")
    parts = [today_line()]
    if earlier:
        parts += ["", "Earlier in this conversation:", quoted("\n".join(earlier))]
    parts += ["", "Question:", quoted(question)]
    result = engine.run(
        prompts.COPILOT,
        user=user,
        content="\n".join(parts),
        redactor=redactor,
        toolbox=toolbox,
    )
    return {"request": str(result.log.pk), "answer": result.text, "citations": toolbox.citations}
