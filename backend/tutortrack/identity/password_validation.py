"""Password strength (FR-03-2): zxcvbn score >= 3 and not in a known breach (HIBP).

The breach check uses the k-anonymity range API: only the first 5 hex characters of the
SHA-1 hash leave the server. If the service is unreachable the check is skipped (logged),
so an outage never blocks sign-ups.
"""

from __future__ import annotations

import hashlib
import urllib.request
from typing import Any

import structlog
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _
from zxcvbn import zxcvbn

logger = structlog.get_logger(__name__)


class ZxcvbnValidator:
    def __init__(self, min_score: int = 3):
        self.min_score = min_score

    def validate(self, password: str, user: Any = None) -> None:
        inputs = [
            v for v in (getattr(user, "email", ""), getattr(user, "first_name", ""),
                        getattr(user, "last_name", "")) if v
        ]  # fmt: skip
        result = zxcvbn(password[:100], user_inputs=inputs)
        if result["score"] < self.min_score:
            hint = result["feedback"].get("warning") or _("Add more words or characters.")
            raise ValidationError(
                _("This password is too easy to guess. %(hint)s") % {"hint": hint},
                code="password_too_weak",
            )

    def get_help_text(self) -> str:
        return _("Use a long password that is hard to guess, such as a few random words.")


class PwnedPasswordValidator:
    URL = "https://api.pwnedpasswords.com/range/"

    def validate(self, password: str, user: Any = None) -> None:
        if not getattr(settings, "PWNED_PASSWORDS_CHECK", True):
            return
        digest = hashlib.sha1(password.encode(), usedforsecurity=False).hexdigest().upper()
        prefix, suffix = digest[:5], digest[5:]
        request = urllib.request.Request(  # noqa: S310 - fixed https URL
            self.URL + prefix, headers={"Add-Padding": "true", "User-Agent": "TutorTrack"}
        )
        try:
            with urllib.request.urlopen(request, timeout=3) as response:  # noqa: S310
                body = response.read().decode()
        except OSError:
            logger.warning("password.pwned_check_unavailable")
            return
        for line in body.splitlines():
            hash_suffix, _sep, count = line.partition(":")
            if hash_suffix == suffix and count.strip() != "0":
                raise ValidationError(
                    _("This password has appeared in a data breach. Choose another."),
                    code="password_pwned",
                )

    def get_help_text(self) -> str:
        return _("Your password must not have appeared in a known data breach.")
