"""ApiBackend — direct Claude API access via the Anthropic Python SDK.

Fallback for when the Claude CLI is not connected (no OAuth token).
Uses ANTHROPIC_API_KEY from the environment. If the key is not set,
the backend raises CLIBackendError on first use.

Yields the same StreamEvent types as CLIBackend, so the turn driver
and consumer don't need to change.
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from django.conf import settings

from apps.sessions.models import Message, Session

from .chat_backend import StreamEvent

logger = logging.getLogger(__name__)


class ApiBackend:
    """Async chat backend using the Anthropic API directly."""

    def __init__(self, *, model: str = "claude-sonnet-4-20250514"):
        self._model = model
        self._client = None

    def _get_client(self):
        if self._client is None:
            import anthropic

            api_key = getattr(settings, "ANTHROPIC_API_KEY", "") or ""
            if not api_key:
                from .cli_backend import CLIBackendError

                raise CLIBackendError(
                    "ANTHROPIC_API_KEY is not set. Configure it in settings or environment."
                )
            self._client = anthropic.AsyncAnthropic(api_key=api_key)
        return self._client

    async def stream_completion(
        self,
        *,
        session: Session,
        new_user_message: str,
        force_fresh_session: bool = False,
    ) -> AsyncIterator[StreamEvent]:
        """Stream one assistant turn via the Anthropic API."""
        client = self._get_client()

        # Build message history from the session
        messages = await self._build_messages(session, new_user_message)

        async with client.messages.stream(
            model=self._model,
            max_tokens=4096,
            messages=messages,
        ) as stream:
            async for event in stream:
                if event.type == "content_block_delta":
                    delta = event.delta
                    if hasattr(delta, "text") and delta.text:
                        yield StreamEvent.delta(text=delta.text)
                elif event.type == "content_block_start":
                    block = event.content_block
                    if hasattr(block, "type") and block.type == "tool_use":
                        yield StreamEvent.tool_use(
                            block={
                                "type": "tool_use",
                                "id": block.id,
                                "name": block.name,
                                "input": {},
                            }
                        )

        yield StreamEvent.done()

    async def _build_messages(
        self, session: Session, new_user_message: str
    ) -> list[dict]:
        """Build the messages array for the API call from session history."""
        from asgiref.sync import sync_to_async

        @sync_to_async
        def _load():
            return list(
                Message.objects.filter(
                    session=session, role__in=("user", "assistant")
                )
                .order_by("turn_index")
                .values("role", "plaintext")
            )

        history = await _load()
        messages = []
        for row in history:
            if row["plaintext"]:
                messages.append(
                    {"role": row["role"], "content": row["plaintext"]}
                )
        messages.append({"role": "user", "content": new_user_message})
        return messages
