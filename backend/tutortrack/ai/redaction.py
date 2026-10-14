"""Pseudonymisation before anything reaches the model (E31 §2 privacy).

Features register the people they know about (``person``) before building a prompt;
``redact`` then swaps their names, and any email address or phone number, for
placeholders such as ``[STUDENT_1]`` / ``[STUDENT_1_FIRST]`` / ``[EMAIL_1]``.
``restore`` puts the real values back into the model's answer, so drafts read naturally
while the provider only ever sees placeholders.

What must never be sent is excluded at the source instead: prompts are built from
explicit allow-lists of fields, so safeguarding notes, ``EncryptedField`` values, bank
details and tokens are never read into a prompt in the first place.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# Phone numbers and other long digit runs (account, card numbers): candidates with
# separators, kept only when they hold at least 10 digits (so dates and amounts stay).
PHONE_RE = re.compile(r"(?<![\w\]])\+?\d[\d \-().]{6,}\d(?![\w\[])")
MIN_PHONE_DIGITS = 10
PLACEHOLDER_RE = re.compile(r"\[[A-Z]+_\d+(?:_FIRST|_LAST)?\]")


class Redactor:
    def __init__(self) -> None:
        self._to_placeholder: dict[str, str] = {}  # lower-cased value -> placeholder
        self._to_value: dict[str, str] = {}
        self._counters: dict[str, int] = {}
        self._pattern: re.Pattern[str] | None = None

    # --- registering -----------------------------------------------------------------------

    def _new(self, kind: str) -> str:
        self._counters[kind] = self._counters.get(kind, 0) + 1
        return f"{kind}_{self._counters[kind]}"

    def _register(self, value: str, placeholder: str) -> None:
        key = value.strip().lower()
        if len(key) < 2 or key in self._to_placeholder:
            return
        self._to_placeholder[key] = placeholder
        self._to_value[placeholder] = value.strip()
        self._pattern = None

    def person(
        self, full_name: str, *, kind: str = "PERSON", first_name: str = "", last_name: str = ""
    ) -> str:
        """Register a person; returns their full-name placeholder (``[KIND_n]``)."""
        full_name = (full_name or "").strip()
        if not full_name and not first_name:
            return ""
        existing = self._to_placeholder.get(full_name.lower()) if full_name else None
        if existing:
            return existing
        base = self._new(kind.upper())
        placeholder = f"[{base}]"
        if full_name:
            self._register(full_name, placeholder)
        parts = full_name.split()
        first = (first_name or (parts[0] if len(parts) > 1 else "")).strip()
        last = (last_name or (parts[-1] if len(parts) > 1 else "")).strip()
        if first and first.lower() != full_name.lower():
            self._register(first, f"[{base}_FIRST]")
        if last and len(last) > 2 and last.lower() != full_name.lower():
            # A bare surname ("Mrs Patel") gets its own placeholder.
            self._register(last, f"[{base}_LAST]")
        return placeholder

    def value(self, text: str, kind: str) -> str:
        """Register any other identifying value (an organisation name, an address)."""
        text = (text or "").strip()
        if not text:
            return ""
        existing = self._to_placeholder.get(text.lower())
        if existing:
            return existing
        placeholder = f"[{self._new(kind.upper())}]"
        self._register(text, placeholder)
        return placeholder

    # --- applying --------------------------------------------------------------------------

    def _names(self) -> re.Pattern[str] | None:
        if self._pattern is None and self._to_placeholder:
            alternatives = sorted(self._to_placeholder, key=len, reverse=True)
            joined = "|".join(re.escape(a) for a in alternatives)
            self._pattern = re.compile(rf"(?<![\w\[])(?:{joined})(?![\w\]])", re.IGNORECASE)
        return self._pattern

    def _scrub(self, regex: re.Pattern[str], text: str, kind: str) -> str:
        def swap(match: re.Match[str]) -> str:
            found = match.group(0)
            if kind == "PHONE" and sum(c.isdigit() for c in found) < MIN_PHONE_DIGITS:
                return found
            existing = self._to_placeholder.get(found.lower())
            if existing:
                return existing
            placeholder = f"[{self._new(kind)}]"
            self._register(found, placeholder)
            return placeholder

        return regex.sub(swap, text)

    def redact(self, text: str) -> str:
        if not text:
            return text
        text = self._scrub(EMAIL_RE, text, "EMAIL")
        text = self._scrub(PHONE_RE, text, "PHONE")
        pattern = self._names()
        if pattern is not None:
            text = pattern.sub(lambda m: self._to_placeholder[m.group(0).lower()], text)
        return text

    def restore(self, text: str) -> str:
        if not text:
            return text
        return PLACEHOLDER_RE.sub(lambda m: self._to_value.get(m.group(0), m.group(0)), text)

    def redact_data(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.redact(value)
        if isinstance(value, list):
            return [self.redact_data(v) for v in value]
        if isinstance(value, dict):
            return {k: self.redact_data(v) for k, v in value.items()}
        return value

    def restore_data(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.restore(value)
        if isinstance(value, list):
            return [self.restore_data(v) for v in value]
        if isinstance(value, dict):
            return {k: self.restore_data(v) for k, v in value.items()}
        return value

    def placeholder_for(self, value: str) -> str | None:
        return self._to_placeholder.get((value or "").strip().lower())

    @property
    def known_values(self) -> list[str]:
        return list(self._to_value.values())


def fingerprint(system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> str:
    """sha256 of exactly what was sent (already redacted): the only trace of a prompt."""
    payload = json.dumps(
        {"system": system, "messages": messages, "tools": [t["name"] for t in tools]},
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()
