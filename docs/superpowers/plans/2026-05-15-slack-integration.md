# Slack Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the v1 Slack integration described in `docs/superpowers/specs/2026-05-15-slack-integration-design.md` — trigger ACE runs from Slack and mirror the Workbench Phase view as a parent status card + one thread message per phase.

**Architecture:** A new `apps/slack/` Django app handles inbound webhooks at `/api/slack/{events,commands,interactions}`, slash commands trigger runs through the existing session/turn-driver machinery, and a `SlackOppConsumer` worker joins the existing `opp.<slug>.<run_id>` Channels groups to fan progress updates back to Slack via `chat.update`. Drive remains source of truth; Slack mirrors the snapshot.

**Tech Stack:** Django 5 + Channels 4 + Django Ninja v1 + `slack-sdk` (Python), Pydantic v2, redis-backed Channels layer, Fernet encryption (existing `apps.service_accounts.encryption`), React 19 frontend for one small `?fork=<phase>` change.

---

## File structure

**New files (Python):**
- `apps/slack/__init__.py` — empty
- `apps/slack/apps.py` — `SlackConfig` with `ready()` that spawns the dispatcher worker
- `apps/slack/models.py` — `SlackInstallation`, `SlackUserLink`, `SlackRunThread`
- `apps/slack/admin.py` — Django admin entries
- `apps/slack/urls.py` — webhook URL routes
- `apps/slack/auth_urls.py` — `/auth/slack/link/` route
- `apps/slack/views.py` — webhook entry points (events, commands, interactions, install, oauth callback)
- `apps/slack/views_auth.py` — link callback view
- `apps/slack/verify.py` — signing-secret HMAC verification
- `apps/slack/handlers.py` — slash subcommand routing + business logic
- `apps/slack/slack_client.py` — thin `slack_sdk.WebClient` wrapper with error mapping
- `apps/slack/blocks.py` — Block Kit renderers (parent card, phase tile, progress bar)
- `apps/slack/dispatcher.py` — `SlackOppConsumer` worker task
- `apps/slack/pending.py` — Redis-backed pending-command cache
- `apps/slack/migrations/0001_initial.py` — generated migration
- `apps/slack/migrations/0002_seed_dimagi_installation_placeholder.py` — only if you want a partial fixture; not required

**New files (tests):**
- `apps/slack/tests/__init__.py`
- `apps/slack/tests/test_verify.py`
- `apps/slack/tests/test_blocks.py`
- `apps/slack/tests/test_pending.py`
- `apps/slack/tests/test_handlers_run.py`
- `apps/slack/tests/test_handlers_new.py`
- `apps/slack/tests/test_handlers_misc.py` (status, list, link, help)
- `apps/slack/tests/test_views.py` (signing-verify in HTTP integration)
- `apps/slack/tests/test_dispatcher.py`
- `apps/slack/tests/test_views_auth.py`

**Modified files (Python):**
- `config/settings/base.py` — add `SLACK_*` env vars, `apps.slack.apps.SlackConfig` in `INSTALLED_APPS`
- `config/urls.py` — include `apps.slack.urls` at `api/slack/` and `apps.slack.auth_urls` at `auth/slack/`
- `pyproject.toml` — add `slack-sdk = "^3.27"` to `[project.dependencies]`

**Modified files (frontend, one small change):**
- `frontend/src/pages/OppWorkbenchPage.tsx` — read `?fork=<phase>` from `useSearchParams` and pre-open the existing `ForkOppDialog` with `forkAtPhase`

**Modified files (docs):**
- `CLAUDE.md` — add learning entry pointer for `slack-integration`
- `docs/learnings/slack-integration.md` — new learning doc with gotchas

---

## Pre-flight

Before starting Task 1, verify:

- You are in the worktree `/Users/jjackson/emdash/worktrees/ace-web/emdash/slack-integration-8jg9d` (confirm with `pwd`).
- `pytest -v -k "not slow" tests/ apps/ --collect-only > /dev/null` runs clean (no import errors).
- `bunx tsc -b` in `frontend/` passes.

---

## Task 1: App skeleton + models + migration

**Files:**
- Create: `apps/slack/__init__.py`
- Create: `apps/slack/apps.py`
- Create: `apps/slack/models.py`
- Create: `apps/slack/admin.py`
- Create: `apps/slack/migrations/__init__.py`
- Create: `apps/slack/tests/__init__.py`
- Create: `apps/slack/tests/test_models.py`
- Modify: `config/settings/base.py` (INSTALLED_APPS, env vars)
- Modify: `pyproject.toml` (add slack-sdk)

- [ ] **Step 1: Add slack-sdk to pyproject + rebuild deps**

Edit `pyproject.toml`. Find the `[project] dependencies` array and add `"slack-sdk>=3.27,<4"` in alphabetical order. Then:

```bash
cd /Users/jjackson/emdash/worktrees/ace-web/emdash/slack-integration-8jg9d
uv sync --extra dev 2>&1 | tail -5   # or `pip install -e ".[dev]"` if no uv
python -c "import slack_sdk; print(slack_sdk.__version__)"
```

Expected: prints `3.27.x` or newer.

- [ ] **Step 2: Create app skeleton**

Create `apps/slack/__init__.py` (empty).

Create `apps/slack/apps.py`:

```python
from django.apps import AppConfig


class SlackConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.slack"
    label = "ace_slack"   # avoid colliding with any third-party "slack" app
    verbose_name = "Slack integration"

    def ready(self):
        # Dispatcher worker spawn is deferred until Task 13.
        pass
```

Create `apps/slack/migrations/__init__.py` (empty).

- [ ] **Step 3: Register the app**

In `config/settings/base.py`, find `INSTALLED_APPS = [...]` and append `"apps.slack.apps.SlackConfig",` after `"apps.videos.apps.VideosConfig",`. Then in the same file, add (after the existing env-var block — search for `ACE_REDIS_URL`):

```python
SLACK_CLIENT_ID = env("SLACK_CLIENT_ID", default="")
SLACK_CLIENT_SECRET = env("SLACK_CLIENT_SECRET", default="")
SLACK_SIGNING_SECRET = env("SLACK_SIGNING_SECRET", default="")
SLACK_DEFAULT_INSTALLATION_ID = env("SLACK_DEFAULT_INSTALLATION_ID", default="")
```

- [ ] **Step 4: Write the model test (failing)**

Create `apps/slack/tests/__init__.py` (empty).
Create `apps/slack/tests/test_models.py`:

```python
import pytest
from django.contrib.auth import get_user_model

from apps.slack.models import SlackInstallation, SlackUserLink, SlackRunThread
from apps.workspaces.models import Workspace


@pytest.mark.django_db
def test_installation_round_trip_encrypts_token():
    User = get_user_model()
    user = User.objects.create(email="admin@dimagi.com")
    ws = Workspace.objects.create(slug="dimagi-team", name="Dimagi Team",
                                  drive_root_folder_id="folder-1",
                                  created_by=user)
    inst = SlackInstallation.objects.create(
        slack_team_id="T0001",
        slack_team_name="Dimagi",
        bot_user_id="U_BOT",
        ace_workspace=ws,
        installed_by_user=user,
    )
    inst.set_bot_token("xoxb-secret-token")
    inst.save()

    refetched = SlackInstallation.objects.get(pk=inst.pk)
    # Raw column is encrypted (not plaintext).
    assert "xoxb-secret-token" not in refetched.bot_token_encrypted
    # Accessor decrypts.
    assert refetched.bot_token == "xoxb-secret-token"


@pytest.mark.django_db
def test_user_link_unique_per_installation_and_slack_user():
    User = get_user_model()
    user1 = User.objects.create(email="jj@dimagi.com")
    user2 = User.objects.create(email="other@dimagi.com")
    ws = Workspace.objects.create(slug="dimagi-team", name="Dimagi Team",
                                  drive_root_folder_id="folder-1",
                                  created_by=user1)
    inst = SlackInstallation.objects.create(
        slack_team_id="T0001", slack_team_name="Dimagi",
        bot_user_id="U_BOT", ace_workspace=ws, installed_by_user=user1,
    )
    SlackUserLink.objects.create(
        installation=inst, slack_user_id="U_JJ", ace_user=user1,
        slack_email="jj@dimagi.com", slack_real_name="JJ",
    )
    with pytest.raises(Exception):
        SlackUserLink.objects.create(
            installation=inst, slack_user_id="U_JJ", ace_user=user2,
            slack_email="other@dimagi.com", slack_real_name="Other",
        )


@pytest.mark.django_db
def test_run_thread_unique_per_slug_and_run_id():
    User = get_user_model()
    user = User.objects.create(email="jj@dimagi.com")
    ws = Workspace.objects.create(slug="dimagi-team", name="Dimagi Team",
                                  drive_root_folder_id="folder-1",
                                  created_by=user)
    inst = SlackInstallation.objects.create(
        slack_team_id="T0001", slack_team_name="Dimagi",
        bot_user_id="U_BOT", ace_workspace=ws, installed_by_user=user,
    )
    SlackRunThread.objects.create(
        installation=inst, channel_id="C1", parent_ts="1.1",
        opp_slug="my-opp", run_id="run-001", ace_user=user,
    )
    with pytest.raises(Exception):
        SlackRunThread.objects.create(
            installation=inst, channel_id="C2", parent_ts="2.2",
            opp_slug="my-opp", run_id="run-001", ace_user=user,
        )
```

- [ ] **Step 5: Run test to verify it fails**

```bash
pytest apps/slack/tests/test_models.py -v
```

Expected: ImportError on `apps.slack.models`.

- [ ] **Step 6: Implement models**

Create `apps/slack/models.py`:

```python
import uuid

from django.conf import settings
from django.db import models

from apps.service_accounts.encryption import decrypt, encrypt
from apps.workspaces.models import Workspace


class SlackInstallation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slack_team_id = models.CharField(max_length=32, unique=True)
    slack_team_name = models.CharField(max_length=255)
    bot_user_id = models.CharField(max_length=32)
    bot_token_encrypted = models.TextField()
    ace_workspace = models.ForeignKey(Workspace, on_delete=models.PROTECT,
                                      related_name="slack_installations")
    installed_at = models.DateTimeField(auto_now_add=True)
    installed_by_user = models.ForeignKey(settings.AUTH_USER_MODEL,
                                          on_delete=models.PROTECT,
                                          related_name="slack_installations")

    @property
    def bot_token(self) -> str:
        return decrypt(self.bot_token_encrypted)

    def set_bot_token(self, plaintext: str) -> None:
        self.bot_token_encrypted = encrypt(plaintext)

    def __str__(self):
        return f"{self.slack_team_name} ({self.slack_team_id})"


class SlackUserLink(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    installation = models.ForeignKey(SlackInstallation, on_delete=models.CASCADE,
                                     related_name="user_links")
    slack_user_id = models.CharField(max_length=32)
    ace_user = models.ForeignKey(settings.AUTH_USER_MODEL,
                                 on_delete=models.CASCADE,
                                 related_name="slack_user_links")
    slack_email = models.EmailField(blank=True)
    slack_real_name = models.CharField(max_length=255, blank=True)
    linked_at = models.DateTimeField(auto_now_add=True)
    unlinked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["installation", "slack_user_id"],
                name="uniq_slack_user_per_installation",
            ),
        ]

    def __str__(self):
        return f"{self.slack_user_id} → {self.ace_user_id}"


class SlackRunThread(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    installation = models.ForeignKey(SlackInstallation, on_delete=models.CASCADE,
                                     related_name="run_threads")
    channel_id = models.CharField(max_length=32)
    parent_ts = models.CharField(max_length=32)
    opp_slug = models.CharField(max_length=255)
    run_id = models.CharField(max_length=64)
    ace_user = models.ForeignKey(settings.AUTH_USER_MODEL,
                                 on_delete=models.PROTECT,
                                 related_name="slack_run_threads")
    triggered_at = models.DateTimeField(auto_now_add=True)
    phase_messages = models.JSONField(default=dict)
    parent_state_hash = models.CharField(max_length=64, blank=True, default="")
    broken_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["opp_slug", "run_id"],
                name="uniq_slack_run_thread_per_run",
            ),
        ]
        indexes = [models.Index(fields=["ace_user", "-triggered_at"])]

    def __str__(self):
        return f"{self.opp_slug}/{self.run_id} → {self.channel_id}"
```

- [ ] **Step 7: Generate + apply migration; run tests**

```bash
python manage.py makemigrations slack -n initial
python manage.py migrate
pytest apps/slack/tests/test_models.py -v
```

Expected: 3/3 pass.

- [ ] **Step 8: Admin entries**

Create `apps/slack/admin.py`:

```python
from django.contrib import admin

from .models import SlackInstallation, SlackRunThread, SlackUserLink


@admin.register(SlackInstallation)
class SlackInstallationAdmin(admin.ModelAdmin):
    list_display = ("slack_team_name", "slack_team_id", "ace_workspace",
                    "installed_at")
    readonly_fields = ("installed_at", "bot_token_encrypted")


@admin.register(SlackUserLink)
class SlackUserLinkAdmin(admin.ModelAdmin):
    list_display = ("slack_user_id", "ace_user", "installation",
                    "linked_at", "unlinked_at")
    list_filter = ("installation",)


@admin.register(SlackRunThread)
class SlackRunThreadAdmin(admin.ModelAdmin):
    list_display = ("opp_slug", "run_id", "channel_id", "ace_user",
                    "triggered_at", "broken_at")
    readonly_fields = ("triggered_at", "phase_messages", "parent_state_hash")
```

- [ ] **Step 9: Commit**

```bash
git add apps/slack/ config/settings/base.py pyproject.toml uv.lock 2>/dev/null || \
git add apps/slack/ config/settings/base.py pyproject.toml
git commit -m "feat(slack): app skeleton + models (SlackInstallation, SlackUserLink, SlackRunThread)"
```

---

## Task 2: Signing-secret verification

**Files:**
- Create: `apps/slack/verify.py`
- Create: `apps/slack/tests/test_verify.py`

- [ ] **Step 1: Write the failing test**

Create `apps/slack/tests/test_verify.py`:

```python
import hashlib
import hmac
import time

import pytest

from apps.slack.verify import verify_slack_signature, SignatureError


SECRET = "abc-test-secret"


def _sign(body: bytes, ts: str, secret: str = SECRET) -> str:
    base = b"v0:" + ts.encode() + b":" + body
    digest = hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()
    return f"v0={digest}"


def test_verify_accepts_valid_signature():
    ts = str(int(time.time()))
    body = b"command=/ace&text=run+my-opp"
    sig = _sign(body, ts)
    verify_slack_signature(secret=SECRET, body=body, timestamp=ts, signature=sig)
    # No exception = pass.


def test_verify_rejects_bad_signature():
    ts = str(int(time.time()))
    body = b"command=/ace&text=run+my-opp"
    with pytest.raises(SignatureError, match="signature mismatch"):
        verify_slack_signature(secret=SECRET, body=body, timestamp=ts,
                               signature="v0=deadbeef")


def test_verify_rejects_stale_timestamp():
    ts = str(int(time.time()) - 60 * 10)  # 10 min old
    body = b"command=/ace"
    sig = _sign(body, ts)
    with pytest.raises(SignatureError, match="stale"):
        verify_slack_signature(secret=SECRET, body=body, timestamp=ts,
                               signature=sig)


def test_verify_rejects_missing_secret():
    with pytest.raises(SignatureError, match="no signing secret"):
        verify_slack_signature(secret="", body=b"x", timestamp="0", signature="v0=x")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest apps/slack/tests/test_verify.py -v
```

Expected: ImportError on `apps.slack.verify`.

- [ ] **Step 3: Implement verify**

Create `apps/slack/verify.py`:

