"""Field-level AES-256-GCM encryption — protect sensitive data at rest.

Pattern from PIL++: nonce-per-value + authenticated encryption + HKDF key derivation.
Format: base64(version_byte || nonce || ciphertext || tag)
"""

from __future__ import annotations

import hashlib

from registry.core.encoding import toBase64, fromBase64
import hmac
import os
import struct

# Version byte for format evolution
_VERSION = 1
_NONCE_LEN = 12  # GCM recommended nonce length
_TAG_LEN = 16  # GCM tag length
_KEY_LEN = 32  # AES-256
_SALT = b"zkml-field-encryption-v1"


def _derive_key(master_key: str | bytes) -> bytes:
    """HKDF-like key derivation using HMAC-SHA256.

    Uses a fixed salt + two HMAC rounds (extract-then-expand)
    to derive a 256-bit encryption key from the master secret.
    """
    if isinstance(master_key, str):
        master_key = master_key.encode()
    # Extract: PRK = HMAC(salt, input key material)
    prk = hmac.new(_SALT, master_key, hashlib.sha256).digest()
    # Expand: OKM = HMAC(PRK, info || 0x01)
    okm = hmac.new(prk, b"aes-gcm-field\x01", hashlib.sha256).digest()
    return okm[:_KEY_LEN]


def encrypt_field(plaintext: str, master_key: str | bytes) -> str:
    """Encrypt a string field with AES-256-GCM.

    Returns: base64-encoded string containing version + nonce + ciphertext + tag.
    Each call uses a fresh random nonce — safe for repeated encryption of the same value.
    """
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    key = _derive_key(master_key)
    nonce = os.urandom(_NONCE_LEN)
    aes = AESGCM(key)
    ct_with_tag = aes.encrypt(nonce, plaintext.encode(), None)

    # Pack: version (1 byte) || nonce (12 bytes) || ciphertext+tag
    payload = struct.pack("B", _VERSION) + nonce + ct_with_tag
    return toBase64(payload)


def decrypt_field(ciphertext_b64: str, master_key: str | bytes) -> str:
    """Decrypt a field encrypted with encrypt_field.

    Raises ValueError on tampered/invalid data.
    """
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    try:
        payload = fromBase64(ciphertext_b64)
    except Exception:
        raise ValueError("Invalid base64 encoding")

    if len(payload) < 1 + _NONCE_LEN + _TAG_LEN:
        raise ValueError("Ciphertext too short")

    version = payload[0]
    if version != _VERSION:
        raise ValueError(f"Unsupported encryption version: {version}")

    nonce = payload[1 : 1 + _NONCE_LEN]
    ct_with_tag = payload[1 + _NONCE_LEN :]

    key = _derive_key(master_key)
    aes = AESGCM(key)
    try:
        plaintext = aes.decrypt(nonce, ct_with_tag, None)
    except Exception:
        raise ValueError("Decryption failed — data may be tampered")

    return plaintext.decode()
