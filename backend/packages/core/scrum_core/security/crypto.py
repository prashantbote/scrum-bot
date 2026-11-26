"""Envelope encryption for integration tokens (plan §5).

Each secret is sealed with a fresh 256-bit data key (DEK) using AES-256-GCM; the DEK is wrapped
by the key-encryption key (KEK). The KEK comes from settings here; in production mount it from
OpenBao/HashiCorp Vault (open source) through the CSI driver, or swap ``LocalKek`` for a Transit
client. Only ``encrypted_token``, ``wrapped_dek`` and ``key_id`` are stored in the database.
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from typing import Protocol

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from scrum_core.settings import get_settings

_NONCE = 12


class KeyEncryptionKey(Protocol):
    key_id: str

    def wrap(self, dek: bytes) -> bytes: ...
    def unwrap(self, wrapped: bytes) -> bytes: ...


class LocalKek:
    def __init__(self, key: bytes, key_id: str) -> None:
        if len(key) != 32:
            raise ValueError("KEK must be 32 bytes (base64-encode 32 random bytes)")
        self._aead = AESGCM(key)
        self.key_id = key_id

    def wrap(self, dek: bytes) -> bytes:
        nonce = os.urandom(_NONCE)
        return nonce + self._aead.encrypt(nonce, dek, b"dek")

    def unwrap(self, wrapped: bytes) -> bytes:
        return self._aead.decrypt(wrapped[:_NONCE], wrapped[_NONCE:], b"dek")


def default_kek() -> LocalKek:
    s = get_settings()
    return LocalKek(base64.b64decode(s.kek_base64.get_secret_value()), s.kek_id)


@dataclass(frozen=True)
class Sealed:
    ciphertext: bytes
    wrapped_dek: bytes
    key_id: str


def seal(plaintext: str, *, aad: str, kek: KeyEncryptionKey | None = None) -> Sealed:
    """``aad`` binds the ciphertext to its row (e.g. "integration:<org>:<kind>") so it can't be swapped."""
    kek = kek or default_kek()
    dek = AESGCM.generate_key(bit_length=256)
    nonce = os.urandom(_NONCE)
    ct = nonce + AESGCM(dek).encrypt(nonce, plaintext.encode(), aad.encode())
    return Sealed(ciphertext=ct, wrapped_dek=kek.wrap(dek), key_id=kek.key_id)


def unseal(sealed: Sealed, *, aad: str, kek: KeyEncryptionKey | None = None) -> str:
    kek = kek or default_kek()
    if sealed.key_id != kek.key_id:
        raise ValueError(f"Secret was sealed with key {sealed.key_id!r}, current KEK is {kek.key_id!r}")
    dek = kek.unwrap(sealed.wrapped_dek)
    ct = sealed.ciphertext
    return AESGCM(dek).decrypt(ct[:_NONCE], ct[_NONCE:], aad.encode()).decode()
