"""WebSocket consumer for the opp workbench.

Subscribes to the `opp.<slug>.<run_id|"default">` channel group (currently
just `opp.updated` events emitted by `apps.sessions.opp_broadcast`) and
relays them to the connected client.

No incoming messages — this consumer is read-only from the client's POV.
The backend broadcasts events via `channel_layer.group_send()`.
"""
from __future__ import annotations

from channels.generic.websocket import AsyncJsonWebsocketConsumer


def _group_name(slug: str, run_id: str) -> str:
    return f"opp.{slug}.{run_id or 'default'}"


class OppConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        user = self.scope.get("user")
        if user is None or not getattr(user, "is_authenticated", False):
            await self.close(code=4001)
            return

        self.slug = self.scope["url_route"]["kwargs"]["slug"]
        self.run_id = self.scope["url_route"]["kwargs"].get("run_id", "") or ""
        self.group = _group_name(self.slug, self.run_id)

        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        group = getattr(self, "group", None)
        if group is not None:
            await self.channel_layer.group_discard(group, self.channel_name)

    # Channel-layer event handler. Channels auto-converts dotted event types
    # ("opp.updated") into method names with dots replaced by underscores
    # ("opp_updated").
    async def opp_updated(self, event):
        await self.send_json({
            "event": "opp.updated",
            "data": {
                "slug": event.get("opp_slug", getattr(self, "slug", "")),
                "run_id": event.get("run_id", "") or "",
            },
        })
