import json

import pytest
from django.contrib.auth import get_user_model

from apps.common.models import UserCredential


@pytest.mark.django_db
def test_user_credential_stores_blob_and_prefix():
    user = get_user_model().objects.create_user(email="test@dimagi.com")
    blob = {
        "claudeAiOauth": {
            "accessToken": "sk-ant-oat01-abcdefghijklmno",
            "refreshToken": "r-token",
            "expiresAt": 1700000000,
            "scopes": ["user:inference"],
        }
    }
    cred = UserCredential.objects.create(
        user=user,
        blob_encrypted=json.dumps(blob),
        token_prefix="sk-ant-oat01-ab",
    )
    cred.refresh_from_db()
    loaded = json.loads(cred.blob_encrypted)
    assert loaded == blob
    assert cred.token_prefix == "sk-ant-oat01-ab"


@pytest.mark.django_db
def test_user_credential_is_unique_per_user():
    user = get_user_model().objects.create_user(email="a@dimagi.com")
    UserCredential.objects.create(
        user=user, blob_encrypted="{}", token_prefix="sk-ant-oat01-aa"
    )
    from django.db import IntegrityError

    with pytest.raises(IntegrityError):
        UserCredential.objects.create(
            user=user, blob_encrypted="{}", token_prefix="sk-ant-oat01-bb"
        )
