"""WebSocket consumer for the opp workbench.

Subscribes to the `opp.<slug>.<run_id|"default">` channel group and
relays events to connected clients.

Accepts incoming messages for multi-player decision editing:
  decision.edit   -> updates shared Redis buffer, broadcasts decision.edited
  decision.revert -> removes from buffer, broadcasts decision.reverted
"""
from __future__ import annotations

from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer


def _group_name(slug: str, run_id: str) -> str:
    return f"opp.{slug}.{run_id or 'default'}"


class OppConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        user = self.scope.get("user")
        if user is None or not getattr(user, "is_authenticated", False):
            await self.close(code=4001)
            return

        self.user = user
        self.slug = self.scope["url_route"]["kwargs"]["slug"]
        self.run_id = self.scope["url_route"]["kwargs"].get("run_id", "") or ""
        self.group = _group_name(self.slug, self.run_id)

        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        group = getattr(self, "group", None)
        if group is not None:
            await self.channel_layer.group_discard(group, self.channel_name)

    async def receive_json(self, content, **kwargs):
        msg_type = content.get("type", "")
        if msg_type == "decision.edit":
            await self._handle_decision_edit(content)
        elif msg_type == "decision.revert":
            await self._handle_decision_revert(content)

    async def _handle_decision_edit(self, content):
        row_id = content.get("row_id", "")
        new_answer = content.get("new_answer", "")
        if not row_id or not new_answer:
            return

        user = self.user
        email = getattr(user, "email", "")
        name = getattr(user, "display_name", "") or email

        await sync_to_async(self._write_edit)(row_id, new_answer, email, name)

        await self.channel_layer.group_send(self.group, {
            "type": "decision.edited",
            "row_id": row_id,
            "new_answer": new_answer,
            "editor_email": email,
            "editor_name": name,
        })

    async def _handle_decision_revert(self, content):
        row_id = content.get("row_id", "")
        if not row_id:
            return

        user = self.user
        email = getattr(user, "email", "")

        await sync_to_async(self._write_revert)(row_id)

        await self.channel_layer.group_send(self.group, {
            "type": "decision.reverted",
            "row_id": row_id,
            "editor_email": email,
        })

    def _write_edit(self, row_id, new_answer, email, name):
        from apps.opps.decisions_buffer import set_edit
        set_edit(self.slug, self.run_id, row_id=row_id,
                 new_answer=new_answer, editor_email=email, editor_name=name)

    def _write_revert(self, row_id):
        from apps.opps.decisions_buffer import remove_edit
        remove_edit(self.slug, self.run_id, row_id=row_id)

    async def opp_updated(self, event):
        await self.send_json({
            "event": "opp.updated",
            "data": {
                "slug": event.get("opp_slug", getattr(self, "slug", "")),
                "run_id": event.get("run_id", "") or "",
            },
        })

    async def decision_edited(self, event):
        await self.send_json({
            "event": "decision.edited",
            "data": {
                "row_id": event["row_id"],
                "new_answer": event["new_answer"],
                "editor_email": event["editor_email"],
                "editor_name": event["editor_name"],
            },
        })

    async def decision_reverted(self, event):
        await self.send_json({
            "event": "decision.reverted",
            "data": {
                "row_id": event["row_id"],
                "editor_email": event["editor_email"],
            },
        })
