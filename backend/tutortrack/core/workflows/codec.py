"""Payload encryption (E32 FR-32-9): AES-256-GCM over every workflow/activity payload.

Temporal (Cloud) only ever stores ciphertext. Keys come from ``TEMPORAL_PAYLOAD_KEYS``
(``"<key id>:<base64 32 bytes>"``, newest first); the key id travels in the payload
metadata so old payloads stay readable after rotation. E29 moves the keys to KMS.
"""

from __future__ import annotations

import base64
import os
from collections.abc import Iterable, Sequence

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings
from temporalio.api.common.v1 import Payload
from temporalio.converter import PayloadCodec

ENCODING = b"binary/encrypted"
KEY_ID = "encryption-key-id"


def _keys() -> list[tuple[str, bytes]]:
    """``"<id>:<base64 key>"``, or ``"<id>:kms:<base64 KMS-wrapped data key>"`` (E29)."""
    keys = []
    for raw in settings.TEMPORAL_PAYLOAD_KEYS:
        key_id, _, material = str(raw).partition(":")
        if material.startswith("kms:"):
            from tutortrack.core import kms

            key = kms.unwrap(material[4:])
        else:
            key = base64.b64decode(material)
        if len(key) != 32:
            raise ValueError(f"Temporal payload key {key_id!r} must be 32 bytes")
        keys.append((key_id, key))
    if not keys:
        raise ValueError("TEMPORAL_PAYLOAD_KEYS is empty")
    return keys


class EncryptionCodec(PayloadCodec):
    async def encode(self, payloads: Sequence[Payload]) -> list[Payload]:
        key_id, key = _keys()[0]
        aes = AESGCM(key)
        out = []
        for payload in payloads:
            nonce = os.urandom(12)
            ciphertext = aes.encrypt(nonce, payload.SerializeToString(), None)
            out.append(
                Payload(
                    metadata={"encoding": ENCODING, KEY_ID: key_id.encode()},
                    data=nonce + ciphertext,
                )
            )
        return out

    async def decode(self, payloads: Sequence[Payload]) -> list[Payload]:
        keys = dict(_keys())
        out = []
        for payload in payloads:
            if payload.metadata.get("encoding") != ENCODING:
                out.append(payload)  # e.g. search attributes, memo written in clear
                continue
            key_id = payload.metadata.get(KEY_ID, b"").decode()
            if key_id not in keys:
                raise ValueError(f"Unknown Temporal payload key {key_id!r}")
            data = payload.data
            plain = AESGCM(keys[key_id]).decrypt(data[:12], data[12:], None)
            decoded = Payload()
            decoded.ParseFromString(plain)
            out.append(decoded)
        return out


def encrypted(payloads: Iterable[Payload]) -> bool:
    return all(p.metadata.get("encoding") == ENCODING for p in payloads)
