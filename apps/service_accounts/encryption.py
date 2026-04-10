"""Fernet encryption for service account credentials.

Derives a stable Fernet key from Django's SECRET_KEY so encrypted values
survive process restarts. If SECRET_KEY rotates, use the
`re_encrypt_credentials` management command to re-encrypt all rows.
"""
import base64
import hashlib

from cryptography.fernet import Fernet
from django.conf import settings


def _derive_key() -> bytes:
    """Derive a 32-byte URL-safe base64-encoded Fernet key from SECRET_KEY."""
    digest = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt(plaintext: str) -> str:
    """Encrypt a string. Returns a Fernet token (URL-safe base64)."""
    return Fernet(_derive_key()).encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """Decrypt a Fernet token back to the original string."""
    return Fernet(_derive_key()).decrypt(ciphertext.encode()).decode()
