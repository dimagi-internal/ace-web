"""Fernet-based encryption for per-user Drive OAuth token caches.

Ported from ../connect-search/backend/app/core/encryption.py with one change:
the key comes from Django settings instead of being passed at every call site.

The key is derived via PBKDF2-HMAC-SHA256 from settings.ACE_DRIVE_TOKEN_ENCRYPTION_KEY
using a fixed salt. This is intentional: a fixed salt makes the derived Fernet
key deterministic for a given input, which means we can rotate the raw env
var without having to re-encrypt every stored token — as long as the old and
new values derive to the same Fernet key, they are interchangeable. For a
genuine key rotation, you need to decrypt everything with the old key and
re-encrypt with the new one, same as connect-search.
"""
import base64
import json

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from django.conf import settings


def _get_fernet() -> Fernet:
    # Called per encrypt/decrypt operation. The 100k-iteration PBKDF2 below is
    # intentionally slow (~tens of ms per call); Drive token read/writes are
    # infrequent enough that we do not need to cache this. If this function
    # starts showing up on a hot path, add an lru_cache keyed on the raw key.
    key = settings.ACE_DRIVE_TOKEN_ENCRYPTION_KEY
    if not key:
        raise ValueError("ACE_DRIVE_TOKEN_ENCRYPTION_KEY must not be empty")
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"ace-web-drive-token-salt",
        iterations=100_000,
    )
    derived = base64.urlsafe_b64encode(kdf.derive(key.encode()))
    return Fernet(derived)


def encrypt_token(token_data: dict) -> str:
    """Encrypt a token-data dict and return a URL-safe base64 ciphertext string."""
    f = _get_fernet()
    return f.encrypt(json.dumps(token_data).encode()).decode()


def decrypt_token(encrypted: str) -> dict:
    """Decrypt a ciphertext string produced by `encrypt_token`."""
    f = _get_fernet()
    return json.loads(f.decrypt(encrypted.encode()))