```python
"""Slack signing-secret HMAC verification.

Slack signs every inbound request with v0=hmac_sha256(secret, "v0:" + ts + ":" + body).
The timestamp protects against replay (we reject anything more than 5 min old).
"""
from __future__ import annotations

import hashlib
import hmac
import time


class SignatureError(Exception):
    pass


_MAX_AGE_SECONDS = 5 * 60


def verify_slack_signature(*, secret: str, body: bytes,
                           timestamp: str, signature: str) -> None:
    if not secret:
        raise SignatureError("no signing secret configured")
    try:
        ts_int = int(timestamp)
    except (TypeError, ValueError):
        raise SignatureError("bad timestamp") from None
    if abs(time.time() - ts_int) > _MAX_AGE_SECONDS:
        raise SignatureError("stale timestamp")
    base = b"v0:" + timestamp.encode() + b":" + body
    expected = "v0=" + hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature or ""):
        raise SignatureError("signature mismatch")
```

- [ ] **Step 4: Run tests to verify pass**

```bash
pytest apps/slack/tests/test_verify.py -v
```

Expected: 4/4 pass.

- [ ] **Step 5: Commit**

```bash
git add apps/slack/verify.py apps/slack/tests/test_verify.py
git commit -m "feat(slack): signing-secret HMAC verification"
```

---

## Task 3: Slack-SDK wrapper

**Files:**
- Create: `apps/slack/slack_client.py`
- Create: `apps/slack/tests/test_slack_client.py`

- [ ] **Step 1: Write the failing test**

```python
# apps/slack/tests/test_slack_client.py
from unittest.mock import MagicMock

from slack_sdk.errors import SlackApiError

from apps.slack.slack_client import (
    SlackClient, SlackChannelGone, SlackRateLimited,
)


def _make_client(web_client_mock):
    c = SlackClient.__new__(SlackClient)
    c._web = web_client_mock
    return c


def test_post_message_returns_ts():
    web = MagicMock()
    web.chat_postMessage.return_value = {"ok": True, "ts": "1.2"}
    client = _make_client(web)
    ts = client.post_message(channel="C1", blocks=[], text="x")
    assert ts == "1.2"


def test_update_message_swallows_channel_not_found():
    web = MagicMock()
    err = SlackApiError(message="channel_not_found",
                       response={"error": "channel_not_found"})
    web.chat_update.side_effect = err
    client = _make_client(web)
    import pytest
    with pytest.raises(SlackChannelGone):
        client.update_message(channel="C1", ts="1.2", blocks=[], text="x")


def test_update_message_rate_limit_raises_typed():
    web = MagicMock()
    err = SlackApiError(message="rate_limited",
                       response={"error": "rate_limited",
                                 "headers": {"Retry-After": "3"}})
    web.chat_update.side_effect = err
    client = _make_client(web)
    import pytest
    with pytest.raises(SlackRateLimited) as exc:
        client.update_message(channel="C1", ts="1.2", blocks=[], text="x")
    assert exc.value.retry_after == 3
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest apps/slack/tests/test_slack_client.py -v
```

Expected: ImportError on `apps.slack.slack_client`.

- [ ] **Step 3: Implement client wrapper**

Create `apps/slack/slack_client.py`:

```python
"""Thin slack_sdk wrapper with typed errors.

We catch `channel_not_found` / `is_archived` / `rate_limited` here so the
dispatcher / handlers don't have to know about slack_sdk's loose error
shape. Everything else bubbles up as the raw SlackApiError.
"""
from __future__ import annotations

import logging
from typing import Any

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

logger = logging.getLogger(__name__)

_GONE_ERRORS = {"channel_not_found", "is_archived", "not_in_channel"}


class SlackChannelGone(Exception):
    pass


class SlackRateLimited(Exception):
    def __init__(self, retry_after: int):
        super().__init__(f"slack rate-limited; retry after {retry_after}s")
        self.retry_after = retry_after


class SlackClient:
    def __init__(self, token: str):
        self._web = WebClient(token=token)

    def post_message(self, *, channel: str, blocks: list[dict],
                     text: str, thread_ts: str | None = None) -> str:
        resp = self._web.chat_postMessage(
            channel=channel, blocks=blocks, text=text, thread_ts=thread_ts,
        )
        return resp["ts"]

    def update_message(self, *, channel: str, ts: str,
                       blocks: list[dict], text: str) -> None:
        try:
            self._web.chat_update(channel=channel, ts=ts, blocks=blocks, text=text)
        except SlackApiError as e:
            self._raise_typed(e)

    def post_ephemeral(self, *, channel: str, user: str,
                       text: str, blocks: list[dict] | None = None) -> None:
        try:
            self._web.chat_postEphemeral(
                channel=channel, user=user, text=text, blocks=blocks or [],
            )
        except SlackApiError as e:
            self._raise_typed(e)

    def dm_user(self, *, user: str, text: str,
                blocks: list[dict] | None = None) -> str:
        opened = self._web.conversations_open(users=user)
        channel = opened["channel"]["id"]
        resp = self._web.chat_postMessage(
            channel=channel, text=text, blocks=blocks or [],
        )
        return resp["ts"]

    def open_view(self, *, trigger_id: str, view: dict) -> None:
        try:
            self._web.views_open(trigger_id=trigger_id, view=view)
        except SlackApiError as e:
            self._raise_typed(e)

    def lookup_user_info(self, *, slack_user_id: str) -> dict[str, Any]:
        resp = self._web.users_info(user=slack_user_id)
        return resp["user"]

    def _raise_typed(self, e: SlackApiError) -> None:
        err = e.response.get("error", "")
        if err in _GONE_ERRORS:
            raise SlackChannelGone(err) from e
        if err == "rate_limited":
            retry = int(e.response.get("headers", {}).get("Retry-After", 1))
            raise SlackRateLimited(retry) from e
        raise


def client_for(installation) -> SlackClient:
    """Construct a SlackClient from a SlackInstallation row."""
    return SlackClient(installation.bot_token)
```

- [ ] **Step 4: Run tests to verify pass**

```bash
pytest apps/slack/tests/test_slack_client.py -v
```

Expected: 3/3 pass.

- [ ] **Step 5: Commit**

```bash
git add apps/slack/slack_client.py apps/slack/tests/test_slack_client.py
git commit -m "feat(slack): slack_sdk wrapper with typed errors"
```

---

## Task 4: Block Kit renderers

**Files:**
- Create: `apps/slack/blocks.py`
- Create: `apps/slack/tests/test_blocks.py`

- [ ] **Step 1: Write the failing test**

```python
# apps/slack/tests/test_blocks.py
from apps.slack.blocks import (
    render_parent_card, render_phase_tile, render_progress_bar,
    phase_state_hash, parent_state_hash,
)


def _snapshot_fixture():
    """Minimal OppSnapshot-shaped dict. Real OppSnapshot is a Pydantic
    model; for renderer tests we use dicts to avoid Pydantic coupling."""
    return {
        "display_name": "Rural Health TB Screening",
        "current_run": {
            "run_id": "run-007",
            "steps": [
                {"phase": "idea-to-design", "skill_name": "draft-pdd",
                 "status": "complete", "ordinal": 0,
                 "judge": {"score_pct": 82}},
                {"phase": "scenarios-and-acceptance", "skill_name": "scenarios",
                 "status": "running", "ordinal": 0, "judge": None},
            ],
        },
        "phases": [
            {"name": "idea-to-design", "display_name": "Idea to Design",
             "agent": "idea-to-design", "ordinal": 1},
            {"name": "scenarios-and-acceptance",
             "display_name": "Scenarios & Acceptance",
             "agent": "scenarios-and-acceptance", "ordinal": 2},
        ],
    }


def test_progress_bar_renders_blocks():
    assert render_progress_bar(0, 4) == "░░░░░░░░░░ 0%"
    assert render_progress_bar(2, 4) == "▓▓▓▓▓░░░░░ 50%"
    assert render_progress_bar(4, 4) == "▓▓▓▓▓▓▓▓▓▓ 100%"
    # Total of 0 means "no skills yet" — render empty bar.
    assert render_progress_bar(0, 0) == "░░░░░░░░░░ 0%"


def test_phase_tile_for_complete_phase():
    snap = _snapshot_fixture()
    blocks = render_phase_tile(snap, phase_name="idea-to-design",
                               opp_slug="rural-health", workspace_slug="dimagi-team")
    serialized = repr(blocks)
    assert "Phase 1" in serialized
    assert "Idea to Design" in serialized
    assert "1/1 done" in serialized
    assert "mean 82" in serialized
    assert "Fork from here" in serialized
    assert "rural-health" in serialized   # deep-link present


def test_phase_tile_for_running_phase_shows_current_skill():
    snap = _snapshot_fixture()
    blocks = render_phase_tile(snap, phase_name="scenarios-and-acceptance",
                               opp_slug="rural-health", workspace_slug="dimagi-team")
    serialized = repr(blocks)
    assert "Currently: scenarios" in serialized
    # Fork button is disabled until at least one skill is complete in this phase.
    assert "Fork from here" not in serialized


def test_parent_card_includes_run_id_and_active_phase():
    snap = _snapshot_fixture()
    blocks = render_parent_card(snap, opp_slug="rural-health",
                                workspace_slug="dimagi-team",
                                triggerer_display="@jjackson",
                                elapsed_seconds=900)
    serialized = repr(blocks)
    assert "Rural Health TB Screening" in serialized
    assert "run-007" in serialized
    assert "@jjackson" in serialized
    assert "Phase 2" in serialized
    assert "Scenarios & Acceptance" in serialized


def test_state_hashes_stable_and_change_meaningfully():
    snap = _snapshot_fixture()
    h1 = phase_state_hash(snap, "idea-to-design")
    h2 = phase_state_hash(snap, "idea-to-design")
    assert h1 == h2
    # Mutating the snapshot changes the hash.
    snap["current_run"]["steps"][0]["status"] = "qa-failed"
    h3 = phase_state_hash(snap, "idea-to-design")
    assert h3 != h1
    # Parent card uses elapsed bucketed to minutes — two calls 30s apart
    # in the same minute bucket should match.
    ph1 = parent_state_hash(snap, elapsed_seconds=300)
    ph2 = parent_state_hash(snap, elapsed_seconds=320)
    assert ph1 == ph2
    ph3 = parent_state_hash(snap, elapsed_seconds=400)
    assert ph3 != ph1
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest apps/slack/tests/test_blocks.py -v
```

Expected: ImportError on `apps.slack.blocks`.

- [ ] **Step 3: Implement renderers**

Create `apps/slack/blocks.py`:

```python
"""Pure Block Kit renderers. Snapshot in, list[dict] out.

These mirror the shape of frontend/src/components/views/PhaseView.tsx
PhaseTile + the WorkbenchHeader parent card. State hashes are computed
from the same fields the renderer reads, so any user-visible diff is
caught by the hash check.

Snapshot shape: we treat the snapshot as a dict with keys
{display_name, current_run.{run_id, steps[]}, phases[]}. The real
OppSnapshot is a Pydantic model; the dispatcher serializes it via
.model_dump() before calling these renderers (keeps the renderers
test-friendly without Pydantic imports).
"""
from __future__ import annotations

import hashlib
import json

_BAR_WIDTH = 10
_PROD_BASE_URL = "https://labs.connect.dimagi.com/ace"


def render_progress_bar(complete: int, total: int) -> str:
    pct = 0 if total == 0 else int(round(100 * complete / total))
    filled = 0 if total == 0 else round(_BAR_WIDTH * complete / total)
    return ("▓" * filled) + ("░" * (_BAR_WIDTH - filled)) + f" {pct}%"


def _phase_stats(snapshot: dict, phase_name: str) -> dict:
    steps = [s for s in snapshot["current_run"]["steps"]
             if s["phase"] == phase_name]
    complete = sum(1 for s in steps if s["status"] == "complete")
    qa_failed = sum(1 for s in steps if s["status"] == "qa-failed")
    open_decisions = 0  # Decisions live on current_run; populated below.
    decisions = snapshot.get("current_run", {}).get("decisions") or []
    open_decisions = sum(1 for d in decisions
                         if d.get("phase") == phase_name and d.get("status") == "open")
    judged = [s["judge"]["score_pct"] for s in steps
              if s.get("judge") and s["judge"].get("score_pct") is not None]
    mean_score = round(sum(judged) / len(judged)) if judged else None
    running = next((s for s in steps if s["status"] == "running"), None)
    statuses = {s["status"] for s in steps}
    terminal = bool(steps) and not (statuses & {"running", "pending", "queued"})
    return {
        "total": len(steps),
        "complete": complete,
        "qa_failed": qa_failed,
        "open_decisions": open_decisions,
        "mean_score": mean_score,
        "current_skill": running["skill_name"] if running else None,
        "terminal": terminal,
        "has_any_complete": complete > 0,
    }


def _phase_info(snapshot: dict, phase_name: str) -> dict:
    for p in snapshot["phases"]:
        if p["name"] == phase_name:
            return p
    raise KeyError(f"phase {phase_name!r} not in snapshot")


def render_phase_tile(snapshot: dict, *, phase_name: str,
                      opp_slug: str, workspace_slug: str) -> list[dict]:
    phase = _phase_info(snapshot, phase_name)
    stats = _phase_stats(snapshot, phase_name)
    bar = render_progress_bar(stats["complete"], stats["total"])

    eyebrow = f"Phase {phase['ordinal']} · {phase['agent']}"
    title = f"*{phase['display_name']}*"

    context_bits = [f"{stats['complete']}/{stats['total']} done"]
    if stats["mean_score"] is not None:
        context_bits.append(f"mean {stats['mean_score']}/100")
    if stats["qa_failed"] > 0:
        context_bits.append(f":x: {stats['qa_failed']} qa-failed")
    if stats["open_decisions"] > 0:
        context_bits.append(f":grey_question: {stats['open_decisions']} open")

    blocks: list[dict] = [
        {"type": "context",
         "elements": [{"type": "mrkdwn", "text": eyebrow}]},
        {"type": "section",
         "text": {"type": "mrkdwn", "text": title}},
        {"type": "context",
         "elements": [{"type": "mrkdwn", "text": " · ".join(context_bits)}]},
        {"type": "section",
         "text": {"type": "mrkdwn", "text": f"`{bar}`"}},
    ]
    if stats["current_skill"]:
        blocks.append({"type": "context",
                       "elements": [{"type": "mrkdwn",
                                     "text": f"Currently: *{stats['current_skill']}*"}]})

    action_elements = [{
        "type": "button",
        "text": {"type": "plain_text", "text": "View phase ↗"},
        "url": f"{_PROD_BASE_URL}/w/{workspace_slug}/opps/{opp_slug}",
        "action_id": f"view_phase:{opp_slug}:{phase_name}",
    }]
    if stats["has_any_complete"]:
        action_elements.append({
            "type": "button",
            "text": {"type": "plain_text", "text": "🍴 Fork from here…"},
            "action_id": "fork_from_phase",
            "value": f"{opp_slug}:{phase_name}",
        })
    blocks.append({"type": "actions", "elements": action_elements})
    return blocks


def _active_phase(snapshot: dict) -> dict | None:
    for p in sorted(snapshot["phases"], key=lambda x: x["ordinal"]):
        stats = _phase_stats(snapshot, p["name"])
        if stats["total"] == 0:
            continue
        if not stats["terminal"]:
            return p
    return None


def render_parent_card(snapshot: dict, *, opp_slug: str, workspace_slug: str,
                       triggerer_display: str, elapsed_seconds: int) -> list[dict]:
    active = _active_phase(snapshot)
    elapsed_min = elapsed_seconds // 60
    run_id = snapshot["current_run"]["run_id"]
    if active:
        active_stats = _phase_stats(snapshot, active["name"])
        active_line = (f"Phase {active['ordinal']} · *{active['display_name']}*"
                       + (f" · running `{active_stats['current_skill']}`"
                          if active_stats["current_skill"] else ""))
    else:
        active_line = "All phases complete · awaiting cleanup"

    text = (f"*{snapshot['display_name']}* — `{run_id}`\n"
            f"Triggered by {triggerer_display} · {elapsed_min}m elapsed\n"
            f"{active_line}")

    return [
        {"type": "section",
         "text": {"type": "mrkdwn", "text": text}},
        {"type": "actions", "elements": [
            {"type": "button",
             "text": {"type": "plain_text", "text": "Open in ace-web ↗"},
             "url": f"{_PROD_BASE_URL}/w/{workspace_slug}/opps/{opp_slug}"},
        ]},
    ]


def phase_state_hash(snapshot: dict, phase_name: str) -> str:
    stats = _phase_stats(snapshot, phase_name)
    payload = {
        "complete": stats["complete"],
        "total": stats["total"],
        "qa_failed": stats["qa_failed"],
        "open_decisions": stats["open_decisions"],
        "mean_score": stats["mean_score"],
        "current_skill": stats["current_skill"],
        "terminal": stats["terminal"],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode()
    ).hexdigest()


def parent_state_hash(snapshot: dict, *, elapsed_seconds: int) -> str:
    active = _active_phase(snapshot)
    stats = _phase_stats(snapshot, active["name"]) if active else None
    payload = {
        "active_phase": active["name"] if active else None,
        "current_skill": stats["current_skill"] if stats else None,
        "elapsed_min_bucket": elapsed_seconds // 60,
        "run_id": snapshot["current_run"]["run_id"],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode()
    ).hexdigest()
```

