import json

import pytest
from django.contrib.auth import get_user_model

from apps.common.cli_backend import CLIBackend
from apps.common.models import SystemConfig, UserCredential
from apps.sessions.models import Session

USER_A_TOKEN = "sk-ant-oat01-A" + "a" * 40
USER_B_TOKEN = "sk-ant-oat01-B" + "b" * 40
GLOBAL_TOKEN = "sk-ant-oat01-G" + "g" * 40


@pytest.mark.django_db
def test_two_users_get_isolated_credentials():
    """Same CLIBackend instance + three sessions with different owners must
    stage three distinct credential blobs into three distinct temp HOMEs.
    Validates the per-invocation isolation guarantee that the per-user
    credential design rests on."""
    User = get_user_model()
    a = User.objects.create_user(email="ea@dimagi.com")
    b = User.objects.create_user(email="eb@dimagi.com")
    c = User.objects.create_user(email="ec@dimagi.com")  # no personal blob

    UserCredential.objects.create(
        user=a,
        blob_encrypted=json.dumps({"claudeAiOauth": {"accessToken": USER_A_TOKEN}}),
        token_prefix=USER_A_TOKEN[:15],
    )
    UserCredential.objects.create(
        user=b,
        blob_encrypted=json.dumps({"claudeAiOauth": {"accessToken": USER_B_TOKEN}}),
        token_prefix=USER_B_TOKEN[:15],
    )
    SystemConfig.objects.create(
        key="claude_credentials_blob",
        value=json.dumps({"claudeAiOauth": {"accessToken": GLOBAL_TOKEN}}),
    )

    sa = Session.objects.create(owner=a, slug="s-a", title="a")
    sb = Session.objects.create(owner=b, slug="s-b", title="b")
    sc = Session.objects.create(owner=c, slug="s-c", title="c")

    backend = CLIBackend()
    env_a, home_a, _ = backend._stage_env_for(sa)
    env_b, home_b, _ = backend._stage_env_for(sb)
    env_c, home_c, _ = backend._stage_env_for(sc)
    try:
        assert env_a["CLAUDE_CODE_OAUTH_TOKEN"] == USER_A_TOKEN
        assert env_b["CLAUDE_CODE_OAUTH_TOKEN"] == USER_B_TOKEN
        assert env_c["CLAUDE_CODE_OAUTH_TOKEN"] == GLOBAL_TOKEN  # fallback
        assert home_a != home_b
        assert home_b != home_c
        assert home_a != home_c
        # And the credentials files contain the right blob per home
        from pathlib import Path

        def _read_access(home: str) -> str:
            blob = json.loads((Path(home) / ".claude" / ".credentials.json").read_text())
            return blob["claudeAiOauth"]["accessToken"]

        assert _read_access(home_a) == USER_A_TOKEN
        assert _read_access(home_b) == USER_B_TOKEN
        assert _read_access(home_c) == GLOBAL_TOKEN
    finally:
        backend._teardown_staged_home(home_a)
        backend._teardown_staged_home(home_b)
        backend._teardown_staged_home(home_c)
