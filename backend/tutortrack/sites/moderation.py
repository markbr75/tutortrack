"""Public profile filter (FR-24-5): stops contact details, links and profanity in tutors'
public text, so families can't be taken off-platform ("agency bypass").

Deliberately conservative: it finds email addresses (also "name at domain dot com"), phone
numbers (7+ digits with common separators), web addresses and bare domains, social handles
and messaging-app mentions, and words from a short profanity list. Staff can still edit
and approve text themselves.
"""

from __future__ import annotations

import re

from django.utils.translation import gettext as _

_EMAIL = re.compile(
    r"[\w.+-]+\s*(@|\(at\)|\[at\]|\sat\s)\s*[\w-]+\s*(\.|\(dot\)|\[dot\]|\sdot\s)\s*[a-z]{2,}",
    re.IGNORECASE,
)
_PHONE = re.compile(r"(?:\+?\d[\s().-]?){7,}")
_URL = re.compile(
    r"(https?://|www\.)\S+|\b[\w-]+\.(com|co\.uk|org|net|io|uk|me|info|biz|ly|app|site)\b",
    re.IGNORECASE,
)
_HANDLE = re.compile(r"(?<![\w.])@[A-Za-z0-9_]{3,}")
_MESSAGING = re.compile(
    r"\b(whats\s?app|telegram|signal\s+me|snap\s?chat|skype|wechat|viber|insta(gram)?|"
    r"facebook|dm\s+me|text\s+me|call\s+me)\b",
    re.IGNORECASE,
)
# Kept short and unambiguous; extend per locale as needed.
_PROFANITY = re.compile(
    r"\b(fuck\w*|shit\w*|bitch\w*|bastard\w*|cunt\w*|wank\w*|twat\w*|bollock\w*|arsehole\w*|"
    r"asshole\w*|dickhead\w*|prick\w*|slut\w*|whore\w*)\b",
    re.IGNORECASE,
)


def issues(text: str, *, contact_filter: bool = True) -> list[str]:
    """Problems found in ``text`` (empty when it is fine)."""
    found: list[str] = []
    if not text:
        return found
    if _PROFANITY.search(text):
        found.append(_("Please remove offensive language."))
    if not contact_filter:
        return found
    if _EMAIL.search(text):
        found.append(_("Email addresses aren't allowed in public profiles."))
    if _PHONE.search(text):
        found.append(_("Phone numbers aren't allowed in public profiles."))
    if _URL.search(text):
        found.append(_("Links and web addresses aren't allowed in public profiles."))
    if _HANDLE.search(text) or _MESSAGING.search(text):
        found.append(_("Social media and messaging details aren't allowed in public profiles."))
    return found
