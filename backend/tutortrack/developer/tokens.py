"""Bearer token format and hashing.

``tt<k>_<prefix>_<secret>`` where ``<k>`` is the kind (``k`` API key, ``a`` access token,
``r`` refresh token, ``c`` authorisation code), ``<prefix>`` 12 lowercase alphanumerics
(unique, stored in clear to find the record) and ``<secret>`` 48 hex characters. Only a
SHA-256 of the whole token is stored; secrets are shown once.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import string
from dataclasses import dataclass

from .models import CredentialKind

KIND_LETTERS = {
    CredentialKind.API_KEY: "k",
    CredentialKind.ACCESS_TOKEN: "a",
    CredentialKind.REFRESH_TOKEN: "r",
    CredentialKind.AUTH_CODE: "c",
}
LETTER_KINDS = {letter: kind for kind, letter in KIND_LETTERS.items()}
_ALPHABET = string.ascii_lowercase + string.digits
PREFIX_LENGTH = 12


@dataclass(frozen=True)
class IssuedToken:
    kind: str
    prefix: str
    token: str  # the full secret: return it once, never store it

    @property
    def hash(self) -> str:
        return hash_token(self.token)

    @property
    def display(self) -> str:
        """What the UI shows afterwards, e.g. ``ttk_abc123def456…``."""
        return f"tt{KIND_LETTERS[CredentialKind(self.kind)]}_{self.prefix}\N{HORIZONTAL ELLIPSIS}"


@dataclass(frozen=True)
class ParsedToken:
    kind: str
    prefix: str
    token: str


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def matches(token: str, stored_hash: str) -> bool:
    return hmac.compare_digest(hash_token(token), stored_hash)


def issue(kind: str) -> IssuedToken:
    prefix = "".join(secrets.choice(_ALPHABET) for _ in range(PREFIX_LENGTH))
    letter = KIND_LETTERS[CredentialKind(kind)]
    return IssuedToken(kind, prefix, f"tt{letter}_{prefix}_{secrets.token_hex(24)}")


def parse(token: str) -> ParsedToken | None:
    parts = token.strip().split("_")
    if len(parts) != 3 or len(parts[0]) != 3 or not parts[0].startswith("tt"):
        return None
    kind = LETTER_KINDS.get(parts[0][2])
    prefix, secret = parts[1], parts[2]
    if kind is None or len(prefix) != PREFIX_LENGTH or len(secret) != 48:
        return None
    if not all(c in _ALPHABET for c in prefix):
        return None
    return ParsedToken(str(kind), prefix, token.strip())


def display(kind: str, prefix: str) -> str:
    return f"tt{KIND_LETTERS[CredentialKind(kind)]}_{prefix}\N{HORIZONTAL ELLIPSIS}"


def new_client_id() -> str:
    return "ttapp_" + secrets.token_hex(12)


def new_client_secret() -> str:
    return "ttsec_" + secrets.token_hex(24)


def new_webhook_secret() -> str:
    return "whsec_" + secrets.token_urlsafe(32)
