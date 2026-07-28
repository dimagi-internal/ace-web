"""Page-key parsing and Channels group naming for presence.

Pure functions — no Redis, no async — so they unit-test without any
infrastructure. Page keys arrive from the client and are therefore parsed
defensively: anything that is not exactly `<app>:<workspace>:<resource>`
is rejected rather than coerced.
"""
from __future__ import annotations

import hashlib


def parse_page_key(page_key: str) -> tuple[str, str, str] | None:
    """Split `<app>:<workspace>:<resource>` into its three parts.

    The resource may itself contain colons (`opp:bednet/run-001`), so the
    split is bounded to 2. Returns None for anything malformed — callers
    MUST treat None as "reject this frame", never as "use a default".
    """
    if not page_key:
        return None
    parts = page_key.split(":", 2)
    if len(parts) != 3:
        return None
    app, workspace, resource = (p.strip() for p in parts)
    if not app or not workspace or not resource:
        return None
    return app, workspace, resource


def group_name(page_key: str) -> str:
    """A Channels-legal group name for a page key.

    Channels group names permit only ASCII alphanumerics, hyphens, periods
    and underscores (max 100 chars). Page keys contain ':' and '/', so the
    key is hashed rather than sanitised — sanitising would let two distinct
    keys collide onto one group.
    """
    digest = hashlib.sha1(page_key.encode("utf-8")).hexdigest()[:32]
    return f"presence.{digest}"
