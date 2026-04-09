"""Tests for the Fernet-based Drive token encryption helper."""
import pytest
from cryptography.fernet import InvalidToken
from django.test import override_settings

from apps.opps.encryption import decrypt_token, encrypt_token


def test_round_trip_with_default_key():
    payload = {"access_token": "abc", "refresh_token": "def", "scopes": ["drive"]}
    encrypted = encrypt_token(payload)
    decrypted = decrypt_token(encrypted)
    assert decrypted == payload


def test_encrypted_output_is_not_the_plaintext():
    payload = {"access_token": "secret-value-123"}
    encrypted = encrypt_token(payload)
    assert "secret-value-123" not in encrypted
    assert encrypted != str(payload)


def test_encrypt_produces_different_ciphertexts_each_call():
    """Fernet includes a random IV, so two encrypts of the same payload differ."""
    payload = {"access_token": "abc"}
    a = encrypt_token(payload)
    b = encrypt_token(payload)
    assert a != b
    assert decrypt_token(a) == decrypt_token(b)


@override_settings(ACE_DRIVE_TOKEN_ENCRYPTION_KEY="")
def test_empty_key_raises():
    with pytest.raises(ValueError, match="must not be empty"):
        encrypt_token({"access_token": "abc"})


@override_settings(ACE_DRIVE_TOKEN_ENCRYPTION_KEY="key-a")
def test_cannot_decrypt_with_a_different_key():
    encrypted = encrypt_token({"access_token": "abc"})
    with override_settings(ACE_DRIVE_TOKEN_ENCRYPTION_KEY="key-b"):
        with pytest.raises(InvalidToken):
            decrypt_token(encrypted)