- [ ] **Step 4: Run tests**

```bash
pytest apps/slack/tests/test_blocks.py -v
```

Expected: 5/5 pass.

- [ ] **Step 5: Commit**

```bash
git add apps/slack/blocks.py apps/slack/tests/test_blocks.py
git commit -m "feat(slack): Block Kit renderers + state hashes (parent card, phase tile, progress bar)"
```

---

## Task 5: Pending-command cache (Redis)

**Files:**
- Create: `apps/slack/pending.py`
- Create: `apps/slack/tests/test_pending.py`

- [ ] **Step 1: Write the failing test**

```python
# apps/slack/tests/test_pending.py
import pytest

from apps.slack.pending import (
    save_pending_command, take_pending_command, PendingMissing,
)


def test_save_and_take_roundtrip():
    nonce = save_pending_command(
        slack_user_id="U_JJ",
        team_id="T1",
        channel_id="C1",
        command_text="/ace run my-opp",
    )
    payload = take_pending_command(nonce)
    assert payload["slack_user_id"] == "U_JJ"
    assert payload["command_text"] == "/ace run my-opp"


def test_take_after_consume_raises():
    nonce = save_pending_command(slack_user_id="U_JJ", team_id="T1",
                                 channel_id="C1", command_text="/ace help")
    take_pending_command(nonce)
    with pytest.raises(PendingMissing):
        take_pending_command(nonce)


def test_take_unknown_nonce_raises():
    with pytest.raises(PendingMissing):
        take_pending_command("never-existed")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest apps/slack/tests/test_pending.py -v
```

Expected: ImportError on `apps.slack.pending`.

- [ ] **Step 3: Implement pending cache**

Create `apps/slack/pending.py`:

```python
"""Short-lived (10 min) cache of slash commands awaiting OAuth link.

Used so the first command from an unlinked Slack user doesn't have to be
retyped: we save it under a nonce, DM the user a link to /auth/slack/link/?nonce=,
and on successful link we pop the entry and replay the command.
"""
from __future__ import annotations

import json
import secrets

from django.core.cache import cache

_TTL_SECONDS = 10 * 60


class PendingMissing(KeyError):
    pass


def _key(nonce: str) -> str:
    return f"slack:pending:{nonce}"


def save_pending_command(*, slack_user_id: str, team_id: str,
                         channel_id: str, command_text: str,
                         trigger_id: str | None = None) -> str:
    nonce = secrets.token_urlsafe(24)
    payload = {
        "slack_user_id": slack_user_id,
        "team_id": team_id,
        "channel_id": channel_id,
        "command_text": command_text,
        "trigger_id": trigger_id,
    }
    cache.set(_key(nonce), json.dumps(payload), timeout=_TTL_SECONDS)
    return nonce


def take_pending_command(nonce: str) -> dict:
    raw = cache.get(_key(nonce))
    if raw is None:
        raise PendingMissing(nonce)
    cache.delete(_key(nonce))
    return json.loads(raw)
```

- [ ] **Step 4: Run tests**

```bash
pytest apps/slack/tests/test_pending.py -v
```

Expected: 3/3 pass.

- [ ] **Step 5: Commit**

```bash
git add apps/slack/pending.py apps/slack/tests/test_pending.py
git commit -m "feat(slack): Redis-backed pending-command cache (10-min TTL)"
```

---

## Task 6: Slack webhook entrypoint + URL routing

**Files:**
- Create: `apps/slack/urls.py`
- Create: `apps/slack/views.py`
- Create: `apps/slack/tests/test_views.py`
- Modify: `config/urls.py`

- [ ] **Step 1: Write the failing test**

```python
# apps/slack/tests/test_views.py
import time
from unittest.mock import patch

import pytest
from django.test import Client, override_settings

from apps.slack.tests.test_verify import _sign, SECRET


@pytest.mark.django_db
@override_settings(SLACK_SIGNING_SECRET=SECRET)
def test_commands_rejects_unsigned():
    c = Client()
    resp = c.post("/api/slack/commands", data={"command": "/ace", "text": "help"})
    assert resp.status_code == 401


@pytest.mark.django_db
@override_settings(SLACK_SIGNING_SECRET=SECRET)
def test_commands_accepts_signed_request_and_dispatches():
    ts = str(int(time.time()))
    body = b"command=/ace&text=help&team_id=T1&user_id=U_JJ&channel_id=C1&trigger_id=tg1"
    sig = _sign(body, ts)
    with patch("apps.slack.handlers.dispatch_slash_command") as mock_dispatch:
        mock_dispatch.return_value = {"response_type": "ephemeral", "text": "ok"}
        c = Client()
        resp = c.post("/api/slack/commands", data=body,
                      content_type="application/x-www-form-urlencoded",
                      HTTP_X_SLACK_REQUEST_TIMESTAMP=ts,
                      HTTP_X_SLACK_SIGNATURE=sig)
    assert resp.status_code == 200
    assert resp.json() == {"response_type": "ephemeral", "text": "ok"}
    mock_dispatch.assert_called_once()
    call_kwargs = mock_dispatch.call_args.kwargs
    assert call_kwargs["text"] == "help"
    assert call_kwargs["slack_user_id"] == "U_JJ"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest apps/slack/tests/test_views.py -v
```

Expected: 404 (URLs not wired yet) or import error.

- [ ] **Step 3: Implement views**

Create `apps/slack/views.py`:

```python
"""Slack webhook entry points.

Each view: (1) verify signing-secret, (2) parse the typed payload,
(3) dispatch to handlers, (4) return Slack's expected response shape.

Handlers return JSON-serializable dicts; we wrap them in JsonResponse.
"""
from __future__ import annotations

import json
import logging

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .verify import SignatureError, verify_slack_signature

logger = logging.getLogger(__name__)


def _verify(request: HttpRequest) -> None:
    ts = request.headers.get("X-Slack-Request-Timestamp", "")
    sig = request.headers.get("X-Slack-Signature", "")
    verify_slack_signature(
        secret=settings.SLACK_SIGNING_SECRET,
        body=request.body,
        timestamp=ts,
        signature=sig,
    )


@csrf_exempt
@require_POST
def slash_commands(request: HttpRequest) -> HttpResponse:
    try:
        _verify(request)
    except SignatureError as e:
        logger.warning("slack signature fail (commands): %s", e)
        return HttpResponse(status=401)

    from .handlers import dispatch_slash_command  # lazy to keep import-time light
    response = dispatch_slash_command(
        text=request.POST.get("text", "").strip(),
        slack_user_id=request.POST["user_id"],
        team_id=request.POST["team_id"],
        channel_id=request.POST["channel_id"],
        trigger_id=request.POST.get("trigger_id", ""),
        response_url=request.POST.get("response_url", ""),
    )
    return JsonResponse(response)


@csrf_exempt
@require_POST
def interactions(request: HttpRequest) -> HttpResponse:
    try:
        _verify(request)
    except SignatureError as e:
        logger.warning("slack signature fail (interactions): %s", e)
        return HttpResponse(status=401)

    payload = json.loads(request.POST.get("payload", "{}"))
    from .handlers import dispatch_interaction
    response = dispatch_interaction(payload)
    return JsonResponse(response)


@csrf_exempt
@require_POST
def events(request: HttpRequest) -> HttpResponse:
    """Inbound Events API. v1 only handles the URL verification challenge;
    we don't subscribe to app_mention or message events yet."""
    try:
        _verify(request)
    except SignatureError as e:
        logger.warning("slack signature fail (events): %s", e)
        return HttpResponse(status=401)

    body = json.loads(request.body or b"{}")
    if body.get("type") == "url_verification":
        return JsonResponse({"challenge": body["challenge"]})
    return JsonResponse({"ok": True})
```

Create `apps/slack/urls.py`:

```python
from django.urls import path

from . import views

app_name = "slack"

urlpatterns = [
    path("commands", views.slash_commands, name="slash_commands"),
    path("interactions", views.interactions, name="interactions"),
    path("events", views.events, name="events"),
]
```

Create a stub `apps/slack/handlers.py` so the import resolves; full implementation lands in Task 8:

```python
"""Slash command + interaction dispatcher. Filled in by subsequent tasks."""
from __future__ import annotations


def dispatch_slash_command(*, text: str, slack_user_id: str, team_id: str,
                           channel_id: str, trigger_id: str,
                           response_url: str) -> dict:
    return {"response_type": "ephemeral",
            "text": "Slack integration not yet wired."}


def dispatch_interaction(payload: dict) -> dict:
    return {"response_type": "ephemeral",
            "text": "Slack integration not yet wired."}
```

- [ ] **Step 4: Wire URL include**

Modify `config/urls.py`. Find the line `path("api/", api.urls),` and add directly after it:

```python
    path("api/slack/", include("apps.slack.urls")),
```

(Make sure `include` is in the imports at the top — it already is.)

- [ ] **Step 5: Run tests**

```bash
pytest apps/slack/tests/test_views.py -v
```

Expected: 2/2 pass.

- [ ] **Step 6: Commit**

```bash
git add apps/slack/views.py apps/slack/urls.py apps/slack/handlers.py \
        apps/slack/tests/test_views.py config/urls.py
git commit -m "feat(slack): webhook entrypoints + URL routing (commands, interactions, events)"
```

---

## Task 7: Slack app install OAuth (admin one-time)

**Files:**
- Modify: `apps/slack/views.py` (add `install`, `oauth_callback`)
- Modify: `apps/slack/urls.py`
- Create: `apps/slack/tests/test_install.py`

- [ ] **Step 1: Write the failing test**

```python
# apps/slack/tests/test_install.py
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import Client, override_settings

from apps.workspaces.models import Workspace


@pytest.fixture
def admin_user(db):
    User = get_user_model()
    user = User.objects.create(email="admin@dimagi.com", is_staff=True,
                               is_superuser=True)
    user.set_password("pw")
    user.save()
    return user


@pytest.fixture
def dimagi_workspace(admin_user):
    return Workspace.objects.create(
        slug="dimagi-team", name="Dimagi Team",
        drive_root_folder_id="folder-1", created_by=admin_user,
    )


@pytest.mark.django_db
@override_settings(SLACK_CLIENT_ID="cid", SLACK_CLIENT_SECRET="secret")
def test_install_redirects_to_slack_oauth(admin_user, client: Client):
    client.force_login(admin_user)
    resp = client.get("/api/slack/install")
    assert resp.status_code == 302
    assert resp.url.startswith("https://slack.com/oauth/v2/authorize")
    assert "client_id=cid" in resp.url
    assert "scope=" in resp.url


@pytest.mark.django_db
@override_settings(SLACK_CLIENT_ID="cid", SLACK_CLIENT_SECRET="secret")
def test_oauth_callback_creates_installation(admin_user, dimagi_workspace,
                                             client: Client):
    client.force_login(admin_user)
    with patch("apps.slack.views._exchange_code") as exchange:
        exchange.return_value = {
            "ok": True,
            "team": {"id": "T0001", "name": "Dimagi"},
            "bot_user_id": "U_BOT",
            "access_token": "xoxb-secret",
        }
        resp = client.get("/api/slack/oauth/callback?code=abc123")
    assert resp.status_code == 200
    from apps.slack.models import SlackInstallation
    inst = SlackInstallation.objects.get(slack_team_id="T0001")
    assert inst.bot_token == "xoxb-secret"
    assert inst.ace_workspace == dimagi_workspace
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest apps/slack/tests/test_install.py -v
```

Expected: 404 on the install URL.

- [ ] **Step 3: Implement install + callback views**

Append to `apps/slack/views.py`:

```python
from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import HttpResponseBadRequest, HttpResponseRedirect
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from apps.workspaces.models import Workspace

from .models import SlackInstallation

_BOT_SCOPES = [
    "commands", "chat:write", "chat:write.public",
    "users:read", "users:read.email",
]


def _is_staff(user) -> bool:
    return user.is_authenticated and user.is_staff


@login_required
@user_passes_test(_is_staff)
def install(request: HttpRequest) -> HttpResponse:
    """Kick off the admin OAuth flow."""
    if not settings.SLACK_CLIENT_ID:
        return HttpResponseBadRequest("SLACK_CLIENT_ID not configured")
    params = {
        "client_id": settings.SLACK_CLIENT_ID,
        "scope": ",".join(_BOT_SCOPES),
        # No user_scope — bot install only. Per-user identity link is
        # a separate Django-side OAuth.
        "redirect_uri": request.build_absolute_uri("/api/slack/oauth/callback"),
    }
    return HttpResponseRedirect("https://slack.com/oauth/v2/authorize?" + urlencode(params))


def _exchange_code(code: str, redirect_uri: str) -> dict:
    client = WebClient()
    return client.oauth_v2_access(
        client_id=settings.SLACK_CLIENT_ID,
        client_secret=settings.SLACK_CLIENT_SECRET,
        code=code,
        redirect_uri=redirect_uri,
    ).data


@login_required
@user_passes_test(_is_staff)
def oauth_callback(request: HttpRequest) -> HttpResponse:
    code = request.GET.get("code")
    if not code:
        return HttpResponseBadRequest("missing code")
    redirect_uri = request.build_absolute_uri("/api/slack/oauth/callback")
    try:
        data = _exchange_code(code, redirect_uri)
    except SlackApiError as e:
        logger.exception("slack oauth exchange failed")
        return HttpResponseBadRequest(f"oauth failed: {e.response.get('error')}")
    if not data.get("ok"):
        return HttpResponseBadRequest(f"oauth not ok: {data}")
    workspace = Workspace.objects.get(slug="dimagi-team")
    inst, _ = SlackInstallation.objects.update_or_create(
        slack_team_id=data["team"]["id"],
        defaults={
            "slack_team_name": data["team"]["name"],
            "bot_user_id": data["bot_user_id"],
            "ace_workspace": workspace,
            "installed_by_user": request.user,
        },
    )
    inst.set_bot_token(data["access_token"])
    inst.save()
    return HttpResponse(
        f"<h1>Installed</h1><p>Slack team <b>{inst.slack_team_name}</b> "
        f"is now wired up. ace workspace: <b>{workspace.slug}</b>.</p>",
        status=200,
    )
```

Append to `apps/slack/urls.py`:

```python
    path("install", views.install, name="install"),
    path("oauth/callback", views.oauth_callback, name="oauth_callback"),
```

- [ ] **Step 4: Run tests**

```bash
pytest apps/slack/tests/test_install.py -v
```

Expected: 2/2 pass.

- [ ] **Step 5: Commit**

