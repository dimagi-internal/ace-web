"""Viewer presence over WebSocket: one socket per browser tab.

Navigation re-keys the connection with a fresh `presence.enter` rather than
reconnecting.

Two rules carry the security weight of this surface:

1. The page key is CLIENT-SUPPLIED. Its workspace segment is checked against
   the user's memberships before any group is joined — otherwise a user
   could observe who is viewing a workspace they cannot access. Membership
   is checked LIVE on every `presence.enter`, never cached for the life of
   the connection: a long-lived socket must not keep granting access to a
   workspace the user has since been removed from. A REJECTED enter (bad
   key or lost membership) also tears down any group the connection
   currently holds — otherwise a member revoked mid-session would keep
   receiving their old workspace's roster broadcasts until they disconnect.
2. Visibility is enforced HERE, not on the client. An opted-out user joins
   the group (so they still see others) but is never written to Redis, so
   no client — tampered, stale, or otherwise — can expose them. Like
   membership, visibility is re-read on every `presence.enter` rather than
   cached at connect time, so flipping "Show me as viewing" off bounds the
   exposure window to "until you next navigate" rather than "until you
   close the tab".
"""
from __future__ import annotations

import uuid

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from apps.workspaces.models import Workspace
from apps.workspaces.permissions import is_member

from . import keys as presence_keys
from . import store as presence_store
from .models import show_presence_for

GLOBAL_WORKSPACE = "global"


class PresenceConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        # Set connection-scoped state before the auth check: Channels still
        # dispatches disconnect() to this consumer after an early close() (a
        # rejected anonymous connection), and _leave_current() reads
        # self.group / self.page_key unconditionally.
        self.page_key: str | None = None
        self.group: str | None = None
        self.sub_location = ""
        self.visible = False
        self.idle = False
        self._last_broadcast_idle = False

        user = self.scope.get("user")
        if not getattr(user, "is_authenticated", False):
            await self.close(code=4001)
            return
        self.user = user
        self.connection_id = uuid.uuid4().hex
        # Deliberately NOT snapshotting visibility or workspace membership
        # here — both are re-read fresh on every presence.enter (see module
        # docstring) so a long-lived socket can't keep trusting a stale
        # connect-time answer.
        await self.accept()

    async def disconnect(self, code):
        await self._leave_current()

    async def receive_json(self, content, **kwargs):
        message_type = content.get("type", "")
        if message_type == "presence.enter":
            await self._enter(content)
        elif message_type == "presence.heartbeat":
            await self._heartbeat(content)

    # -- frame handlers --

    async def _enter(self, content):
        page_key = str(content.get("page_key") or "")
        sub_location = str(content.get("sub_location") or "")[:120]

        parsed = presence_keys.parse_page_key(page_key)
        if parsed is None:
            # Malformed — drop silently, never confirm key shapes. Still
            # tear down any group this connection currently holds: a
            # rejected enter must never leave a stale subscription in place
            # (see the non-member branch below for why this matters).
            await self._leave_current()
            return
        app, workspace, resource = parsed
        # Rebuild the canonical form from the (whitespace-stripped) parsed
        # parts rather than trusting the raw client string — parse_page_key
        # strips each segment, so "ace: ws :activity" and "ace:ws:activity"
        # must resolve to the SAME group/Redis key, not silently fragment the
        # roster across two.
        canonical_key = f"{app}:{workspace}:{resource}"

        if workspace != GLOBAL_WORKSPACE and not await self._member_of(workspace):
            # Not a member — drop silently, no existence leak. ALSO tear
            # down whatever group this connection currently holds:
            # without this, a member whose access to their CURRENT
            # workspace is revoked mid-session keeps receiving that
            # workspace's roster broadcasts (and stays writeable in its
            # Redis hash) until they disconnect or the TTL expires, even
            # though every subsequent enter is correctly rejected from
            # here on. No frame is sent back to this client either way —
            # the departure broadcast this triggers only reaches the
            # OTHER viewers of the page being left.
            await self._leave_current()
            return

        if canonical_key != self.page_key:
            await self._leave_current()
            self.page_key = canonical_key
            self.group = presence_keys.group_name(canonical_key)
            await self.channel_layer.group_add(self.group, self.channel_name)
            # Idle state is per-page, not per-connection — arriving on a new
            # page must not carry over "idle" from whatever page the user
            # was previously parked on.
            self.idle = False
            self._last_broadcast_idle = False

        # Re-read fresh on every enter (see module docstring rule 2) — this
        # is the ONLY place visibility is (re-)computed for this connection.
        self.visible = await database_sync_to_async(show_presence_for)(self.user)

        self.sub_location = sub_location
        await self._write()
        await self._broadcast()

    async def _heartbeat(self, content):
        if self.page_key is None:
            return
        self.idle = bool(content.get("idle"))
        await self._write()
        # Only an idle transition changes what others see; a plain keepalive
        # does not need a broadcast.
        if self.idle != self._last_broadcast_idle:
            self._last_broadcast_idle = self.idle
            await self._broadcast()

    # -- helpers --

    @database_sync_to_async
    def _member_of(self, slug: str) -> bool:
        # Deliberately NOT cached per connection — re-checked on every
        # presence.enter (see module docstring rule 1). ace-web has no
        # cheap "all my workspace slugs" call, so this resolves the
        # Workspace and delegates to apps.workspaces.permissions.is_member,
        # which already returns False for an unauthenticated user.
        workspace = Workspace.objects.filter(pk=slug).first()
        return bool(workspace and is_member(self.user, workspace))

    async def _write(self):
        if not self.visible or self.page_key is None:
            return
        await presence_store.touch(
            self.page_key,
            user_id=self.user.id,
            connection_id=self.connection_id,
            name=getattr(self.user, "display_name", "") or self.user.email,
            email=self.user.email or "",
            sub_location=self.sub_location,
            idle=bool(self.idle),
        )

    async def _leave_current(self):
        if self.group is None or self.page_key is None:
            return
        if self.visible:
            await presence_store.forget(
                self.page_key, user_id=self.user.id, connection_id=self.connection_id
            )
        group, page_key = self.group, self.page_key
        await self.channel_layer.group_discard(group, self.channel_name)
        self.group, self.page_key = None, None
        await self.channel_layer.group_send(
            group, {"type": "presence.roster_changed", "page_key": page_key}
        )

    async def _broadcast(self):
        if self.group is None:
            return
        await self.channel_layer.group_send(
            self.group, {"type": "presence.roster_changed", "page_key": self.page_key}
        )

    async def presence_roster_changed(self, event):
        """Every connection recomputes the roster itself.

        The `self` flag is per-recipient, so a single pre-rendered payload
        cannot be shared across the group. At tens of viewers per page the
        extra Redis reads are cheaper than the bookkeeping to avoid them.
        """
        page_key = event.get("page_key")
        if page_key != self.page_key:
            return
        viewers = await presence_store.roster(page_key)
        await self.send_json({
            "event": "presence.roster",
            "data": {
                "page_key": page_key,
                "viewers": [
                    {
                        "email": v["email"],
                        "name": v["name"],
                        "sub_location": v["sub_location"],
                        "idle": v["idle"],
                        "self": v["user_id"] == self.user.id,
                    }
                    for v in viewers
                ],
            },
        })
