import pytest

from apps.service_accounts.encryption import decrypt, encrypt


def test_round_trip():
    plaintext = '{"type": "service_account", "project_id": "test"}'
    ciphertext = encrypt(plaintext)
    assert ciphertext != plaintext
    assert decrypt(ciphertext) == plaintext


def test_different_plaintexts_produce_different_ciphertexts():
    a = encrypt("secret-a")
    b = encrypt("secret-b")
    assert a != b


def test_tampered_ciphertext_raises():
    ciphertext = encrypt("valid")
    tampered = ciphertext[:-4] + "XXXX"
    with pytest.raises(Exception):
        decrypt(tampered)


def test_empty_string_round_trip():
    assert decrypt(encrypt("")) == ""