```bash
git add apps/slack/views.py apps/slack/urls.py apps/slack/tests/test_install.py
git commit -m "feat(slack): admin Slack-app install OAuth (creates SlackInstallation row)"
```

---

## Task 8: Per-user OAuth link page

**Files:**
- Create: `apps/slack/views_auth.py`
- Create: `apps/slack/auth_urls.py`
- Create: `apps/slack/tests/test_views_auth.py`
- Modify: `config/urls.py`

- [ ] **Step 1: Write the failing test**

```python
# apps/slack/tests/test_views_auth.py
import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from apps.slack.models import SlackInstallation, SlackUserLink
from apps.slack.pending import save_pending_command
from apps.workspaces.models import Workspace


@pytest.fixture
def setup_installation(db):
    User = get_user_model()
    admin = User.objects.create(email="admin@dimagi.com")
    ws = Workspace.objects.create(slug="dimagi-team", name="Dimagi Team",
                                  drive_root_folder_id="f", created_by=admin)
    inst = SlackInstallation.objects.create(
        slack_team_id="T1", slack_team_name="Dimagi",
        bot_user_id="U_BOT", ace_workspace=ws, installed_by_user=admin,
    )
    inst.set_bot_token("xoxb-1"); inst.save()
    return inst, admin


@pytest.mark.django_db
def test_link_route_creates_user_link_and_replays(setup_installation):
    inst, admin = setup_installation
    User = get_user_model()
    jj = User.objects.create(email="jj@dimagi.com")
    jj.set_password("pw"); jj.save()

    nonce = save_pending_command(slack_user_id="U_JJ", team_id="T1",
                                 channel_id="C1", command_text="/ace help")

    from unittest.mock import patch
    with patch("apps.slack.views_auth._replay_command") as replay:
        replay.return_value = None
        c = Client()
        c.force_login(jj)
        resp = c.get(f"/auth/slack/link/?nonce={nonce}")
    assert resp.status_code == 200
    assert SlackUserLink.objects.filter(
        installation=inst, slack_user_id="U_JJ", ace_user=jj,
    ).exists()
    replay.assert_called_once()


@pytest.mark.django_db
def test_link_route_requires_login(setup_installation):
    nonce = save_pending_command(slack_user_id="U_JJ", team_id="T1",
                                 channel_id="C1", command_text="/ace help")
    c = Client()
    resp = c.get(f"/auth/slack/link/?nonce={nonce}")
    # Should redirect to Connect login.
    assert resp.status_code in (302, 401)


@pytest.mark.django_db
def test_link_route_rejects_unknown_nonce(setup_installation):
    User = get_user_model()
    jj = User.objects.create(email="jj@dimagi.com")
    c = Client()
    c.force_login(jj)
    resp = c.get("/auth/slack/link/?nonce=nope")
    assert resp.status_code == 400
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest apps/slack/tests/test_views_auth.py -v
```

Expected: 404 (route not wired).

- [ ] **Step 3: Implement the link view + URL include**

Create `apps/slack/views_auth.py`:

```python
"""Slack-account-link page.

A logged-in ace-web user lands here from a DM the bot sent them. We
look up the pending command (saved when they tried to run a slash
command), create a SlackUserLink row, and replay the command so they
don't have to retype it.
"""
from __future__ import annotations

import logging

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest

from .models import SlackInstallation, SlackUserLink
from .pending import PendingMissing, take_pending_command

logger = logging.getLogger(__name__)


def _replay_command(payload: dict) -> None:
    """Re-dispatch the originally-attempted slash command now that the
    user is linked. Best-effort — failures here are logged, not surfaced.
    """
    from .handlers import dispatch_slash_command
    try:
        dispatch_slash_command(
            text=payload["command_text"].lstrip("/ace ").strip(),
            slack_user_id=payload["slack_user_id"],
            team_id=payload["team_id"],
            channel_id=payload["channel_id"],
            trigger_id=payload.get("trigger_id") or "",
            response_url="",  # we can't re-acquire the ephemeral url
        )
    except Exception:
        logger.exception("replay of pending slack command failed")


@login_required
def link_page(request: HttpRequest) -> HttpResponse:
    nonce = request.GET.get("nonce", "")
    try:
        pending = take_pending_command(nonce)
    except PendingMissing:
        return HttpResponseBadRequest("link expired or already used; run the "
                                      "command again from Slack")
    try:
        installation = SlackInstallation.objects.get(slack_team_id=pending["team_id"])
    except SlackInstallation.DoesNotExist:
        return HttpResponseBadRequest("no Slack installation for that team")
    SlackUserLink.objects.update_or_create(
        installation=installation,
        slack_user_id=pending["slack_user_id"],
        defaults={
            "ace_user": request.user,
            "slack_email": request.user.email or "",
            "slack_real_name": request.user.get_full_name() or "",
            "unlinked_at": None,
        },
    )
    _replay_command(pending)
    return HttpResponse(
        "<h1>Linked!</h1><p>Your Slack identity is now connected to ace-web. "
        "You can close this tab and head back to Slack.</p>",
        status=200,
    )
```

Create `apps/slack/auth_urls.py`:

```python
from django.urls import path

from . import views_auth

app_name = "slack_auth"

urlpatterns = [
    path("link/", views_auth.link_page, name="link"),
]
```

Wire it in `config/urls.py`. Find the line `path("auth/", include("apps.auth.urls")),` and add directly after it:

```python
    path("auth/slack/", include("apps.slack.auth_urls")),
```

- [ ] **Step 4: Run tests**

```bash
pytest apps/slack/tests/test_views_auth.py -v
```

Expected: 3/3 pass.

- [ ] **Step 5: Commit**

```bash
git add apps/slack/views_auth.py apps/slack/auth_urls.py \
        apps/slack/tests/test_views_auth.py config/urls.py
git commit -m "feat(slack): per-user OAuth link page (SlackUserLink) + pending-command replay"
```

---

## Task 9: Slash command dispatcher — help + link + ensure-link

**Files:**
- Modify: `apps/slack/handlers.py` (replace stub)
- Create: `apps/slack/tests/test_handlers_misc.py`

This task lands the dispatcher harness and the simplest two verbs (`help`, `link`), plus the `ensure_link` shared helper that subsequent tasks reuse.

- [ ] **Step 1: Write the failing test**

```python
# apps/slack/tests/test_handlers_misc.py
from unittest.mock import patch, MagicMock

import pytest
from django.contrib.auth import get_user_model

from apps.slack.models import SlackInstallation, SlackUserLink
from apps.workspaces.models import Workspace


@pytest.fixture
def setup(db):
    User = get_user_model()
    admin = User.objects.create(email="admin@dimagi.com")
    ws = Workspace.objects.create(slug="dimagi-team", name="Dimagi",
                                  drive_root_folder_id="f", created_by=admin)
    inst = SlackInstallation.objects.create(
        slack_team_id="T1", slack_team_name="Dimagi",
        bot_user_id="U_BOT", ace_workspace=ws, installed_by_user=admin,
    )
    inst.set_bot_token("xoxb-1"); inst.save()
    jj = User.objects.create(email="jj@dimagi.com")
    SlackUserLink.objects.create(installation=inst, slack_user_id="U_JJ",
                                 ace_user=jj, slack_email="jj@dimagi.com",
                                 slack_real_name="JJ")
    return inst, jj


@pytest.mark.django_db
def test_help_returns_ephemeral_usage(setup):
    from apps.slack.handlers import dispatch_slash_command
    resp = dispatch_slash_command(
        text="help", slack_user_id="U_JJ", team_id="T1", channel_id="C1",
        trigger_id="", response_url="",
    )
    assert resp["response_type"] == "ephemeral"
    assert "/ace run" in resp["text"]


@pytest.mark.django_db
def test_unknown_subcommand_returns_help(setup):
    from apps.slack.handlers import dispatch_slash_command
    resp = dispatch_slash_command(
        text="banana", slack_user_id="U_JJ", team_id="T1", channel_id="C1",
        trigger_id="", response_url="",
    )
    assert resp["response_type"] == "ephemeral"
    assert "Usage" in resp["text"] or "/ace help" in resp["text"]


@pytest.mark.django_db
def test_unlinked_user_gets_dm_link(setup):
    from apps.slack.handlers import dispatch_slash_command
    with patch("apps.slack.handlers._get_client") as get_client:
        mock = MagicMock(); get_client.return_value = mock
        resp = dispatch_slash_command(
            text="run my-opp", slack_user_id="U_UNKNOWN",
            team_id="T1", channel_id="C1", trigger_id="", response_url="",
        )
    mock.dm_user.assert_called_once()
    dm_kwargs = mock.dm_user.call_args.kwargs
    assert dm_kwargs["user"] == "U_UNKNOWN"
    assert "/auth/slack/link" in dm_kwargs["text"] or any(
        "/auth/slack/link" in repr(b) for b in (dm_kwargs.get("blocks") or [])
    )
    assert resp["response_type"] == "ephemeral"
    assert "link" in resp["text"].lower()


@pytest.mark.django_db
def test_link_subcommand_resends_link(setup):
    from apps.slack.handlers import dispatch_slash_command
    with patch("apps.slack.handlers._get_client") as get_client:
        mock = MagicMock(); get_client.return_value = mock
        resp = dispatch_slash_command(
            text="link", slack_user_id="U_JJ", team_id="T1", channel_id="C1",
            trigger_id="", response_url="",
        )
    mock.dm_user.assert_called_once()
    assert resp["response_type"] == "ephemeral"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest apps/slack/tests/test_handlers_misc.py -v
```

Expected: stub returns "not yet wired" — 4 failures.

- [ ] **Step 3: Implement handlers**

Replace the entire contents of `apps/slack/handlers.py`:

```python
"""Slash command + interaction dispatcher.

Subcommand routing: text is everything after `/ace` in the raw command.
We split on whitespace; the first token is the verb.
"""
from __future__ import annotations

import logging
from urllib.parse import urlencode

from django.conf import settings
from django.urls import reverse

from .models import SlackInstallation, SlackUserLink
from .pending import save_pending_command
from .slack_client import SlackClient, client_for

logger = logging.getLogger(__name__)


_HELP_TEXT = (
    "*ACE bot* — Run and monitor ACE opportunities from Slack.\n\n"
    "`/ace run <pdd-link-or-opp-slug>` — Start the full ACE lifecycle.\n"
    "`/ace new` — Open a modal to create a new opp from an idea.\n"
    "`/ace status [<slug>]` — Show the current state of a run.\n"
    "`/ace list` — Show your 5 most recent active runs.\n"
    "`/ace link` — (Re)link your Slack identity to ace-web.\n"
    "`/ace help` — This message.\n"
)


def _get_client(installation) -> SlackClient:
    """Indirection so tests can patch."""
    return client_for(installation)


def _get_installation(team_id: str) -> SlackInstallation | None:
    try:
        return SlackInstallation.objects.get(slack_team_id=team_id)
    except SlackInstallation.DoesNotExist:
        return None


def _get_user_link(installation, slack_user_id: str) -> SlackUserLink | None:
    return SlackUserLink.objects.filter(
        installation=installation, slack_user_id=slack_user_id,
        unlinked_at__isnull=True,
    ).select_related("ace_user").first()


def _link_url(nonce: str) -> str:
    base = getattr(settings, "ACE_PUBLIC_BASE_URL", "https://labs.connect.dimagi.com/ace")
    return f"{base}{reverse('slack_auth:link')}?{urlencode({'nonce': nonce})}"


def _ephemeral(text: str) -> dict:
    return {"response_type": "ephemeral", "text": text}


def _send_link_dm(*, installation, slack_user_id: str, team_id: str,
                  channel_id: str, command_text: str, trigger_id: str) -> dict:
    nonce = save_pending_command(
        slack_user_id=slack_user_id, team_id=team_id,
        channel_id=channel_id, command_text=command_text,
        trigger_id=trigger_id or None,
    )
    url = _link_url(nonce)
    client = _get_client(installation)
    client.dm_user(
        user=slack_user_id,
        text=f"Link your ace-web account to use /ace: {url}",
        blocks=[
            {"type": "section", "text": {"type": "mrkdwn",
             "text": "Link your ace-web account to use `/ace`."}},
            {"type": "actions", "elements": [
                {"type": "button",
                 "text": {"type": "plain_text", "text": "Link account"},
                 "url": url, "action_id": "link_account"},
            ]},
        ],
    )
    return _ephemeral("I sent you a DM with a link to connect your account. "
                      "Once linked, I'll resume your command.")


def dispatch_slash_command(*, text: str, slack_user_id: str, team_id: str,
                           channel_id: str, trigger_id: str,
                           response_url: str) -> dict:
    parts = text.split(maxsplit=1) if text else [""]
    verb = parts[0].lower() if parts else ""
    rest = parts[1] if len(parts) > 1 else ""

    installation = _get_installation(team_id)
    if installation is None:
        return _ephemeral("This Slack workspace isn't installed in ace-web. "
                          "Ask an admin to run the /api/slack/install flow.")

    if verb == "help" or verb == "":
        return _ephemeral(_HELP_TEXT)

    if verb == "link":
        return _send_link_dm(installation=installation, slack_user_id=slack_user_id,
                             team_id=team_id, channel_id=channel_id,
                             command_text=f"/ace {text}", trigger_id=trigger_id)

    user_link = _get_user_link(installation, slack_user_id)
    if user_link is None:
        return _send_link_dm(installation=installation, slack_user_id=slack_user_id,
                             team_id=team_id, channel_id=channel_id,
                             command_text=f"/ace {text}", trigger_id=trigger_id)

    # Verbs that require a linked user. Sub-handler imports are lazy to keep
    # import-time cheap and to let tests patch.
    if verb == "run":
        from .verbs_run import handle_run
        return handle_run(installation=installation, user_link=user_link,
                          rest=rest, channel_id=channel_id,
                          trigger_id=trigger_id)
    if verb == "new":
        from .verbs_new import handle_new
        return handle_new(installation=installation, user_link=user_link,
                          channel_id=channel_id, trigger_id=trigger_id)
    if verb == "status":
        from .verbs_query import handle_status
        return handle_status(installation=installation, user_link=user_link,
                             rest=rest, channel_id=channel_id)
    if verb == "list":
        from .verbs_query import handle_list
        return handle_list(installation=installation, user_link=user_link,
                           channel_id=channel_id)

    return _ephemeral(f"Unknown subcommand `{verb}`. {_HELP_TEXT}")


def dispatch_interaction(payload: dict) -> dict:
    """Block action / view submission entrypoint. Filled in by Task 13."""
    return {"response_action": "clear"}
```

Also add `ACE_PUBLIC_BASE_URL` to `config/settings/base.py` (alongside the SLACK_* vars from Task 1):

```python
ACE_PUBLIC_BASE_URL = env("ACE_PUBLIC_BASE_URL",
                          default="https://labs.connect.dimagi.com/ace")
```

- [ ] **Step 4: Run tests**

```bash
pytest apps/slack/tests/test_handlers_misc.py -v
```

Expected: 4/4 pass.

- [ ] **Step 5: Commit**

```bash
git add apps/slack/handlers.py apps/slack/tests/test_handlers_misc.py \
        config/settings/base.py
git commit -m "feat(slack): slash command dispatcher + help/link + ensure-link helper"
```

---

## Task 10: `/ace run` — happy path

**Files:**
- Create: `apps/slack/verbs_run.py`
- Create: `apps/slack/run_starter.py`
- Create: `apps/slack/tests/test_handlers_run.py`

This task is the load-bearing one — read carefully.

`run_starter.py` resolves an opp slug or PDD link into an opp, picks the next `run-NNN`, creates a `Session` bound to the run, and injects the `/ace:run` command. We isolate it so it can be unit-tested without touching Slack.

- [ ] **Step 1: Write the failing test**

