"""Pre-send hooks: other apps can stop a message before it is sent (E29 FR-29-6/7).

E29 registers the messaging safeguards (contact-detail and keyword screening of messages
people write, no direct tutor-to-child messages, no marketing to children). Every outgoing
message runs through ``run_pre_send``; anything that builds messages outside ``notify``
(an inbox, broadcasts) should call it too. A hook returns a reason to block, or ``""``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import structlog

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class OutgoingMessage:
    type_key: str
    category: str
    channel: str
    recipient_kind: str  # contact | tutor | user | student | ...
    recipient_id: str
    recipient_user_id: str | None
    subject: str
    body: str
    # Set when a person wrote the message (inbox, broadcast); None for system notifications.
    sender_user_id: str | None = None
    # Everyone on the conversation, as (kind, id) pairs (inbox threads).
    participants: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    source_type: str = "comms.message"
    source_id: str = ""


PreSendHook = Callable[[OutgoingMessage], str]
_hooks: list[PreSendHook] = []


def register_pre_send(hook: PreSendHook) -> PreSendHook:
    if hook not in _hooks:
        _hooks.append(hook)
    return hook


def run_pre_send(message: OutgoingMessage) -> str:
    """The first block reason any hook gives, or ``""`` to send."""
    for hook in _hooks:
        reason = hook(message)
        if reason:
            logger.info("comms.message_blocked", type_key=message.type_key, reason=reason)
            return reason
    return ""
