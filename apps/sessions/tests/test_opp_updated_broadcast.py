"""Tests for apps.sessions.opp_broadcast.maybe_emit_opp_updated."""
import asyncio

import pytest
from asgiref.sync import sync_to_async
from channels.layers import get_channel_layer

from apps.auth.models import User
from apps.sessions.models import Session
from apps.sessions.opp_broadcast import maybe_emit_opp_updated

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.asyncio
async def test_broadcast_on_drive_tool_use():
    user = await sync_to_async(User.objects.create)(email="a@dimagi.com", display_name="A")
    session = await sync_to_async(Session.objects.create)(
        owner=user, opp_slug="malaria-pilot", opp_run_id="run-001",
        backend_kind="cli", status="active", source="web",
    )
    tool_uses = [{"name": "ace-gdrive:drive_create_file"}]

    layer = get_channel_layer()
    await layer.group_add("opp.malaria-pilot.run-001", "test-channel")

    await maybe_emit_opp_updated(session, tool_uses)

    msg = await layer.receive("test-channel")
    assert msg["type"] == "opp.updated"
    assert msg["opp_slug"] == "malaria-pilot"
    assert msg["run_id"] == "run-001"


@pytest.mark.asyncio
async def test_no_broadcast_for_non_drive_tools():
    user = await sync_to_async(User.objects.create)(email="b@dimagi.com", display_name="B")
    session = await sync_to_async(Session.objects.create)(
        owner=user, opp_slug="malaria-pilot", opp_run_id="run-001",
        backend_kind="cli", status="active", source="web",
    )
    tool_uses = [{"name": "other:some_tool"}]

    layer = get_channel_layer()
    await layer.group_add("opp.malaria-pilot.run-001", "test-channel-2")

    await maybe_emit_opp_updated(session, tool_uses)

    done, pending = await asyncio.wait(
        [asyncio.create_task(layer.receive("test-channel-2"))],
        timeout=0.2,
    )
    assert not done
    for p in pending:
        p.cancel()


@pytest.mark.asyncio
async def test_no_broadcast_for_non_opp_session():
    user = await sync_to_async(User.objects.create)(email="c@dimagi.com", display_name="C")
    session = await sync_to_async(Session.objects.create)(
        owner=user, opp_slug="", opp_run_id="",  # no opp linkage
        backend_kind="cli", status="active", source="web",
    )
    tool_uses = [{"name": "ace-gdrive:drive_create_file"}]

    layer = get_channel_layer()
    await layer.group_add("opp.malaria-pilot.run-001", "test-channel-3")

    await maybe_emit_opp_updated(session, tool_uses)

    done, pending = await asyncio.wait(
        [asyncio.create_task(layer.receive("test-channel-3"))],
        timeout=0.2,
    )
    assert not done
    for p in pending:
        p.cancel()