```python
# apps/slack/tests/test_handlers_run.py
from unittest.mock import patch, MagicMock

import pytest
from django.contrib.auth import get_user_model

from apps.slack.models import (
    SlackInstallation, SlackRunThread, SlackUserLink,
)
from apps.workspaces.models import Workspace


@pytest.fixture
def setup(db):
    User = get_user_model()
    admin = User.objects.create(email="admin@dimagi.com")
    ws = Workspace.objects.create(slug="dimagi-team", name="Dimagi",
                                  drive_root_folder_id="f", created_by=admin)
    inst = SlackInstallation.objects.create(
        slack_team_id="T1", slack_team_name="Dimagi",
        bot_user_id="U_BOT", ace_workspace=ws, installed_by_user=admin,
    )
    inst.set_bot_token("xoxb-1"); inst.save()
    jj = User.objects.create(email="jj@dimagi.com")
    link = SlackUserLink.objects.create(
        installation=inst, slack_user_id="U_JJ", ace_user=jj,
        slack_email="jj@dimagi.com", slack_real_name="JJ",
    )
    return inst, link, ws


@pytest.mark.django_db
def test_run_creates_thread_and_posts_parent_card(setup):
    inst, link, ws = setup
    with patch("apps.slack.verbs_run.start_run_from_slack") as start, \
         patch("apps.slack.verbs_run._get_client") as get_client:
        start.return_value = ("my-opp", "run-001")
        client = MagicMock(); get_client.return_value = client
        client.post_message.return_value = "1.1"
        from apps.slack.verbs_run import handle_run
        resp = handle_run(installation=inst, user_link=link,
                          rest="my-opp", channel_id="C1", trigger_id="tg")

    assert resp["response_type"] == "ephemeral"
    assert "kicking off" in resp["text"].lower()
    start.assert_called_once()
    client.post_message.assert_called_once()
    thread = SlackRunThread.objects.get(opp_slug="my-opp", run_id="run-001")
    assert thread.channel_id == "C1"
    assert thread.parent_ts == "1.1"
    assert thread.ace_user_id == link.ace_user_id


@pytest.mark.django_db
def test_run_duplicate_returns_already_running(setup):
    inst, link, ws = setup
    SlackRunThread.objects.create(
        installation=inst, channel_id="C1", parent_ts="9.9",
        opp_slug="my-opp", run_id="run-001", ace_user=link.ace_user,
    )
    with patch("apps.slack.verbs_run.start_run_from_slack") as start, \
         patch("apps.slack.verbs_run._get_client") as get_client:
        # Same opp; resolve says "already has an active run".
        start.side_effect = NotImplementedError(
            "should not have been called for duplicate"
        )
        from apps.slack.verbs_run import handle_run
        # Use the same resolver to short-circuit:
        with patch("apps.slack.verbs_run._lookup_active_run") as lookup:
            lookup.return_value = ("my-opp", "run-001")
            client = MagicMock(); get_client.return_value = client
            resp = handle_run(installation=inst, user_link=link,
                              rest="my-opp", channel_id="C1", trigger_id="tg")

    assert resp["response_type"] == "ephemeral"
    assert "already running" in resp["text"].lower()


@pytest.mark.django_db
def test_run_with_empty_slug_returns_usage(setup):
    inst, link, ws = setup
    from apps.slack.verbs_run import handle_run
    resp = handle_run(installation=inst, user_link=link,
                      rest="", channel_id="C1", trigger_id="tg")
    assert resp["response_type"] == "ephemeral"
    assert "/ace run" in resp["text"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest apps/slack/tests/test_handlers_run.py -v
```

Expected: ImportError on `apps.slack.verbs_run`.

- [ ] **Step 3: Implement `run_starter.py`**

Create `apps/slack/run_starter.py`:

```python
"""Resolve a slash-command argument into a triggered run.

`start_run_from_slack(slug_or_link, user, workspace)`:
  1. Resolve slug_or_link → an existing Opp slug (raise if not found
     in the workspace).
  2. Pre-allocate the next run-NNN folder under that opp via the
     existing opp_creator path.
  3. Create a Session bound to (slug, run_id) for the user.
  4. Inject the /ace:run command using the same action-injection model
     as the web Workbench (apps.opps.actions.inject_action), so the
     turn_driver picks it up and spawns claude -p /ace:run.
"""
from __future__ import annotations

import logging

from django.contrib.auth import get_user_model

from apps.opps import actions as opp_actions
from apps.opps.access import (
    get_opp_by_slug, allocate_next_run_id, opp_workspace,
)
from apps.sessions.models import Session

logger = logging.getLogger(__name__)


class RunStartError(Exception):
    pass


def _is_pdd_link(text: str) -> bool:
    return text.startswith("https://docs.google.com/document/")


def start_run_from_slack(*, slug_or_link: str, user, workspace) -> tuple[str, str]:
    """Returns (slug, run_id). Raises RunStartError on misuse."""
    if not slug_or_link:
        raise RunStartError("missing opp slug or PDD link")
    if _is_pdd_link(slug_or_link):
        # Defer to opp_creator's PDD-link path. Returns the new opp_slug.
        from apps.opps.opp_creator import create_opp_from_pdd
        slug = create_opp_from_pdd(pdd_link=slug_or_link, user=user,
                                   workspace=workspace)
    else:
        slug = slug_or_link.strip()
        opp = get_opp_by_slug(slug=slug, workspace=workspace)
        if opp is None:
            raise RunStartError(f"no opp `{slug}` in workspace `{workspace.slug}`")
    run_id = allocate_next_run_id(slug=slug, workspace=workspace)
    session = Session.objects.create(
        created_by=user, opp_slug=slug, opp_run_id=run_id,
        title=f"Slack run · {slug} · {run_id}",
    )
    opp_actions.inject_action(
        session=session, action="run", slug=slug,
        payload=opp_actions.ActionPayload(skill="run"), user=user,
    )
    return slug, run_id
```

> **Implementation note:** `get_opp_by_slug`, `allocate_next_run_id`, and `create_opp_from_pdd` may not exist with those exact names in `apps.opps`. Before running the test, scan `apps/opps/access.py` and `apps/opps/opp_creator.py`. If the function names differ, update **both** `run_starter.py` imports **and** the test mocks (the tests mock `start_run_from_slack` directly, so they don't care about the names — but the actual handler does). If the necessary primitives don't exist at all, write thin wrappers in `apps/opps/access.py` for them (`allocate_next_run_id` in particular may need to be authored — peek `apps/opps/opp_forker.py` for the "next run-NNN" logic).

- [ ] **Step 4: Implement `verbs_run.py`**

Create `apps/slack/verbs_run.py`:

```python
"""`/ace run <slug-or-link>` subcommand."""
from __future__ import annotations

import logging

from .blocks import render_parent_card
from .models import SlackRunThread
from .run_starter import RunStartError, start_run_from_slack
from .slack_client import client_for, SlackClient

logger = logging.getLogger(__name__)


def _get_client(installation) -> SlackClient:
    return client_for(installation)


def _lookup_active_run(*, workspace, slug: str) -> tuple[str, str] | None:
    """Return (slug, run_id) of an active run for this opp, or None."""
    from apps.opps.access import get_active_run_id
    run_id = get_active_run_id(slug=slug, workspace=workspace)
    return (slug, run_id) if run_id else None


def handle_run(*, installation, user_link, rest: str, channel_id: str,
               trigger_id: str) -> dict:
    rest = rest.strip()
    if not rest:
        return {"response_type": "ephemeral",
                "text": ("Usage: `/ace run <opp-slug-or-pdd-link>`. "
                         "Example: `/ace run rural-health-tb-screening`.")}

    workspace = installation.ace_workspace
    user = user_link.ace_user

    # Duplicate-run short circuit (only for slug args; PDD-link triggers
    # always create a new opp).
    if not rest.startswith("https://"):
        existing = _lookup_active_run(workspace=workspace, slug=rest)
        if existing is not None:
            slug, run_id = existing
            thread = SlackRunThread.objects.filter(
                opp_slug=slug, run_id=run_id,
            ).first()
            permalink = (f"https://labs.connect.dimagi.com/ace/w/"
                         f"{workspace.slug}/opps/{slug}")
            return {"response_type": "ephemeral",
                    "text": (f"`{slug}` is already running ({run_id}). "
                             f"See: {permalink}"
                             + (f" · thread: <#{thread.channel_id}>"
                                if thread else ""))}

    try:
        slug, run_id = start_run_from_slack(
            slug_or_link=rest, user=user, workspace=workspace,
        )
    except RunStartError as e:
        return {"response_type": "ephemeral", "text": f":x: {e}"}
    except Exception:
        logger.exception("start_run_from_slack failed")
        return {"response_type": "ephemeral",
                "text": ":x: Internal error starting run. Check ace-web logs."}

    # Post the initial parent card. Snapshot may not be available yet
    # (run just started), so render a placeholder.
    placeholder_snapshot = {
        "display_name": slug,
        "current_run": {"run_id": run_id, "steps": [], "decisions": []},
        "phases": [],
    }
    client = _get_client(installation)
    blocks = render_parent_card(
        placeholder_snapshot, opp_slug=slug,
        workspace_slug=workspace.slug,
        triggerer_display=f"<@{user_link.slack_user_id}>",
        elapsed_seconds=0,
    )
    ts = client.post_message(channel=channel_id, blocks=blocks,
                             text=f"ACE run started — {slug}")
    SlackRunThread.objects.create(
        installation=installation, channel_id=channel_id, parent_ts=ts,
        opp_slug=slug, run_id=run_id, ace_user=user,
    )
    # Group-add to the consumer is wired in Task 13; for now the row
    # exists and the 60s sweep (Task 15) will catch it up once the
    # consumer is running.

    return {"response_type": "ephemeral",
            "text": f":rocket: Kicking off `{slug}` ({run_id}). "
                    f"Watch the thread for progress."}
```

- [ ] **Step 5: Run tests**

```bash
pytest apps/slack/tests/test_handlers_run.py -v
```

Expected: 3/3 pass.

- [ ] **Step 6: Commit**

```bash
git add apps/slack/verbs_run.py apps/slack/run_starter.py \
        apps/slack/tests/test_handlers_run.py
git commit -m "feat(slack): /ace run subcommand (resolve slug/PDD → start run → post parent card)"
```

---

## Task 11: `/ace new` modal

**Files:**
- Create: `apps/slack/verbs_new.py`
- Create: `apps/slack/tests/test_handlers_new.py`

- [ ] **Step 1: Write the failing test**

```python
# apps/slack/tests/test_handlers_new.py
from unittest.mock import patch, MagicMock

import pytest
from django.contrib.auth import get_user_model

from apps.slack.models import SlackInstallation, SlackUserLink
from apps.workspaces.models import Workspace


@pytest.fixture
def setup(db):
    User = get_user_model()
    admin = User.objects.create(email="admin@dimagi.com")
    ws = Workspace.objects.create(slug="dimagi-team", name="Dimagi",
                                  drive_root_folder_id="f", created_by=admin)
    inst = SlackInstallation.objects.create(
        slack_team_id="T1", slack_team_name="Dimagi",
        bot_user_id="U_BOT", ace_workspace=ws, installed_by_user=admin,
    )
    inst.set_bot_token("xoxb-1"); inst.save()
    jj = User.objects.create(email="jj@dimagi.com")
    link = SlackUserLink.objects.create(
        installation=inst, slack_user_id="U_JJ", ace_user=jj,
        slack_email="jj@dimagi.com", slack_real_name="JJ",
    )
    return inst, link, jj


@pytest.mark.django_db
def test_new_opens_modal(setup):
    inst, link, _ = setup
    with patch("apps.slack.verbs_new._get_client") as get_client:
        client = MagicMock(); get_client.return_value = client
        from apps.slack.verbs_new import handle_new
        resp = handle_new(installation=inst, user_link=link,
                          channel_id="C1", trigger_id="tg1")
    assert resp == {}
    client.open_view.assert_called_once()
    view = client.open_view.call_args.kwargs["view"]
    assert view["type"] == "modal"
    serialized = repr(view)
    assert "Name" in serialized
    assert "Idea" in serialized


@pytest.mark.django_db
def test_new_modal_submission_starts_run(setup):
    inst, link, _ = setup
    with patch("apps.slack.verbs_new.start_run_from_slack") as start, \
         patch("apps.slack.verbs_new._get_client") as get_client:
        start.return_value = ("rural-tb", "run-001")
        client = MagicMock(); get_client.return_value = client
        client.post_message.return_value = "1.1"
        from apps.slack.verbs_new import handle_new_submission
        payload = {
            "type": "view_submission",
            "team": {"id": "T1"},
            "user": {"id": "U_JJ"},
            "view": {
                "callback_id": "ace_new_modal",
                "private_metadata": '{"channel_id": "C1"}',
                "state": {"values": {
                    "name_block": {"name_input": {"value": "Rural TB"}},
                    "idea_block": {"idea_input": {"value": "Screen TB in rural clinics"}},
                }},
            },
        }
        resp = handle_new_submission(payload)
    assert resp.get("response_action") in (None, "clear")
    start.assert_called_once()
    kwargs = start.call_args.kwargs
    assert "Screen TB" in kwargs["slug_or_link"] or kwargs.get("idea_text")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest apps/slack/tests/test_handlers_new.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement modal + submission**

Create `apps/slack/verbs_new.py`:

```python
"""`/ace new` opens a modal; submission triggers a new opp + run."""
from __future__ import annotations

import json
import logging
from typing import Any

from .blocks import render_parent_card
from .models import SlackInstallation, SlackUserLink, SlackRunThread
from .run_starter import RunStartError, start_run_from_slack
from .slack_client import client_for, SlackClient

logger = logging.getLogger(__name__)


def _get_client(installation) -> SlackClient:
    return client_for(installation)


def _modal_view(*, channel_id: str) -> dict:
    return {
        "type": "modal",
        "callback_id": "ace_new_modal",
        "private_metadata": json.dumps({"channel_id": channel_id}),
        "title": {"type": "plain_text", "text": "New ACE opportunity"},
        "submit": {"type": "plain_text", "text": "Start"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "input", "block_id": "name_block",
                "label": {"type": "plain_text", "text": "Name"},
                "element": {"type": "plain_text_input", "action_id": "name_input",
                            "placeholder": {"type": "plain_text",
                                            "text": "e.g. Rural TB Screening"}},
                "optional": True,
            },
            {
                "type": "input", "block_id": "idea_block",
                "label": {"type": "plain_text", "text": "Idea"},
                "element": {"type": "plain_text_input", "action_id": "idea_input",
                            "multiline": True,
                            "placeholder": {"type": "plain_text",
                                            "text": "Describe the problem, "
                                                    "the behavior you want, "
                                                    "and who the LLOs are."}},
            },
        ],
    }


def handle_new(*, installation, user_link, channel_id: str,
               trigger_id: str) -> dict:
    client = _get_client(installation)
    try:
        client.open_view(trigger_id=trigger_id, view=_modal_view(channel_id=channel_id))
    except Exception:
        logger.exception("failed to open /ace new modal")
        return {"response_type": "ephemeral",
                "text": ":x: Couldn't open the modal. Try again."}
    # Empty body — Slack expects 200 OK with no content for trigger acks.
    return {}


