"""Print a new VAPID key pair for Web Push (E16-T09).

Put the values in ``VAPID_PUBLIC_KEY`` / ``VAPID_PRIVATE_KEY`` (a secret: the secrets
manager in production). Changing the keys makes every browser subscribe again.
"""

from __future__ import annotations

import base64
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from django.core.management.base import BaseCommand


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def generate() -> tuple[str, str]:
    """(public key as the browser's applicationServerKey, raw private key), base64url."""
    key = ec.generate_private_key(ec.SECP256R1())
    private = key.private_numbers().private_value.to_bytes(32, "big")
    public = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return _b64url(public), _b64url(private)


class Command(BaseCommand):
    help = "Generate a VAPID key pair for Web Push notifications."

    def handle(self, *args: Any, **options: Any) -> None:
        public, private = generate()
        self.stdout.write(f"VAPID_PUBLIC_KEY={public}")
        self.stdout.write(f"VAPID_PRIVATE_KEY={private}")