def handle_new_submission(payload: dict) -> dict:
    """Called from dispatch_interaction when view['callback_id'] == 'ace_new_modal'."""
    view = payload["view"]
    team_id = payload["team"]["id"]
    slack_user_id = payload["user"]["id"]
    metadata = json.loads(view.get("private_metadata") or "{}")
    channel_id = metadata.get("channel_id", "")

    values = view["state"]["values"]
    name = values.get("name_block", {}).get("name_input", {}).get("value", "") or ""
    idea = values.get("idea_block", {}).get("idea_input", {}).get("value", "") or ""

    if not idea.strip():
        return {"response_action": "errors",
                "errors": {"idea_block": "Idea is required."}}

    try:
        installation = SlackInstallation.objects.get(slack_team_id=team_id)
    except SlackInstallation.DoesNotExist:
        return {"response_action": "errors",
                "errors": {"idea_block": "Slack workspace not installed in ace-web."}}
    user_link = SlackUserLink.objects.filter(
        installation=installation, slack_user_id=slack_user_id,
        unlinked_at__isnull=True,
    ).select_related("ace_user").first()
    if user_link is None:
        return {"response_action": "errors",
                "errors": {"idea_block": "Link your account with `/ace link` first."}}

    workspace = installation.ace_workspace
    user = user_link.ace_user

    try:
        # opp_creator interprets `slug_or_link` containing newlines as an
        # idea-block; the resolver in run_starter checks for `https://` first,
        # so a multiline idea text gets routed to the idea-to-design path.
        # If your opp_creator signature requires a separate `idea_text` arg,
        # branch on it in run_starter; for now we encode "new from idea" as
        # an idea payload prefixed with `idea:` for the resolver to detect.
        slug_or_link = f"idea:{name}\n\n{idea}" if name else f"idea:{idea}"
        slug, run_id = start_run_from_slack(
            slug_or_link=slug_or_link, user=user, workspace=workspace,
        )
    except RunStartError as e:
        return {"response_action": "errors",
                "errors": {"idea_block": str(e)}}
    except Exception:
        logger.exception("start_run_from_slack failed for /ace new")
        return {"response_action": "errors",
                "errors": {"idea_block": "Internal error; check ace-web logs."}}

    client = _get_client(installation)
    placeholder_snapshot = {
        "display_name": slug,
        "current_run": {"run_id": run_id, "steps": [], "decisions": []},
        "phases": [],
    }
    blocks = render_parent_card(
        placeholder_snapshot, opp_slug=slug,
        workspace_slug=workspace.slug,
        triggerer_display=f"<@{slack_user_id}>",
        elapsed_seconds=0,
    )
    if channel_id:
        ts = client.post_message(channel=channel_id, blocks=blocks,
                                 text=f"ACE run started — {slug}")
        SlackRunThread.objects.create(
            installation=installation, channel_id=channel_id, parent_ts=ts,
            opp_slug=slug, run_id=run_id, ace_user=user,
        )
    return {"response_action": "clear"}
```

Also extend `run_starter.py` to handle the `idea:` prefix. Append below `_is_pdd_link`:

```python
def _is_idea(text: str) -> bool:
    return text.startswith("idea:")


def _extract_idea(text: str) -> str:
    return text[len("idea:"):].lstrip()
```

And modify the body of `start_run_from_slack` so the branch order is:

```python
    if _is_idea(slug_or_link):
        idea_text = _extract_idea(slug_or_link)
        from apps.opps.opp_creator import create_opp_from_idea
        slug = create_opp_from_idea(idea_text=idea_text, user=user,
                                    workspace=workspace)
    elif _is_pdd_link(slug_or_link):
        from apps.opps.opp_creator import create_opp_from_pdd
        slug = create_opp_from_pdd(pdd_link=slug_or_link, user=user,
                                   workspace=workspace)
    else:
        slug = slug_or_link.strip()
        opp = get_opp_by_slug(slug=slug, workspace=workspace)
        if opp is None:
            raise RunStartError(f"no opp `{slug}` in workspace `{workspace.slug}`")
```

> Same caveat as Task 10 about function names: if `create_opp_from_idea` doesn't exist by that name in `apps.opps.opp_creator`, scan the module and adapt (or author a thin wrapper). The existing `apps/opps/api.py` already has an opp-creation endpoint — its handler points at the canonical entry.

Wire `handle_new_submission` into `dispatch_interaction` (replace stub in `handlers.py`):

```python
def dispatch_interaction(payload: dict) -> dict:
    p_type = payload.get("type")
    if p_type == "view_submission":
        if payload["view"].get("callback_id") == "ace_new_modal":
            from .verbs_new import handle_new_submission
            return handle_new_submission(payload)
    if p_type == "block_actions":
        # Block actions (fork button etc.) lands in Task 16.
        return {}
    return {}
```

- [ ] **Step 4: Run tests**

```bash
pytest apps/slack/tests/test_handlers_new.py -v
```

Expected: 2/2 pass.

- [ ] **Step 5: Commit**

```bash
git add apps/slack/verbs_new.py apps/slack/run_starter.py apps/slack/handlers.py \
        apps/slack/tests/test_handlers_new.py
git commit -m "feat(slack): /ace new modal + submission (creates opp from idea)"
```

---

## Task 12: `/ace status` and `/ace list`

**Files:**
- Create: `apps/slack/verbs_query.py`
- Add to: `apps/slack/tests/test_handlers_misc.py`

- [ ] **Step 1: Add tests**

Append to `apps/slack/tests/test_handlers_misc.py`:

```python
@pytest.mark.django_db
def test_status_returns_parent_card_for_user_recent_run(setup):
    inst, jj = setup
    from apps.slack.models import SlackRunThread
    SlackRunThread.objects.create(
        installation=inst, channel_id="C1", parent_ts="1.1",
        opp_slug="my-opp", run_id="run-001", ace_user=jj,
    )
    from unittest.mock import patch
    with patch("apps.slack.verbs_query._load_snapshot") as load:
        load.return_value = {
            "display_name": "My Opp",
            "current_run": {"run_id": "run-001", "steps": [], "decisions": []},
            "phases": [],
        }
        from apps.slack.handlers import dispatch_slash_command
        resp = dispatch_slash_command(
            text="status", slack_user_id="U_JJ", team_id="T1",
            channel_id="C1", trigger_id="", response_url="",
        )
    assert resp["response_type"] == "ephemeral"
    assert "My Opp" in repr(resp.get("blocks", [])) or "My Opp" in resp.get("text", "")


@pytest.mark.django_db
def test_status_with_no_runs_returns_message(setup):
    from apps.slack.handlers import dispatch_slash_command
    resp = dispatch_slash_command(
        text="status", slack_user_id="U_JJ", team_id="T1",
        channel_id="C1", trigger_id="", response_url="",
    )
    assert resp["response_type"] == "ephemeral"
    assert "no active runs" in resp["text"].lower()


@pytest.mark.django_db
def test_list_shows_user_runs(setup):
    inst, jj = setup
    from apps.slack.models import SlackRunThread
    for i in range(3):
        SlackRunThread.objects.create(
            installation=inst, channel_id=f"C{i}", parent_ts=f"{i}.0",
            opp_slug=f"opp-{i}", run_id="run-001", ace_user=jj,
        )
    from apps.slack.handlers import dispatch_slash_command
    resp = dispatch_slash_command(
        text="list", slack_user_id="U_JJ", team_id="T1",
        channel_id="C1", trigger_id="", response_url="",
    )
    assert resp["response_type"] == "ephemeral"
    body = repr(resp.get("blocks", [])) + resp.get("text", "")
    assert "opp-0" in body and "opp-1" in body and "opp-2" in body
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest apps/slack/tests/test_handlers_misc.py::test_status_returns_parent_card_for_user_recent_run \
       apps/slack/tests/test_handlers_misc.py::test_list_shows_user_runs -v
```

Expected: failures (ImportError on `verbs_query`).

- [ ] **Step 3: Implement `verbs_query.py`**

Create `apps/slack/verbs_query.py`:

```python
"""`/ace status` and `/ace list` read-only queries."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from .blocks import render_parent_card
from .models import SlackRunThread

logger = logging.getLogger(__name__)


def _load_snapshot(slug: str, workspace) -> dict | None:
    """Indirection so tests can patch."""
    from apps.opps.access import get_snapshot
    snap = get_snapshot(slug=slug, workspace=workspace)
    return snap.model_dump() if snap is not None else None


def handle_status(*, installation, user_link, rest: str, channel_id: str) -> dict:
    workspace = installation.ace_workspace
    rest = rest.strip()
    if rest:
        thread = SlackRunThread.objects.filter(
            installation=installation, opp_slug=rest, broken_at__isnull=True,
        ).order_by("-triggered_at").first()
    else:
        thread = SlackRunThread.objects.filter(
            installation=installation, ace_user=user_link.ace_user,
            broken_at__isnull=True,
        ).order_by("-triggered_at").first()

    if thread is None:
        return {"response_type": "ephemeral",
                "text": "You have no active runs. Try `/ace run <slug>`."}

    snap = _load_snapshot(thread.opp_slug, workspace)
    if snap is None:
        return {"response_type": "ephemeral",
                "text": f"Could not load snapshot for `{thread.opp_slug}`."}

    elapsed = int((datetime.now(timezone.utc) - thread.triggered_at).total_seconds())
    blocks = render_parent_card(
        snap, opp_slug=thread.opp_slug, workspace_slug=workspace.slug,
        triggerer_display=f"<@{user_link.slack_user_id}>",
        elapsed_seconds=elapsed,
    )
    return {"response_type": "ephemeral", "blocks": blocks,
            "text": f"Status of {thread.opp_slug}"}


def handle_list(*, installation, user_link, channel_id: str) -> dict:
    threads = (SlackRunThread.objects
               .filter(installation=installation, ace_user=user_link.ace_user,
                       broken_at__isnull=True)
               .order_by("-triggered_at")[:5])
    if not threads:
        return {"response_type": "ephemeral",
                "text": "You have no active runs. Try `/ace run <slug>`."}
    lines = [f"• `{t.opp_slug}` ({t.run_id}) — "
             f"<https://labs.connect.dimagi.com/ace/w/"
             f"{installation.ace_workspace.slug}/opps/{t.opp_slug}|open ↗>"
             for t in threads]
    return {"response_type": "ephemeral",
            "text": "Your recent ACE runs:\n" + "\n".join(lines)}
```

- [ ] **Step 4: Run tests**

```bash
pytest apps/slack/tests/test_handlers_misc.py -v
```

Expected: 7/7 pass (4 from Task 9 + 3 new).

- [ ] **Step 5: Commit**

```bash
git add apps/slack/verbs_query.py apps/slack/tests/test_handlers_misc.py
git commit -m "feat(slack): /ace status + /ace list read-only queries"
```

---

## Task 13: `SlackOppConsumer` worker — wire dispatcher

**Files:**
- Create: `apps/slack/dispatcher.py`
- Modify: `apps/slack/apps.py`
- Modify: `apps/slack/verbs_run.py` (group_add on run start)
- Modify: `apps/slack/verbs_new.py` (group_add on submission)
- Create: `apps/slack/tests/test_dispatcher.py`

- [ ] **Step 1: Write the failing test**

```python
# apps/slack/tests/test_dispatcher.py
from unittest.mock import patch, MagicMock

import pytest
from django.contrib.auth import get_user_model

from apps.slack.models import SlackInstallation, SlackRunThread
from apps.workspaces.models import Workspace


@pytest.fixture
def setup(db):
    User = get_user_model()
    admin = User.objects.create(email="admin@dimagi.com")
    ws = Workspace.objects.create(slug="dimagi-team", name="Dimagi",
                                  drive_root_folder_id="f", created_by=admin)
    inst = SlackInstallation.objects.create(
        slack_team_id="T1", slack_team_name="Dimagi",
        bot_user_id="U_BOT", ace_workspace=ws, installed_by_user=admin,
    )
    inst.set_bot_token("xoxb-1"); inst.save()
    user = User.objects.create(email="jj@dimagi.com")
    return inst, user, ws


def _snap():
    return {
        "display_name": "My Opp",
        "current_run": {
            "run_id": "run-001",
            "steps": [
                {"phase": "idea-to-design", "skill_name": "draft", "status": "complete",
                 "ordinal": 0, "judge": {"score_pct": 80}},
            ],
            "decisions": [],
        },
        "phases": [
            {"name": "idea-to-design", "display_name": "Idea to Design",
             "agent": "i2d", "ordinal": 1},
        ],
    }


@pytest.mark.django_db
def test_dispatch_tick_posts_new_phase_message(setup):
    inst, user, ws = setup
    thread = SlackRunThread.objects.create(
        installation=inst, channel_id="C1", parent_ts="1.1",
        opp_slug="my-opp", run_id="run-001", ace_user=user,
    )
    with patch("apps.slack.dispatcher._load_snapshot") as load, \
         patch("apps.slack.dispatcher._get_client") as get_client:
        load.return_value = _snap()
        client = MagicMock(); get_client.return_value = client
        client.post_message.return_value = "2.0"
        from apps.slack.dispatcher import dispatch_tick
        dispatch_tick(thread_id=thread.pk)
    thread.refresh_from_db()
    assert "idea-to-design" in thread.phase_messages
    assert thread.phase_messages["idea-to-design"]["ts"] == "2.0"
    client.update_message.assert_called()  # parent card updated


@pytest.mark.django_db
def test_dispatch_tick_skips_unchanged_phase(setup):
    inst, user, ws = setup
    snap = _snap()
    from apps.slack.blocks import phase_state_hash
    h = phase_state_hash(snap, "idea-to-design")
    thread = SlackRunThread.objects.create(
        installation=inst, channel_id="C1", parent_ts="1.1",
        opp_slug="my-opp", run_id="run-001", ace_user=user,
        phase_messages={"idea-to-design": {"ts": "2.0", "last_state_hash": h}},
    )
    with patch("apps.slack.dispatcher._load_snapshot") as load, \
         patch("apps.slack.dispatcher._get_client") as get_client:
        load.return_value = snap
        client = MagicMock(); get_client.return_value = client
        from apps.slack.dispatcher import dispatch_tick
        dispatch_tick(thread_id=thread.pk)
    # No chat.update for the (unchanged) phase. Parent card may be updated
    # — but the phase tile must not be.
    for call in client.update_message.call_args_list:
        assert call.kwargs.get("ts") != "2.0"


@pytest.mark.django_db
def test_dispatch_tick_marks_broken_on_channel_gone(setup):
    inst, user, ws = setup
    thread = SlackRunThread.objects.create(
        installation=inst, channel_id="C1", parent_ts="1.1",
        opp_slug="my-opp", run_id="run-001", ace_user=user,
    )
    from apps.slack.slack_client import SlackChannelGone
    with patch("apps.slack.dispatcher._load_snapshot") as load, \
         patch("apps.slack.dispatcher._get_client") as get_client:
        load.return_value = _snap()
        client = MagicMock(); get_client.return_value = client
        client.post_message.side_effect = SlackChannelGone("channel_not_found")
        from apps.slack.dispatcher import dispatch_tick
        dispatch_tick(thread_id=thread.pk)
    thread.refresh_from_db()
    assert thread.broken_at is not None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest apps/slack/tests/test_dispatcher.py -v
```

Expected: ImportError on `apps.slack.dispatcher`.

- [ ] **Step 3: Implement dispatch tick (synchronous, no Channels yet)**

Create `apps/slack/dispatcher.py`:

```python
"""SlackOppConsumer: per-tick dispatcher + worker bootstrap.

The synchronous `dispatch_tick(thread_id)` is the pure-Python heart —
unit-tested without Channels. The async wrapper (`_run_worker`) listens
on a unique channel name, joins opp.<slug>.<run_id> groups for active
threads, and calls dispatch_tick on each `opp.updated` event with a
2-second debounce.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from asgiref.sync import sync_to_async
from channels.layers import get_channel_layer

from .blocks import (
    parent_state_hash, phase_state_hash,
    render_parent_card, render_phase_tile,
)
from .models import SlackRunThread
from .slack_client import SlackChannelGone, SlackRateLimited, client_for

logger = logging.getLogger(__name__)


def _opp_group(slug: str, run_id: str) -> str:
    return f"opp.{slug}.{run_id or 'default'}"


def _load_snapshot(slug: str, workspace) -> dict | None:
    from apps.opps.access import get_snapshot
    snap = get_snapshot(slug=slug, workspace=workspace)
    return snap.model_dump() if snap is not None else None


def _get_client(installation):
    return client_for(installation)


def dispatch_tick(*, thread_id) -> None:
    """One dispatch tick. Reads snapshot, diffs phase hashes, posts/updates.

    Safe to call from any thread / loop. Catches Slack channel-gone and
    rate-limit errors and reflects them on the SlackRunThread row.
    """
    try:
        thread = SlackRunThread.objects.select_related(
            "installation__ace_workspace", "ace_user",
        ).get(pk=thread_id)
    except SlackRunThread.DoesNotExist:
        return
    if thread.broken_at is not None:
        return

    workspace = thread.installation.ace_workspace
    snapshot = _load_snapshot(thread.opp_slug, workspace)
    if snapshot is None:
        logger.info("snapshot not yet available for %s/%s",
                    thread.opp_slug, thread.run_id)
        return

    client = _get_client(thread.installation)
    elapsed = int((datetime.now(timezone.utc) - thread.triggered_at).total_seconds())
    phase_messages = dict(thread.phase_messages or {})

    # 1. Per-phase create / update
    for phase in snapshot.get("phases", []):
        # Skip phases with no steps yet — nothing to render.
        steps_in_phase = [s for s in snapshot["current_run"]["steps"]
                          if s["phase"] == phase["name"]]
        if not steps_in_phase:
            continue
        h = phase_state_hash(snapshot, phase["name"])
        existing = phase_messages.get(phase["name"])
        blocks = render_phase_tile(snapshot, phase_name=phase["name"],
                                   opp_slug=thread.opp_slug,
                                   workspace_slug=workspace.slug)
        text = f"Phase {phase['ordinal']}: {phase['display_name']}"
        try:
            if existing is None:
                ts = client.post_message(channel=thread.channel_id,
                                         blocks=blocks, text=text,
                                         thread_ts=thread.parent_ts)
                phase_messages[phase["name"]] = {"ts": ts, "last_state_hash": h}
            elif existing.get("last_state_hash") != h:
                client.update_message(channel=thread.channel_id,
                                      ts=existing["ts"],
                                      blocks=blocks, text=text)
                existing["last_state_hash"] = h
                phase_messages[phase["name"]] = existing
        except SlackChannelGone:
            thread.broken_at = datetime.now(timezone.utc)
            thread.save(update_fields=["broken_at"])
            return
        except SlackRateLimited as e:
            logger.info("slack rate-limited on %s/%s; deferring (retry %ss)",
                        thread.opp_slug, thread.run_id, e.retry_after)
            return  # next opp.updated will retry

    # 2. Parent card
    new_parent_hash = parent_state_hash(snapshot, elapsed_seconds=elapsed)
    if new_parent_hash != thread.parent_state_hash:
        triggerer = thread.ace_user
        triggerer_display = (triggerer.get_full_name() or triggerer.email
                             or f"user {triggerer.pk}")
        parent_blocks = render_parent_card(
            snapshot, opp_slug=thread.opp_slug,
            workspace_slug=workspace.slug,
            triggerer_display=triggerer_display, elapsed_seconds=elapsed,
        )
        try:
            client.update_message(channel=thread.channel_id, ts=thread.parent_ts,
                                  blocks=parent_blocks,
                                  text=f"ACE run · {thread.opp_slug}")
        except SlackChannelGone:
            thread.broken_at = datetime.now(timezone.utc)
            thread.save(update_fields=["broken_at"])
            return
        except SlackRateLimited:
            return
        thread.parent_state_hash = new_parent_hash

    thread.phase_messages = phase_messages
    thread.save(update_fields=["phase_messages", "parent_state_hash"])


async def _run_worker() -> None:
    """Long-running worker: join opp groups for active threads and
    dispatch_tick on opp.updated events. Per-thread 2s debounce."""
    layer = get_channel_layer()
    if layer is None:
        logger.info("no channel layer; slack worker not started")
        return
    channel_name = await layer.new_channel()
    joined: set[str] = set()
    debounce: dict[int, asyncio.Task] = {}

    async def _refresh_subscriptions():
        threads = await sync_to_async(list)(
            SlackRunThread.objects.filter(broken_at__isnull=True)
            .values_list("opp_slug", "run_id", "pk")
        )
        wanted_groups = {_opp_group(s, r) for s, r, _ in threads}
        for g in wanted_groups - joined:
            await layer.group_add(g, channel_name)
            joined.add(g)
        for g in joined - wanted_groups:
            await layer.group_discard(g, channel_name)
            joined.discard(g)

    async def _debounced_dispatch(thread_id: int):
        await asyncio.sleep(2.0)
        try:
            await sync_to_async(dispatch_tick)(thread_id=thread_id)
        except Exception:
            logger.exception("dispatch_tick failed for thread %s", thread_id)
        debounce.pop(thread_id, None)

    # Initial sweep + group joins
    await _refresh_subscriptions()
    # On boot, run a one-shot tick across all active threads.
    threads = await sync_to_async(list)(
        SlackRunThread.objects.filter(broken_at__isnull=True).values_list("pk", flat=True)
    )
    for tid in threads:
        await sync_to_async(dispatch_tick)(thread_id=tid)

    while True:
        try:
            event = await layer.receive(channel_name)
        except Exception:
            logger.exception("channel receive failed; worker exiting")
            return
        if event.get("type") != "opp.updated":
            continue
        slug = event.get("opp_slug")
        run_id = event.get("run_id") or ""
        if not slug:
            continue
        thread_id = await sync_to_async(
            lambda: SlackRunThread.objects.filter(
                opp_slug=slug, run_id=run_id, broken_at__isnull=True,
            ).values_list("pk", flat=True).first()
        )()
        if thread_id is None:
            continue
        # Coalesce: cancel any pending debounced dispatch for this thread.
        prev = debounce.get(thread_id)
        if prev is not None and not prev.done():
            prev.cancel()
        debounce[thread_id] = asyncio.create_task(_debounced_dispatch(thread_id))
        # Periodic sub refresh — cheap, every event.
        await _refresh_subscriptions()


def start_worker() -> None:
    """Spawn the worker task in the running event loop. Called from
    SlackConfig.ready() once an event loop is available (ASGI startup)."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        return
    if loop.is_closed():
        return
    loop.create_task(_run_worker())
```

- [ ] **Step 4: Wire group_add on run creation**

Modify `apps/slack/verbs_run.py`. After the `SlackRunThread.objects.create(...)` call, add (still inside `handle_run`):

```python
    # Subscribe the worker to this run's group. Best-effort.
    try:
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync
        from .dispatcher import _opp_group
        layer = get_channel_layer()
        # The worker rediscovers subscriptions on every event; we don't
        # need to know the worker's channel_name here. The 60s sweep
        # (Task 15) is the belt-and-suspenders that catches everything.
    except Exception:
        logger.exception("could not request slack worker subscription")
```

(That's intentionally a no-op import — the worker self-subscribes via `_refresh_subscriptions()` on every event. The block above documents the intent and forces the imports to validate. Remove it if you prefer; the worker's periodic refresh is what actually does the work.)

Apply the same docstring-only block to `verbs_new.py:handle_new_submission` after its `SlackRunThread.objects.create(...)`.

- [ ] **Step 5: Wire worker startup**

Edit `apps/slack/apps.py` `ready()`:

```python
    def ready(self):
        # Skip during tests and migrate to avoid spurious worker spawns.
        import os
        import sys
        if os.environ.get("DJANGO_SLACK_DISABLE_WORKER") == "1":
            return
        if "pytest" in sys.modules or "test" in sys.argv or "migrate" in sys.argv:
            return
        from .dispatcher import start_worker
        start_worker()
```

- [ ] **Step 6: Run tests**

```bash
pytest apps/slack/tests/test_dispatcher.py -v
```

Expected: 3/3 pass.

- [ ] **Step 7: Commit**

```bash
git add apps/slack/dispatcher.py apps/slack/apps.py apps/slack/verbs_run.py \
        apps/slack/verbs_new.py apps/slack/tests/test_dispatcher.py
git commit -m "feat(slack): SlackOppConsumer worker + 2s-debounced dispatch_tick"
```

---

## Task 14: Multi-process dedup lock + periodic sweep

**Files:**
- Modify: `apps/slack/dispatcher.py`
- Add to: `apps/slack/tests/test_dispatcher.py`

ECS runs N tasks each with their own consumer, so two tasks can receive the same `opp.updated` event. Add a Redis SETNX lock so only one wins per tick. Add a 60s sweep so missed events recover.

- [ ] **Step 1: Write the failing test**

Append to `apps/slack/tests/test_dispatcher.py`:

```python
@pytest.mark.django_db
def test_dispatch_tick_skips_when_lock_held(setup):
    inst, user, ws = setup
    thread = SlackRunThread.objects.create(
        installation=inst, channel_id="C1", parent_ts="1.1",
        opp_slug="my-opp", run_id="run-001", ace_user=user,
    )
    from django.core.cache import cache
    cache.set(f"slack:dispatch:{thread.pk}", "held", timeout=5)
    with patch("apps.slack.dispatcher._load_snapshot") as load, \
         patch("apps.slack.dispatcher._get_client") as get_client:
        load.return_value = _snap()
        client = MagicMock(); get_client.return_value = client
        from apps.slack.dispatcher import dispatch_tick
        dispatch_tick(thread_id=thread.pk)
    # Lock held → no Slack calls.
    client.post_message.assert_not_called()
    client.update_message.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest apps/slack/tests/test_dispatcher.py::test_dispatch_tick_skips_when_lock_held -v
```

Expected: fails (no lock check).

- [ ] **Step 3: Add the lock**

In `apps/slack/dispatcher.py`, wrap the body of `dispatch_tick` after the SlackRunThread lookup but before snapshot load:

```python
    from django.core.cache import cache
    lock_key = f"slack:dispatch:{thread.pk}"
    if not cache.add(lock_key, "held", timeout=5):
        return  # another worker is dispatching for this thread
    try:
        # ... existing body (snapshot load, phase loop, parent card) ...
    finally:
        cache.delete(lock_key)
```

Move all existing code in `dispatch_tick` (from snapshot load onward) inside the `try:` block. Indent accordingly.

- [ ] **Step 4: Add the 60s sweep**

Append to `apps/slack/dispatcher.py`:

```python
async def _periodic_sweep() -> None:
    """Belt-and-suspenders: every 60s, dispatch_tick all active threads.

    Catches missed opp.updated events (worker restart, lost event) and
    drives phase 1 of newly-created threads that haven't received their
    first opp.updated yet (snapshot not yet populated → first sweep
    after Drive writes lands a phase tile)."""
    while True:
        await asyncio.sleep(60)
        try:
            ids = await sync_to_async(list)(
                SlackRunThread.objects.filter(broken_at__isnull=True)
                .values_list("pk", flat=True)
            )
            for tid in ids:
                await sync_to_async(dispatch_tick)(thread_id=tid)
        except Exception:
            logger.exception("periodic sweep failed")
```

Modify `_run_worker` to also kick off the periodic sweep. Inside `_run_worker`, after `await _refresh_subscriptions()` and the initial one-shot tick loop, add:

```python
    sweep_task = asyncio.create_task(_periodic_sweep())
    _ = sweep_task  # kept alive by the task ref in this scope
```

- [ ] **Step 5: Run tests**

```bash
pytest apps/slack/tests/test_dispatcher.py -v
```

Expected: 4/4 pass.

- [ ] **Step 6: Commit**

```bash
git add apps/slack/dispatcher.py apps/slack/tests/test_dispatcher.py
git commit -m "feat(slack): Redis dedup lock per dispatch tick + 60s periodic sweep"
```

---

## Task 15: Fork-from-here block action

**Files:**
- Modify: `apps/slack/handlers.py` (dispatch_interaction)
- Modify: `apps/slack/blocks.py` (already emits the right `action_id`)
- Modify: `apps/slack/tests/test_views.py` (add interaction test)

- [ ] **Step 1: Write the failing test**

Append to `apps/slack/tests/test_views.py`:

```python
@pytest.mark.django_db
@override_settings(SLACK_SIGNING_SECRET=SECRET)
def test_fork_action_returns_ephemeral_deeplink():
    import json as _json
    payload = {
        "type": "block_actions",
        "team": {"id": "T1"},
        "user": {"id": "U_JJ"},
        "actions": [{"action_id": "fork_from_phase",
                     "value": "rural-tb:scenarios-and-acceptance"}],
    }
    body_form = "payload=" + _quote(_json.dumps(payload))
    ts = str(int(time.time()))
    sig = _sign(body_form.encode(), ts)
    # Need a SlackInstallation in dimagi-team workspace so the workspace
    # slug resolves.
    from django.contrib.auth import get_user_model
    User = get_user_model()
    admin = User.objects.create(email="admin@dimagi.com")
    from apps.workspaces.models import Workspace
    ws = Workspace.objects.create(slug="dimagi-team", name="Dimagi",
                                  drive_root_folder_id="f", created_by=admin)
    from apps.slack.models import SlackInstallation
    inst = SlackInstallation.objects.create(
        slack_team_id="T1", slack_team_name="Dimagi",
        bot_user_id="U_BOT", ace_workspace=ws, installed_by_user=admin,
    )
    inst.set_bot_token("xoxb-1"); inst.save()

    c = Client()
    resp = c.post("/api/slack/interactions", data=body_form,
                  content_type="application/x-www-form-urlencoded",
                  HTTP_X_SLACK_REQUEST_TIMESTAMP=ts, HTTP_X_SLACK_SIGNATURE=sig)
    assert resp.status_code == 200
    body = resp.json()
    serialized = repr(body)
    assert "rural-tb" in serialized
    assert "fork=scenarios-and-acceptance" in serialized
    assert "dimagi-team" in serialized
```

Add the imports at the top of `test_views.py`:

```python
from urllib.parse import quote as _quote
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest apps/slack/tests/test_views.py::test_fork_action_returns_ephemeral_deeplink -v
```

Expected: empty response body / no deep-link present.

- [ ] **Step 3: Implement fork-action branch**

Edit `apps/slack/handlers.py` — replace `dispatch_interaction`:

```python
def dispatch_interaction(payload: dict) -> dict:
    p_type = payload.get("type")
    if p_type == "view_submission":
        if payload["view"].get("callback_id") == "ace_new_modal":
            from .verbs_new import handle_new_submission
            return handle_new_submission(payload)
        return {}
    if p_type == "block_actions":
        action = (payload.get("actions") or [{}])[0]
        action_id = action.get("action_id", "")
        if action_id == "fork_from_phase":
            return _fork_redirect(payload, action)
        if action_id == "link_account":
            return {}  # button has its own url; nothing to do server-side
        # Unknown actions — silently 200.
        return {}
    return {}


def _fork_redirect(payload: dict, action: dict) -> dict:
    value = action.get("value", "")
    try:
        slug, phase = value.split(":", 1)
    except ValueError:
        return {"response_type": "ephemeral", "text": ":x: malformed fork action"}
    team_id = payload.get("team", {}).get("id", "")
    installation = _get_installation(team_id)
    if installation is None:
        return {"response_type": "ephemeral", "text": ":x: workspace not installed"}
    workspace_slug = installation.ace_workspace.slug
    base = getattr(settings, "ACE_PUBLIC_BASE_URL",
                   "https://labs.connect.dimagi.com/ace")
    url = (f"{base}/w/{workspace_slug}/opps/{slug}"
           f"?fork={phase}")
    return {"response_type": "ephemeral",
            "text": f"Open the fork dialog: <{url}>"}
```

- [ ] **Step 4: Run tests**

```bash
pytest apps/slack/tests/test_views.py -v
```

Expected: 3/3 pass (the new one + 2 from Task 6).

- [ ] **Step 5: Commit**

```bash
git add apps/slack/handlers.py apps/slack/tests/test_views.py
git commit -m "feat(slack): fork-from-phase block action returns deep-link to ForkOppDialog"
```

---

## Task 16: Frontend — `?fork=<phase>` auto-open

**Files:**
- Modify: `frontend/src/pages/OppWorkbenchPage.tsx`
- Create: `frontend/src/pages/OppWorkbenchPage.test.tsx` (or extend existing)

- [ ] **Step 1: Read the existing page**

Open `frontend/src/pages/OppWorkbenchPage.tsx` and find:

1. Where `useSearchParams` is imported (line 2) — already imported.
2. Where the page renders `<PhaseView .../>`. Note `PhaseView` internally renders `ForkOppDialog` only when the user clicks the in-tile button. We need a way to open it from a query param.

The simplest path: lift the `forkOpen` + `forkAtPhase` state up to `OppWorkbenchPage` and pass them down. But `ForkOppDialog` is rendered inside `PhaseView` already; passing controlled props requires plumbing through `PhaseView`. Cleaner: render a *second* `ForkOppDialog` at the page level when `?fork=` is set.

- [ ] **Step 2: Implement the auto-open dialog**

Add this near the top of `OppWorkbenchPage.tsx`, after the existing imports:

```tsx
import { ForkOppDialog } from "../components/opps/ForkOppDialog";
```

Inside the `OppWorkbenchPage` component, after the existing `useSearchParams` hook, add:

```tsx
const [searchParams, setSearchParams] = useSearchParams();
const forkPhaseQuery = searchParams.get("fork");
const [autoForkOpen, setAutoForkOpen] = useState(false);

useEffect(() => {
  if (forkPhaseQuery && loadState.kind === "loaded") {
    setAutoForkOpen(true);
  }
}, [forkPhaseQuery, loadState.kind]);

const handleAutoForkClose = useCallback((next: boolean) => {
  setAutoForkOpen(next);
  if (!next) {
    // Clear the query param so the dialog doesn't auto-reopen on refetch.
    const params = new URLSearchParams(searchParams);
    params.delete("fork");
    setSearchParams(params, { replace: true });
  }
}, [searchParams, setSearchParams]);
```

> If `useSearchParams` is already destructured as `const [searchParams] = useSearchParams();` in the existing file, replace it with the two-tuple form above.

Then, near the bottom of the rendered JSX (before the closing fragment / outer div), add:

```tsx
{loadState.kind === "loaded" && forkPhaseQuery && (
  <ForkOppDialog
    open={autoForkOpen}
    onOpenChange={handleAutoForkClose}
    sourceSlug={loadState.snapshot.opp_slug ?? slug}
    sourceRunId={loadState.snapshot.current_run.run_id}
    forkAtPhase={forkPhaseQuery}
    forkAtPhaseDisplay={
      loadState.snapshot.phases.find(p => p.name === forkPhaseQuery)?.display_name
      ?? forkPhaseQuery
    }
    sourceLastActorAt={null}
  />
)}
```

> Adjust the `sourceSlug` reference if `OppSnapshot` exposes the slug under a different field. Look at `PhaseView.tsx:305-313` for the canonical call site.

- [ ] **Step 3: Smoke-check typecheck**

```bash
cd frontend
bunx tsc -b
```

Expected: no errors.

- [ ] **Step 4: (Optional) Smoke-check the page renders**

If your local dev server is up: visit `http://localhost:8000/w/dimagi-team/opps/<any-slug>?fork=scenarios-and-acceptance` and confirm the dialog opens.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/OppWorkbenchPage.tsx
git commit -m "feat(slack): frontend opens ForkOppDialog when ?fork=<phase> is set"
```

---

## Task 17: Runbook docs + learning entry

**Files:**
- Create: `docs/architecture/slack-integration.md`
- Create: `docs/learnings/slack-integration.md`
- Modify: `CLAUDE.md` (add learning pointer)

- [ ] **Step 1: Write the runbook**

Create `docs/architecture/slack-integration.md`:

```markdown
# Slack integration — operator runbook

## Install the Slack app (one-time)

1. Create a Slack app at https://api.slack.com/apps with the following:
   - Bot scopes: `commands`, `chat:write`, `chat:write.public`, `users:read`, `users:read.email`
   - Slash command `/ace` pointing at
     `https://labs.connect.dimagi.com/ace/api/slack/commands`
   - Interactivity request URL: `https://labs.connect.dimagi.com/ace/api/slack/interactions`
   - Events request URL: `https://labs.connect.dimagi.com/ace/api/slack/events`
     (only used today for `url_verification`).
2. Copy `Client ID`, `Client Secret`, `Signing Secret` into AWS Secrets Manager
   under the existing ace-web secret, keyed `SLACK_CLIENT_ID`,
   `SLACK_CLIENT_SECRET`, `SLACK_SIGNING_SECRET`. Run the labs deploy workflow.
3. As a Django superuser, visit `https://labs.connect.dimagi.com/ace/api/slack/install`
   and approve the install. This creates the `SlackInstallation` row in the
   `dimagi-team` workspace.

## Per-user account linking

The first time a Slack user runs `/ace …`, the bot DMs them a link. The link
goes to `/ace/auth/slack/link/?nonce=…` and requires the standard Connect
OAuth login. On success, a `SlackUserLink` row is created and the original
command is replayed.

To force a re-link, the user can run `/ace link`.

## Day-to-day flows

| Command                              | What it does                                                  |
| ------------------------------------ | ------------------------------------------------------------- |
| `/ace run <slug>`                    | Start `/ace:run` on an existing opp.                          |
| `/ace run <pdd-link>`                | Create an opp from a PDD in Drive and run it.                 |
| `/ace new`                           | Open a modal: name + idea → new opp.                          |
| `/ace status [<slug>]`               | Ephemeral parent-card snapshot.                                |
| `/ace list`                          | Top 5 active runs the user triggered.                          |
| `/ace link`                          | Re-issue the OAuth-link DM.                                    |
| `/ace help`                          | Print usage.                                                   |

## Troubleshooting

- **`signature mismatch` in logs**: rotate or re-paste `SLACK_SIGNING_SECRET`
  in Secrets Manager and redeploy.
- **`channel_not_found` on update**: bot was removed from the channel.
  `SlackRunThread.broken_at` is set; the user must `/ace run` again from a
  channel where the bot is present.
- **Thread not updating but the run is progressing on the Workbench**: check
  that the ASGI worker started — look for `_run_worker` in the logs. If
  missing, the SlackConfig `ready()` skipped startup (test/migrate detection
  is a heuristic). Set `DJANGO_SLACK_DISABLE_WORKER=0` in the task definition
  and redeploy.
- **Duplicate updates**: the per-tick Redis lock should prevent this. If you
  see them, `redis-cli KEYS 'slack:dispatch:*'` and `DEL` any stale entries.

## Architecture summary

See `docs/superpowers/specs/2026-05-15-slack-integration-design.md`. Key
reuse: the existing `opp.updated` channel-layer group from
`apps/sessions/opp_broadcast.py` is the progress signal — the
`SlackOppConsumer` worker just adds itself as a second listener alongside
the browser's `OppConsumer`.
```

- [ ] **Step 2: Write the learning entry**

Create `docs/learnings/slack-integration.md`:

```markdown
# slack-integration

Practical traps caught while building the v1 Slack integration.

- **`SlackConfig.ready()` runs in every Django command, including `manage.py
  migrate`, `pytest`, and `makemigrations`**. Starting the worker in those
  contexts will either fail (no event loop) or worse, fire `chat.update` on
  test runs. Guard with `DJANGO_SLACK_DISABLE_WORKER=1`, `pytest` module
  detection, and `migrate` in `sys.argv`.
- **`channel_not_found` is silent.** Slack returns 200 with `ok=false` and the
  error in the body — `slack_sdk` raises `SlackApiError`. The wrapper in
  `apps/slack/slack_client.py` normalizes this to `SlackChannelGone`; the
  dispatcher marks the thread `broken_at` and stops.
- **`chat.update` on a `ts` from a different channel returns `message_not_found`,
  not the obvious error.** Always store `(channel_id, ts)` together in
  `SlackRunThread`.
- **`response_type` matters for slash commands.** Omitting it makes the response
  default to `ephemeral`, which is what we want. For action handlers,
  `block_actions` payloads do NOT accept `response_type` — they use either
  `response_action: "clear"` or a JSON body posted to `response_url`.
- **Slack rate-limit is per-method-per-channel**. The 2s debounce + per-thread
  dispatch is enough for one run, but a busy channel with many concurrent runs
  could still hit limits. Watch `slack.rate_limited` log lines.
- **Per-tick dedup lock must be `cache.add` (SETNX), not `cache.set`.** Otherwise
  every worker overwrites the lock and both run.
```

- [ ] **Step 3: Add learning pointer to CLAUDE.md**

Modify `CLAUDE.md`. Find the "Auth & identity" section in the Learnings list
and add at the end of that section:

```markdown
- [slack-integration](docs/learnings/slack-integration.md) — `SlackConfig.ready()` runs in every management command (guard with env + sys.argv); `channel_not_found` is silent (wrapper normalizes); `(channel_id, ts)` must be stored together; dedup lock must be SETNX.
```

- [ ] **Step 4: Commit**

```bash
git add docs/architecture/slack-integration.md docs/learnings/slack-integration.md CLAUDE.md
git commit -m "docs(slack): runbook + learnings + CLAUDE.md pointer"
```

---

## Task 18: Integration test — end-to-end happy path

**Files:**
- Create: `apps/slack/tests/test_e2e.py`

This is an in-process integration test that exercises: signing-secret verify →
slash command → run start → opp.updated broadcast → dispatcher → Slack call.
We mock only the outbound Slack HTTP.

- [ ] **Step 1: Write the test**

```python
# apps/slack/tests/test_e2e.py
"""End-to-end happy path: /ace run → SlackRunThread created → opp.updated
event → SlackOppConsumer dispatches → Slack chat.update called with a
phase tile."""
import json
import time
from unittest.mock import patch, MagicMock

import pytest
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.contrib.auth import get_user_model
from django.test import Client, override_settings

from apps.slack.models import (
    SlackInstallation, SlackRunThread, SlackUserLink,
)
from apps.slack.tests.test_verify import _sign, SECRET
from apps.workspaces.models import Workspace


@pytest.mark.django_db
@override_settings(SLACK_SIGNING_SECRET=SECRET)
def test_run_to_phase_tile_happy_path():
    User = get_user_model()
    admin = User.objects.create(email="admin@dimagi.com")
    ws = Workspace.objects.create(slug="dimagi-team", name="Dimagi",
                                  drive_root_folder_id="f", created_by=admin)
    inst = SlackInstallation.objects.create(
        slack_team_id="T1", slack_team_name="Dimagi",
        bot_user_id="U_BOT", ace_workspace=ws, installed_by_user=admin,
    )
    inst.set_bot_token("xoxb-1"); inst.save()
    jj = User.objects.create(email="jj@dimagi.com")
    SlackUserLink.objects.create(installation=inst, slack_user_id="U_JJ",
                                 ace_user=jj, slack_email="jj@dimagi.com",
                                 slack_real_name="JJ")

    # 1. Slash command POST → signature verified → handler called →
    #    start_run_from_slack is mocked, but the dispatcher path is real.
    ts = str(int(time.time()))
    body = (b"command=/ace&text=run+rural-tb&team_id=T1&user_id=U_JJ"
            b"&channel_id=C1&trigger_id=tg1")
    sig = _sign(body, ts)

    snapshot = {
        "display_name": "Rural TB",
        "current_run": {
            "run_id": "run-001",
            "steps": [
                {"phase": "idea-to-design", "skill_name": "draft",
                 "status": "complete", "ordinal": 0,
                 "judge": {"score_pct": 80}},
            ],
            "decisions": [],
        },
        "phases": [{"name": "idea-to-design", "display_name": "Idea to Design",
                    "agent": "i2d", "ordinal": 1}],
    }

    slack_calls: list[tuple[str, dict]] = []

    def _record(method_name):
        def wrapped(**kw):
            slack_calls.append((method_name, kw))
            return MagicMock(ts="2.0") if method_name == "post_message" else None
        return wrapped

    with patch("apps.slack.verbs_run.start_run_from_slack") as start, \
         patch("apps.slack.dispatcher._load_snapshot") as load, \
         patch("apps.slack.slack_client.WebClient") as web_cls:
        start.return_value = ("rural-tb", "run-001")
        load.return_value = snapshot
        web_inst = web_cls.return_value
        web_inst.chat_postMessage.return_value = {"ok": True, "ts": "1.1"}
        web_inst.chat_update.return_value = {"ok": True}

        c = Client()
        resp = c.post("/api/slack/commands", data=body,
                      content_type="application/x-www-form-urlencoded",
                      HTTP_X_SLACK_REQUEST_TIMESTAMP=ts,
                      HTTP_X_SLACK_SIGNATURE=sig)
        assert resp.status_code == 200
        assert SlackRunThread.objects.filter(
            opp_slug="rural-tb", run_id="run-001",
        ).exists()

        # 2. Now simulate the opp.updated broadcast that opp_broadcast
        #    would emit when the run writes its first Drive artifact.
        #    Call dispatch_tick directly (bypassing Channels layer) to
        #    keep the test deterministic.
        thread = SlackRunThread.objects.get(opp_slug="rural-tb", run_id="run-001")
        from apps.slack.dispatcher import dispatch_tick
        dispatch_tick(thread_id=thread.pk)

        # Expect: chat.postMessage for the new phase tile, chat.update for parent.
        assert web_inst.chat_postMessage.call_count >= 1
        assert web_inst.chat_update.call_count >= 1
        # Phase 1 message landed.
        phase_post = next(
            c for c in web_inst.chat_postMessage.call_args_list
            if c.kwargs.get("thread_ts") == "1.1"
        )
        serialized = repr(phase_post.kwargs["blocks"])
        assert "Idea to Design" in serialized
```

- [ ] **Step 2: Run the test**

```bash
pytest apps/slack/tests/test_e2e.py -v
```

Expected: 1/1 pass.

- [ ] **Step 3: Run the full app test suite**

```bash
pytest apps/slack/ -v
```

Expected: every test green (24+ tests across 9 test files).

- [ ] **Step 4: Lint + typecheck**

```bash
ruff check apps/slack/
basedpyright apps/slack/  # may not be configured for the app; if it errors on missing config, skip
cd frontend && bunx tsc -b
```

Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add apps/slack/tests/test_e2e.py
git commit -m "test(slack): end-to-end integration test (signed POST → dispatch → Slack call)"
```

---

## After Task 18 — manual smoke

This plan covers everything the spec calls out for v1. Before opening the PR:

- Run the full repo test suite: `pytest -v` from the worktree root.
- Run frontend tests: `cd frontend && bun run test`.
- Local browser smoke: `docker compose up`, hit `http://localhost:8000/w/dimagi-team/opps/<some-slug>?fork=idea-to-design` and confirm the dialog auto-opens.
- (Optional) Wire a staging Slack app against an ngrok tunnel; run `/ace help` and `/ace status` to confirm shape.

---

## Self-review notes (for the implementer)

The spec calls out a few open questions; this plan resolves them as follows:

- **Bot token encryption key**: reuse the existing `apps.service_accounts.encryption` helper (Fernet derived from `SECRET_KEY`).
- **`run_id` resolution at trigger time**: pre-allocate via `allocate_next_run_id` (option (a) from the spec). The handler reserves the run-NNN folder before injecting the action, so `SlackRunThread.run_id` is known immediately. If your repo doesn't have an `allocate_next_run_id` primitive, author one in `apps/opps/access.py` per Task 10's caveat — it should be a 4-line function that lists Drive folders under `runs/` and returns the next sequential name.
- **LLO seed list in `/ace new`**: dropped from the v1 modal per the spec — not needed and adds a Drive coupling.

If any task discovers that a referenced `apps.opps` primitive (`get_opp_by_slug`, `allocate_next_run_id`, `create_opp_from_pdd`, `create_opp_from_idea`, `get_active_run_id`, `get_snapshot`) doesn't exist under that name: do NOT skip — author the thin wrapper in `apps/opps/access.py` first, in its own commit, then continue. Each one should be <10 lines.
